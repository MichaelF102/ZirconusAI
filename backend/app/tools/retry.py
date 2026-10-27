"""Exponential backoff for transient failures."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")

_TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, asyncio.TimeoutError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_STATUS
    # Google / LangChain errors don't share a base class; fall back to message heuristics.
    text = f"{type(exc).__name__} {exc}".lower()
    return any(
        marker in text
        for marker in ("429", "resource_exhausted", "rate limit", "503", "unavailable", "deadline", "timeout", "overloaded")
    )


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    label: str = "operation",
    retry_if: Callable[[BaseException], bool] = is_transient,
) -> T:
    attempt = 0
    while True:
        try:
            return await fn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if attempt >= max_retries or not retry_if(exc):
                raise
            delay = min(max_delay, base_delay * 2**attempt) * (0.5 + random.random() / 2)
            attempt += 1
            logger.warning("%s failed (%s); retry %d/%d in %.1fs", label, type(exc).__name__, attempt, max_retries, delay)
            await asyncio.sleep(delay)
