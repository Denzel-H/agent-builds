import operator
import asyncio
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from transport import get_pending_papers, execute_paper

class GraphState(TypedDict):
    topic: str
    execution: dict
    max_workers: int
    pending_papers: list[dict]
    findings: Annotated[list[dict], operator.add]
    review: str

async def load_pending_papers(state: GraphState):
    papers = await get_pending_papers(state["execution"])

    return {"pending_papers": papers}

async def research_worker(state: dict):
    result = await execute_paper(
        paper_id=state["paper_id"],
        topic=state["topic"],
        filename=state["filename"],
        execution=state["execution"],
    )

    return {"findings": [result]}

def dispatch_papers(state: GraphState):
    papers = state["pending_papers"]
    if not papers:
        return END

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


builder = StateGraph(GraphState)

builder.add_node("load_pending", load_pending_papers)
builder.add_node("research_worker", research_worker)

builder.add_edge(START, "load_pending")

builder.add_conditional_edges(
    "load_pending",
    dispatch_papers,
)

builder.add_edge("research_worker", END)

graph = builder.compile()



if __name__ == "__main__":
    execution = {
        "mode": "ssh",
        "host": "worker1",
        "project_dir": "/home/worker-android-env-1/agent-builds",
    }
    result = asyncio.run(
        graph.ainvoke(
            {
                "topic": "Counter-UAS detection methods",
                "execution": execution,
                "max_workers": 3,
                "pending_papers": [],
                "findings": [],
                "review": "",
            },
            config={"max_concurrency": 3},
        )
    )

    print(result["pending_papers"])