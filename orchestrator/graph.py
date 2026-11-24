import operator
import asyncio
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

try:
    from .papers import get_ready_papers
    from .transport import (
        get_pending_papers,
        get_completed_research,
        get_research_stats,
        generate_review,
        execute_paper,
        get_investigation_status,
        finish_investigation,
        start_investigation,
        request_investigation_stop,
        transfer_paper,
        register_paper,
        paper_exists,
    )
    from .review_store import save_review as save_local_review
except ImportError:  # executed directly as `python3 orchestrator/graph.py`
    from papers import get_ready_papers
    from transport import (
        get_pending_papers,
        get_completed_research,
        get_research_stats,
        generate_review,
        execute_paper,
        get_investigation_status,
        finish_investigation,
        start_investigation,
        request_investigation_stop,
        transfer_paper,
        register_paper,
        paper_exists,
    )
    from review_store import save_review as save_local_review


DEFAULT_POLL_INTERVAL = 2
DEFAULT_RECURSION_LIMIT = 10000


class GraphState(TypedDict, total=False):
    topic: str
    execution: dict
    max_workers: int
    paper_directory: str
    poll_interval: float
    output_dir: str | None
    pending_papers: list[dict]
    registered_files: list[str]
    findings: Annotated[list[dict], operator.add]
    status: str
    completed_research: list[dict]
    eligible_research: list[dict]
    skipped_research: list[dict]
    review: str
    review_path: str
    worker_review_path: str
    review_generated: bool
    writer_completed: bool
    review_error: str


# ---------------------------------------------------------------------------
# Research graph: continuous discovery and bounded concurrent researchers
# ---------------------------------------------------------------------------

async def load_pending_papers(state: GraphState):
    papers = await get_pending_papers(state["execution"])
    return {"pending_papers": papers}


async def research_worker(state: dict):
    paper_id = state["paper_id"]

    try:
        result = await execute_paper(
            paper_id=paper_id,
            topic=state["topic"],
            filename=state["filename"],
            execution=state["execution"],
        )
    except Exception as error:
        result = {
            "paper_id": paper_id,
            "processed": False,
            "error": str(error),
        }

    return {"findings": [result]}


def dispatch_papers(state: GraphState):
    max_workers = state.get("max_workers", 1)
    if not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers must be at least 1")

    papers = state.get("pending_papers", [])[:max_workers]
    if not papers:
        return "idle"

    return [
        Send(
            "research_worker",
            {
                "paper_id": paper["id"],
                "filename": paper["filename"],
                "topic": state["topic"],
                "execution": state["execution"],
            },
        )
        for paper in papers
    ]


async def check_investigation_status(state: GraphState):
    status = await get_investigation_status(state["execution"])
    return {"status": status}


def route_investigation(state: GraphState):
    status = state["status"]

    if status == "running":
        return "discover"
    if status == "stopping":
        return "finish"
    if status == "stopped":
        return END

    raise ValueError(f"Unknown investigation status: {status}")


async def finish_research(state: GraphState):
    result = await finish_investigation(state["execution"])

    if not result.get("finished"):
        raise RuntimeError(
            f"Could not finish investigation: {result.get('status')}"
        )

    return {"status": "stopped"}


async def wait_for_papers(state: GraphState):
    """Wait for new PDFs without ending an active investigation."""
    execution = state["execution"]
    interval = state.get("poll_interval", DEFAULT_POLL_INTERVAL)

    while True:
        status = await get_investigation_status(execution)
        if status != "running":
            return {}

        papers = await get_pending_papers(execution)
        if papers:
            return {}

        await asyncio.sleep(interval)


async def discover_papers(state: GraphState):
    registered = set(state.get("registered_files", []))
    execution = state["execution"]

    for paper in get_ready_papers(state["paper_directory"]):
        if str(paper) in registered:
            continue

        if execution["mode"] == "ssh":
            filename = f"papers/{paper.name}"
        else:
            filename = str(paper)

        if await paper_exists(filename, execution):
            registered.add(str(paper))
            continue

        filename = await transfer_paper(paper, execution)
        await register_paper(filename, execution)

        registered.add(str(paper))

    return {"registered_files": sorted(registered)}


research_builder = StateGraph(GraphState)
research_builder.add_node("check_status", check_investigation_status)
research_builder.add_node("load_pending", load_pending_papers)
research_builder.add_node("research_worker", research_worker)
research_builder.add_node("idle", wait_for_papers)
research_builder.add_node("finish", finish_research)
research_builder.add_node("discover", discover_papers)

research_builder.add_edge(START, "check_status")
research_builder.add_conditional_edges("check_status", route_investigation)
research_builder.add_edge("discover", "load_pending")
research_builder.add_conditional_edges("load_pending", dispatch_papers)
research_builder.add_edge("research_worker", "check_status")
research_builder.add_edge("idle", "check_status")
research_builder.add_edge("finish", END)

research_graph = research_builder.compile()
graph = research_graph  # backwards-compatible name for the research graph


