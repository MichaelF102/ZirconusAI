"""Conditional routing for the research graph."""

from __future__ import annotations

from typing import Literal

from langchain_core.runnables import RunnableConfig

from app.graph.context import get_ctx
from app.graph.state import ResearchState


def route_after_critic(state: ResearchState, config: RunnableConfig) -> Literal["revise", "finalizer"]:
    """Revise while material problems remain and the revision budget is not exhausted."""
    critic = state.get("critic")
    if critic is None or not critic.requires_revision:
        return "finalizer"
    if state.get("revision_count", 0) >= get_ctx(config).settings.max_revision_cycles:
        return "finalizer"
    return "revise"


def route_after_revise(state: ResearchState) -> Literal["researcher", "writer"]:
    """Targeted research when the critic found evidence gaps; otherwise rewrite with critic feedback."""
    return "researcher" if state.get("pending_queries") else "writer"

