"""BrightHR Customer API client.

Source of truth for who is clocked in via BrightHR Blip.

The exact JSON field names BrightHR returns are an open question in the
handover, so nothing here reads a hardcoded key. Every field goes through
FieldMap (field_map.json), which tries a list of candidate names. When the real
sample JSON arrives, adjust the JSON file - not this module.

Docs: https://docs.bright.hr | Portal: https://developer.brighthr.com
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

import requests

from config import BrightHRConfig

log = logging.getLogger(__name__)

# Presence states derived from the Blip event stream.
STATE_ON_SITE = "on_site"
STATE_ON_BREAK = "on_break"
STATE_OFF_SITE = "off_site"


class BrightHRError(RuntimeError):
    """BrightHR could not be reached or returned something unusable.

    Callers must treat this as 'presence unknown' and make no changes to
    InVentry - an API outage must never empty the fire roll call.
    """


def _normalise_key(key: str) -> str:
    return key.replace("_", "").replace("-", "").replace(" ", "").strip().lower()


def _normalise_value(value: Any) -> str:
    return str(value).replace("_", "").replace("-", "").replace(" ", "").strip().lower()


def _lookup(record: Mapping[str, Any], candidates: Sequence[str]) -> Optional[Any]:
    """Return the first candidate key present in record, or None.

    Supports dotted paths ("employee.id") and matches keys case-insensitively,
    ignoring underscores and hyphens.
    """
    if not isinstance(record, Mapping):
        return None
    flat = {_normalise_key(str(k)): v for k, v in record.items()}
    for candidate in candidates:
        if "." in candidate:
            cursor: Any = record
            for part in candidate.split("."):
                if not isinstance(cursor, Mapping):
                    cursor = None
                    break
                cursor = {_normalise_key(str(k)): v for k, v in cursor.items()}.get(_normalise_key(part))
                if cursor is None:
                    break
            if cursor is not None and cursor != "":
                return cursor
            continue
        value = flat.get(_normalise_key(candidate))
        if value is not None and value != "":
            return value
    return None


@dataclass
class FieldMap:
    """BrightHR field-name mapping loaded from field_map.json."""

    events_root: Sequence[str]
    employees_root: Sequence[str]
    absences_root: Sequence[str]
    event: Mapping[str, Sequence[str]]
    employee: Mapping[str, Sequence[str]]
    absence: Mapping[str, Sequence[str]]
    event_types: Mapping[str, Sequence[str]]
    absence_statuses_blocking: Sequence[str]

    @classmethod
    def load(cls, path: Path) -> "FieldMap":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise BrightHRError(f"Field map not found at {path}") from exc
        except json.JSONDecodeError as exc:
            raise BrightHRError(f"Field map at {path} is not valid JSON: {exc}") from exc
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "FieldMap":
        event_types = {k: v for k, v in raw.get("event_types", {}).items() if not k.startswith("_")}
        return cls(
            events_root=raw.get("events_root", ["events", "data"]),
            employees_root=raw.get("employees_root", ["employees", "data"]),
            absences_root=raw.get("absences_root", ["absences", "data"]),
            event=raw.get("event", {}),
            employee=raw.get("employee", {}),
            absence=raw.get("absence", {}),
            event_types=event_types,
            absence_statuses_blocking=raw.get("absence_statuses_blocking", ["approved"]),
        )

    def get(self, section: str, logical_name: str, record: Mapping[str, Any]) -> Optional[Any]:
        candidates = getattr(self, section, {}).get(logical_name, [logical_name])
        return _lookup(record, candidates)

    def classify_event_type(self, raw_value: Any) -> Optional[str]:
        """Map a raw BrightHR event type onto clock_in/clock_out/break_*."""
        if raw_value is None:
            return None
        needle = _normalise_value(raw_value)
        # Longest candidate first so "break_start" wins over a bare "break"
        # prefix match, and "clock_out" is never mistaken for "clock_in".
        best: Optional[str] = None
        best_len = -1
        for logical, values in self.event_types.items():
            for value in values:
                if _normalise_value(value) == needle and len(value) > best_len:
                    best, best_len = logical, len(value)
        return best


def unwrap_collection(payload: Any, roots: Sequence[str]) -> List[Dict[str, Any]]:
    """Pull the list of records out of a response body.

    Handles a bare list, {"events": [...]}, and {"data": {"events": [...]}}.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, Mapping):
        return []
    for root in roots:
        value = _lookup(payload, [root])
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, Mapping):
            nested = unwrap_collection(value, roots)
            if nested:
                return nested
    # Single object responses come back as one record.
    if any(_normalise_key(str(k)) in {"employeeid", "employee_id", "id"} for k in payload.keys()):
        return [dict(payload)]
    return []


