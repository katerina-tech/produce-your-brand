"""Design attachment: upload lookup, and AI generation.

Generation is the one feature in this system with a real per-call cost, added
beyond the original sprint scope at explicit user request. It reuses the exact
same upload validation a client-supplied file gets - these tests exercise that
reuse directly, with a scripted provider so no test here spends money.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.llm.factory import LLMError
from app.security.uploads import get_upload, store_upload
from app.services.design_service import DesignGenerationError, generate_design
from tests.fakes import TINY_PNG, FailingImageProvider, ScriptedImageProvider


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(upload_dir=tmp_path / "uploads")


# ---------------------------------------------------------------- get_upload


def test_get_upload_finds_a_stored_file(settings: Settings) -> None:
    record = store_upload("logo.png", TINY_PNG, settings)

    found = get_upload(record.upload_id, settings)

    assert found is not None
    assert found.upload_id == record.upload_id
    assert found.mime_type == "image/png"
    assert found.size_bytes == len(TINY_PNG)


def test_get_upload_returns_none_for_an_unknown_id(settings: Settings) -> None:
    assert get_upload("0" * 32, settings) is None


def test_get_upload_returns_none_when_the_directory_does_not_exist(settings: Settings) -> None:
    """No upload has ever been made yet - a missing directory is not an error."""
    assert not settings.upload_dir.exists()
    assert get_upload("anything", settings) is None


@pytest.mark.parametrize("malformed", ["../../etc/passwd", "a/b", "a.b.c", ""])
def test_get_upload_rejects_a_malformed_id_without_touching_the_filesystem(
    settings: Settings, malformed: str
) -> None:
    """upload_id is always a secrets.token_hex output; anything else is refused
    before it ever reaches glob(), regardless of where it came from."""
    assert get_upload(malformed, settings) is None


# ------------------------------------------------------------ generate_design


def test_generate_design_stores_the_image_like_any_upload(settings: Settings) -> None:
    provider = ScriptedImageProvider(TINY_PNG)

    record = generate_design("a minimalist gold star logo", provider, settings)

    assert provider.prompts == ["a minimalist gold star logo"]
    assert record.mime_type == "image/png"
    assert get_upload(record.upload_id, settings) is not None


def test_generate_design_propagates_a_provider_failure(settings: Settings) -> None:
    provider = ScriptedImageProvider(LLMError("model refused the prompt"))

    with pytest.raises(DesignGenerationError, match="refused"):
        generate_design("anything", provider, settings)


def test_generate_design_outage_raises_a_controlled_error(settings: Settings) -> None:
    with pytest.raises(DesignGenerationError):
        generate_design("anything", FailingImageProvider(), settings)


def test_generate_design_rejects_bytes_that_are_not_actually_an_image(
    settings: Settings,
) -> None:
    """Defense in depth: the same magic-byte check a client upload gets.

    If the model ever returns a refusal rendered as plain text, or a malformed
    payload, it must fail the same way a disguised upload would - not be
    trusted just because it came from our own call.
    """
    provider = ScriptedImageProvider(b"not actually an image, just some bytes")

    with pytest.raises(DesignGenerationError, match="could not be saved"):
        generate_design("anything", provider, settings)


def test_a_rejected_generation_writes_nothing(settings: Settings) -> None:
    provider = ScriptedImageProvider(b"not an image")

    with pytest.raises(DesignGenerationError):
        generate_design("anything", provider, settings)

    assert not settings.upload_dir.exists() or not list(settings.upload_dir.iterdir())
