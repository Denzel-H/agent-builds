import operator
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from transport import get_pending_papers

class GraphState(TypedDict):
    topic: str
    execution: dict
    max_workers: int
    pending_papers: list[dict]
    findings: Annotated[list[dict], operator.add]
    review: str