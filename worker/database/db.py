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

def complete_paper(paper_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE papers
            SET status = 'completed'
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
