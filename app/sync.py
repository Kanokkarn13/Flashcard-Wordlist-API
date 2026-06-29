import csv
import os
import sqlite3
import logging
import asyncio
from typing import Optional
import requests

logger = logging.getLogger("api")

# Load database paths
DB_PATH = os.getenv("DB_PATH", "hsk_vocab.db")
CSV_PATH = os.getenv("CSV_PATH", "hsk_vocab.csv")

async def sync_database_from_supabase(db_path: str = None):
    """
    Fetch the latest vocabulary dataset from Supabase (HSK and translation definitions),
    merge EN and TH definitions, and rewrite the words and metadata tables in SQLite.
    This preserves other tables (like api_keys) untouched.
    """
    if db_path is None:
        db_path = DB_PATH

    url_base = os.getenv("SUPABASE_URL") or os.getenv("EXPO_PUBLIC_SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("EXPO_PUBLIC_SUPABASE_ANON_KEY")

    if not url_base or not anon_key:
        logger.error("Sync: Supabase credentials not found in environment variables. Sync aborted.")
        return False

    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}"
    }

    try:
        # Run standard synchronous HTTP requests inside an executor thread to prevent blocking FastAPI
        loop = asyncio.get_running_loop()
        enriched_vocab = await loop.run_in_executor(None, _fetch_and_merge_data, url_base, headers)
        
        if not enriched_vocab:
            logger.error("Sync: Fetched dataset is empty. Sync aborted.")
            return False

        # Validate safety threshold
        csv_count = len(enriched_vocab)
        min_threshold = 5300
        if csv_count < min_threshold:
            logger.error(
                f"Sync: Integrity check failed. Downloaded dataset has {csv_count} records, "
                f"which is less than the safety threshold of {min_threshold}. Sync aborted."
            )
            return False

        # 1. Update the local CSV file
        with open(CSV_PATH, mode="w", encoding="utf-8", newline="") as f:
            fields = ["id", "word", "pinyin", "definition", "definition_th", "level", "example_sentence", "example_pinyin"]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(enriched_vocab)
        logger.info(f"Sync: Successfully updated CSV cache at '{CSV_PATH}' dynamically.")

        # 2. Update SQLite words and metadata tables
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Recreate words table dynamically
        cursor.execute("DROP TABLE IF EXISTS words")
        cursor.execute("""
            CREATE TABLE words (
                id INTEGER PRIMARY KEY,
                word TEXT NOT NULL,
                pinyin TEXT,
                definition TEXT,
                definition_th TEXT,
                level INTEGER,
                example_sentence TEXT,
                example_pinyin TEXT
            )
        """)

        # Insert fresh records
        cursor.executemany("""
            INSERT INTO words (id, word, pinyin, definition, definition_th, level, example_sentence, example_pinyin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                int(row["id"]),
                row["word"],
                row["pinyin"],
                row["definition"],
                row["definition_th"],
                int(row["level"]) if row["level"] else None,
                row["example_sentence"],
                row["example_pinyin"]
            ) for row in enriched_vocab
        ])

        # Create indexes
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_words_word ON words(word)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_words_level ON words(level)")

        # Create metadata table and insert dynamic expected records count
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('expected_records', ?)",
            (str(csv_count),)
        )

        conn.commit()
        conn.close()

        logger.info(f"Sync: Successfully updated SQLite database at '{db_path}' with {csv_count} records.")
        return True

    except Exception as e:
        logger.error(f"Sync: Database synchronization failed: {e}")
        return False

def _fetch_and_merge_data(url_base: str, headers: dict):
    """Internal helper running HTTP calls synchronously inside a thread pool."""
    vocab_url = f"{url_base}/rest/v1/vocab_hsk"
    trans_url = f"{url_base}/rest/v1/vocab_translations"
    
    hsk_fields = ["id", "word", "pinyin", "definition", "level", "example_sentence", "example_pinyin"]
    trans_fields = ["vocab_id", "content"]

    # 1. Fetch HSK Vocabulary
    all_vocab = []
    limit = 1000
    offset = 0
    while True:
        url = f"{vocab_url}?select={','.join(hsk_fields)}&order=id.asc&limit={limit}&offset={offset}"
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            raise Exception(f"Failed to fetch HSK records: {res.text}")
        data = res.json()
        if not data:
            break
        all_vocab.extend(data)
        if len(data) < limit:
            break
        offset += limit

    # 2. Fetch English Definitions
    en_translations = {}
    offset = 0
    while True:
        url = f"{trans_url}?select={','.join(trans_fields)}&lang=eq.EN&type=eq.DEFINITION&limit={limit}&offset={offset}"
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            raise Exception(f"Failed to fetch EN translations: {res.text}")
        data = res.json()
        if not data:
            break
        for item in data:
            en_translations[item["vocab_id"]] = item["content"]
        if len(data) < limit:
            break
        offset += limit

    # 3. Fetch Thai Definitions
    th_translations = {}
    offset = 0
    while True:
        url = f"{trans_url}?select={','.join(trans_fields)}&lang=eq.TH&type=eq.DEFINITION&limit={limit}&offset={offset}"
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            raise Exception(f"Failed to fetch TH translations: {res.text}")
        data = res.json()
        if not data:
            break
        for item in data:
            th_translations[item["vocab_id"]] = item["content"]
        if len(data) < limit:
            break
        offset += limit

    # 4. Merge Translations
    enriched_vocab = []
    for item in all_vocab:
        vocab_id = item["id"]
        en_def = en_translations.get(vocab_id)
        th_def = th_translations.get(vocab_id)

        if en_def:
            item["definition"] = en_def
        else:
            item["definition"] = item.get("definition") or ""

        item["definition_th"] = th_def or ""
        enriched_vocab.append(item)

    return enriched_vocab


class WebhookDebouncer:
    """Manages an asynchronous, cancellable debounce timer for incoming webhook signals."""
    
    def __init__(self, delay_seconds: float = 10.0):
        self.delay_seconds = delay_seconds
        self.task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

    async def trigger(self):
        """Trigger or reset the debounce timer before executing database synchronization."""
        async with self.lock:
            # If a task is scheduled but not finished, cancel it to reset the debounce timer
            if self.task and not self.task.done():
                self.task.cancel()
                logger.info(f"Sync: Received new webhook signal. Resetting debounce timer ({self.delay_seconds}s delay)...")
            else:
                logger.info(f"Sync: Webhook signal received. Scheduling sync pipeline execution in {self.delay_seconds}s...")

            # Schedule a new delayed sync task
            self.task = asyncio.create_task(self._delayed_sync())

    async def _delayed_sync(self):
        try:
            await asyncio.sleep(self.delay_seconds)
            logger.info("Sync: Debounce timer expired. Executing database synchronization...")
            success = await sync_database_from_supabase()
            if success:
                logger.info("Sync: Dynamic database synchronization completed successfully.")
            else:
                logger.error("Sync: Dynamic database synchronization failed.")
        except asyncio.CancelledError:
            # Task was cancelled due to a newer incoming webhook trigger
            logger.info("Sync: Debounce task cancelled (overridden by new webhook).")
        except Exception as e:
            logger.error(f"Sync: Error during debounced sync task: {e}")


# Global instance of the debouncer with a 10-second window
debouncer = WebhookDebouncer(delay_seconds=10.0)
