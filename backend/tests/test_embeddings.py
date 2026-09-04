"""Embedding backend selection, and the local provider's wrapper logic.

The model weights are never downloaded here: the local provider's loaded
model is stubbed directly on ``provider._model``, exactly as
test_image_provider.py stubs ``_client``. So what these tests cover is the
code this project actually owns - materialising fastembed's lazy numpy
output into plain lists, wrapping every failure as ``LLMError``, and
choosing a backend - rather than re-testing fastembed itself.

The ``active_embedding_model`` tests are the load-bearing ones. Switching
backend changes the vector dimensionality, so if that name did not change
with it, a stale index of the wrong shape would be silently reused.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from app.config import Settings
from app.llm.factory import (
    LLMError,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)


class _StubModel:
    """Stands in for a loaded ``fastembed.TextEmbedding``.

    Returns numpy arrays rather than lists, because that is what fastembed
    actually yields and the conversion is the thing under test.
    """

    def __init__(self, vectors: list[list[float]], error: Exception | None = None) -> None:
        self._vectors = vectors
        self._error = error

    def embed(self, texts: list[str]) -> Any:
        if self._error is not None:
            raise self._error
        return (np.array(vector, dtype="float32") for vector in self._vectors)

    def query_embed(self, text: str) -> Any:
        if self._error is not None:
            raise self._error
        return (np.array(vector, dtype="float32") for vector in self._vectors)


def _local(vectors: list[list[float]], error: Exception | None = None) -> LocalEmbeddingProvider:
    provider = LocalEmbeddingProvider(Settings(embedding_backend="local"))
    provider._model = _StubModel(vectors, error)
    return provider


# --------------------------------------------------------- backend selection


def test_default_backend_is_the_hosted_one() -> None:
    """The deployed default must not change silently: a local backend needs a
    model download, so opting in is deliberate."""
    assert Settings().embedding_backend == "openai"
    assert isinstance(get_embedding_provider(Settings()), OpenAIEmbeddingProvider)


def test_local_backend_is_selected_by_configuration() -> None:
    provider = get_embedding_provider(Settings(embedding_backend="local"))
    assert isinstance(provider, LocalEmbeddingProvider)


def test_an_unknown_backend_is_rejected_by_validation() -> None:
    with pytest.raises(ValueError):
        Settings(embedding_backend="something-else")


def test_the_backend_is_settable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The way it is actually configured in deployment. Worth pinning
    separately: the constructor takes field names while the environment takes
    the PYS_-prefixed form, and Settings ignores unknown keys rather than
    complaining, so a wrong name fails silently."""
    monkeypatch.setenv("PYS_EMBEDDING_BACKEND", "local")
    assert Settings().embedding_backend == "local"


# ------------------------------------------- fingerprint / index invalidation


def test_active_model_name_tracks_the_hosted_backend() -> None:
    settings = Settings(embedding_backend="openai")
    assert settings.active_embedding_model == settings.embedding_model


def test_active_model_name_tracks_the_local_backend() -> None:
    settings = Settings(embedding_backend="local")
    assert settings.active_embedding_model == f"local/{settings.local_embedding_model}"


def test_switching_backend_changes_the_fingerprint_input() -> None:
    """The whole point: an index built by one backend must read as stale to
    the other, because 1536-dimension and 384-dimension vectors are not
    interchangeable."""
    hosted = Settings(embedding_backend="openai").active_embedding_model
    local = Settings(embedding_backend="local").active_embedding_model
    assert hosted != local


# ------------------------------------------------- local provider conversion


def test_documents_are_materialised_as_plain_lists() -> None:
    """The vector store and the JSON manifest both want lists; an ndarray
    leaking into either would break serialisation."""
    provider = _local([[0.1, 0.2], [0.3, 0.4]])

    vectors = provider.embed_documents(["a", "b"])

    assert isinstance(vectors, list)
    assert all(isinstance(vector, list) for vector in vectors), "no ndarray may leak"
    assert len(vectors) == 2
    assert vectors[0] == pytest.approx([0.1, 0.2], abs=1e-6)
    assert vectors[1] == pytest.approx([0.3, 0.4], abs=1e-6)


def test_query_returns_the_single_vector_not_a_generator() -> None:
    provider = _local([[0.5, 0.6]])

    vector = provider.embed_query("a query")

    assert isinstance(vector, list)
    assert vector == pytest.approx([0.5, 0.6], abs=1e-6)


# ------------------------------------------------------------ failure policy


def test_a_document_embedding_failure_becomes_an_llm_error() -> None:
    provider = _local([], error=RuntimeError("onnx session died"))

    with pytest.raises(LLMError, match="document embedding failed"):
        provider.embed_documents(["a"])


def test_a_query_embedding_failure_becomes_an_llm_error() -> None:
    provider = _local([], error=RuntimeError("onnx session died"))

    with pytest.raises(LLMError, match="query embedding failed"):
        provider.embed_query("a query")


def test_an_empty_query_result_is_an_error_not_an_index_crash() -> None:
    """Guarding this explicitly: without it, ``vectors[0]`` would raise a raw
    IndexError past the provider instead of the typed error every other
    failure in this system produces."""
    provider = _local([])

    with pytest.raises(LLMError, match="no vector"):
        provider.embed_query("a query")
