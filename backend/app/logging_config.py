"""Logging setup with secret redaction."""

from __future__ import annotations

import logging
import re

_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|authorization|bearer|token|secret)([\"'=:\s]+)([A-Za-z0-9_\-\.]{8,})"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google API keys
    re.compile(r"tvly-[0-9A-Za-z_\-]{10,}"),  # Tavily keys
]


class RedactSecretsFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self._secrets = [s for s in (secrets or []) if s and len(s) >= 6]

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED]")
        text = _PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        for pattern in _PATTERNS[1:]:
            text = pattern.sub("[REDACTED]", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = self.redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def configure_logging(level: str, secrets: list[str]) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    if not any(getattr(h, "_research_agent", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler._research_agent = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    redactor = RedactSecretsFilter(secrets)
    for handler in root.handlers:
        handler.filters = [f for f in handler.filters if not isinstance(f, RedactSecretsFilter)]
        handler.addFilter(redactor)
    for noisy in ("httpx", "httpcore", "trafilatura", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
