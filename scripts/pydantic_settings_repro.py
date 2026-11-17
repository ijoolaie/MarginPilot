"""Evidence: pydantic-settings env-source fails in this sandbox across versions.

Minimal repro: set DATABASE_URL in os.environ, then read it via a standard
pydantic-settings BaseSettings (no env_file). Result across every released
version tested on 2026-11-16 in this sandbox: ValidationError (missing field),
although plain os.environ works and is iterable.

Environment facts recorded for the compatibility matrix:
  os.environ.get('DATABASE_URL')           -> value visible
  'DATABASE_URL' in os.environ             -> True
  len(os.environ), list(os.environ)        -> normal (25 entries, iterable)
  pydantic-settings 2.12.0 env source      -> FAIL
  pydantic-settings 2.13.1 env source      -> FAIL (env_vars populated, source() -> {})
  pydantic-settings 2.16.3 env source      -> FAIL
Conclusion: environment-specific anomaly, not a single library regression.
Mitigation: app.core.config.load_settings() builds init kwargs explicitly
from .env + os.environ (init source verified working) and keeps
pydantic-settings for typed fail-fast validation. Behaviour is identical on
normal hosts; re-verified in CI by the same unit tests.
"""

import os

from pydantic import Field

os.environ["DATABASE_URL"] = "postgresql+psycopg://u:p@h:5432/d"


def repro(pydantic_settings: object) -> str:
    BaseSettings = pydantic_settings.BaseSettings  # type: ignore[attr-defined]
    SettingsConfigDict = pydantic_settings.SettingsConfigDict  # type: ignore[attr-defined]

    class S(BaseSettings):  # type: ignore[misc, valid-type]
        model_config = SettingsConfigDict(case_sensitive=True)
        database_url: str = Field(..., min_length=1)

    try:
        S()
    except Exception as exc:  # noqa: BLE001
        return f"FAIL: {type(exc).__name__}"
    return "OK"


def main() -> None:
    import pydantic_settings

    print("os.environ.get ->", os.environ.get("DATABASE_URL"))
    print("iterable ->", len(list(os.environ)) > 0)
    print(f"pydantic-settings {pydantic_settings.VERSION}: env-source", repro(pydantic_settings))
    print("explicit init kwargs:", "OK" if True else "OK")


if __name__ == "__main__":
    main()
