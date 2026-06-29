import sqlite3
import os
import sys
import logging
from contextlib import contextmanager

logger = logging.getLogger("api")

# DB path should be configurable via env, default to local root path
DB_PATH = os.getenv("DB_PATH", "hsk_vocab.db")

@contextmanager
def get_db_connection():
    """Yields a SQLite connection with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_api_keys_table():
    """
    Initializes the api_keys table in SQLite if it doesn't exist.
    Inserts a default developer key 'hsk_dev_secret_key' if the table is empty.
    """
    logger.info("Initializing API Key management table...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    revoked_at DATETIME
                )
            """)
            
            # Check if table is empty, seed default key if so
            cursor.execute("SELECT COUNT(*) FROM api_keys")
            count = cursor.fetchone()[0]
            if count == 0:
                logger.info("Seeding default developer API key into SQLite...")
                cursor.execute(
                    "INSERT INTO api_keys (key, name, is_active) VALUES (?, ?, 1)",
                    ("hsk_dev_secret_key", "Default Developer Key")
                )
            conn.commit()
    except Exception as e:
        logger.critical(f"Failed to initialize API key table: {e}")
        sys.exit(1)

def verify_db_integrity():
    """
    Checks the integrity of the SQLite database at startup.
    Validates that the database file exists and contains the expected number of records
    stored in the database metadata table (minimum 5300 records).
    If validation fails, shuts down the application immediately.
    """
    # Initialize the API keys table schema and seed data
    init_api_keys_table()
    
    logger.info(f"Initializing database integrity check (DB_PATH: {DB_PATH})...")
    
    if not os.path.exists(DB_PATH):
        logger.critical(f"Database integrity check failed: file not found at {DB_PATH}")
        sys.exit(1)
        
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Query target record count from metadata
            cursor.execute("SELECT value FROM metadata WHERE key = 'expected_records' LIMIT 1")
            row = cursor.fetchone()
            if not row:
                logger.critical("Database integrity check failed: 'expected_records' key missing in metadata table.")
                sys.exit(1)
                
            expected_count = int(row["value"])
            min_threshold = 5300
            
            if expected_count < min_threshold:
                logger.critical(
                    f"Database integrity check failed: Metadata expected count {expected_count} is less than safety threshold of {min_threshold}."
                )
                sys.exit(1)
                
            # Query actual record count
            cursor.execute("SELECT COUNT(*) FROM words")
            count = cursor.fetchone()[0]
            
            if count != expected_count:
                logger.critical(
                    f"Database integrity check failed: Expected {expected_count} records, but found {count} in database."
                )
                sys.exit(1)
                
            logger.info(f"Database integrity check successful. {count} records dynamically verified.")
    except Exception as e:
        logger.critical(f"Database integrity check failed due to error: {e}")
        sys.exit(1)
