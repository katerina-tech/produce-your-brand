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


# ------------------------------------------ failures a person can act on


class _StatusError(Exception):
    """Stands in for a provider exception carrying an HTTP status.

    Deliberately not the SDK's own class: the provider reads the status by
    attribute rather than by isinstance, so that a provider changing its
    exception hierarchy costs a generic message rather than a crash inside
    error handling. This test holds that contract.
    """

    def __init__(self, status_code: int, message: str = "upstream said no") -> None:
        super().__init__(message)
        self.status_code = status_code


def test_running_out_of_credit_says_so_and_points_at_the_free_path() -> None:
    """The reason reaches the user, so it has to be worth reading.

    "Image generation failed" sends somebody to read the code. Only one person
    can fix an empty image budget, and uploading a file costs nothing and
    still works - which is where the message should send them.
    """
    provider = _provider()
    provider._client = _stub_client(create_error=_StatusError(402, "requires more credits"))

    with pytest.raises(LLMError) as raised:
        provider.generate_image("a gold logo")

    message = str(raised.value).lower()
    assert "budget" in message
    assert "upload" in message


def test_being_rate_limited_asks_for_a_retry_rather_than_a_fix() -> None:
    """429 is temporary, so the message must not send anybody to change
    anything - the same prompt a minute later is the whole remedy."""
    provider = _provider()
    provider._client = _stub_client(create_error=_StatusError(429, "rate limited upstream"))

    with pytest.raises(LLMError) as raised:
        provider.generate_image("a gold logo")

    assert "try again" in str(raised.value).lower()


def test_an_unrecognised_status_stays_generic() -> None:
    """An error message that guesses is worse than one that admits ignorance."""
    provider = _provider()
    provider._client = _stub_client(create_error=_StatusError(500, "internal"))

    with pytest.raises(LLMError) as raised:
        provider.generate_image("a gold logo")

    assert str(raised.value) == "Image generation failed"


def test_an_exception_with_no_status_does_not_crash_the_handler() -> None:
    """A provider that raises something shapeless must still produce the typed
    error every other failure in this system produces."""
    provider = _provider()
    provider._client = _stub_client(create_error=RuntimeError("socket went away"))

    with pytest.raises(LLMError) as raised:
        provider.generate_image("a gold logo")

    assert str(raised.value) == "Image generation failed"
