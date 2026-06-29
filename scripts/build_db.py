import csv
import sqlite3
import sys
import os

def build_db(csv_path="hsk_vocab.csv", db_path="hsk_vocab.db"):
    print(f"Loading data from CSV: {csv_path}...")
    if not os.path.exists(csv_path):
        print(f"CRITICAL ERROR: CSV file not found at {csv_path}")
        sys.exit(1)
        
    try:
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to read CSV: {e}")
        sys.exit(1)
        
    # Data Integrity: Check CSV row count dynamically
    csv_count = len(rows)
    min_threshold = 5300
    if csv_count < min_threshold:
        print(f"CRITICAL ERROR: Row count check failed. Dataset has {csv_count} rows, which is less than the safety threshold of {min_threshold}.")
        sys.exit(1)
        
    print(f"CSV Row count check passed: {csv_count} rows found.")
    
    # Establish SQLite Connection
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Drop table if exists to ensure clean run
        cursor.execute("DROP TABLE IF EXISTS words")
        
        # Create Table
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
        
        # Insert Data
        print("Inserting records into SQLite...")
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
            ) for row in rows
        ])
        
        # Create Indexes for query performance
        print("Creating indexes on 'word' and 'level' columns...")
        cursor.execute("CREATE UNIQUE INDEX idx_words_word ON words(word)")
        cursor.execute("CREATE INDEX idx_words_level ON words(level)")
        
        # Create Metadata table and insert expected records count
        print("Creating metadata table and saving expected records count...")
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
        
        # Database Integrity: Check DB row count
        cursor.execute("SELECT COUNT(*) FROM words")
        db_count = cursor.fetchone()[0]
        conn.close()
        
        if db_count != csv_count:
            print(f"CRITICAL ERROR: DB Row count check failed. Expected {csv_count} rows in DB, found {db_count}.")
            sys.exit(1)
            
        print(f"Successfully built SQLite database at '{db_path}' with {db_count} records.")
        
    except Exception as e:
        print(f"CRITICAL ERROR: Failed during database build: {e}")
        sys.exit(1)

if __name__ == "__main__":
    build_db()
