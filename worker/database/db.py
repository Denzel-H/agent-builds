import json
import sqlite3
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).parent / "research.db"


def get_pending_papers():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM papers WHERE status = ?",
                ("pending",),
            )
            return [dict(row) for row in cursor.fetchall()]


def claim_paper(paper_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            cursor = conn.execute(
                """
                UPDATE papers
                SET status = 'processing'
                WHERE id = ? AND status = 'pending'
                """,
                (paper_id,),
            )
            return cursor.rowcount == 1


def failed_paper(paper_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            cursor = conn.execute(
                """
                UPDATE papers
                SET status = 'failed'
                WHERE id = ? AND status = 'processing'
                """,
                (paper_id,),
            )
            return cursor.rowcount == 1


def save_findings(paper_id, citation, findings):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            cursor = conn.execute(
                """
                UPDATE papers
                SET citation = ?, findings = ?, status = 'completed'
                WHERE id = ? AND status = 'processing'
                """,
                (citation, json.dumps(findings), paper_id),
            )
            return cursor.rowcount == 1


def get_investigation_status():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            cursor = conn.execute(
                "SELECT status FROM investigation_control WHERE id = 1"
            )
            row = cursor.fetchone()
            return row[0]


def set_investigation_status(status):
    valid_statuses = {"running", "stopping", "stopped"}

    if status not in valid_statuses:
        raise ValueError(f"Invalid investigation status: {status}")

    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            conn.execute(
                "UPDATE investigation_control SET status = ? WHERE id = 1",
                (status,),
            )


def request_stop():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            cursor = conn.execute("""
                UPDATE investigation_control
                SET status = 'stopping'
                WHERE id = 1 AND status = 'running'
            """)
            return cursor.rowcount == 1


def finish_investigation():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            cursor = conn.execute("""
                UPDATE investigation_control
                SET status = 'stopped'
                WHERE id = 1 AND status = 'stopping'
            """)
            return cursor.rowcount == 1


def add_paper(filename):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
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
            return cursor.lastrowid


def paper_exists(filename):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            cursor = conn.execute(
                "SELECT 1 FROM papers WHERE filename = ?",
                (filename,),
            )
            return cursor.fetchone() is not None


def deserialize_findings(raw_findings):
    """Return (findings, error) for a stored findings value.

    Malformed data is reported to the caller instead of being turned into
    fabricated research evidence.
    """
    if raw_findings is None or raw_findings == "":
        return [], None

    if isinstance(raw_findings, list):
        return raw_findings, None

    if not isinstance(raw_findings, str):
        return [], "Findings are not a JSON string or list"

    try:
        decoded = json.loads(raw_findings)
    except (TypeError, ValueError) as error:
        return [], f"Malformed findings JSON: {error}"

    if not isinstance(decoded, list):
        return [], "Findings JSON is not a list"

    return decoded, None


def get_completed_papers():
    """Return every completed paper with deserialized findings.

    Papers with an empty findings array are included so that the caller can
    distinguish "no relevant evidence" from a failed paper.  Papers that did
    not complete successfully are never returned.
    """
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, filename, citation, findings
                FROM papers
                WHERE status = 'completed'
                ORDER BY id
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]

    papers = []
    for row in rows:
        findings, error = deserialize_findings(row.get("findings"))
        row["findings"] = findings
        if error:
            row["findings_error"] = error
        papers.append(row)

    return papers


def get_paper_stats():
    """Return paper counts keyed by status, including a total."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) FROM papers GROUP BY status"
            )
            counts = {row[0]: row[1] for row in cursor.fetchall()}

    stats = {
        status: counts.get(status, 0)
        for status in ("pending", "processing", "completed", "failed")
    }
    stats["total"] = sum(stats.values())
    return stats


def get_papers():
    """Return per-paper status with finding counts, without full findings."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        with conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, filename, status, citation, findings
                FROM papers
                ORDER BY id
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]

    papers = []
    for row in rows:
        findings, error = deserialize_findings(row.pop("findings"))
        row["finding_count"] = len(findings)
        if error:
            row["findings_error"] = error
        papers.append(row)

    return papers
