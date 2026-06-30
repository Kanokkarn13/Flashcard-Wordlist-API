import os
import csv
import sys
import requests
from dotenv import load_dotenv

# Load env variables (if any)
load_dotenv()

def fetch_and_merge_data(url_base: str, anon_key: str):
    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}"
    }

    vocab_url = f"{url_base}/rest/v1/vocab_hsk"
    trans_url = f"{url_base}/rest/v1/vocab_translations"
    
    hsk_fields = ["id", "word", "pinyin", "definition", "level", "example_sentence", "example_pinyin"]
    trans_fields = ["vocab_id", "content"]

    # 1. Fetch HSK Vocabulary
    print("Fetching HSK records from Supabase...")
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

    print(f"Fetched {len(all_vocab)} HSK records.")

    # 2. Fetch English Definitions
    print("Fetching EN translations...")
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
    print("Fetching TH translations...")
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
    print("Merging translations...")
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

def main():
    url_base = os.getenv("SUPABASE_URL") or os.getenv("EXPO_PUBLIC_SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("EXPO_PUBLIC_SUPABASE_ANON_KEY")
    csv_path = os.getenv("CSV_PATH", "hsk_vocab.csv")
    db_path = os.getenv("DB_PATH", "hsk_vocab.db")

    if not url_base or not anon_key:
        print("CRITICAL ERROR: Supabase credentials not found in environment variables.")
        sys.exit(1)

    try:
        enriched_vocab = fetch_and_merge_data(url_base, anon_key)
        
        if not enriched_vocab:
            print("CRITICAL ERROR: Fetched dataset is empty.")
            sys.exit(1)

        # Validate safety threshold
        count = len(enriched_vocab)
        min_threshold = 5300
        if count < min_threshold:
            print(f"CRITICAL ERROR: Integrity check failed. Fetched {count} records, expected >= {min_threshold}.")
            sys.exit(1)

        # 1. Update CSV file
        print(f"Writing to local CSV: {csv_path}...")
        with open(csv_path, mode="w", encoding="utf-8", newline="") as f:
            fields = ["id", "word", "pinyin", "definition", "definition_th", "level", "example_sentence", "example_pinyin"]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(enriched_vocab)
        print("CSV cache file successfully written.")

        # 2. Build/Verify SQLite database
        print("Recompiling SQLite database using build_db...")
        # Add parent folder of scripts to path to allow importing build_db
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from build_db import build_db
        build_db(csv_path=csv_path, db_path=db_path)
        print("SQLite database successfully compiled and verified.")
        
        print("Sync backup completed successfully!")

    except Exception as e:
        print(f"CRITICAL ERROR: Backup synchronization failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
