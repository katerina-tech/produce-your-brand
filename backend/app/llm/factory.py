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
from app.observability import tracing

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# "main" is the reasoning model; "classifier" is the cheap one used for routing
# and injection screening, where a large model buys nothing.
Purpose = Literal["main", "classifier"]


# Markers used by upstream providers when their own content policy blocks a
# request. A refusal is not a neutral outage: for the injection classifier it is
# corroborating evidence that the text was hostile.
_CONTENT_FILTER_MARKERS = (
    "content management policy",
    "content_filter",
    "content policy",
    "responsibleaipolicyviolation",
)


class LLMError(RuntimeError):
    """A model call failed or returned something unusable.

    Raised instead of leaking provider-specific exceptions upward, so nodes can
    convert any failure into a controlled workflow error.

    ``content_filtered`` distinguishes "the provider refused this text" from
    "the call did not work", because the two mean different things to a caller
    that is screening input.
    """

    def __init__(self, message: str, *, content_filtered: bool = False) -> None:
        super().__init__(message)
        self.content_filtered = content_filtered


def _is_content_filter(error: BaseException) -> bool:
    lowered = str(error).lower()
    return any(marker in lowered for marker in _CONTENT_FILTER_MARKERS)


def _provider_status(error: BaseException) -> int | None:
    """The HTTP status a provider exception carries, if it carries one.

    Read defensively rather than by isinstance: this must not import the
    provider SDK's exception classes, and a provider that changes its
    exception hierarchy should cost a generic message, not a crash inside
    error handling.
    """
    status = getattr(error, "status_code", None)
    return status if isinstance(status, int) else None


# Two upstream failures mean something a person can act on, and everything
# else means "it did not work". Keeping the list this short is deliberate:
# an error message that guesses is worse than one that admits ignorance.
_OUT_OF_CREDIT = 402
_RATE_LIMITED = 429


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
        settings = self._settings
        model_name = settings.model_name if purpose == "main" else settings.classifier_model_name

        # The generation wraps the call rather than following it, so a failure
        # is recorded as a generation that errored instead of vanishing from
        # the trace - the failed runs are the ones worth looking at. With no
        # credentials configured this is a no-op context manager.
        with tracing.generation(
            schema.__name__,
            model=model_name,
            metadata={"purpose": purpose, "schema": schema.__name__},
        ) as observation:
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
                    status_code=getattr(error, "status_code", None),
                    body=getattr(getattr(error, "response", None), "text", None) or str(error),
                    request_id=getattr(error, "request_id", None),
                )
                raise LLMError(
                    f"{schema.__name__} generation failed",
                    content_filtered=_is_content_filter(error),
                ) from error

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

            if observation is not None:
                _record_usage(observation, result)

            return result


def _record_usage(observation: Any, result: object) -> None:
    """Attach token usage to a generation when the provider reported it.

    Best effort by design: usage metadata is not part of the structured-output
    contract, and a provider that omits it must cost a figure on a dashboard,
    never the response itself.
    """
    from contextlib import suppress

    with suppress(Exception):
        usage = getattr(result, "usage_metadata", None) or {}
        if not isinstance(usage, dict):
            return
        details = {
            key: int(usage[key])
            for key in ("input_tokens", "output_tokens", "total_tokens")
            if isinstance(usage.get(key), int)
        }
        if details:
            observation.update(usage_details=details)


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


class LocalEmbeddingProvider:
    """On-device embeddings via fastembed. No API key, no network at call time.

    Chosen over ``sentence-transformers`` deliberately: fastembed runs the
    model through ONNX Runtime rather than PyTorch, which keeps the deployed
    image around 80 MB heavier instead of 2-3 GB heavier. On a container host
    that difference is the whole decision.

    The model weights are downloaded once, on first use, and cached. That is
    the one moment this provider touches the network - see the note on
    ``PYS_EMBEDDING_BACKEND`` in the README about pre-warming it so a cold
    start does not pay for the download mid-request.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._model: Any = None

    def _embeddings(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from fastembed import TextEmbedding
        except ImportError as error:  # pragma: no cover - dependency is pinned
            raise LLMError(
                "The local embedding backend needs the 'fastembed' package. "
                "Run `uv sync`, or set PYS_EMBEDDING_BACKEND=openai."
            ) from error

        name = self._settings.local_embedding_model
        try:
            self._model = TextEmbedding(model_name=name)
        except Exception as error:
            log_event(
                logger,
                Event.LLM_ERROR,
                "local embedding model failed to load",
                level=logging.ERROR,
                model=name,
                error_type=type(error).__name__,
            )
            raise LLMError(f"could not load local embedding model '{name}'") from error
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            # fastembed yields numpy arrays lazily; the vector store and the
            # JSON manifest both want plain lists, so materialise here rather
            # than leaking an ndarray into either.
            vectors = [vector.tolist() for vector in self._embeddings().embed(texts)]
        except LLMError:
            raise
        except Exception as error:
            log_event(
                logger,
                Event.LLM_ERROR,
                "local document embedding failed",
                level=logging.ERROR,
                count=len(texts),
                error_type=type(error).__name__,
            )
            raise LLMError("document embedding failed") from error
        return vectors

    def embed_query(self, text: str) -> list[float]:
        try:
            vectors = list(self._embeddings().query_embed(text))
        except LLMError:
            raise
        except Exception as error:
            log_event(
                logger,
                Event.LLM_ERROR,
                "local query embedding failed",
                level=logging.ERROR,
                error_type=type(error).__name__,
            )
            raise LLMError("query embedding failed") from error
        if not vectors:
            raise LLMError("local embedding model returned no vector for the query")
        vector: list[float] = vectors[0].tolist()
        return vector


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Return the production embedding provider. The only construction site.

    Which backend is a configuration choice, not a code path callers pick -
    see ``PYS_EMBEDDING_BACKEND`` in ``app/config.py``. Everything downstream
    depends on the protocol, so the RAG pipeline is unchanged either way.
    """
    resolved = settings or get_settings()
    if resolved.embedding_backend == "local":
        return LocalEmbeddingProvider(resolved)
    return OpenAIEmbeddingProvider(resolved)


