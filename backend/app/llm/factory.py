"""The single place a chat model is constructed.

Everything that needs a model asks for it through :class:`LLMProvider`. Two
consequences follow, and both are deliberate:

*One configuration.* Model name, temperature, timeout and retries are set here
once. There is no second ``ChatOpenAI(...)`` anywhere in the codebase, and
``scripts/audit_architecture.py`` fails the build if one appears.

*Testable graph.* Nodes depend on the protocol, not on OpenAI, so the whole
workflow runs in tests against a fake provider with no API key and no network.

Every call returns a validated Pydantic model. There is no free-text path out of
this module: if a response does not fit the schema, it raises rather than letting
unvalidated model output reach business logic.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Protocol, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# "main" is the reasoning model; "classifier" is the cheap one used for routing
# and injection screening, where a large model buys nothing.
Purpose = Literal["main", "classifier"]


class LLMError(RuntimeError):
    """A model call failed or returned something unusable.

    Raised instead of leaking provider-specific exceptions upward, so nodes can
    convert any failure into a controlled workflow error.
    """


class LLMProvider(Protocol):
    """What the graph needs from a model. Deliberately one method."""

    def structured(
        self,
        schema: type[SchemaT],
        messages: list[BaseMessage],
        *,
        purpose: Purpose = "main",
    ) -> SchemaT:
        """Return a validated ``schema`` instance, or raise :class:`LLMError`."""
        ...


class OpenAIProvider:
    """Production provider.

    Works against OpenAI or any OpenAI-compatible gateway (this project is
    configured against OpenRouter), because only the base URL differs.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._models: dict[Purpose, BaseChatModel] = {}

    def _model(self, purpose: Purpose) -> BaseChatModel:
        """Build once per purpose and reuse. Import is local so that importing
        this module does not require the provider SDK to be configured."""
        if purpose in self._models:
            return self._models[purpose]

        from langchain_openai import ChatOpenAI

        settings = self._settings
        if not settings.has_api_key:
            raise LLMError("No API key configured. Set OPENAI_API_KEY in .env - see .env.example.")

        self._models[purpose] = ChatOpenAI(
            model=(settings.model_name if purpose == "main" else settings.classifier_model_name),
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            max_completion_tokens=settings.llm_max_tokens,
        )
        return self._models[purpose]

    def structured(
        self,
        schema: type[SchemaT],
        messages: list[BaseMessage],
        *,
        purpose: Purpose = "main",
    ) -> SchemaT:
        model = self._model(purpose)
        try:
            result = model.with_structured_output(schema).invoke(messages)
        except Exception as error:  # provider, network, timeout, parse
            log_event(
                logger,
                Event.LLM_ERROR,
                "structured call failed",
                level=logging.ERROR,
                schema=schema.__name__,
                purpose=purpose,
                error_type=type(error).__name__,
            )
            raise LLMError(f"{schema.__name__} generation failed") from error

        if not isinstance(result, schema):
            # Defensive: a gateway that ignores the schema must not slip an
            # unvalidated dict into business logic.
            log_event(
                logger,
                Event.VALIDATION_ERROR,
                "model returned an unexpected type",
                level=logging.ERROR,
                schema=schema.__name__,
                got=type(result).__name__,
            )
            raise LLMError(f"{schema.__name__} generation returned {type(result).__name__}")

        return result


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """Return the production provider. The only construction site."""
    return OpenAIProvider(settings)


class EmbeddingProvider(Protocol):
    """What the RAG pipeline needs to turn text into vectors."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed corpus chunks at index-build time."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""
        ...


class OpenAIEmbeddingProvider:
    """Production embeddings. Same gateway and key as the chat models."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any = None

    def _embeddings(self) -> Any:
        if self._client is not None:
            return self._client

        from langchain_openai import OpenAIEmbeddings

        settings = self._settings
        if not settings.has_api_key:
            raise LLMError("No API key configured. Set OPENAI_API_KEY in .env - see .env.example.")

        self._client = OpenAIEmbeddings(
            model=settings.embedding_model,
            openai_api_key=settings.openai_api_key,
            openai_api_base=settings.openai_base_url,
            request_timeout=settings.llm_timeout_seconds,
            # Send plain strings rather than pre-tokenised arrays. The default
            # tokenises client-side with tiktoken, which OpenAI accepts but
            # OpenAI-compatible gateways frequently do not.
            check_embedding_ctx_length=False,
        )
        return self._client

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors: list[list[float]] = self._embeddings().embed_documents(texts)
        except Exception as error:
            log_event(
                logger,
                Event.LLM_ERROR,
                "embedding documents failed",
                level=logging.ERROR,
                count=len(texts),
                error_type=type(error).__name__,
            )
            raise LLMError("document embedding failed") from error
        return vectors

    def embed_query(self, text: str) -> list[float]:
        try:
            vector: list[float] = self._embeddings().embed_query(text)
        except Exception as error:
            log_event(
                logger,
                Event.LLM_ERROR,
                "embedding query failed",
                level=logging.ERROR,
                error_type=type(error).__name__,
            )
            raise LLMError("query embedding failed") from error
        return vector


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Return the production embedding provider. The only construction site."""
    return OpenAIEmbeddingProvider(settings)
