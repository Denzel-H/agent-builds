import operator
import asyncio
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from papers import get_ready_papers
from transport import (
    get_pending_papers,
    execute_paper,
    get_investigation_status,
    finish_investigation,
    start_investigation,
    request_investigation_stop,
    transfer_paper,
    register_paper,
    paper_exists,
)

class GraphState(TypedDict):
    topic: str
    execution: dict
    max_workers: int
    pending_papers: list[dict]
    findings: Annotated[list[dict], operator.add]
    review: str
    status: str
    paper_directory: str
    registered_files: list[str]

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
    max_workers = state["max_workers"]

    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")

    papers = state["pending_papers"][:max_workers]

    if not papers:
        return "idle"

    tasks = []

    for paper in papers:
        task = Send(
            "research_worker",
            {
                "paper_id": paper["id"],
                "filename": paper["filename"],
                "topic": state["topic"],
                "execution": state["execution"],
            },
        )

        tasks.append(task)

    return tasks

async def check_investigation_status(state: GraphState):
    status = await get_investigation_status(state["execution"])
    return {"status": status}

def route_investigation(state: GraphState):
    status = state["status"]

    if status == "running":
        return "discover"

    elif status == "stopping":
        return "finish"

    elif status == "stopped":
        return END

    else:
        raise ValueError(f"Unknown investigation status: {status}")

async def finish_research(state: GraphState):
    result = await finish_investigation(state["execution"])

    if not result["finished"]:
        raise RuntimeError(
            f"Could not finish investigation: {result['status']}"
        )

    return {"status": "stopped"}

async def wait_for_papers(state: GraphState):
    while True:
        status = await get_investigation_status(
            state["execution"]
        )
        if status != "running":
            return {}
        papers = await get_pending_papers(
            state["execution"]
        )
        if papers:
            return {}
        await asyncio.sleep(2)

async def discover_papers(state: GraphState):
    registered = set(state["registered_files"])
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

builder = StateGraph(GraphState)

builder.add_node("check_status", check_investigation_status)
builder.add_node("load_pending", load_pending_papers)
builder.add_node("research_worker", research_worker)
builder.add_node("idle", wait_for_papers)
builder.add_node("finish", finish_research)
builder.add_node("discover", discover_papers)

builder.add_edge(START, "check_status")
builder.add_conditional_edges(
    "check_status",
    route_investigation,
)
builder.add_edge("discover", "load_pending")
builder.add_conditional_edges(
    "load_pending",
    dispatch_papers,
)
builder.add_edge("research_worker", "check_status")
builder.add_edge("idle", "check_status")
builder.add_edge("finish", END)

graph = builder.compile()



if __name__ == "__main__":
    execution = {
        "mode": "ssh",
        "host": "worker1",
        "project_dir": "/home/worker-android-env-1/agent-builds",
    }

    async def test():
        await start_investigation(execution)

        task = asyncio.create_task(
            graph.ainvoke(
                {
                    "topic": "Counter-UAS detection methods",
                    "execution": execution,
                    "max_workers": 3,
                    "pending_papers": [],
                    "findings": [],
                    "review": "",
                    "status": "running",
                    "paper_directory": "/Users/oa/research-papers/test",
                    "registered_files": [],
                },
                config={
                    "max_concurrency": 3,
                    "recursion_limit": 10000,
                },
            )
        )

        await asyncio.sleep(10)

        print(await request_investigation_stop(execution))

        result = await task
        print("Final status:", result["status"])

    asyncio.run(test())