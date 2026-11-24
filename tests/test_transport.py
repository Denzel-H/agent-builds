import asyncio
import json
import unittest
from unittest.mock import patch

from orchestrator import transport

LOCAL_EXECUTION = {"mode": "local", "project_dir": "/tmp/project"}
SSH_EXECUTION = {
    "mode": "ssh",
    "host": "worker1",
    "project_dir": "/home/worker/agent-builds",
}


class FakeProcess:
    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.communicated = None

    async def communicate(self, data=None):
        self.communicated = data
        return self.stdout, self.stderr


def process_for(payload):
    return FakeProcess(stdout=json.dumps(payload).encode(), stderr=b"", returncode=0)


class TransportInterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_command_uses_project_dir_and_devnull(self):
        with patch.object(
            transport.asyncio, "create_subprocess_exec", return_value=process_for([])
        ) as spawn:
            papers = await transport.get_pending_papers(LOCAL_EXECUTION)

        self.assertEqual(papers, [])
        args, kwargs = spawn.call_args
        self.assertEqual(args[:3], ("python3", "worker/database/cli.py", "pending"))
        self.assertEqual(kwargs["cwd"], "/tmp/project")
        self.assertIs(kwargs["stdin"], asyncio.subprocess.DEVNULL)

    async def test_ssh_command_uses_batch_mode_and_no_shell(self):
        with patch.object(
            transport.asyncio, "create_subprocess_exec", return_value=process_for([])
        ) as spawn:
            await transport.get_completed_research(SSH_EXECUTION)

        args, kwargs = spawn.call_args
        self.assertEqual(args[0], "ssh")
        self.assertIn("-o", args)
        self.assertIn("BatchMode=yes", args)
        self.assertIn("worker1", args)
        remote_command = args[-1]
        self.assertIn("/home/worker/agent-builds", remote_command)
        self.assertIn("worker/database/cli.py completed", remote_command)
        self.assertIs(kwargs["stdin"], asyncio.subprocess.DEVNULL)

    async def test_completed_research_is_retrieved_through_transport(self):
        records = [
            {
                "id": 1,
                "filename": "a.pdf",
                "citation": "cite",
                "findings": [{"text": "finding", "page": 1}],
            }
        ]
        with patch.object(
            transport.asyncio, "create_subprocess_exec", return_value=process_for(records)
        ):
            result = await transport.get_completed_research(LOCAL_EXECUTION)

        self.assertEqual(result, records)

    async def test_large_review_payload_is_sent_on_stdin(self):
        research = [{"id": i, "findings": [{"text": "x" * 100}]} for i in range(20)]
        fake = process_for({"success": True, "path": "output/review.md", "review": "r"})
        with patch.object(
            transport.asyncio, "create_subprocess_exec", return_value=fake
        ) as spawn:
            result = await transport.generate_review(
                "topic", research, SSH_EXECUTION, output_dir="/tmp/out"
            )

        self.assertTrue(result["success"])
        args, kwargs = spawn.call_args
        remote_command = args[-1]
        self.assertIn("worker/literature_writer.py", " ".join(args))
        self.assertIn("--output-dir", remote_command)
        self.assertIs(kwargs["stdin"], asyncio.subprocess.PIPE)
        payload = json.loads(fake.communicated.decode())
        self.assertEqual(payload["topic"], "topic")
        self.assertEqual(len(payload["research"]), 20)
        self.assertNotIn('"findings"', remote_command)

    async def test_nonzero_exit_raises_with_stderr(self):
        failing = FakeProcess(stderr=b"worker exploded", returncode=3)
        with patch.object(transport.asyncio, "create_subprocess_exec", return_value=failing):
            with self.assertRaisesRegex(RuntimeError, "worker exploded"):
                await transport.get_research_stats(LOCAL_EXECUTION)

    async def test_stats_are_retrieved(self):
        with patch.object(
            transport.asyncio,
            "create_subprocess_exec",
            return_value=process_for({"completed": 2, "pending": 1}),
        ):
            stats = await transport.get_research_stats(LOCAL_EXECUTION)

        self.assertEqual(stats["completed"], 2)

    async def test_paper_details_are_retrieved(self):
        details = [{"id": 1, "filename": "a.pdf", "status": "completed", "finding_count": 3}]
        with patch.object(
            transport.asyncio, "create_subprocess_exec", return_value=process_for(details)
        ):
            papers = await transport.get_papers(LOCAL_EXECUTION)

        self.assertEqual(papers, details)


if __name__ == "__main__":
    unittest.main()
