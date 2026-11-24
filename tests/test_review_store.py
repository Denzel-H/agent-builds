import tempfile
import unittest
from pathlib import Path

from orchestrator import review_store

REVIEW = """# Literature Review

A synthesized review of the supplied evidence [1].

# References

[1] A. Author, "A paper," IEEE X, 2024.
"""


class ReviewStoreTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.output_dir = Path(temp_dir.name)

    def test_save_review_creates_utf8_markdown_with_metadata(self):
        path = Path(review_store.save_review(
            "Counter-UAS detection",
            REVIEW,
            [{"id": 1, "filename": "paper-a.pdf"}],
            output_dir=str(self.output_dir),
        ))

        self.assertTrue(path.is_file())
        self.assertEqual(path.suffix, ".md")
        content = path.read_text(encoding="utf-8")
        self.assertIn('topic: "Counter-UAS detection"', content)
        self.assertIn("generated_at:", content)
        self.assertIn("source_count: 1", content)
        self.assertIn("paper-a.pdf", content)
        self.assertIn("# Literature Review", content)

    def test_reviews_do_not_overwrite_previous_files(self):
        first = review_store.save_review("t", REVIEW, [], output_dir=str(self.output_dir))
        second = review_store.save_review("t", REVIEW, [], output_dir=str(self.output_dir))

        self.assertNotEqual(first, second)
        self.assertEqual(len(list(self.output_dir.glob("review-*.md"))), 2)

    def test_latest_review_retrieval(self):
        first = Path(review_store.save_review(
            "t", REVIEW, [], output_dir=str(self.output_dir)
        ))
        second = Path(review_store.save_review(
            "t", REVIEW, [], output_dir=str(self.output_dir)
        ))
        import os
        os.utime(first, (1, 1))
        os.utime(second, (2, 2))

        self.assertEqual(
            review_store.get_latest_review(output_dir=str(self.output_dir)),
            str(second),
        )
        self.assertIn("# Literature Review", review_store.read_review(second))

    def test_empty_output_directory(self):
        self.assertIsNone(review_store.get_latest_review(output_dir=str(self.output_dir)))

    def test_empty_review_is_rejected(self):
        with self.assertRaises(ValueError):
            review_store.save_review("t", "  ", [], output_dir=str(self.output_dir))


if __name__ == "__main__":
    unittest.main()