# ---------------------------------------------------------------------------
# Finalization graph: explicit, one-shot literature review generation
# ---------------------------------------------------------------------------

def select_eligible_for_review(records):
    eligible = []
    skipped = []

    for record in records:
        if not isinstance(record, dict):
            skipped.append({"reason": "Invalid research record"})
            continue

        if record.get("findings_error"):
            skipped.append({
                "filename": record.get("filename"),
                "reason": record["findings_error"],
            })
            continue

        findings = record.get("findings")
        if not isinstance(findings, list) or not findings:
            skipped.append({
                "filename": record.get("filename"),
                "reason": "No relevant findings",
            })
            continue

        eligible.append(record)

    return eligible, skipped


async def collect_completed_research(state: GraphState):
    records = await get_completed_research(state["execution"])
    eligible, skipped = select_eligible_for_review(records)
    return {
        "completed_research": records,
        "eligible_research": eligible,
        "skipped_research": skipped,
    }


async def write_literature_review(state: GraphState):
    if state.get("writer_completed") or state.get("review_generated"):
        return {}

    if not state.get("eligible_research"):
        return {
            "writer_completed": True,
            "review_generated": False,
            "review_error": "No completed papers with relevant findings are available",
        }

    try:
        result = await generate_review(
            topic=state["topic"],
            research=state["eligible_research"],
            execution=state["execution"],
            output_dir=state.get("output_dir"),
        )
    except Exception as error:
        return {
            "writer_completed": True,
            "review_generated": False,
            "review_error": str(error),
        }

    if not result.get("success") or not result.get("review", "").strip():
        return {
            "writer_completed": True,
            "review_generated": False,
            "review_error": result.get("error", "Literature writer produced no output"),
        }

    return {
        "writer_completed": True,
        "review_generated": True,
        "review": result["review"],
        "worker_review_path": result.get("path", ""),
        "review_error": "",
    }


async def persist_literature_review(state: GraphState):
    if not state.get("review_generated"):
        return {}

    path = save_local_review(
        topic=state["topic"],
        review=state["review"],
        records=state.get("eligible_research", []),
        output_dir=state.get("output_dir"),
    )
    return {"review_path": path}


finalization_builder = StateGraph(GraphState)
finalization_builder.add_node("collect", collect_completed_research)
finalization_builder.add_node("write", write_literature_review)
finalization_builder.add_node("save", persist_literature_review)

finalization_builder.add_edge(START, "collect")
finalization_builder.add_edge("collect", "write")
finalization_builder.add_edge("write", "save")
finalization_builder.add_edge("save", END)

finalization_graph = finalization_builder.compile()


async def run_research(config, poll_interval=DEFAULT_POLL_INTERVAL,
                       recursion_limit=DEFAULT_RECURSION_LIMIT):
    """Start an investigation and block until it is gracefully stopped."""
    execution = config["execution"]
    max_workers = config["max_workers"]

    await start_investigation(execution)

    return await research_graph.ainvoke(
        {
            "topic": config["topic"],
            "execution": execution,
            "max_workers": max_workers,
            "paper_directory": config["paper_directory"],
            "poll_interval": poll_interval,
            "output_dir": config.get("output_dir"),
            "pending_papers": [],
            "registered_files": [],
            "findings": [],
            "status": "running",
        },
        config={
            "max_concurrency": max_workers,
            "recursion_limit": recursion_limit,
        },
    )


async def run_finalization(config):
    """Explicitly generate and save one literature review."""
    return await finalization_graph.ainvoke(
        {
            "topic": config["topic"],
            "execution": config["execution"],
            "output_dir": config.get("output_dir"),
            "writer_completed": False,
            "review_generated": False,
            "review_error": "",
        },
        config={"recursion_limit": 50},
    )


if __name__ == "__main__":
    execution = {
        "mode": "ssh",
        "host": "worker1",
        "project_dir": "/home/worker-android-env-1/agent-builds",
    }
    config = {
        "topic": "Counter-UAS detection methods",
        "execution": execution,
        "max_workers": 3,
        "paper_directory": "/Users/oa/research-papers/test",
    }

    async def test():
        print("Starting investigation...")
        print(await start_investigation(execution))

        task = asyncio.create_task(graph.ainvoke(
            {
                "topic": config["topic"],
                "execution": execution,
                "max_workers": config["max_workers"],
                "pending_papers": [],
                "findings": [],
                "review": "",
                "status": "running",
                "paper_directory": config["paper_directory"],
                "registered_files": [],
            },
            config={
                "max_concurrency": config["max_workers"],
                "recursion_limit": 10000,
            },
        ))

        await asyncio.sleep(10)

        print(await request_investigation_stop(execution))

        result = await task
        print("Final research status:", result["status"])
        print("Paper stats:", await get_research_stats(execution))

        final = await run_finalization(config)
        print("Review generated:", final.get("review_generated"))
        print("Review path:", final.get("review_path"))
        if final.get("review_error"):
            print("Review error:", final["review_error"])

    asyncio.run(test())
