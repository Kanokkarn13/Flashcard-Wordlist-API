import os
import csv
import logging
import random
from typing import List, Dict, Optional

logger = logging.getLogger("api")

class VocabularyCache:
    """In-memory cache for HSK vocabulary list/dictionary."""
    def __init__(self):
        self._words: List[Dict] = []
        self._words_by_word: Dict[str, Dict] = {}
        self._words_by_level: Dict[int, List[Dict]] = {i: [] for i in range(1, 7)}

    def set_words(self, words: List[Dict]):
        """Sets the cache content and rebuilds indices for fast O(1) query performance."""
        # Ensure rows are dict representation and sorted by ID to maintain pagination order
        sorted_words = sorted(words, key=lambda x: int(x.get("id") or 0))
        self._words = sorted_words
        
        # Build index map for word lookup
        self._words_by_word = {w["word"]: w for w in sorted_words if "word" in w}
        
        # Build level lists
        self._words_by_level = {i: [] for i in range(1, 7)}
        for w in sorted_words:
            level = w.get("level")
            if level is not None:
                try:
                    lvl_int = int(level)
                    if lvl_int in self._words_by_level:
                        self._words_by_level[lvl_int].append(w)
                except (ValueError, TypeError):
                    pass

    def get_all(self) -> List[Dict]:
        """Returns all HSK words, sorted by id."""
        return self._words

    def get_by_word(self, word: str) -> Optional[Dict]:
        """Returns details of a specific word by its Chinese characters."""
        return self._words_by_word.get(word)

    def get_by_level(self, level: int) -> List[Dict]:
        """Returns a list of words for a specific HSK level, sorted by id."""
        return self._words_by_level.get(level, [])

    def get_random(self, level: Optional[int] = None) -> Optional[Dict]:
        """Returns a random word, optionally filtered by level."""
        if level is not None:
            level_words = self.get_by_level(level)
            if not level_words:
                return None
            return random.choice(level_words)
        
        if not self._words:
            return None
        return random.choice(self._words)

    def count(self) -> int:
        """Returns the total number of words in cache."""
        return len(self._words)

# Global instance of the vocabulary RAM cache
vocab_cache = VocabularyCache()


def load_vocab_cache() -> bool:
    """
    Fetches the vocabulary dataset from Supabase REST API,
    merges details, and populates the in-memory RAM cache.
    """
    url_base = os.getenv("SUPABASE_URL") or os.getenv("EXPO_PUBLIC_SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("EXPO_PUBLIC_SUPABASE_ANON_KEY")

    if not url_base or not anon_key:
        logger.error("VocabCache: Supabase credentials not found in environment. Sync aborted.")
        return False

    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}"
    }

    try:
        logger.info("VocabCache: Initiating dataset pull from Supabase...")
        # Import sync utility to reuse _fetch_and_merge_data logic
        from app.sync import _fetch_and_merge_data
        
        enriched_vocab = _fetch_and_merge_data(url_base, headers)
        if not enriched_vocab:
            logger.error("VocabCache: Fetched dataset is empty.")
            return False

        # Validate minimum record threshold (5300 records)
        count = len(enriched_vocab)
        min_threshold = 5300
        if count < min_threshold:
            logger.error(
                f"VocabCache: Integrity check failed. Downloaded dataset has {count} records, "
                f"which is less than the safety threshold of {min_threshold}."
            )
            return False

        vocab_cache.set_words(enriched_vocab)
        logger.info(f"VocabCache: Successfully fetched and loaded {count} records into RAM cache.")
        return True
    except Exception as e:
        logger.error(f"VocabCache: Failed to fetch vocabulary from Supabase: {e}")
        return False


def load_vocab_from_csv() -> bool:
    """
    Loads HSK vocabulary from the local CSV cache.
    Used as a fallback if remote Supabase is unreachable at startup.
    """
    csv_path = os.getenv("CSV_PATH", "hsk_vocab.csv")
    if not os.path.exists(csv_path):
        logger.error(f"VocabCache: Fallback CSV file not found at '{csv_path}'.")
        return False

    try:
        logger.info(f"VocabCache: Loading from local fallback CSV cache '{csv_path}'...")
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        count = len(rows)
        min_threshold = 5300
        if count < min_threshold:
            logger.error(
                f"VocabCache: Integrity check failed on fallback CSV. Expected >= {min_threshold} records, found {count}."
            )
            return False

        # Cast level/id fields to integer for compatibility
        formatted_rows = []
        for r in rows:
            formatted_row = {
                "id": int(r["id"]),
                "word": r["word"],
                "pinyin": r["pinyin"],
                "definition": r["definition"],
                "definition_th": r["definition_th"],
                "level": int(r["level"]) if r.get("level") else None,
                "example_sentence": r.get("example_sentence", ""),
                "example_pinyin": r.get("example_pinyin", "")
            }
            formatted_rows.append(formatted_row)

        vocab_cache.set_words(formatted_rows)
        logger.info(f"VocabCache: Successfully loaded {count} records from fallback CSV cache.")
        return True
    except Exception as e:
        logger.error(f"VocabCache: Failed to load fallback CSV cache: {e}")
        return False
