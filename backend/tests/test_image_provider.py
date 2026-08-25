"""OpenRouterImageProvider - the real design-generation client.

Nothing else in this suite exercises it: everywhere the graph or the API
needs image generation, tests use ScriptedImageProvider (see fakes.py)
instead - deliberately, so the rest of the suite stays free of the network.
This is the one place the actual response-parsing logic is verified,
including against response shapes the OpenAI SDK's own types don't rule out
- which is exactly where this class had an uncaught bug (the last two tests
below) that reached a customer as an opaque 500 in production instead of the
typed error every other failure in this system produces.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.llm.factory import LLMError, OpenRouterImageProvider


def _provider() -> OpenRouterImageProvider:
    provider = OpenRouterImageProvider(Settings(OPENAI_API_KEY="sk-test-key"))
    return provider


def _stub_client(create_result: Any = None, create_error: Exception | None = None) -> Any:
    """A minimal stand-in for the ``openai`` SDK client's one method this
    class calls. Installed directly on ``provider._client`` so a test never
    touches the network or the real SDK."""

    def create(**_kwargs: Any) -> Any:
        if create_error is not None:
            raise create_error
        return create_result

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _response_with_url(url: str) -> Any:
    image = SimpleNamespace(image_url=SimpleNamespace(url=url))
    message = SimpleNamespace(images=[image])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_a_valid_data_url_decodes_to_bytes() -> None:
    provider = _provider()
    provider._client = _stub_client(
        create_result=_response_with_url("data:image/png;base64,aGVsbG8=")
    )

    assert provider.generate_image("a gold star") == b"hello"


def test_an_api_failure_becomes_an_llm_error() -> None:
    provider = _provider()
    provider._client = _stub_client(create_error=RuntimeError("upstream outage"))

    with pytest.raises(LLMError):
        provider.generate_image("a gold star")


def test_a_text_only_refusal_becomes_an_llm_error() -> None:
    """The model answered with prose, not an image - most often a
    content-policy refusal, not an HTTP-level failure."""
    provider = _provider()
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(images=[]))])
    provider._client = _stub_client(create_result=response)

    with pytest.raises(LLMError, match="did not return an image"):
        provider.generate_image("a gold star")


def test_a_non_data_url_becomes_an_llm_error() -> None:
    provider = _provider()
    provider._client = _stub_client(create_result=_response_with_url("https://example.com/img.png"))

    with pytest.raises(LLMError, match="expected data URL format"):
        provider.generate_image("a gold star")


def test_a_data_url_with_no_comma_becomes_an_llm_error_not_a_crash() -> None:
    """Regression test. A URL prefixed ``data:`` but missing the comma used
    to raise a raw, unwrapped ``ValueError`` on unpacking ``url.split(",", 1)``
    - see the docstring on ``generate_image``."""
    provider = _provider()
    provider._client = _stub_client(create_result=_response_with_url("data:image/png;base64"))

    with pytest.raises(LLMError):
        provider.generate_image("a gold star")


def test_a_malformed_response_shape_becomes_an_llm_error_not_a_crash() -> None:
    """Regression test. An ``images`` entry with no ``image_url`` at all used
    to raise a raw ``AttributeError`` past this class - this is the actual
    bug that reached the deployed site as "An unexpected error occurred"."""
    provider = _provider()
    message = SimpleNamespace(images=[SimpleNamespace()])  # no .image_url
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    provider._client = _stub_client(create_result=response)

    with pytest.raises(LLMError):
        provider.generate_image("a gold star")
