"""LangGraph workflow definition.

    planner → researcher → extractor → analyst → writer → critic ─┬→ finalizer → END
                  ↑                                 ↑              │
                  └──────────── revise ─────────────┴──────────────┘ (bounded by MAX_REVISION_CYCLES)
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph import nodes
from app.graph.edges import route_after_critic, route_after_revise
from app.graph.state import ResearchState

NODE_ORDER = ["planner", "researcher", "extractor", "analyst", "writer", "critic", "revise", "finalizer"]


def build_workflow(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(ResearchState)
    graph.add_node("planner", nodes.planner)
    graph.add_node("researcher", nodes.researcher)
    graph.add_node("extractor", nodes.extractor)
    graph.add_node("analyst", nodes.analyst)
    graph.add_node("writer", nodes.writer)
    graph.add_node("critic", nodes.critic)
    graph.add_node("revise", nodes.revise)
    graph.add_node("finalizer", nodes.finalizer)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "extractor")
    graph.add_edge("extractor", "analyst")
    graph.add_edge("analyst", "writer")
    graph.add_edge("writer", "critic")
    graph.add_conditional_edges("critic", route_after_critic, {"revise": "revise", "finalizer": "finalizer"})
    graph.add_conditional_edges("revise", route_after_revise, {"researcher": "researcher", "writer": "writer"})
    graph.add_edge("finalizer", END)

    return graph.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
