"""Application configuration.

This is the ONLY module in the codebase that reads the environment. Every other
module receives configuration through :func:`get_settings`. That keeps secrets in
one auditable place and makes tests able to override settings without touching
``os.environ``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent

# Values that mean "nobody edited .env yet" rather than a usable credential.
_PLACEHOLDER_KEYS = frozenset(
    {"sk-", "sk-...", "sk-xxx", "sk-proj-...", "your-key-here", "changeme", "todo"}
)


class Settings(BaseSettings):
    """Runtime settings, loaded from environment / ``.env``.

    Note the ``PYS_`` prefix on everything except ``OPENAI_API_KEY``, which keeps
    the conventional name so the OpenAI SDK and our config agree.
    """

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="PYS_",
        extra="ignore",
    )

    # --- secrets -----------------------------------------------------------
    # SecretStr so an accidental log/repr of settings cannot leak the key.
    openai_api_key: SecretStr = Field(default=SecretStr(""), alias="OPENAI_API_KEY")

    # --- models ------------------------------------------------------------
    # The base URL makes the provider swappable. It defaults to OpenRouter
    # because that is the gateway this project is configured against; OpenRouter
    # speaks the OpenAI API, so the SDK, structured outputs and embeddings all
    # work unchanged. To talk to OpenAI directly instead, set an OpenAI key, set
    # PYS_OPENAI_BASE_URL= (empty) and drop the "openai/" prefix from the model
    # names below. Nothing in the code changes.
    openai_base_url: str | None = "https://openrouter.ai/api/v1"
    model_name: str = "openai/gpt-4o"
    classifier_model_name: str = "openai/gpt-4o-mini"
    embedding_model: str = "openai/text-embedding-3-small"
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    # Every response here is a small structured object, so a large completion
    # budget buys nothing. It must be set explicitly: the client library
    # otherwise reserves the model's full output window, which gateways bill or
    # gate against up front - OpenRouter rejects such a request with HTTP 402
    # even when the actual response would be a few hundred tokens.
    llm_max_tokens: int = 1024

    # --- design generation ---------------------------------------------------
    # A real per-image cost applies here (roughly a few cents on OpenRouter at
    # the time this was written), unlike every other model call in this system,
    # which produces a small structured object. This is the one feature added
    # beyond the original sprint scope, at explicit user request - see the
    # README's Design attachment section.
    image_model: str = "google/gemini-2.5-flash-image"
    image_max_tokens: int = 2048

    # --- paths (all derived; never user-supplied) ---------------------------
    data_dir: Path = BACKEND_ROOT / "data"
    suppliers_file: Path = BACKEND_ROOT / "data" / "suppliers.json"
    knowledge_dir: Path = BACKEND_ROOT / "data" / "knowledge"
    index_dir: Path = BACKEND_ROOT / "data" / "index"
    upload_dir: Path = BACKEND_ROOT / "data" / "uploads"
    app_db_path: Path = BACKEND_ROOT / "data" / "app.db"
    checkpoint_db_path: Path = BACKEND_ROOT / "data" / "checkpoints.db"

    # --- workflow behaviour ------------------------------------------------
    max_clarification_rounds: int = 3
    top_matches: int = 3
    deadline_buffer_days: int = 5

    # --- rag ---------------------------------------------------------------
    chunk_size: int = 800
    chunk_overlap: int = 120
    retrieval_k: int = 4

    # --- security ----------------------------------------------------------
    max_upload_bytes: int = 5 * 1024 * 1024
    allowed_upload_types: tuple[str, ...] = ("image/png", "image/jpeg", "application/pdf")
    injection_heuristic_threshold: float = 0.35
    injection_classifier_enabled: bool = True

    # --- observability -----------------------------------------------------
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # --- api ---------------------------------------------------------------
    cors_origins: tuple[str, ...] = ("http://localhost:3000",)

    @field_validator("openai_base_url", mode="before")
    @classmethod
    def _blank_base_url_means_openai(cls, value: object) -> object:
        """Treat ``PYS_OPENAI_BASE_URL=`` as "use OpenAI directly"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cors_origins", "allowed_upload_types", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow ``A,B`` in env vars for tuple-typed settings."""
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @property
    def has_api_key(self) -> bool:
        """True only for a key that could plausibly work.

        A copied-but-unedited ``.env`` still contains the example placeholder. If
        that counted as configured, ``/api/health`` would report ``ok`` and the
        failure would only surface later as an opaque 401 from OpenAI.
        """
        key = self.openai_api_key.get_secret_value().strip()
        return bool(key) and key not in _PLACEHOLDER_KEYS and not key.endswith("...")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
