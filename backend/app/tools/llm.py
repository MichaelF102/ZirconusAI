"""LLM client abstraction with a Gemini implementation."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when the model call fails or returns output that does not match the schema."""


class LLMClient(Protocol):
    name: str

    async def generate(self, schema: type[T], system: str, prompt: str) -> tuple[T, dict[str, int]]:
        """Return a parsed instance of ``schema`` and token usage ({input_tokens, output_tokens})."""
        ...


class GeminiLLM:
    """Gemini via langchain-google-genai, using native JSON-schema structured output."""

    def __init__(self, api_key: str, model: str, timeout: float = 90, temperature: float = 0.2):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not configured")
        from langchain_google_genai import ChatGoogleGenerativeAI

        self.name = f"gemini:{model}"
        # Retries are handled by our own backoff wrapper so they are bounded and logged consistently.
        self._chat = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=temperature,
            timeout=timeout,
            max_retries=0,
        )

    async def generate(self, schema: type[T], system: str, prompt: str) -> tuple[T, dict[str, int]]:
        from langchain_core.messages import HumanMessage, SystemMessage

        runnable = self._chat.with_structured_output(schema, include_raw=True)
        result = await runnable.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)])
        parsed = result.get("parsed") if isinstance(result, dict) else result
        if result.get("parsing_error") or parsed is None:
            raise LLMError(f"Model output did not match {schema.__name__}: {result.get('parsing_error')}")
        if isinstance(parsed, dict):
            parsed = schema.model_validate(parsed)
        raw = result.get("raw")
        usage = getattr(raw, "usage_metadata", None) or {}
        return parsed, {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
        }
