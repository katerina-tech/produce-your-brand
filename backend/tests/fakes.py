"""Test doubles for the LLM provider.

No test in this suite touches the network. That keeps the suite fast, free and
deterministic, and it means the graph's control flow is verified independently of
whether a model happens to behave well on a given day.

``scripts/demo_run.py`` exercises the real provider separately.
"""

from __future__ import annotations

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
