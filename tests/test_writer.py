import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from worker import literature_writer as writer

VALID_REVIEW = """# Literature Review

Prior work converges on the value of combining complementary sensors for
detection [1]. Other studies emphasize the importance of field evaluation [2].
Taken together, these results suggest that no single sensing modality is
sufficient across all operating conditions.

# References

[1] A. Author, "Sensor fusion study," IEEE Trans. X, 2024.
[2] B. Writer, "Field evaluation," Proc. Conf. Y, 2023.
"""

RECORDS = [
    {
        "id": 1,
        "filename": "paper-a.pdf",
        "citation": "A. Author, \"Sensor fusion study,\" IEEE Trans. X, 2024.",
        "findings": [{"text": "Sensor fusion improved detection.", "page": 2}],
    },
    {
        "id": 2,
        "filename": "paper-b.pdf",
        "citation": "B. Writer, \"Field evaluation,\" Proc. Conf. Y, 2023.",
        "findings": [{"text": "Field tests showed variability.", "page": 5}],
    },
]


class WriterInvocationTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.output_dir = Path(temp_dir.name) / "output"

    def successful_run(self, stdout=VALID_REVIEW):
        return Mock(returncode=0, stdout=stdout, stderr="")

    def test_invokes_existing_agent_noninteractively(self):
        seen = {}

        def fake_run(command, **kwargs):
            seen["command"] = command
            seen["kwargs"] = kwargs
            seen["prompt"] = Path(command[command.index("--file") + 1]).read_text(
                encoding="utf-8"
            )
            return self.successful_run()

        with patch.object(writer.subprocess, "run", side_effect=fake_run):
            result = writer.write_review(
                "Counter-UAS detection", RECORDS, output_dir=str(self.output_dir)
            )

        command = seen["command"]
        self.assertEqual(command[0], "opencode")
        self.assertEqual(command[1], "run")
        self.assertEqual(command[2], "--agent")
        self.assertEqual(command[3], "literature-writer")
        self.assertIn("--file", command)
        self.assertIs(seen["kwargs"]["stdin"], writer.subprocess.DEVNULL)
        self.assertFalse(seen["kwargs"]["check"])

        prompt = json.loads(seen["prompt"])
        self.assertEqual(prompt["topic"], "Counter-UAS detection")
        self.assertEqual(len(prompt["research"]), 2)
        self.assertEqual(prompt["research"][0]["findings"], RECORDS[0]["findings"])

        self.assertTrue(result["success"])
        self.assertEqual(result["paper_count"], 2)
        self.assertEqual(result["skipped_count"], 0)
        self.assertTrue(Path(result["path"]).is_file())

    def test_markdown_file_contains_metadata(self):
        with patch.object(writer.subprocess, "run", return_value=self.successful_run()):
            result = writer.write_review(
                "Counter-UAS detection", RECORDS, output_dir=str(self.output_dir)
            )

        content = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn('topic: "Counter-UAS detection"', content)
        self.assertIn("generated_at:", content)
        self.assertIn("paper-a.pdf", content)
        self.assertIn("# Literature Review", content)
        self.assertIn("[1]", content)

    def test_empty_findings_are_excluded_from_writer_input(self):
        records = RECORDS + [
            {
                "id": 3,
                "filename": "irrelevant.pdf",
                "citation": "cite",
                "findings": [],
            }
        ]
        seen = {}

        def fake_run(command, **kwargs):
            seen["prompt"] = Path(command[command.index("--file") + 1]).read_text()
            return self.successful_run()

        with patch.object(writer.subprocess, "run", side_effect=fake_run):
            result = writer.write_review(
                "topic", records, output_dir=str(self.output_dir)
            )

        prompt = json.loads(seen["prompt"])
        self.assertEqual(len(prompt["research"]), 2)
        self.assertEqual(result["skipped_count"], 1)

    def test_invalid_writer_output_is_rejected(self):
        invalid_outputs = [
            "short",
            "# Wrong heading\n\n" + ("text " * 60) + "\n\n# References\n\n[1] x",
            "# Literature Review\n\n" + ("text " * 60),
        ]
        for output in invalid_outputs:
            with self.subTest(output=output[:30]):
                with patch.object(
                    writer.subprocess, "run", return_value=self.successful_run(output)
                ):
                    with self.assertRaises(ValueError):
                        writer.write_review(
                            "topic", RECORDS, output_dir=str(self.output_dir)
                        )

    def test_writer_subprocess_failure_is_reported(self):
        failure = Mock(returncode=2, stdout="", stderr="model unavailable")
        with patch.object(writer.subprocess, "run", return_value=failure):
            with self.assertRaisesRegex(RuntimeError, "model unavailable"):
                writer.write_review(
                    "topic", RECORDS, output_dir=str(self.output_dir)
                )

    def test_no_eligible_research_is_an_error(self):
        with patch.object(writer.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                writer.write_review(
                    "topic", [{"id": 1, "filename": "a.pdf", "findings": []}],
                    output_dir=str(self.output_dir),
                )
        run.assert_not_called()

    def test_load_payload_rejects_missing_topic_or_research(self):
        with self.assertRaises(json.JSONDecodeError):
            writer.load_payload(io.StringIO("not json"))
        with self.assertRaises(ValueError):
            writer.load_payload(io.StringIO('{"topic": "t"}'))
        with self.assertRaises(ValueError):
            writer.load_payload(io.StringIO('{"research": []}'))

    def test_review_names_do_not_collide(self):
        with patch.object(writer.subprocess, "run", return_value=self.successful_run()):
            first = writer.write_review("topic", RECORDS, output_dir=str(self.output_dir))
            second = writer.write_review("topic", RECORDS, output_dir=str(self.output_dir))

        self.assertNotEqual(first["path"], second["path"])
        self.assertEqual(len(list(self.output_dir.glob("review-*.md"))), 2)


if __name__ == "__main__":
    unittest.main()