class ImageProvider(Protocol):
    """What design generation needs from a model.

    Deliberately separate from :class:`LLMProvider`: image generation has a real
    per-call cost, unlike every other call in this system, and returns raw bytes
    rather than a validated schema. Keeping the protocol narrow means the cost
    surface is exactly one method.
    """

    def generate_image(self, prompt: str) -> bytes:
        """Return PNG bytes for the prompt, or raise :class:`LLMError`."""
        ...


class OpenRouterImageProvider:
    """Production image generation.

    Uses the raw ``openai`` client rather than ``langchain_openai.ChatOpenAI``.
    The image comes back in a ``message.images[0].image_url.url`` data URL - a
    field the OpenAI chat-completions response shape does not define and
    LangChain's response parser does not surface, so the plain SDK client is the
    correct tool here, not a workaround. This is the only place it is
    constructed; a second construction site would defeat the point of having a
    single factory.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client: Any = None

    def _openai_client(self) -> Any:
        if self._client is not None:
            return self._client

        from openai import OpenAI

        settings = self._settings
        if not settings.has_api_key:
            raise LLMError("No API key configured. Set OPENAI_API_KEY in .env - see .env.example.")
        self._client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        return self._client

    def generate_image(self, prompt: str) -> bytes:
        """Raises :class:`LLMError` on any failure - the API call, an
        unexpected response shape, or bytes that fail to decode. Nothing here
        may escape as a different exception type: a raw ``AttributeError`` or
        ``ValueError`` from parsing a third-party response would otherwise
        reach the client as an opaque 500 instead of the typed, user-safe
        error every other failure in this system produces.
        """
        settings = self._settings
        try:
            response = self._openai_client().chat.completions.create(
                model=settings.image_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.image_max_tokens,
                extra_body={"modalities": ["image", "text"]},
            )
            images = getattr(response.choices[0].message, "images", None) or []
            if not images:
                # The model answered with text only - most often a
                # content-policy refusal phrased as prose rather than an
                # HTTP error.
                raise LLMError("The model did not return an image for this prompt.")

            url = images[0].image_url.url
            if not url.startswith("data:") or "," not in url:
                raise LLMError("Image response was not in the expected data URL format.")

            import base64

            _header, encoded = url.split(",", 1)
            return base64.b64decode(encoded)
        except LLMError:
            raise
        except Exception as error:
            status = _provider_status(error)
            log_event(
                logger,
                Event.LLM_ERROR,
                "image generation failed",
                level=logging.ERROR,
                model=settings.image_model,
                error_type=type(error).__name__,
                provider_status=status,
                content_filtered=_is_content_filter(error),
            )

            # The reason reaches the user, so it has to be worth reading. A
            # generation that failed because the model account is out of
            # credit is fixable by exactly one person, and telling them
            # "Image generation failed" sends them to look at the code
            # instead. Uploading a file costs nothing and still works, which
            # is what the message should send them to.
            if status == _OUT_OF_CREDIT:
                raise LLMError(
                    "Design generation is out of image budget on this deployment. "
                    "Uploading your own design file still works and costs nothing."
                ) from error
            if status == _RATE_LIMITED:
                raise LLMError(
                    "The image provider is busy right now. Try again in a minute, "
                    "or upload your own design file instead."
                ) from error

            raise LLMError(
                "Image generation failed", content_filtered=_is_content_filter(error)
            ) from error


def get_image_provider(settings: Settings | None = None) -> ImageProvider:
    """Return the production image provider. The only construction site."""
    return OpenRouterImageProvider(settings)
