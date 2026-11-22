"""Environment-based configuration.  Secrets never live in source control."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ConfigError(RuntimeError):
    """Raised when live Maximo access is requested without usable configuration."""


def parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a minimal ``.env`` file without adding a dependency.

    Real environment variables always win; this only fills gaps.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


class Settings(BaseModel):
    """Validated runtime settings.

    ``api_key`` is a :class:`SecretStr`, so accidental logging or ``repr``
    prints ``**********`` rather than the key.
    """

    model_config = ConfigDict(extra="forbid")

    host: str | None = None
    api_key: SecretStr | None = None
    site_id: str = "BISHA-BESS"
    org_id: str = "BISHA"
    live_enabled: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=4, ge=0, le=10)
    page_size: int = Field(default=100, gt=0, le=1000)

    @field_validator("host")
    @classmethod
    def _trim_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().rstrip("/")
        if not cleaned:
            return None
        for prefix in ("https://", "http://"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :]
        return cleaned

    @property
    def api_root(self) -> str:
        """Base URL the client appends ``/api/os/<objectstructure>`` to."""
        if not self.host:
            raise ConfigError("MAXIMO_HOST is not set")
        base = f"https://{self.host}"
        if self.host.endswith("/maximo"):
            return base
        return f"{base}/maximo"

    def require_live(self) -> None:
        """Guard live API use behind an explicit opt-in and complete config."""
        if not self.live_enabled:
            raise ConfigError(
                "Live Maximo access is disabled. Set MAXIMO_LIVE_ENABLED=true only after "
                "Phase 0 confirms API access."
            )
        missing = []
        if not self.host:
            missing.append("MAXIMO_HOST")
        if self.api_key is None or not self.api_key.get_secret_value():
            missing.append("MAXIMO_APIKEY")
        if missing:
            raise ConfigError("Missing live Maximo configuration: " + ", ".join(missing))


def _env_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_settings(
    env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> Settings:
    """Load settings from the environment, optionally filling gaps from ``.env``."""
    merged: dict[str, str] = {}
    if dotenv_path is not None:
        merged.update(parse_dotenv(dotenv_path))
    merged.update(dict(os.environ if env is None else env))

    def get(name: str) -> str | None:
        value = merged.get(name)
        return value if value not in (None, "") else None

    api_key = get("MAXIMO_APIKEY")
    return Settings(
        host=get("MAXIMO_HOST"),
        api_key=SecretStr(api_key) if api_key else None,
        site_id=get("MAXIMO_SITE_ID") or "BISHA-BESS",
        org_id=get("MAXIMO_ORG_ID") or "BISHA",
        live_enabled=_env_bool(get("MAXIMO_LIVE_ENABLED")),
        timeout_seconds=float(get("MAXIMO_TIMEOUT_SECONDS") or 30.0),
        max_retries=int(get("MAXIMO_MAX_RETRIES") or 4),
        page_size=int(get("MAXIMO_PAGE_SIZE") or 100),
    )
