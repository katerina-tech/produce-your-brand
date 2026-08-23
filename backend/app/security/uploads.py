"""Design-file upload validation.

Two rules shape this module.

**Trust the bytes, not the name.** A file called ``logo.png`` proves nothing. The
declared extension and the sniffed magic bytes must agree, or the upload is
rejected - that is what stops a renamed script or a polyglot file.

**Store inert.** The file is written under a generated name, never the one the
client supplied, so a crafted filename cannot traverse directories or overwrite
anything. Nothing here executes, parses or renders the content, and in this phase
only metadata reaches the agent - there is no image understanding, so the file
body never becomes model input.

SVG is rejected despite being an image format. It is XML that can carry script
and external references, which makes it the wrong thing to accept from a stranger
and then hand to a browser.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings
from app.logging_config import Event, log_event, redact_text

logger = logging.getLogger(__name__)

# (mime type, extension, magic-byte prefixes)
_SIGNATURES: tuple[tuple[str, str, tuple[bytes, ...]], ...] = (
    ("image/png", ".png", (b"\x89PNG\r\n\x1a\n",)),
    ("image/jpeg", ".jpg", (b"\xff\xd8\xff",)),
    ("application/pdf", ".pdf", (b"%PDF-",)),
)

_EXTENSION_ALIASES = {".jpeg": ".jpg"}

# Formats a caller might reasonably expect to work, refused on purpose. Naming
# them lets the API explain itself instead of returning a bare rejection.
EXPLICITLY_REJECTED: dict[str, str] = {
    ".svg": "SVG is XML that can carry scripts and external references.",
    ".html": "HTML can carry scripts.",
    ".htm": "HTML can carry scripts.",
    ".zip": "Archives hide their contents from validation.",
    ".eps": "PostScript is an executable format.",
    ".ai": "Illustrator files may embed PostScript.",
}


class UploadRejectedError(ValueError):
    """The file failed validation. The message is safe to show a user."""


@dataclass(frozen=True)
class UploadRecord:
    """Metadata for an accepted file. The body stays on disk, unopened."""

    upload_id: str
    stored_name: str
    original_name: str
    mime_type: str
    size_bytes: int


def _safe_original_name(name: str) -> str:
    """Keep a display name without trusting it as a path.

    Only the final component is kept, and separators are stripped, so nothing
    the client sends can escape the upload directory even in a log line.
    """
    tail = Path(name.replace("\\", "/")).name
    cleaned = "".join(char for char in tail if char.isalnum() or char in "._- ").strip()
    return (cleaned or "upload")[:120]


def _match_signature(content: bytes) -> tuple[str, str] | None:
    for mime, extension, prefixes in _SIGNATURES:
        if any(content.startswith(prefix) for prefix in prefixes):
            return mime, extension
    return None


def validate_upload(
    filename: str, content: bytes, settings: Settings | None = None
) -> tuple[str, str, str]:
    """Validate and return ``(mime_type, canonical_extension, display_name)``.

    Raises :class:`UploadRejectedError` with a user-safe message. Never writes anything.
    """
    settings = settings or get_settings()
    display_name = _safe_original_name(filename)
    declared = Path(display_name).suffix.lower()
    declared = _EXTENSION_ALIASES.get(declared, declared)

    if not content:
        raise UploadRejectedError("The file is empty.")

    if len(content) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes / (1024 * 1024)
        raise UploadRejectedError(f"The file exceeds the {limit_mb:.0f} MB limit.")

    if declared in EXPLICITLY_REJECTED:
        raise UploadRejectedError(
            f"{declared} files are not accepted. {EXPLICITLY_REJECTED[declared]} "
            "Please supply a PNG, JPEG or PDF."
        )

    sniffed = _match_signature(content)
    if sniffed is None:
        raise UploadRejectedError(
            "The file content is not a PNG, JPEG or PDF, whatever its name suggests."
        )

    mime_type, canonical = sniffed

    if mime_type not in settings.allowed_upload_types:
        raise UploadRejectedError(f"{mime_type} files are not accepted.")

    # The decisive check: name and content must agree. A mismatch means either a
    # mistake or an attempt to smuggle one format past a filter for another.
    if declared and declared != canonical:
        raise UploadRejectedError(
            f"The file is named {declared} but its contents are {mime_type}. "
            "Rename it to match, or upload the correct file."
        )

    return mime_type, canonical, display_name


def store_upload(filename: str, content: bytes, settings: Settings | None = None) -> UploadRecord:
    """Validate, then write under a generated name. Rejection writes nothing."""
    settings = settings or get_settings()

    try:
        mime_type, extension, display_name = validate_upload(filename, content, settings)
    except UploadRejectedError as rejection:
        log_event(
            logger,
            Event.UPLOAD_REJECTED,
            "upload rejected",
            level=logging.WARNING,
            reason=str(rejection),
            size_bytes=len(content),
            **redact_text(filename),
        )
        raise

    upload_id = secrets.token_hex(16)
    stored_name = f"{upload_id}{extension}"

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / stored_name).write_bytes(content)

    log_event(
        logger,
        Event.UPLOAD_ACCEPTED,
        upload_id=upload_id,
        mime_type=mime_type,
        size_bytes=len(content),
    )
    return UploadRecord(
        upload_id=upload_id,
        stored_name=stored_name,
        original_name=display_name,
        mime_type=mime_type,
        size_bytes=len(content),
    )


_MIME_BY_EXTENSION: dict[str, str] = {extension: mime for mime, extension, _ in _SIGNATURES}


def get_upload(upload_id: str, settings: Settings | None = None) -> UploadRecord | None:
    """Look up a previously stored file by id. None if it does not exist.

    ``upload_id`` is the stem of the stored filename by construction, so a
    lookup is a directory scan rather than a database - proportionate for the
    handful of files an MVP session holds. This is what lets project creation
    verify a ``design_upload_id`` is real before trusting it, which is the
    structural reason a client cannot attach a file that was never uploaded.

    The original client-supplied filename is not persisted (it is only ever
    returned once, in the upload response), so it is not available here.
    """
    settings = settings or get_settings()
    if not settings.upload_dir.is_dir():
        return None

    # upload_id is generated by secrets.token_hex and never taken from a client
    # path, but a defensive check costs nothing and stops a malformed id from
    # ever reaching glob().
    if not upload_id.isalnum():
        return None

    for path in settings.upload_dir.glob(f"{upload_id}.*"):
        mime_type = _MIME_BY_EXTENSION.get(path.suffix.lower())
        if mime_type is None:
            continue
        return UploadRecord(
            upload_id=upload_id,
            stored_name=path.name,
            original_name=path.name,
            mime_type=mime_type,
            size_bytes=path.stat().st_size,
        )
    return None
