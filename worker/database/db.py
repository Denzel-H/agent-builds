import sqlite3
from pathlib import Path
import json

DB_PATH = Path(__file__).parent / "research.db"

def get_pending_papers():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row 
        cursor = conn.execute(
            "SELECT * FROM papers WHERE status = ?",
            ("pending",)
        )

    return [dict(row) for row in cursor.fetchall()]

def claim_paper(paper_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE papers
            SET status = 'processing'
            WHERE id = ? AND status = 'pending'
            """,
            (paper_id,)
        )
        conn.commit()
        return cursor.rowcount == 1

def failed_paper(paper_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE papers
            SET status = 'failed'
            WHERE id = ? AND status = 'processing'
            """,
            (paper_id,)
        )
        conn.commit()
        return cursor.rowcount == 1

def save_findings(paper_id, citation, findings):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE papers
            SET citation = ?, findings = ?, status = 'completed'
            WHERE id = ? AND status = 'processing'
            """,
            (citation, json.dumps(findings), paper_id)
        )
        conn.commit()
        return cursor.rowcount == 1

def get_investigation_status():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT status FROM investigation_control WHERE id = 1"
        )
        row = cursor.fetchone()
        return row[0]


def set_investigation_status(status):
    valid_statuses = {"running", "stopping", "stopped"}

    if status not in valid_statuses:
        raise ValueError(f"Invalid investigation status: {status}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE investigation_control SET status = ? WHERE id = 1",
            (status,),
        )
        conn.commit()

def request_stop():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            UPDATE investigation_control
            SET status = 'stopping'
            WHERE id = 1 AND status = 'running'
        """)
        conn.commit()
        return cursor.rowcount == 1

def finish_investigation():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            UPDATE investigation_control
            SET status = 'stopped'
            WHERE id = 1 AND status = 'stopping'
        """)
        conn.commit()
        return cursor.rowcount == 1

def add_paper(filename):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT id FROM papers WHERE filename = ?",
            (filename,),
        )

        existing = cursor.fetchone()

        if existing:
            return existing[0]

        cursor = conn.execute(
            "INSERT INTO papers (filename) VALUES (?)",
            (filename,),
        )

        conn.commit()
        return cursor.lastrowid

def paper_exists(filename):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT 1 FROM papers WHERE filename = ?",
            (filename,),
        )

        return cursor.fetchone() is not None