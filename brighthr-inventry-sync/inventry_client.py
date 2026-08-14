"""InVentry client.

InVentry has no public REST API. Per the handover, integration is via a
database link that InVentry support must enable, and the schema below is the
handover's approximate guess - not confirmed by the vendor.

Everything vendor-specific therefore sits behind InVentryClient so the sync
engine never depends on how InVentry is reached:

  * DryRunInVentryClient  - default. Logs intended writes, changes nothing.
                            Lets the whole sync be built and tested before
                            InVentry credentials exist.
  * SqlServerInVentryClient - real writes over ODBC once InVentry supply the
                            server, database, credentials and true schema.

Only table/column identifiers come from config (they are quoted and validated,
never interpolated from API data); all values are passed as bound parameters.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import InVentryConfig

log = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]*$")


class InVentryError(RuntimeError):
    """InVentry could not be reached or refused a write."""


def _quote_identifier(name: str, what: str) -> str:
    """Validate and bracket-quote a SQL Server identifier from config."""
    if not name or not _IDENTIFIER_RE.match(name):
        raise InVentryError(f"Invalid {what} in configuration: {name!r}")
    return f"[{name}]"


@dataclass
class OnSiteRecord:
    """One person InVentry currently shows as on site."""

    staff_id: str
    staff_name: str = ""
    sign_in_time: Optional[datetime] = None
    location: str = ""
    source: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def is_managed_by_sync(self, source_tag: str) -> bool:
        """True when this record was created by this sync rather than manually.

        With no source column configured we cannot tell, so we report False -
        the caller then leaves the record alone, which is the safe direction.
        """
        if not self.source:
            return False
        return self.source.strip().lower() == source_tag.strip().lower()


class InVentryClient(ABC):
    """Interface the sync engine depends on."""

    @abstractmethod
    def get_on_site(self) -> List[OnSiteRecord]:
        """Everyone InVentry currently shows as signed in (no sign-out time)."""

    @abstractmethod
    def sign_in(self, staff_id: str, staff_name: str, when: datetime, location: str) -> None:
        """Record an arrival."""

    @abstractmethod
    def sign_out(self, staff_id: str, when: datetime) -> None:
        """Record a departure."""

    def close(self) -> None:
        """Release resources. Safe to call more than once."""

    def __enter__(self) -> "InVentryClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    @property
    def is_read_only(self) -> bool:
        return False


class DryRunInVentryClient(InVentryClient):
    """Simulates InVentry. Writes nothing to any real system.

    State is held in memory and optionally persisted to a JSON file so
    consecutive runs behave like a stateful system while testing.
    """

    def __init__(self, config: InVentryConfig, state_path: Optional[Path] = None) -> None:
        self.config = config
        self.state_path = Path(state_path) if state_path else config.dryrun_state_path
        self._records: Dict[str, OnSiteRecord] = {}
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path or not self.state_path.is_file():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read dry-run state at %s: %s", self.state_path, exc)
            return
        for item in raw.get("on_site", []):
            staff_id = str(item.get("staff_id", "")).strip()
            if not staff_id:
                continue
            sign_in = item.get("sign_in_time")
            self._records[staff_id] = OnSiteRecord(
                staff_id=staff_id,
                staff_name=str(item.get("staff_name", "")),
                sign_in_time=datetime.fromisoformat(sign_in) if sign_in else None,
                location=str(item.get("location", "")),
                source=str(item.get("source", "")),
                raw=dict(item),
            )
        log.info("Dry-run InVentry state loaded: %s on site", len(self._records))

    def _save_state(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "_comment": "Simulated InVentry state for dry-run testing. Not real data.",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "on_site": [
                {
                    "staff_id": record.staff_id,
                    "staff_name": record.staff_name,
                    "sign_in_time": record.sign_in_time.isoformat() if record.sign_in_time else None,
                    "location": record.location,
                    "source": record.source,
                }
                for record in self._records.values()
            ],
        }
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_on_site(self) -> List[OnSiteRecord]:
        return list(self._records.values())

    def sign_in(self, staff_id: str, staff_name: str, when: datetime, location: str) -> None:
        log.info("[DRY RUN] would SIGN IN  %s (%s) at %s", staff_id, staff_name or "?", when.isoformat())
        self._records[staff_id] = OnSiteRecord(
            staff_id=staff_id,
            staff_name=staff_name,
            sign_in_time=when,
            location=location,
            source=self.config.source_tag,
        )
        self._save_state()

    def sign_out(self, staff_id: str, when: datetime) -> None:
        log.info("[DRY RUN] would SIGN OUT %s at %s", staff_id, when.isoformat())
        self._records.pop(staff_id, None)
        self._save_state()

    @property
    def is_read_only(self) -> bool:
        return True


class SqlServerInVentryClient(InVentryClient):
    """Writes presence to InVentry's database over ODBC.

    UNVERIFIED against a real InVentry instance. The table and column names in
    config are the handover's best guess; confirm them with InVentry support
    before enabling this driver, and re-check that writing to the presence
    table is supported rather than a stored procedure being required.
    """

    def __init__(self, config: InVentryConfig) -> None:
        self.config = config
        self._connection = None
        # Validate identifiers once, up front, so a typo fails before any write.
        self._table = _quote_identifier(config.table, "InVentry table name")
        self._c_staff_id = _quote_identifier(config.col_staff_id, "staff id column")
        self._c_staff_name = _quote_identifier(config.col_staff_name, "staff name column")
        self._c_sign_in = _quote_identifier(config.col_sign_in, "sign-in column")
        self._c_sign_out = _quote_identifier(config.col_sign_out, "sign-out column")
        self._c_location = _quote_identifier(config.col_location, "location column")
        self._c_updated_at = _quote_identifier(config.col_updated_at, "updated-at column")
        self._c_source = _quote_identifier(config.col_source, "source column") if config.col_source else ""

    # ---------------------------------------------------------- connection

    @property
    def connection(self):
        if self._connection is None:
            try:
                import pyodbc  # imported lazily so dry runs need no ODBC stack
            except ImportError as exc:
                raise InVentryError(
                    "pyodbc is required for the sqlserver driver. Install it with "
                    "`pip install -r requirements.txt`."
                ) from exc
            conn_str = (
                f"DRIVER={{{self.config.odbc_driver}}};"
                f"SERVER={self.config.db_server};"
                f"DATABASE={self.config.db_name};"
                f"UID={self.config.db_user};"
                f"PWD={self.config.db_password};"
                f"Encrypt={'yes' if self.config.encrypt else 'no'};"
                f"TrustServerCertificate={'yes' if self.config.trust_server_certificate else 'no'};"
            )
            try:
                self._connection = pyodbc.connect(conn_str, timeout=self.config.timeout_seconds)
            except Exception as exc:  # pyodbc.Error, but keep the import lazy
                raise InVentryError(f"Could not connect to InVentry database: {exc}") from exc
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    # -------------------------------------------------------------- queries

    def get_on_site(self) -> List[OnSiteRecord]:
        source_select = f", {self._c_source}" if self._c_source else ""
        sql = (
            f"SELECT {self._c_staff_id}, {self._c_staff_name}, {self._c_sign_in}, "
            f"{self._c_location}{source_select} "
            f"FROM {self._table} WHERE {self._c_sign_out} IS NULL"
        )
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql)
            rows = cursor.fetchall()
        except InVentryError:
            raise
        except Exception as exc:
            raise InVentryError(f"Failed to read on-site staff from InVentry: {exc}") from exc

        records = []
        for row in rows:
            records.append(
                OnSiteRecord(
                    staff_id=str(row[0]).strip(),
                    staff_name=str(row[1] or "").strip(),
                    sign_in_time=row[2],
                    location=str(row[3] or "").strip(),
                    source=str(row[4] or "").strip() if self._c_source else "",
                )
            )
        return records

    def sign_in(self, staff_id: str, staff_name: str, when: datetime, location: str) -> None:
        columns = [self._c_staff_id, self._c_staff_name, self._c_sign_in, self._c_location, self._c_updated_at]
        values: List[Any] = [staff_id, staff_name, when, location, when]
        if self._c_source:
            columns.append(self._c_source)
            values.append(self.config.source_tag)
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO {self._table} ({', '.join(columns)}) VALUES ({placeholders})"
        self._execute(sql, values, f"sign in {staff_id}")

    def sign_out(self, staff_id: str, when: datetime) -> None:
        sql = (
            f"UPDATE {self._table} SET {self._c_sign_out} = ?, {self._c_updated_at} = ? "
            f"WHERE {self._c_staff_id} = ? AND {self._c_sign_out} IS NULL"
        )
        self._execute(sql, [when, when, staff_id], f"sign out {staff_id}")

    def _execute(self, sql: str, params: List[Any], description: str) -> None:
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, params)
            self.connection.commit()
        except InVentryError:
            raise
        except Exception as exc:
            try:
                self.connection.rollback()
            except Exception:  # pragma: no cover - rollback is best effort
                pass
            raise InVentryError(f"InVentry write failed ({description}): {exc}") from exc


def build_inventry_client(config: InVentryConfig, force_dry_run: bool = False) -> InVentryClient:
    """Pick the driver named in config, or the dry-run client when forced."""
    if force_dry_run or config.driver == "dryrun":
        return DryRunInVentryClient(config)
    if config.driver == "sqlserver":
        return SqlServerInVentryClient(config)
    raise InVentryError(f"Unknown INVENTRY_DRIVER {config.driver!r}; expected 'dryrun' or 'sqlserver'.")
