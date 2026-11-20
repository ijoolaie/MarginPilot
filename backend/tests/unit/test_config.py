"""Unit tests: Settings fail-fast behaviour (no network, no database)."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core import config
from app.core.config import Settings, load_settings, reset_settings_cache

VALID_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+psycopg://marginpilot:secret@localhost:5432/marginpilot",
}


def make_settings(env: dict[str, str]) -> Settings:
    # Map env-var-style names (DATABASE_URL) onto Settings field names.
    return Settings(**{name.lower(): value for name, value in env.items()})


@pytest.fixture()
def isolated_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point DEFAULT_ENV_FILE at a non-existent temp path so the sandbox's
    real repo-root .env (git-ignored, developer-specific) can never influence
    unit-test outcomes — in CI there is no .env at all."""
    missing = tmp_path / "no.env"
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", missing)
    return missing


class TestSettingsFailFast:
    def test_missing_database_url_raises(
        self, monkeypatch: pytest.MonkeyPatch, isolated_env_file: Path
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ValidationError) as excinfo:
            load_settings()
        assert "database_url" in str(excinfo.value)

    def test_wrong_scheme_rejected(self) -> None:
        env: dict[str, str] = {**VALID_ENV, "DATABASE_URL": "postgresql+asyncpg://u:p@h/db"}
        with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
            make_settings(env)

    def test_sqlite_rejected(self) -> None:
        env: dict[str, str] = {**VALID_ENV, "DATABASE_URL": "sqlite:///./local.db"}
        with pytest.raises(ValidationError):
            make_settings(env)

    def test_bare_postgresql_scheme_rejected(self) -> None:
        # P1-02: plain postgresql:// is EXPLICITLY rejected — SQLAlchemy
        # would silently fall back to the psycopg2 DBAPI driver family.
        env: dict[str, str] = {
            **VALID_ENV,
            "DATABASE_URL": "postgresql://marginpilot:secret@localhost:5432/marginpilot",
        }
        with pytest.raises(ValidationError, match="psycopg2"):
            make_settings(env)

    def test_psycopg_scheme_accepted(self) -> None:
        # P1-02: the pinned scheme passes and reaches the engine unchanged.
        settings = make_settings(VALID_ENV)
        assert settings.database_url.startswith("postgresql+psycopg://")

    def test_placeholder_password_rejected(self) -> None:
        env: dict[str, str] = {
            **VALID_ENV,
            "DATABASE_URL": "postgresql+psycopg://marginpilot:change-me@localhost:5432/marginpilot",
        }
        with pytest.raises(ValidationError, match="placeholder"):
            make_settings(env)

    def test_valid_minimal_config_parses(self) -> None:
        settings = make_settings(VALID_ENV)
        assert settings.app_env == "development"
        assert settings.log_format == "json"
        assert settings.db_pool_size == 10
        assert settings.cors_origins == ["http://localhost:3000"]

    def test_cors_origins_csv_split(self) -> None:
        env: dict[str, str] = {
            **VALID_ENV,
            "CORS_ORIGINS": " http://localhost:3000 , https://app.example.com ",
        }
        settings = make_settings(env)
        assert settings.cors_origins == ["http://localhost:3000", "https://app.example.com"]

    def test_invalid_app_env_rejected(self) -> None:
        env: dict[str, Any] = {**VALID_ENV, "APP_ENV": "test"}
        with pytest.raises(ValidationError):
            make_settings(env)

    def test_console_log_forbidden_in_production(self) -> None:
        env: dict[str, str] = {**VALID_ENV, "APP_ENV": "production", "LOG_FORMAT": "console"}
        with pytest.raises(ValidationError, match="production"):
            make_settings(env)

    def test_pool_size_must_be_positive(self) -> None:
        env: dict[str, Any] = {**VALID_ENV, "DB_POOL_SIZE": "0"}
        with pytest.raises(ValidationError):
            make_settings(env)

    def test_comparison_row_limit_default_and_upper_bound(self) -> None:
        settings = make_settings(VALID_ENV)
        assert settings.comparison_max_rows_per_list == 100000
        env: dict[str, Any] = {**VALID_ENV, "COMPARISON_MAX_ROWS_PER_LIST": "100001"}
        with pytest.raises(ValidationError):
            make_settings(env)

    def test_unknown_env_keys_are_ignored(self) -> None:
        env: dict[str, str] = {**VALID_ENV, "FUTURE_KEY": "x"}
        settings = make_settings(env)
        assert settings.database_url == VALID_ENV["DATABASE_URL"]

    def test_cache_reset(self, monkeypatch: pytest.MonkeyPatch, isolated_env_file: Path) -> None:
        monkeypatch.setenv("DATABASE_URL", VALID_ENV["DATABASE_URL"])
        reset_settings_cache()
        first = load_settings()
        reset_settings_cache()
        second = load_settings()
        assert first is not second


class TestEnvFileResolution:
    """P1-01: the default .env lives at the PROJECT ROOT, not the CWD."""

    def test_default_env_file_is_project_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # backend/tests/unit/test_config.py -> parents[3] == repo root.
        repo_root = Path(__file__).resolve().parents[3]
        monkeypatch.chdir(tmp_path)  # CWD must be irrelevant
        assert config.DEFAULT_ENV_FILE.is_absolute()
        assert repo_root / ".env" == config.DEFAULT_ENV_FILE

    def test_running_from_backend_reads_root_env_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Functional proof of the default-resolution mechanism: the file is
        # read from wherever DEFAULT_ENV_FILE points, with the process CWD
        # elsewhere (as when uvicorn runs from backend/ against root .env).
        env_file = tmp_path / "root.env"
        env_file.write_text("DB_POOL_SIZE=7\n", encoding="utf-8")
        empty_cwd = tmp_path / "cwd"
        empty_cwd.mkdir()
        monkeypatch.setattr(config, "DEFAULT_ENV_FILE", env_file)
        monkeypatch.chdir(empty_cwd)
        monkeypatch.setenv("DATABASE_URL", VALID_ENV["DATABASE_URL"])
        monkeypatch.delenv("DB_POOL_SIZE", raising=False)
        settings = load_settings()
        assert settings.db_pool_size == 7  # value came from the "root" file

    def test_environment_overrides_file_values(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # P1-01 requirement: env vars keep precedence over .env values.
        env_file = tmp_path / "root.env"
        env_file.write_text("DB_POOL_SIZE=7\nLOG_LEVEL=ERROR\n", encoding="utf-8")
        monkeypatch.setattr(config, "DEFAULT_ENV_FILE", env_file)
        monkeypatch.setenv("DATABASE_URL", VALID_ENV["DATABASE_URL"])
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        monkeypatch.delenv("DB_POOL_SIZE", raising=False)
        settings = load_settings()
        assert settings.log_level == "WARNING"  # env var won
        assert settings.db_pool_size == 7  # file filled the untouched field

    def test_missing_default_file_is_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # No .env anywhere (e.g. CI / container): env vars alone must work.
        monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / "absent.env")
        monkeypatch.setenv("DATABASE_URL", VALID_ENV["DATABASE_URL"])
        settings = load_settings()
        assert settings.database_url == VALID_ENV["DATABASE_URL"]
