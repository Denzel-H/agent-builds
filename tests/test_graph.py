import unittest
from unittest.mock import AsyncMock, patch

from langgraph.graph import END
from langgraph.types import Send

from orchestrator import graph as graph_module

EXECUTION = {"mode": "local", "project_dir": "/tmp/project"}
CONFIG = {
    "topic": "Counter-UAS detection",
    "execution": EXECUTION,
    "max_workers": 2,
    "paper_directory": "/tmp/papers",
}


class DispatchTests(unittest.TestCase):
    def test_dispatch_respects_max_workers(self):
        state = {
            "topic": "topic",
            "execution": EXECUTION,
            "max_workers": 2,
            "pending_papers": [
                {"id": index, "filename": f"paper-{index}.pdf"}
                for index in range(5)
            ],
        }

        tasks = graph_module.dispatch_papers(state)

        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(isinstance(task, Send) for task in tasks))
        self.assertEqual(tasks[0].arg["paper_id"], 0)
        self.assertEqual(tasks[1].arg["paper_id"], 1)

    def test_empty_queue_is_idle_not_termination(self):
        state = {"max_workers": 2, "pending_papers": []}

        self.assertEqual(graph_module.dispatch_papers(state), "idle")

    def test_invalid_max_workers_is_rejected(self):
        with self.assertRaises(ValueError):
            graph_module.dispatch_papers({"max_workers": 0, "pending_papers": []})

    def test_route_investigation(self):
        self.assertEqual(
            graph_module.route_investigation({"status": "running"}), "discover"
        )
        self.assertEqual(
            graph_module.route_investigation({"status": "stopping"}), "finish"
        )
        self.assertEqual(graph_module.route_investigation({"status": "stopped"}), END)


class ResearchLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_for_papers_stops_when_status_changes(self):
        with patch.object(
            graph_module, "get_investigation_status", new=AsyncMock(return_value="stopping")
        ), patch.object(
            graph_module, "get_pending_papers", new=AsyncMock(return_value=[])
        ) as pending, patch.object(
            graph_module.asyncio, "sleep", new=AsyncMock(side_effect=AssertionError("slept"))
        ):
            result = await graph_module.wait_for_papers({"execution": EXECUTION})

        self.assertEqual(result, {})
        pending.assert_not_awaited()

    async def test_active_researchers_finish_after_graceful_stop(self):
        papers = [
            {"id": 1, "filename": "a.pdf"},
            {"id": 2, "filename": "b.pdf"},
        ]
        with patch.object(
            graph_module, "get_investigation_status",
            new=AsyncMock(side_effect=["running", "stopping"]),
        ), patch.object(
            graph_module, "get_ready_papers", return_value=[]
        ), patch.object(
            graph_module, "get_pending_papers", new=AsyncMock(return_value=papers)
        ), patch.object(
            graph_module, "execute_paper",
            new=AsyncMock(side_effect=lambda **kwargs: {
                "paper_id": kwargs["paper_id"], "processed": True,
            }),
        ) as execute, patch.object(
            graph_module, "finish_investigation",
            new=AsyncMock(return_value={"finished": True, "status": "stopped"}),
        ) as finish, patch.object(
            graph_module, "generate_review", new=AsyncMock()
        ) as writer:
            result = await graph_module.research_graph.ainvoke(
                {
                    "topic": CONFIG["topic"],
                    "execution": EXECUTION,
                    "max_workers": 2,
                    "paper_directory": "/tmp/papers",
                    "pending_papers": [],
                    "registered_files": [],
                    "findings": [],
                    "status": "running",
                },
                config={"max_concurrency": 2, "recursion_limit": 50},
            )

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(execute.await_count, 2)
        finish.assert_awaited_once()
        writer.assert_not_awaited()
        self.assertEqual(len(result["findings"]), 2)

    async def test_failed_researcher_does_not_terminate_investigation(self):
        with patch.object(
            graph_module, "execute_paper",
            new=AsyncMock(side_effect=RuntimeError("opencode failed")),
        ):
            result = await graph_module.research_worker(
                {
                    "paper_id": 7,
                    "filename": "bad.pdf",
                    "topic": "topic",
                    "execution": EXECUTION,
                }
            )

        self.assertFalse(result["findings"][0]["processed"])
        self.assertIn("opencode failed", result["findings"][0]["error"])

    async def test_finish_requires_successful_transition(self):
        with patch.object(
            graph_module, "finish_investigation",
            new=AsyncMock(return_value={"finished": False, "status": "running"}),
        ):
            with self.assertRaises(RuntimeError):
                await graph_module.finish_research({"execution": EXECUTION})


