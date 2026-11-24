import sqlite3
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).parent / "research.db"


def initialize_database():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS investigation_control (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    status TEXT NOT NULL
                        CHECK (status IN ('running', 'stopping', 'stopped'))
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO investigation_control (id, status)
                VALUES (1, 'stopped')
                """
            )


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized at {DB_PATH}.")
