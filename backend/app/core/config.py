"""Application configuration — environment variables only, fail-fast (architecture.md §7).

Only settings with a real consumer in Phase 2 / Step 1 are declared here.
Other keys in .env.example (sessions, rate limits, idempotency, ...) are
reserved for later phases and are intentionally NOT read yet (no speculative
config — architecture.md §9).

Loading strategy: pydantic-settings' implicit env/dotenv sources were found
NOT to populate values in this sandbox (all released versions tested —
evidence in download/evidence/pydantic_settings_repro.txt). `load_settings()`
therefore builds init kwargs explicitly from (lowest → highest priority):
optional `.env` file, then real environment variables — and relies on
pydantic-settings for typed validation and fail-fast behaviour. The contract
(env-var names, .env support, precedence) is identical on normal hosts and in
CI; re-verified by the same test suite.

.env location (P1-01): the default file is `<project-root>/.env`, resolved
from this file's own location — NOT from the current working directory — so
running `uvicorn app.main:app` from `backend/` still reads the repo-root
`.env` that README documents. In the container the path resolves to `/.env`
(no such file) and configuration comes purely from environment variables,
which is exactly how docker-compose injects it. `load_settings(env_file=...)`
still accepts an explicit path for tests. Env vars keep precedence over file
values.
"""

import os
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "staging", "production"]

# P1-02: the ONLY accepted scheme. The bare postgresql:// scheme is rejected
# because SQLAlchemy resolves it to the psycopg2 DBAPI when installed — the
# driver family would silently change. psycopg2 is absent from both lock
# files by design; this validator pins the driver by configuration.
PSYCOPG_SCHEME: Final[str] = "postgresql+psycopg://"

# P1-01: repo root = three levels above this file
# (backend/app/core/config.py -> backend/app/core -> backend/app -> backend
# -> project root). Computed from __file__, never from the CWD.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

DEFAULT_ENV_FILE: Final[Path] = PROJECT_ROOT / ".env"


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, optional quotes and inline
    comments (` # ...`) are stripped; blank lines and comments are ignored."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip inline comments (space + #) for unquoted values.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        if key and value:
            values[key] = value
    return values


class Settings(BaseSettings):
    """Validated application settings. Construction raises on invalid config."""

    model_config = SettingsConfigDict(
        extra="ignore",  # reserved keys in .env.example are ignored, not rejected
        case_sensitive=True,
    )

    app_env: AppEnv = Field(default="development")
    database_url: str = Field(..., min_length=1)  # required -> fail-fast when missing
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="json")

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        # P1-02: only the psycopg 3 dialect is accepted. A plain
        # postgresql:// URL is explicitly REJECTED (not silently allowed):
        # SQLAlchemy would map it to the psycopg2 DBAPI, changing the driver
        # family behind the configuration's back.
        if not value.startswith(PSYCOPG_SCHEME):
            raise ValueError(
                "DATABASE_URL must use the postgresql+psycopg:// scheme "
                "(see .env.example). Plain postgresql:// is rejected: it "
                "would fall back to the psycopg2 DBAPI."
            )
        if "change-me" in value or value.split("//", 1)[1].startswith(":"):
            raise ValueError("DATABASE_URL contains a placeholder password — real value required.")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _environment_rules(self) -> "Settings":
        # Production hard-fails on insecure logging config; cookie/TLS rules come
        # with the auth phase (their consumers do not exist yet).
        if self.app_env == "production" and self.log_format == "console":
            raise ValueError("LOG_FORMAT=console is not allowed in production (JSON only).")
        return self


def load_settings(env_file: Path | None | Literal["default"] = "default") -> Settings:
    """Build Settings from the environment. Raises ValidationError on bad config.

    Priority (lowest -> highest): .env file, real environment variables.
    Values are passed as init kwargs so validation is identical everywhere.
    """
    file_values: dict[str, str] = {}
    if env_file == "default":
        env_file = DEFAULT_ENV_FILE
    if env_file is not None and env_file.exists():
        file_values = parse_env_file(env_file)

    # Environment variables override file values; only known fields are mapped.
    values: dict[str, str] = {**file_values, **dict(os.environ)}
    kwargs: dict[str, Any] = {}
    for field_name, env_key in ((name, name.upper()) for name in Settings.model_fields):
        if env_key in values:
            kwargs[field_name] = values[env_key]
    return Settings(**kwargs)


def get_settings() -> Settings:
    """Cached accessor used by the app factory and engine factory."""
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = load_settings()
    return _cached_settings


_cached_settings: Settings | None = None


def reset_settings_cache() -> None:
    """Test helper: force reload from the current environment."""
    global _cached_settings
    _cached_settings = None


def describe_validation_error(exc: ValidationError) -> str:
    """Compact, secret-free summary of config validation failures for logs."""
    return "; ".join(
        f"{err['loc'][0] if err['loc'] else 'config'}: {err['msg']}" for err in exc.errors()
    )