def parse_timestamp(raw: Any) -> Optional[datetime]:
    """Parse a BrightHR timestamp into a timezone-aware UTC datetime."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        # Epoch values are sometimes in milliseconds.
        seconds = float(raw) / 1000.0 if float(raw) > 1e11 else float(raw)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = str(raw).strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    log.warning("Could not parse BrightHR timestamp %r", raw)
    return None


@dataclass
class AttendanceEvent:
    employee_id: str
    employee_name: str = ""
    event_type: Optional[str] = None
    raw_event_type: str = ""
    timestamp: Optional[datetime] = None
    location: str = ""
    device_id: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_record(cls, record: Mapping[str, Any], field_map: FieldMap) -> Optional["AttendanceEvent"]:
        employee_id = field_map.get("event", "employee_id", record)
        if employee_id is None:
            log.warning("Skipping BrightHR event with no recognisable employee id: %s", record)
            return None
        raw_type = field_map.get("event", "event_type", record)
        return cls(
            employee_id=str(employee_id).strip(),
            employee_name=str(field_map.get("event", "employee_name", record) or "").strip(),
            event_type=field_map.classify_event_type(raw_type),
            raw_event_type=str(raw_type or "").strip(),
            timestamp=parse_timestamp(field_map.get("event", "timestamp", record)),
            location=str(field_map.get("event", "location", record) or "").strip(),
            device_id=str(field_map.get("event", "device_id", record) or "").strip(),
            raw=dict(record),
        )


@dataclass
class StaffPresence:
    """Derived current state for one employee."""

    employee_id: str
    employee_name: str
    state: str
    since: Optional[datetime]
    location: str = ""
    last_event_type: str = ""

    @property
    def is_on_site(self) -> bool:
        return self.state in (STATE_ON_SITE, STATE_ON_BREAK)


def derive_presence(
    events: Iterable[AttendanceEvent],
    treat_break_as_on_site: bool = True,
) -> Dict[str, StaffPresence]:
    """Reduce an event stream to each employee's current state.

    The last event per employee wins. Events with no recognisable type are
    treated as a clock-in when the caller asked BrightHR for clocked-in staff
    only, which is the common shape of the /attendance/events?status= response.
    """
    latest: Dict[str, AttendanceEvent] = {}
    for index, event in enumerate(events):
        current = latest.get(event.employee_id)
        if current is None or _event_sort_key(event, index) >= _event_sort_key(current, -1):
            latest[event.employee_id] = event

    presence: Dict[str, StaffPresence] = {}
    for employee_id, event in latest.items():
        if event.event_type == "clock_out":
            state = STATE_OFF_SITE
        elif event.event_type == "break_start":
            state = STATE_ON_BREAK if treat_break_as_on_site else STATE_OFF_SITE
        elif event.event_type in ("clock_in", "break_end"):
            state = STATE_ON_SITE
        elif event.event_type is None:
            # Unrecognised or absent type: the record exists in a
            # currently-clocked-in response, so treat presence as implied and
            # surface the raw value for mapping.
            if event.raw_event_type:
                log.warning(
                    "Unrecognised BrightHR event type %r for %s - add it to field_map.json event_types",
                    event.raw_event_type,
                    employee_id,
                )
            state = STATE_ON_SITE
        else:
            state = STATE_ON_SITE
        presence[employee_id] = StaffPresence(
            employee_id=employee_id,
            employee_name=event.employee_name,
            state=state,
            since=event.timestamp,
            location=event.location,
            last_event_type=event.raw_event_type,
        )
    return presence


def _event_sort_key(event: AttendanceEvent, index: int) -> tuple:
    # Events without a usable timestamp fall back to arrival order rather than
    # being silently dropped.
    stamp = event.timestamp or datetime.min.replace(tzinfo=timezone.utc)
    return (stamp, index)


class BrightHRClient:
    """Thin wrapper over the BrightHR Customer API."""

    def __init__(
        self,
        config: BrightHRConfig,
        session: Optional[requests.Session] = None,
        field_map: Optional[FieldMap] = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.field_map = field_map or FieldMap.load(config.field_map_path)
        self._status_filter_supported = config.supports_status_filter

    # ---------------------------------------------------------------- HTTP

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self.config.base_url.rstrip("/") + "/" + path.lstrip("/")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        last_error: Optional[Exception] = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.session.get(
                    url, headers=headers, params=params, timeout=self.config.timeout_seconds
                )
            except requests.RequestException as exc:
                last_error = exc
                log.warning("BrightHR request to %s failed (attempt %s): %s", url, attempt, exc)
                self._sleep_before_retry(attempt)
                continue

            if response.status_code == 429:
                wait = self._retry_after_seconds(response, attempt)
                log.warning("BrightHR rate limited on %s; waiting %.1fs", url, wait)
                last_error = BrightHRError(f"Rate limited by BrightHR ({url})")
                if attempt < self.config.max_retries:
                    time.sleep(wait)
                continue

            if response.status_code in (401, 403):
                raise BrightHRError(
                    f"BrightHR rejected the API key ({response.status_code}) for {url}. "
                    "Regenerate it in Settings -> Integrations -> Customer API."
                )

            if response.status_code >= 500:
                last_error = BrightHRError(f"BrightHR returned {response.status_code} for {url}")
                log.warning("BrightHR %s on %s (attempt %s)", response.status_code, url, attempt)
                self._sleep_before_retry(attempt)
                continue

            if not response.ok:
                raise BrightHRError(
                    f"BrightHR returned {response.status_code} for {url}: {response.text[:500]}"
                )

            try:
                return response.json()
            except ValueError as exc:
                raise BrightHRError(f"BrightHR returned non-JSON content for {url}") from exc

        raise BrightHRError(f"BrightHR unreachable after {self.config.max_retries} attempts: {last_error}")

    def _sleep_before_retry(self, attempt: int) -> None:
        if attempt < self.config.max_retries:
            time.sleep(self.config.retry_backoff_seconds * (2 ** (attempt - 1)))

    def _retry_after_seconds(self, response: requests.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return self.config.retry_backoff_seconds * (2 ** (attempt - 1))

    # ------------------------------------------------------------ Endpoints

    def get_attendance_events(
        self,
        status: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[AttendanceEvent]:
        params: Dict[str, Any] = {}
        if status:
            params["status"] = status
        if start:
            params["from"] = start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if end:
            params["to"] = end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        payload = self._request(self.config.events_path, params or None)
        records = unwrap_collection(payload, self.field_map.events_root)
        events: List[AttendanceEvent] = []
        for record in records:
            event = AttendanceEvent.from_record(record, self.field_map)
            if event is not None:
                events.append(event)
        log.debug("BrightHR returned %s attendance records (%s parsed)", len(records), len(events))
        return events

    def get_clocked_in_staff(self, treat_break_as_on_site: bool = True) -> List[StaffPresence]:
        """Return everyone currently on site.

        Prefers the server-side status filter; if the tenant does not support
        it, falls back to replaying today's event stream.
        """
        events: List[AttendanceEvent] = []
        if self._status_filter_supported:
            try:
                events = self.get_attendance_events(status="clocked_in")
            except BrightHRError as exc:
                if "returned 4" not in str(exc):
                    raise
                log.warning("status=clocked_in filter rejected by BrightHR, replaying event stream: %s", exc)
                self._status_filter_supported = False

        if not self._status_filter_supported:
            now = datetime.now(timezone.utc)
            start = (now - timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
            events = self.get_attendance_events(start=start, end=now)

        presence = derive_presence(events, treat_break_as_on_site=treat_break_as_on_site)
        return [p for p in presence.values() if p.is_on_site]

    def get_employees(self) -> List[Dict[str, Any]]:
        payload = self._request(self.config.employees_path)
        records = unwrap_collection(payload, self.field_map.employees_root)
        employees = []
        for record in records:
            employee_id = self.field_map.get("employee", "employee_id", record)
            if employee_id is None:
                continue
            name = self.field_map.get("employee", "employee_name", record)
            if not name:
                first = self.field_map.get("employee", "first_name", record) or ""
                last = self.field_map.get("employee", "last_name", record) or ""
                name = f"{first} {last}".strip()
            employees.append(
                {
                    "employee_id": str(employee_id).strip(),
                    "employee_name": str(name or "").strip(),
                    "email": str(self.field_map.get("employee", "email", record) or "").strip(),
                    "employee_number": str(
                        self.field_map.get("employee", "employee_number", record) or ""
                    ).strip(),
                    "raw": record,
                }
            )
        return employees

    def get_absent_employee_ids(self, on_date: Optional[date] = None) -> Set[str]:
        """Employee ids with an approved absence covering on_date.

        Used to avoid signing in someone BrightHR shows as on holiday or off
        sick because of a stale or duplicated clock-in event.
        """
        target = on_date or datetime.now(timezone.utc).date()
        params = {
            "from": target.isoformat(),
            "to": target.isoformat(),
        }
        payload = self._request(self.config.absences_path, params)
        records = unwrap_collection(payload, self.field_map.absences_root)
        blocking = {_normalise_value(s) for s in self.field_map.absence_statuses_blocking}

        absent: Set[str] = set()
        for record in records:
            employee_id = self.field_map.get("absence", "employee_id", record)
            if employee_id is None:
                continue
            status = self.field_map.get("absence", "status", record)
            # No status field at all means the endpoint only returns approved
            # absences; treat it as blocking rather than ignoring it.
            if status is not None and _normalise_value(status) not in blocking:
                continue
            start = parse_timestamp(self.field_map.get("absence", "start_date", record))
            end = parse_timestamp(self.field_map.get("absence", "end_date", record))
            if start and start.date() > target:
                continue
            if end and end.date() < target:
                continue
            absent.add(str(employee_id).strip())
        return absent
