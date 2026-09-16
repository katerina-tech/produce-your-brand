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

from pydantic import AliasChoices, Field, SecretStr, field_validator
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

    # --- embedding backend ---------------------------------------------------
    # Retrieval is the one part of this system that can run entirely on-device.
    # "local" embeds with fastembed (ONNX, no torch) instead of billing the
    # gateway per call, which is what lets the knowledge base work when the
    # provider balance is exhausted - the failure mode this project actually
    # hit. The corpus is ~21 KB across 13 documents, so the quality cost of a
    # 384-dimension local model over a 1536-dimension hosted one is negligible
    # here; that would not be true of a large corpus.
    #
    # Reasoning and extraction stay hosted on purpose. Structured-output
    # reliability is the core value path, and small local models are not
    # dependable at strict JSON schemas.
    # Tracing. Entirely optional: without a key pair the app behaves exactly as
    # it does today, which is why these default to empty rather than raising.
    # The secret is a SecretStr for the same reason the model key is - an
    # accidental repr of settings must not leak it.
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr | None = None
    # EU region by default: traces from a Berlin product describing Berlin
    # businesses should not leave the EU without a deliberate decision.
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "development"

    embedding_backend: Literal["openai", "local"] = "openai"
    local_embedding_model: str = "BAAI/bge-small-en-v1.5"

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

    # --- nearby studios (OpenStreetMap) --------------------------------------
    # A live, unscored complement to the curated (currently synthetic) supplier
    # dataset - see app/services/osm_search.py. Free, keyless, no billing
    # account, unlike the commercial alternatives. Deliberately not folded into
    # supplier matching: OpenStreetMap has no capability, MOQ or lead-time data,
    # so these results cannot be scored the way app/services/matching.py scores
    # a real supplier record - they are presented as unverified leads only.
    osm_overpass_url: str = "https://overpass-api.de/api/interpreter"
    osm_request_timeout_seconds: float = 20.0
    osm_result_limit: int = 12
    osm_cache_ttl_seconds: int = 3600

    # --- paths (all derived; never user-supplied) ---------------------------
    data_dir: Path = BACKEND_ROOT / "data"
    partners_file: Path = BACKEND_ROOT / "data" / "berlin_partners.json"
    suppliers_file: Path = BACKEND_ROOT / "data" / "suppliers.json"
    offers_file: Path = BACKEND_ROOT / "data" / "offers.json"
    track_records_file: Path = BACKEND_ROOT / "data" / "track_records.json"

    # Accounts. Signing in is optional by design - the demo must stay openable
    # by anyone following a link - so an unset secret disables sign-in rather
    # than breaking the app.
    session_secret: SecretStr = SecretStr("")
    session_ttl_seconds: int = 60 * 60 * 24 * 14
    # Off locally so http://localhost keeps working; on everywhere else, because
    # a session cookie sent over plain http is a session cookie somebody else has.
    session_cookie_secure: bool = False
    knowledge_dir: Path = BACKEND_ROOT / "data" / "knowledge"
    index_dir: Path = BACKEND_ROOT / "data" / "index"
    upload_dir: Path = BACKEND_ROOT / "data" / "uploads"
    database_url: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_URL", "PYS_DATABASE_URL"),
        description=(
            "PostgreSQL connection string. Read from DATABASE_URL without the PYS_ "
            "prefix because that is the name Railway injects when a Postgres service "
            "exists - so adding the database is the whole of the switch, with no "
            "setting anybody has to remember to flip. Empty means the local file."
        ),
    )
    app_db_path: Path = BACKEND_ROOT / "data" / "app.db"
    # Fill an empty tender board once, in the background, after startup.
    #
    # Off by default and switched on in the Dockerfile, so the deployed image
    # seeds itself while a test run and a developer's machine reach no network
    # unless asked. Anything that dials out from a boot should be opt-in: a
    # default that only bites in one environment is a default nobody remembers.
    seed_tenders_on_boot: bool = False
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

    @property
    def tracing_configured(self) -> bool:
        """Both halves of the key pair present. Anything less means tracing off.

        Checked rather than assumed because a half-configured deployment - one
        variable set, the other forgotten - is the likeliest misconfiguration,
        and it should degrade silently rather than error on every request.
        """
        return bool(self.langfuse_public_key) and bool(
            self.langfuse_secret_key and self.langfuse_secret_key.get_secret_value()
        )

    @property
    def active_embedding_model(self) -> str:
        """The embedding model actually in use, whichever backend is selected.

        This, not ``embedding_model``, is what must reach the index
        fingerprint. Switching backends changes the vector dimensionality
        (1536 -> 384), so an index built by the other backend is not merely
        out of date - it is unusable, and reusing it would either crash the
        search or silently return nonsense. Feeding the effective name into
        the fingerprint makes that a rebuild rather than a bug.
        """
        if self.embedding_backend == "local":
            return f"local/{self.local_embedding_model}"
        return self.embedding_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
