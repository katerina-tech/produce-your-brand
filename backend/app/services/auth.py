"""Accounts: optional sign-in, so a project can belong to somebody.

Two decisions shape this module, and both are product decisions rather than
technical ones.

**Signing in is optional.** The demo has to stay openable by a funding evaluator
or a reviewer following a link, and a login wall would turn that link into a
dead end. So anonymous use works exactly as before; signing in adds ownership,
privacy and a place to come back to. Nothing that worked without an account
stops working.

**No new dependency.** Passwords use ``hashlib.scrypt`` and sessions are signed
with ``hmac``, both from the standard library. A password hash is not a place to
be clever, and scrypt is the memory-hard algorithm Python already ships; adding
a package for it would buy nothing and cost an install that has already failed
twice in this environment.

Sessions are stateless signed tokens rather than rows in a table. The trade is
deliberate: a stolen token stays valid until it expires and cannot be revoked
server-side, which is acceptable for a tool holding production briefs and is not
acceptable for anything holding money. If this ever holds payment data, sessions
become rows.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time

from app.config import Settings, get_settings
from app.logging_config import Event, log_event

logger = logging.getLogger(__name__)

# scrypt parameters. n=2**14 keeps a single hash around a tenth of a second on
# ordinary hardware - slow enough to make offline guessing expensive, fast
# enough that signing in does not feel broken.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32

SESSION_COOKIE = "pys_session"


class AuthError(Exception):
    """Registration or sign-in failed. The message is safe to show a user."""


def hash_password(password: str) -> str:
    """Return ``salt$hash``, both hex. A fresh salt per password, always."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
    )
    return f"{salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check. A malformed record fails rather than raising.

    Comparison uses ``compare_digest`` so the time taken cannot reveal how much
    of the hash matched.
    """
    try:
        salt_hex, expected_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False

    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
    )
    return hmac.compare_digest(derived.hex(), expected_hex)


def _secret(settings: Settings) -> bytes:
    key = settings.session_secret.get_secret_value()
    if not key:
        # A deployment with no configured secret would otherwise sign every
        # session with the empty string, which is the same as not signing.
        raise AuthError("Sign-in is not configured on this deployment.")
    return key.encode("utf-8")


def issue_session(
    user_id: str, settings: Settings | None = None, *, now: float | None = None
) -> str:
    """Mint a signed ``user_id.expiry.signature`` token."""
    settings = settings or get_settings()
    expires_at = int((now if now is not None else time.time()) + settings.session_ttl_seconds)
    payload = f"{user_id}.{expires_at}"
    signature = hmac.new(_secret(settings), payload.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


def read_session(
    token: str | None, settings: Settings | None = None, *, now: float | None = None
) -> str | None:
    """Return the user id a token proves, or ``None``.

    Every failure returns ``None`` rather than raising: an expired cookie, a
    truncated one and a forged one are all simply "not signed in", and a caller
    that had to distinguish them would be a caller that could leak which.
    """
    if not token:
        return None

    settings = settings or get_settings()
    parts = token.rsplit(".", 2)
    if len(parts) != 3:
        return None

    user_id, expiry_text, signature_text = parts
    try:
        expires_at = int(expiry_text)
    except ValueError:
        return None

    expected = hmac.new(
        _secret(settings), f"{user_id}.{expires_at}".encode(), hashlib.sha256
    ).digest()
    padding = "=" * (-len(signature_text) % 4)
    try:
        offered = base64.urlsafe_b64decode(signature_text + padding)
    except Exception:
        return None

    if not hmac.compare_digest(expected, offered):
        log_event(
            logger,
            Event.INJECTION_SUSPECTED,
            "session signature did not verify",
            level=logging.WARNING,
        )
        return None

    if (now if now is not None else time.time()) >= expires_at:
        return None

    return user_id


def normalise_email(email: str) -> str:
    """Lowercase and trim. Two accounts differing only in case are one mistake."""
    return email.strip().lower()


def validate_credentials(email: str, password: str) -> None:
    """Reject what cannot become an account, with a message a person can act on."""
    cleaned = normalise_email(email)
    if "@" not in cleaned or "." not in cleaned.split("@")[-1] or len(cleaned) < 5:
        raise AuthError("That does not look like an email address.")
    if len(password) < 10:
        raise AuthError("Use at least 10 characters - length matters more than symbols.")
