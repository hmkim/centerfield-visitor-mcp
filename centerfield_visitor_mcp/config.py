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

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

USER_ENV_FILE = Path.home() / ".config" / "centerfield-visitor-mcp" / ".env"
REQUIRED_FIELDS = ("company_name", "person_in_charge_mobile")
VALID_FLOORS = ("12", "18")


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

    # ── Transport ─────────────────────────────────────────────────────────
    # "stdio" for local agents (Kiro CLI/IDE, Claude Code, Codex, Cursor, ...).
    # "streamable-http" for remote agents (Amazon Quick, hosted deployments).
    transport: Literal["stdio", "streamable-http"] = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    http_path: str = "/mcp"
    http_stateless: bool = True
    http_json_response: bool = True
    # Comma-separated Host header allow-list for DNS-rebinding protection.
    # Empty = protection off (typical behind a managed HTTPS front such as AgentCore).
    http_allowed_hosts: str = ""

    # File-path tools (register/preview *_from_file) only make sense when the agent and
    # the server share a filesystem. Default: on for stdio, off for streamable-http.
    expose_file_tools: bool | None = None

    # ── Convenience helpers ───────────────────────────────────────────────
    @property
    def file_tools_enabled(self) -> bool:
        if self.expose_file_tools is not None:
            return self.expose_file_tools
        return self.transport == "stdio"

    @property
    def allowed_hosts(self) -> list[str]:
        return [h.strip() for h in self.http_allowed_hosts.split(",") if h.strip()]

    def loaded_env_files(self) -> list[str]:
        """Return the .env files that actually exist (in load order)."""
        return [str(p) for p in ENV_FILES if p.is_file()]

    def missing_required(self) -> list[str]:
        """Return CF_* names of required settings that are still empty."""
        return [f"CF_{name.upper()}" for name in REQUIRED_FIELDS if not getattr(self, name).strip()]

    def startup_problems(self) -> list[str]:
        """Configuration errors that should be reported at startup (non-fatal)."""
        problems: list[str] = []
        if self.default_floor not in VALID_FLOORS:
            problems.append(
                f"CF_DEFAULT_FLOOR={self.default_floor!r} is invalid (use one of {', '.join(VALID_FLOORS)})"
            )
        if self.bulk_max_visitors < 1:
            problems.append("CF_BULK_MAX_VISITORS must be >= 1")
        if self.request_delay < 0:
            problems.append("CF_REQUEST_DELAY must be >= 0")
        return problems

    def public_summary(self) -> dict[str, str]:
        """Settings safe to show to an operator (no phone number)."""
        return {
            "company_name": self.company_name or "(unset)",
            "person_in_charge_mobile": _mask_mobile(self.person_in_charge_mobile),
            "building": f"{self.building}/{self.building_key}",
            "default_floor": self.default_floor,
            "transport": self.transport,
            "file_tools": "on" if self.file_tools_enabled else "off",
            "env_files": ", ".join(self.loaded_env_files()) or "(none)",
        }


def _mask_mobile(value: str) -> str:
    digits = value.strip()
    if not digits:
        return "(unset)"
    if len(digits) <= 4:
        return "*" * len(digits)
    return digits[:3] + "*" * (len(digits) - 5) + digits[-2:]


settings = Settings()
