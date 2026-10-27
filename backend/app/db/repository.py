"""Persistence operations for research tasks, events and sources."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update

from app.db.models import ResearchEvent, ResearchSource, ResearchTask, utcnow
from app.db.session import Database
from app.schemas.evidence import SourceRecord
from app.schemas.research import (
    ProgressEvent,
    ResearchDetail,
    ResearchPlan,
    ResearchReport,
    ResearchRequest,
    ResearchStatus,
    ResearchSummary,
    UsageStats,
)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite drops tzinfo; everything we store is UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class ResearchRepository:
    def __init__(self, db: Database):
        self.db = db

    # ---- tasks -------------------------------------------------------------
    def create_task(self, research_id: str, request: ResearchRequest) -> None:
        with self.db.session() as s:
            s.add(
                ResearchTask(
                    id=research_id,
                    question=request.question,
                    depth=request.depth,
                    request=request.model_dump(mode="json"),
                    status=ResearchStatus.queued.value,
                    usage={},
                    warnings=[],
                )
            )

    def update_task(self, research_id: str, **fields: Any) -> None:
        if "status" in fields and isinstance(fields["status"], ResearchStatus):
            fields["status"] = fields["status"].value
        fields["updated_at"] = utcnow()
        with self.db.session() as s:
            s.execute(update(ResearchTask).where(ResearchTask.id == research_id).values(**fields))

    def finish_task(
        self, research_id: str, event_type: str, message: str, data: dict[str, Any] | None = None, **fields: Any
    ) -> None:
        """Set a terminal status and record the terminal event in one transaction (no SSE race)."""
        if "status" in fields and isinstance(fields["status"], ResearchStatus):
            fields["status"] = fields["status"].value
        now = utcnow()
        fields.setdefault("completed_at", now)
        fields["updated_at"] = now
        with self.db.session() as s:
            s.execute(update(ResearchTask).where(ResearchTask.id == research_id).values(**fields))
            s.add(ResearchEvent(research_id=research_id, type=event_type, node=None, message=message, data=data or {}))

    def add_warning(self, research_id: str, warning: str) -> None:
        with self.db.session() as s:
            task = s.get(ResearchTask, research_id)
            if task is None:
                return
            if warning not in (task.warnings or []):
                task.warnings = [*(task.warnings or []), warning]
                task.updated_at = utcnow()

    def get_status(self, research_id: str) -> ResearchStatus | None:
        with self.db.session() as s:
            status = s.scalar(select(ResearchTask.status).where(ResearchTask.id == research_id))
        return ResearchStatus(status) if status else None

    def get_detail(self, research_id: str) -> ResearchDetail | None:
        with self.db.session() as s:
            task = s.get(ResearchTask, research_id)
            if task is None:
                return None
            return self._detail(task)

    def list_tasks(self, limit: int = 20, offset: int = 0) -> list[ResearchSummary]:
        with self.db.session() as s:
            rows = s.scalars(
                select(ResearchTask).order_by(ResearchTask.created_at.desc()).limit(limit).offset(offset)
            ).all()
            return [self._summary(t) for t in rows]

    def mark_interrupted_tasks(self) -> int:
        """Tasks left running by a previous process can never finish; fail them explicitly."""
        with self.db.session() as s:
            result = s.execute(
                update(ResearchTask)
                .where(ResearchTask.status.in_([ResearchStatus.queued.value, ResearchStatus.running.value]))
                .values(
                    status=ResearchStatus.failed.value,
                    error="Interrupted: the server restarted before this research finished.",
                    updated_at=utcnow(),
                    completed_at=utcnow(),
                )
            )
            return result.rowcount or 0

    def save_report(self, report: ResearchReport) -> None:
        self.update_task(
            report.research_id,
            report=report.model_dump(mode="json"),
            title=report.title,
        )

    def get_report(self, research_id: str) -> ResearchReport | None:
        with self.db.session() as s:
            data = s.scalar(select(ResearchTask.report).where(ResearchTask.id == research_id))
        return ResearchReport.model_validate(data) if data else None

    # ---- sources -----------------------------------------------------------
    def replace_sources(self, research_id: str, sources: list[SourceRecord]) -> None:
        with self.db.session() as s:
            s.execute(delete(ResearchSource).where(ResearchSource.research_id == research_id))
            for position, src in enumerate(sources):
                s.add(
                    ResearchSource(
                        research_id=research_id,
                        source_id=src.source_id,
                        position=position,
                        record=src.model_dump(mode="json"),
                    )
                )
            s.execute(
                update(ResearchTask)
                .where(ResearchTask.id == research_id)
                .values(source_count=len(sources), updated_at=utcnow())
            )

    def get_sources(self, research_id: str) -> list[SourceRecord]:
        with self.db.session() as s:
            rows = s.scalars(
                select(ResearchSource.record)
                .where(ResearchSource.research_id == research_id)
                .order_by(ResearchSource.position)
            ).all()
        return [SourceRecord.model_validate(r) for r in rows]

    # ---- events ------------------------------------------------------------
    def add_event(
        self,
        research_id: str,
        type: str,
        message: str,
        node: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> ProgressEvent:
        with self.db.session() as s:
            row = ResearchEvent(
                research_id=research_id, type=type, node=node, message=message, data=data or {}
            )
            s.add(row)
            s.flush()
            return self._event(row)

    def get_events(self, research_id: str, after_id: int = 0, limit: int = 500) -> list[ProgressEvent]:
        with self.db.session() as s:
            rows = s.scalars(
                select(ResearchEvent)
                .where(ResearchEvent.research_id == research_id, ResearchEvent.id > after_id)
                .order_by(ResearchEvent.id)
                .limit(limit)
            ).all()
            return [self._event(r) for r in rows]

    # ---- mapping -----------------------------------------------------------
    @staticmethod
    def _event(row: ResearchEvent) -> ProgressEvent:
        return ProgressEvent(
            id=row.id,
            research_id=row.research_id,
            type=row.type,
            node=row.node,
            message=row.message,
            data=row.data or {},
            timestamp=_aware(row.created_at),
        )

    @staticmethod
    def _summary(task: ResearchTask) -> ResearchSummary:
        return ResearchSummary(
            id=task.id,
            question=task.question,
            title=task.title,
            status=ResearchStatus(task.status),
            depth=task.depth,
            current_stage=task.current_stage,
            source_count=task.source_count or 0,
            revision_count=task.revision_count or 0,
            created_at=_aware(task.created_at),
            updated_at=_aware(task.updated_at),
            completed_at=_aware(task.completed_at),
        )

    def _detail(self, task: ResearchTask) -> ResearchDetail:
        summary = self._summary(task)
        started = _aware(task.started_at)
        elapsed = None
        if started:
            end = _aware(task.completed_at) or utcnow()
            elapsed = round((end - started).total_seconds(), 1)
        return ResearchDetail(
            **summary.model_dump(),
            request=ResearchRequest.model_validate(task.request),
            plan=ResearchPlan.model_validate(task.plan) if task.plan else None,
            error=task.error,
            warnings=task.warnings or [],
            usage=UsageStats.model_validate(task.usage or {}),
            elapsed_seconds=elapsed,
            has_report=task.report is not None,
        )
