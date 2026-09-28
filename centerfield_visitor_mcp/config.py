"""Runtime configuration for the Centerfield Visitor MCP server.

Resolution order (highest priority first):
  1. Process environment variables (e.g. the MCP client's "env" block)
  2. .env files — loaded in this order, later files override earlier ones:
       a. ~/.config/centerfield-visitor-mcp/.env
       b. ./.env  (current working directory)
       c. the file pointed to by CF_ENV_FILE
  3. Field defaults below

Copy `.env.example` to `.env`, fill in the real values, and point the MCP client
at it with CF_ENV_FILE. `.env` is git-ignored — never commit real phone numbers.
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

USER_ENV_FILE = Path.home() / ".config" / "centerfield-visitor-mcp" / ".env"
REQUIRED_FIELDS = ("company_name", "person_in_charge_mobile")


def _env_files() -> tuple[Path, ...]:
    candidates = [USER_ENV_FILE, Path.cwd() / ".env"]
    explicit = os.environ.get("CF_ENV_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    files: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            files.append(path)
    return tuple(files)


ENV_FILES = _env_files()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CF_",
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    centerfield_base_url: str = "https://www.centerfield.co.kr"
    # Deployment-specific values — MUST be provided via .env or environment
    # variables (CF_COMPANY_NAME, CF_PERSON_IN_CHARGE_MOBILE). No defaults are shipped.
    company_name: str = ""
    person_in_charge_mobile: str = ""
    building: str = "east"
    building_key: str = "East"
    # Default floor applied when a visitor record/tool call omits `floor` ("12" or "18").
    default_floor: str = "12"
    request_timeout: int = 30
    bulk_max_visitors: int = 200
    request_delay: float = 0.5

    def loaded_env_files(self) -> list[str]:
        """Return the .env files that actually exist (in load order)."""
        return [str(p) for p in ENV_FILES if p.is_file()]

    def missing_required(self) -> list[str]:
        """Return CF_* names of required settings that are still empty."""
        return [f"CF_{name.upper()}" for name in REQUIRED_FIELDS if not getattr(self, name).strip()]


settings = Settings()