class FinalizationTests(unittest.IsolatedAsyncioTestCase):
    def records(self):
        return [
            {
                "id": 1,
                "filename": "a.pdf",
                "citation": "cite a",
                "findings": [{"text": "Finding A", "page": 1}],
            },
            {
                "id": 2,
                "filename": "b.pdf",
                "citation": "cite b",
                "findings": [{"text": "Finding B", "page": 2}],
            },
            {
                "id": 3,
                "filename": "irrelevant.pdf",
                "citation": "cite c",
                "findings": [],
            },
        ]

    async def run_finalization(self, records=None):
        with patch.object(
            graph_module, "get_completed_research",
            new=AsyncMock(return_value=self.records() if records is None else records),
        ), patch.object(
            graph_module, "generate_review",
            new=AsyncMock(return_value={
                "success": True,
                "review": "# Literature Review\n\nSynthesized across papers [1], [2].\n\n# References\n\n[1] a\n[2] b",
                "path": "output/worker-review.md",
            }),
        ) as writer, patch.object(
            graph_module, "save_local_review",
            return_value="/Users/me/output/review.md",
        ) as save:
            result = await graph_module.run_finalization(CONFIG)
            return result, writer, save

    async def test_finalization_hands_all_eligible_research_to_writer(self):
        result, writer, save = await self.run_finalization()

        self.assertTrue(result["review_generated"])
        writer.assert_awaited_once()
        kwargs = writer.await_args.kwargs
        self.assertEqual(kwargs["topic"], CONFIG["topic"])
        self.assertEqual(len(kwargs["research"]), 2)
        self.assertEqual(
            [item["filename"] for item in kwargs["research"]], ["a.pdf", "b.pdf"]
        )
        self.assertEqual(result["review_path"], "/Users/me/output/review.md")
        self.assertEqual(result["worker_review_path"], "output/worker-review.md")
        save.assert_called_once()

    async def test_empty_completed_research_does_not_invoke_writer(self):
        with patch.object(
            graph_module, "get_completed_research", new=AsyncMock(return_value=[])
        ), patch.object(
            graph_module, "generate_review", new=AsyncMock()
        ) as writer, patch.object(
            graph_module, "save_local_review"
        ) as save:
            result = await graph_module.run_finalization(CONFIG)

        self.assertFalse(result["review_generated"])
        self.assertIn("No completed papers", result["review_error"])
        writer.assert_not_awaited()
        save.assert_not_called()

    async def test_duplicate_writer_execution_is_prevented(self):
        state = {
            "topic": "topic",
            "execution": EXECUTION,
            "eligible_research": self.records()[:2],
            "writer_completed": True,
        }
        with patch.object(graph_module, "generate_review", new=AsyncMock()) as writer:
            result = await graph_module.write_literature_review(state)

        self.assertEqual(result, {})
        writer.assert_not_awaited()

    async def test_writer_failure_is_reported(self):
        with patch.object(
            graph_module, "get_completed_research",
            new=AsyncMock(return_value=self.records()),
        ), patch.object(
            graph_module, "generate_review",
            new=AsyncMock(side_effect=RuntimeError("OpenCode failed")),
        ), patch.object(graph_module, "save_local_review") as save:
            result = await graph_module.run_finalization(CONFIG)

        self.assertFalse(result["review_generated"])
        self.assertEqual(result["review_error"], "OpenCode failed")
        save.assert_not_called()

    async def test_malformed_research_excluded_from_review_input(self):
        records = self.records() + [
            {
                "id": 4,
                "filename": "broken.pdf",
                "citation": "cite",
                "findings": [],
                "findings_error": "Malformed findings JSON",
            }
        ]
        result, writer, _ = await self.run_finalization(records)

        self.assertEqual(len(writer.await_args.kwargs["research"]), 2)
        self.assertEqual(len(result["skipped_research"]), 2)


if __name__ == "__main__":
    unittest.main()
