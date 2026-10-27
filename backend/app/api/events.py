"""Server-Sent Events stream of persisted workflow progress.

Events are read from the database (the source of truth), so a client can reconnect with the
standard ``Last-Event-ID`` header (or ``?after=``) and resume exactly where it left off.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_repo
from app.db.repository import ResearchRepository

router = APIRouter(prefix="/api/research", tags=["events"])

POLL_INTERVAL_SECONDS = 0.5


@router.get("/{research_id}/events")
async def stream_events(
    research_id: str,
    request: Request,
    after: int = Query(0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    repo: ResearchRepository = Depends(get_repo),
):
    if repo.get_status(research_id) is None:
        raise HTTPException(404, "Research task not found")
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after

    async def generator():
        nonlocal cursor
        while True:
            if await request.is_disconnected():
                return
            events = repo.get_events(research_id, after_id=cursor)
            for event in events:
                cursor = event.id
                yield {"id": str(event.id), "event": "progress", "data": event.model_dump_json()}
            if events:
                continue
            status = repo.get_status(research_id)
            if status is None or status.is_terminal:
                # Terminal status and its event are written atomically, so the backlog is complete.
                yield {"event": "end", "data": json.dumps({"status": status.value if status else "unknown"})}
                return
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    return EventSourceResponse(generator(), ping=15, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
