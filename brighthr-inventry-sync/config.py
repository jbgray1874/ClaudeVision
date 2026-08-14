"""Configuration for the BrightHR -> InVentry sync.

Credentials are read from the environment (or a local .env file) rather than
being written into this file, so nothing secret ends up in source control.
Copy .env.example to .env and fill it in.

    from config import load_config
    cfg = load_config()
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def load_dotenv(path: Optional[Path] = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Uses python-dotenv when it is installed; otherwise falls back to a small
    parser so the module works in a bare interpreter (and in tests).
    Existing environment variables always win.
    """
    env_path = Path(path) if path else PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv as _load_dotenv  # type: ignore

        _load_dotenv(env_path, override=False)
        return
    except ImportError:
        pass

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ConfigError(f"{name} must be a boolean value, got {raw!r}")


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass
class BrightHRConfig:
    """BrightHR Customer API settings.

    The API key comes from app.brighthr.com -> Settings -> Integrations ->
    Customer API.
    """

    api_key: str = ""
    base_url: str = "https://api.brighthr.com/v1"
    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0
    # Endpoint paths are configurable because BrightHR has versioned these in
    # the past and we do not want a vendor change to require a code change.
    events_path: str = "/attendance/events"
    employees_path: str = "/employees"
    absences_path: str = "/absences"
    # Some tenants expose a server-side filter for currently-clocked-in staff.
    # When False the client derives presence from the raw event stream instead.
    supports_status_filter: bool = True
    field_map_path: Path = field(default_factory=lambda: PROJECT_ROOT / "field_map.json")


@dataclass
class InVentryConfig:
    """InVentry connection settings.

    InVentry has no public REST API. Access is via a database integration that
    InVentry support must enable, so every value here is TBC until they reply.
    See docs/INVENTRY_SUPPORT_EMAIL.md.

    driver options: "dryrun" (default, writes nothing) | "sqlserver"
    """

    driver: str = "dryrun"
    db_server: str = ""
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    odbc_driver: str = "ODBC Driver 18 for SQL Server"
    encrypt: bool = True
    trust_server_certificate: bool = False
    timeout_seconds: int = 30
    # Schema names are configuration because the real schema is unconfirmed;
    # the defaults follow the approximate table in the handover.
    table: str = "InVentry_Staff_OnSite"
    col_staff_id: str = "StaffID"
    col_staff_name: str = "StaffName"
    col_sign_in: str = "SignInTime"
    col_sign_out: str = "SignOutTime"
    col_location: str = "Location"
    col_updated_at: str = "UpdatedAt"
    # Optional column used to tell our writes apart from manual sign-ins made
    # at the InVentry terminal. If the real schema has no such column, set
    # INVENTRY_COL_SOURCE to an empty string and manual-override protection
    # falls back to the employee map (see sync.py).
    col_source: str = "UpdatedBy"
    source_tag: str = "BRIGHTHR_SYNC"
    # Seed file used by the dry-run driver so a realistic starting state can be
    # simulated before InVentry access exists.
    dryrun_state_path: Path = field(default_factory=lambda: PROJECT_ROOT / "state" / "dryrun_inventry.json")


@dataclass
class SyncConfig:
    """Sync behaviour and safety rails."""

    site_name: str = "Shepshed"
    interval_minutes: int = 5
    # Staff on a break are still physically in the building, so they stay
    # signed in for the fire roll call. Handover flags this as a decision for
    # James/Matt, so it is a switch rather than a hardcoded assumption.
    treat_break_as_on_site: bool = True
    # Cross-reference the absences endpoint and refuse to sign in anyone
    # recorded as on holiday or off sick.
    check_absences: bool = True
    # Do not sign out anyone whose InVentry record was not created by us.
    respect_manual_sign_in: bool = True
    # Safety rails against a bad or partial BrightHR response emptying the
    # fire roll call. A run that trips these aborts without writing.
    max_sign_outs_per_run: int = 25
    max_sign_out_ratio: float = 0.5
    # If BrightHR reports nobody on site, assume a data problem rather than an
    # empty building unless this is explicitly enabled.
    allow_full_sign_out: bool = False
    employee_map_path: Path = field(default_factory=lambda: PROJECT_ROOT / "employee_map.json")
    # Sign out staff InVentry knows about but the employee map does not?
    # Off by default: an unmapped person is an unknown, not an absence.
    sign_out_unmapped: bool = False


@dataclass
class LoggingConfig:
    log_path: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")
    level: str = "INFO"
    retention_days: int = 90


