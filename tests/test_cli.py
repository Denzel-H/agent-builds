import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from orchestrator import cli
from orchestrator.review_store import save_review

REVIEW = "# Literature Review\n\nSynthesized evidence [1].\n\n# References\n\n[1] A paper.\n"


def parse_output(buffer):
    return json.loads(buffer.getvalue())


class ConfigValidationTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.paper_dir = Path(temp_dir.name)
        self.output_dir = Path(temp_dir.name) / "output"

    def base_args(self):
        return cli.build_parser().parse_args([
            "start",
            "--topic", "Counter-UAS detection",
            "--paper-directory", str(self.paper_dir),
            "--mode", "local",
        ])

    def test_valid_research_config(self):
        config = cli.build_research_config(self.base_args())

        self.assertEqual(config["topic"], "Counter-UAS detection")
        self.assertEqual(config["max_workers"], 1)
        self.assertEqual(config["execution"]["mode"], "local")
        self.assertEqual(config["paper_directory"], str(self.paper_dir.resolve()))

    def test_topic_and_paper_directory_are_required(self):
        args = cli.build_parser().parse_args([
            "start", "--mode", "local", "--paper-directory", str(self.paper_dir)
        ])
        with self.assertRaisesRegex(ValueError, "topic"):
            cli.build_research_config(args)

        args = cli.build_parser().parse_args([
            "start", "--topic", "topic", "--mode", "local"
        ])
        with self.assertRaisesRegex(ValueError, "paper-directory"):
            cli.build_research_config(args)

    def test_ssh_requires_host_and_project_dir(self):
        args = cli.build_parser().parse_args([
            "start", "--topic", "topic",
            "--paper-directory", str(self.paper_dir),
            "--mode", "ssh",
        ])
        with self.assertRaisesRegex(ValueError, "--host"):
            cli.build_research_config(args)

    def test_max_workers_must_be_positive(self):
        args = cli.build_parser().parse_args([
            "start", "--topic", "topic",
            "--paper-directory", str(self.paper_dir),
            "--max-workers", "0",
        ])
        with self.assertRaisesRegex(ValueError, "at least 1"):
            cli.build_research_config(args)

    def test_config_file_values_are_used(self):
        config_file = self.paper_dir / "config.json"
        config_file.write_text(json.dumps({
            "topic": "From file",
            "paper_directory": str(self.paper_dir),
            "execution": {"mode": "local"},
            "max_workers": 4,
        }))
        args = cli.build_parser().parse_args([
            "start", "--config", str(config_file)
        ])

        config = cli.build_research_config(args)

        self.assertEqual(config["topic"], "From file")
        self.assertEqual(config["max_workers"], 4)


class CLICommandTests(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.output_dir = Path(temp_dir.name) / "output"
        self.path = Path(save_review(
            "topic", REVIEW, [], output_dir=str(self.output_dir)
        ))

    def test_finalize_command_reports_generated_review(self):
        result = {
            "review_generated": True,
            "review_path": str(self.path),
            "worker_review_path": "output/worker.md",
            "eligible_research": [{"id": 1}],
            "skipped_research": [],
            "review_error": "",
        }
        with patch.object(cli, "run_finalization", new=AsyncMock(return_value=result)):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cli.main([
                    "finalize", "--topic", "topic", "--mode", "local",
                    "--output-dir", str(self.output_dir),
                ])

        payload = parse_output(buffer)
        self.assertEqual(code, 0)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["review_path"], str(self.path))
        self.assertEqual(payload["eligible_papers"], 1)

    def test_review_command_returns_latest_path_and_content(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["review", "--output-dir", str(self.output_dir)])
        self.assertEqual(code, 0)
        self.assertEqual(parse_output(buffer)["path"], str(self.path))

        content = io.StringIO()
        with redirect_stdout(content):
            cli.main(["review", "--output-dir", str(self.output_dir), "--content"])
        self.assertIn("# Literature Review", content.getvalue())

    def test_status_command_can_include_per_paper_details(self):
        details = [{"id": 1, "filename": "a.pdf", "status": "completed", "finding_count": 3}]
        with patch.object(
            cli.transport, "get_investigation_status", new=AsyncMock(return_value="running")
        ), patch.object(
            cli.transport, "get_research_stats",
            new=AsyncMock(return_value={"completed": 1, "total": 1}),
        ), patch.object(
            cli.transport, "get_papers", new=AsyncMock(return_value=details)
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli.main(["status", "--mode", "local", "--papers"])

        payload = parse_output(buffer)
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["papers"]["completed"], 1)
        self.assertEqual(payload["paper_details"], details)

    def test_stop_command_uses_transport(self):
        with patch.object(
            cli.transport, "request_investigation_stop",
            new=AsyncMock(return_value={"stop_requested": True, "status": "stopping"}),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                cli.main(["stop", "--mode", "local"])

        self.assertTrue(parse_output(buffer)["stop_requested"])

    def test_background_start_detaches_and_returns_immediately(self):
        log_file = self.output_dir / "research.log"
        process = Mock(pid=4242)

        with patch.object(cli.subprocess, "Popen", return_value=process) as popen:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cli.main([
                    "start", "--topic", "topic",
                    "--paper-directory", str(self.output_dir.parent),
                    "--mode", "local",
                    "--background", "--log-file", str(log_file),
                ])

        payload = parse_output(buffer)
        self.assertEqual(code, 0)
        self.assertTrue(payload["started"])
        self.assertEqual(payload["pid"], 4242)
        self.assertEqual(payload["log"], str(log_file.resolve()))
        self.assertTrue(log_file.exists())

        args, kwargs = popen.call_args
        command = args[0]
        self.assertEqual(command[2], "start")
        self.assertNotIn("--background", command)
        self.assertNotIn("--log-file", command)
        self.assertIs(kwargs["stdin"], cli.subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
