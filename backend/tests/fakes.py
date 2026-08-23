"""Test doubles for the LLM provider.

No test in this suite touches the network. That keeps the suite fast, free and
deterministic, and it means the graph's control flow is verified independently of
whether a model happens to behave well on a given day.

``scripts/demo_run.py`` exercises the real provider separately.
"""

from __future__ import annotations

import hashlib
from typing import Any, TypeVar

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.llm.factory import LLMError, Purpose

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def _schema_name(schema: Any) -> str:
    """Accept a schema class or its bare name as a key."""
    return schema if isinstance(schema, str) else str(schema.__name__)


class ScriptedProvider:
    """Returns pre-built objects, keyed by the schema being requested.

    Keying on schema rather than call order keeps tests readable: a test says
    "extraction yields this brief" instead of "the third call returns this".
    """

    def __init__(self, responses: dict[Any, Any] | None = None) -> None:
        # Keys may be the schema class or its name, so tests can override via
        # keyword arguments without importing every schema.
        self._responses: dict[str, Any] = {
            _schema_name(schema): value for schema, value in (responses or {}).items()
        }
        self.calls: list[tuple[str, Purpose]] = []

    def set(self, schema: type[BaseModel] | str, value: Any) -> None:
        self._responses[_schema_name(schema)] = value

    def structured(
        self,
        schema: type[SchemaT],
        messages: list[BaseMessage],
        *,
        purpose: Purpose = "main",
    ) -> SchemaT:
        self.calls.append((schema.__name__, purpose))

        if schema.__name__ not in self._responses:
            raise AssertionError(
                f"ScriptedProvider has no response for {schema.__name__}. "
                "Add one, or the test is exercising an unintended path."
            )

        value = self._responses[schema.__name__]
        # A queue lets one test script successive answers for the same schema,
        # which the clarification loop needs.
        if isinstance(value, list):
            if not value:
                raise AssertionError(f"ScriptedProvider ran out of {schema.__name__} responses")
            value = value.pop(0)
        if isinstance(value, Exception):
            # Honour the provider contract: OpenAIProvider wraps every failure in
            # LLMError, so a fake must not leak a raw exception type that
            # production could never produce.
            raise value if isinstance(value, LLMError) else LLMError(str(value)) from value
        if not isinstance(value, schema):
            raise AssertionError(f"scripted {type(value).__name__} is not a {schema.__name__}")
        return value

    def prompt_text(self, index: int = -1) -> str:
        """Not recorded here - see :class:`CapturingProvider`."""
        raise NotImplementedError


class FailingProvider:
    """Fails every call, to prove failures degrade rather than crash."""

    def __init__(self, message: str = "simulated provider outage") -> None:
        self._message = message
        self.calls = 0

    def structured(
        self,
        schema: type[SchemaT],
        messages: list[BaseMessage],
        *,
        purpose: Purpose = "main",
    ) -> SchemaT:
        self.calls += 1
        raise LLMError(self._message)


class CapturingProvider:
    """Wraps another provider and records the messages it was sent.

    Used by the security tests to assert what actually reached the prompt - for
    example that untrusted text arrived fenced, in a user message, and never in
    the system message.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.prompts: list[list[BaseMessage]] = []

    def structured(
        self,
        schema: type[SchemaT],
        messages: list[BaseMessage],
        *,
        purpose: Purpose = "main",
    ) -> SchemaT:
        self.prompts.append(messages)
        result: SchemaT = self._inner.structured(schema, messages, purpose=purpose)
        return result

    def last_system_text(self) -> str:
        return "\n".join(
            str(message.content) for message in self.prompts[-1] if message.type == "system"
        )

    def last_human_text(self) -> str:
        return "\n".join(
            str(message.content) for message in self.prompts[-1] if message.type == "human"
        )


class HashingEmbedder:
    """Deterministic offline embeddings with genuine lexical similarity.

    Not a stub returning noise. Each token is hashed into a fixed-width bucket and
    the vector is L2-normalised, which makes cosine similarity a real measure of
    term overlap. That matters: it means the retrieval tests assert actual
    ranking behaviour rather than merely that the plumbing runs.

    Semantic (non-overlapping vocabulary) similarity is beyond it, so genuine
    embedding quality is exercised separately by scripts/demo_run.py.
    """

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions
        self.document_calls = 0
        self.query_calls = 0

    @staticmethod
    def _tokens(text: str) -> list[str]:
        cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
        return [token for token in cleaned.split() if len(token) > 2]

    def _vector(self, text: str) -> list[float]:
        import math

        buckets = [0.0] * self.dimensions
        for token in self._tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            buckets[index] += 1.0

        norm = math.sqrt(sum(value * value for value in buckets))
        if norm == 0.0:
            buckets[0] = 1.0
            return buckets
        return [value / norm for value in buckets]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return self._vector(text)


class FailingEmbedder:
    """Fails every call, to prove retrieval outages degrade rather than crash."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise LLMError("simulated embedding outage")

    def embed_query(self, text: str) -> list[float]:
        raise LLMError("simulated embedding outage")


# A minimal valid PNG (1x1 pixel), used wherever a test needs bytes that pass
# the real magic-byte validation without depending on a real image library.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000100ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


class ScriptedImageProvider:
    """Returns fixed bytes, or raises, on every call. Records prompts sent."""

    def __init__(self, image_bytes: bytes | Exception = TINY_PNG) -> None:
        self._result = image_bytes
        self.prompts: list[str] = []

    def generate_image(self, prompt: str) -> bytes:
        self.prompts.append(prompt)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FailingImageProvider:
    """Fails every call, to prove generation outages degrade rather than crash."""

    def generate_image(self, prompt: str) -> bytes:
        raise LLMError("simulated image provider outage")
