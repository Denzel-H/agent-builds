import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from worker.database import db, init_db


class CompletedResearchTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.db_path = Path(temp_dir.name) / "research.db"

        db_patch = patch.object(db, "DB_PATH", self.db_path)
        init_patch = patch.object(init_db, "DB_PATH", self.db_path)
        db_patch.start()
        init_patch.start()
        self.addCleanup(db_patch.stop)
        self.addCleanup(init_patch.stop)

        init_db.initialize_database()

    def add_paper(self, filename, status, citation, findings):
        with closing(sqlite3.connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO papers (filename, status, citation, findings)
                    VALUES (?, ?, ?, ?)
                    """,
                    (filename, status, citation, findings),
                )

    def test_completed_research_includes_id_filename_citation_and_findings(self):
        self.add_paper(
            "paper-a.pdf",
            "completed",
            "J. Smith, \"A study,\" IEEE Trans. X, 2024.",
            '[{"text": "Finding one.", "page": 3}]',
        )
        self.add_paper("pending.pdf", "pending", None, "[]")
        self.add_paper("failed.pdf", "failed", None, "[]")

        papers = db.get_completed_papers()

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["filename"], "paper-a.pdf")
        self.assertEqual(paper["citation"], "J. Smith, \"A study,\" IEEE Trans. X, 2024.")
        self.assertEqual(paper["findings"], [{"text": "Finding one.", "page": 3}])
        self.assertNotIn("findings_error", paper)

    def test_findings_json_is_deserialized(self):
        findings = [
            {"text": "Result A.", "page": 1},
            {"text": "Result B.", "page": 4},
        ]
        self.add_paper("paper-a.pdf", "completed", "cite", json.dumps(findings))

        paper = db.get_completed_papers()[0]

        self.assertEqual(paper["findings"], findings)
        self.assertIsInstance(paper["findings"][0], dict)

    def test_completed_paper_with_empty_findings_is_preserved(self):
        self.add_paper("irrelevant.pdf", "completed", "cite", "[]")

        papers = db.get_completed_papers()

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["findings"], [])
        self.assertNotIn("findings_error", papers[0])

    def test_malformed_findings_are_reported_not_fabricated(self):
        self.add_paper("broken.pdf", "completed", "cite", "not-json")

        paper = db.get_completed_papers()[0]

        self.assertEqual(paper["findings"], [])
        self.assertIn("Malformed findings JSON", paper["findings_error"])

    def test_empty_completed_research(self):
        self.add_paper("pending.pdf", "pending", None, "[]")

        self.assertEqual(db.get_completed_papers(), [])

    def test_paper_stats(self):
        self.add_paper("a.pdf", "completed", "cite", "[]")
        self.add_paper("b.pdf", "failed", None, "[]")
        self.add_paper("c.pdf", "processing", None, "[]")

        stats = db.get_paper_stats()

        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["processing"], 1)
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["total"], 3)

    def test_paper_details_include_status_and_finding_counts(self):
        self.add_paper(
            "a.pdf", "completed", "cite",
            '[{"text": "finding one"}, {"text": "finding two"}]',
        )
        self.add_paper("b.pdf", "pending", None, "[]")

        papers = db.get_papers()

        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0]["filename"], "a.pdf")
        self.assertEqual(papers[0]["status"], "completed")
        self.assertEqual(papers[0]["finding_count"], 2)
        self.assertEqual(papers[1]["status"], "pending")
        self.assertNotIn("findings", papers[0])


if __name__ == "__main__":
    unittest.main()