@dataclass
class Config:
    brighthr: BrightHRConfig
    inventry: InVentryConfig
    sync: SyncConfig
    logging: LoggingConfig

    def validate_for_brighthr(self) -> None:
        if not self.brighthr.api_key:
            raise ConfigError(
                "BRIGHTHR_API_KEY is not set. Copy .env.example to .env and add the "
                "key from app.brighthr.com -> Settings -> Integrations -> Customer API."
            )

    def validate_for_write(self) -> None:
        """Checks that must pass before anything is written to InVentry."""
        self.validate_for_brighthr()
        if self.inventry.driver == "dryrun":
            return
        if self.inventry.driver != "sqlserver":
            raise ConfigError(
                f"Unknown INVENTRY_DRIVER {self.inventry.driver!r}; expected 'dryrun' or 'sqlserver'."
            )
        missing = [
            name
            for name, value in (
                ("INVENTRY_DB_SERVER", self.inventry.db_server),
                ("INVENTRY_DB_NAME", self.inventry.db_name),
                ("INVENTRY_DB_USER", self.inventry.db_user),
                ("INVENTRY_DB_PASSWORD", self.inventry.db_password),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                "InVentry database settings are incomplete: "
                + ", ".join(missing)
                + ". These come from InVentry support - see docs/INVENTRY_SUPPORT_EMAIL.md."
            )


def load_config(dotenv_path: Optional[Path] = None) -> Config:
    """Build a Config from the environment, loading .env first if present."""
    load_dotenv(dotenv_path)

    brighthr = BrightHRConfig(
        api_key=_env("BRIGHTHR_API_KEY", "") or "",
        base_url=_env("BRIGHTHR_BASE_URL", BrightHRConfig.base_url) or BrightHRConfig.base_url,
        timeout_seconds=_env_float("BRIGHTHR_TIMEOUT_SECONDS", 30.0),
        max_retries=_env_int("BRIGHTHR_MAX_RETRIES", 3),
        retry_backoff_seconds=_env_float("BRIGHTHR_RETRY_BACKOFF_SECONDS", 2.0),
        events_path=_env("BRIGHTHR_EVENTS_PATH", BrightHRConfig.events_path) or BrightHRConfig.events_path,
        employees_path=_env("BRIGHTHR_EMPLOYEES_PATH", BrightHRConfig.employees_path)
        or BrightHRConfig.employees_path,
        absences_path=_env("BRIGHTHR_ABSENCES_PATH", BrightHRConfig.absences_path)
        or BrightHRConfig.absences_path,
        supports_status_filter=_env_bool("BRIGHTHR_SUPPORTS_STATUS_FILTER", True),
        field_map_path=Path(_env("BRIGHTHR_FIELD_MAP_PATH", str(PROJECT_ROOT / "field_map.json"))),
    )

    inventry = InVentryConfig(
        driver=(_env("INVENTRY_DRIVER", "dryrun") or "dryrun").strip().lower(),
        db_server=_env("INVENTRY_DB_SERVER", "") or "",
        db_name=_env("INVENTRY_DB_NAME", "") or "",
        db_user=_env("INVENTRY_DB_USER", "") or "",
        db_password=_env("INVENTRY_DB_PASSWORD", "") or "",
        odbc_driver=_env("INVENTRY_ODBC_DRIVER", InVentryConfig.odbc_driver) or InVentryConfig.odbc_driver,
        encrypt=_env_bool("INVENTRY_ENCRYPT", True),
        trust_server_certificate=_env_bool("INVENTRY_TRUST_SERVER_CERTIFICATE", False),
        timeout_seconds=_env_int("INVENTRY_TIMEOUT_SECONDS", 30),
        table=_env("INVENTRY_TABLE", InVentryConfig.table) or InVentryConfig.table,
        col_staff_id=_env("INVENTRY_COL_STAFF_ID", InVentryConfig.col_staff_id) or InVentryConfig.col_staff_id,
        col_staff_name=_env("INVENTRY_COL_STAFF_NAME", InVentryConfig.col_staff_name)
        or InVentryConfig.col_staff_name,
        col_sign_in=_env("INVENTRY_COL_SIGN_IN", InVentryConfig.col_sign_in) or InVentryConfig.col_sign_in,
        col_sign_out=_env("INVENTRY_COL_SIGN_OUT", InVentryConfig.col_sign_out) or InVentryConfig.col_sign_out,
        col_location=_env("INVENTRY_COL_LOCATION", InVentryConfig.col_location) or InVentryConfig.col_location,
        col_updated_at=_env("INVENTRY_COL_UPDATED_AT", InVentryConfig.col_updated_at)
        or InVentryConfig.col_updated_at,
        col_source=_env("INVENTRY_COL_SOURCE", InVentryConfig.col_source) or "",
        source_tag=_env("INVENTRY_SOURCE_TAG", InVentryConfig.source_tag) or InVentryConfig.source_tag,
        dryrun_state_path=Path(
            _env("INVENTRY_DRYRUN_STATE_PATH", str(PROJECT_ROOT / "state" / "dryrun_inventry.json"))
        ),
    )

    sync = SyncConfig(
        site_name=_env("SITE_NAME", "Shepshed") or "Shepshed",
        interval_minutes=_env_int("SYNC_INTERVAL_MINUTES", 5),
        treat_break_as_on_site=_env_bool("SYNC_TREAT_BREAK_AS_ON_SITE", True),
        check_absences=_env_bool("SYNC_CHECK_ABSENCES", True),
        respect_manual_sign_in=_env_bool("SYNC_RESPECT_MANUAL_SIGN_IN", True),
        max_sign_outs_per_run=_env_int("SYNC_MAX_SIGN_OUTS_PER_RUN", 25),
        max_sign_out_ratio=_env_float("SYNC_MAX_SIGN_OUT_RATIO", 0.5),
        allow_full_sign_out=_env_bool("SYNC_ALLOW_FULL_SIGN_OUT", False),
        employee_map_path=Path(_env("SYNC_EMPLOYEE_MAP_PATH", str(PROJECT_ROOT / "employee_map.json"))),
        sign_out_unmapped=_env_bool("SYNC_SIGN_OUT_UNMAPPED", False),
    )

    logging_cfg = LoggingConfig(
        log_path=Path(_env("LOG_PATH", str(PROJECT_ROOT / "logs"))),
        level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
        retention_days=_env_int("LOG_RETENTION_DAYS", 90),
    )

    return Config(brighthr=brighthr, inventry=inventry, sync=sync, logging=logging_cfg)
