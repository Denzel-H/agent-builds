
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "research.db"

def initialize_database():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                citation TEXT,
                findings TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        conn.commit()
if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized at {DB_PATH}.")