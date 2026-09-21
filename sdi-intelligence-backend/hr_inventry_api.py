"""
InVentry Partner API client.

Built from InVentry's Partner API documentation (received 16 Sep 2026). This is
the supported route into InVentry, replacing the earlier - and never verified -
assumption that a service swept a folder of CSVs.

What the documentation establishes:

  * Auth      apikey + partnersecret, both in request HEADERS.
              apikey comes from the InVentry console (Setup & Options ->
              Partner API -> Add API Key). partnersecret is issued by
              InVentry Ltd and is the same across their installations.
  * Network   ON-PREMISES ONLY, not reachable externally, usually running on
              the reception sign-in touchscreen. Certificates are locally
              issued and self-signed.
  * GET       JSON response bodies. Limited to 20 calls per minute; a 429 must
              be handled. Polling should be no more often than every 5s.
  * POST      Bodies are x-www-form-urlencoded key/value pairs, NOT JSON.
              Responses carry at least 'response' and 'message' keys; adding a
              person also returns the new person's ID. POST is EXEMPT from the
              rate limit.
  * Identity  The personnel field PersonID (varchar 40) is settable and is
              documented as the place to store *our* system's ID - so the
              BrightHR employee UUID lives there and no mapping table is
              needed.
  * Presence  The events table exposes settable EventType and EventDateTime,
              and InVentry's own ANPR partners use the API to sign staff in and
              out. So pushing presence is supported.
  * Sandbox   162.13.119.241, self-signed, keys issued by InVentry. Multiple
              partners share it - DUMMY DATA ONLY.

Endpoint PATHS are not in these documents; they are in the Postman collection,
which we do not yet have. Every path is therefore config (INVENTRY_PATH_*), so
applying that collection is a settings change rather than a code change. Until
the paths are confirmed, calls will 404 - which is why the push defaults to a
dry run.
"""
import datetime
import threading
import time

import requests

import hr_config as cfg

# 20 GET calls per minute, per the documentation. Kept slightly under.
GET_CALLS_PER_WINDOW = 19
GET_WINDOW_SECONDS = 60.0


class InVentryAPIError(RuntimeError):
    """InVentry's API could not be reached, or refused a call."""


class RateLimiter:
    """Sliding-window limiter for GET calls (POST is exempt)."""

    def __init__(self, calls: int = GET_CALLS_PER_WINDOW, window: float = GET_WINDOW_SECONDS):
        self.calls = calls
        self.window = window
        self._times = []
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """Block until a call is allowed. Returns seconds waited."""
        waited = 0.0
        with self._lock:
            while True:
                now = time.monotonic()
                self._times = [t for t in self._times if now - t < self.window]
                if len(self._times) < self.calls:
                    self._times.append(now)
                    return waited
                sleep_for = self.window - (now - self._times[0]) + 0.05
                time.sleep(sleep_for)
                waited += sleep_for


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def format_datetime(value) -> str:
    """Format a timestamp for InVentry's datetime fields.

    Their fields are SQL Server datetime, so send a plain local-style string
    without a timezone suffix rather than an ISO string ending in Z.
    """
    if value is None:
        value = _utc_now()
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            value = datetime.datetime.fromisoformat(text)
        except ValueError:
            return value if isinstance(value, str) else str(value)
    if value.tzinfo is not None:
        value = value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


class InVentryAPI:
    """Thin wrapper over the InVentry Partner API."""

    def __init__(self, base_url=None, api_key=None, partner_secret=None,
                 verify=None, timeout=None, session=None, limiter=None):
        self.base_url = (base_url if base_url is not None else cfg.INVENTRY_API_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else cfg.INVENTRY_API_KEY
        self.partner_secret = partner_secret if partner_secret is not None else cfg.INVENTRY_PARTNER_SECRET
        self.timeout = timeout or cfg.INVENTRY_API_TIMEOUT
        self.session = session or requests.Session()
        self.limiter = limiter if limiter is not None else RateLimiter()
        self.warnings = []

        # Their certificate is self-signed. A pinned CA bundle keeps
        # verification on and is preferred; otherwise verification is off,
        # which is tolerable only because this is a LAN call to a known host.
        if verify is not None:
            self.verify = verify
        elif cfg.INVENTRY_API_CA_BUNDLE:
            self.verify = cfg.INVENTRY_API_CA_BUNDLE
        else:
            self.verify = bool(cfg.INVENTRY_API_VERIFY)
        if self.verify is False:
            self.warnings.append(
                "TLS verification is OFF for InVentry (self-signed certificate). "
                "Set INVENTRY_API_CA_BUNDLE to the exported certificate to turn it back on."
            )

    # ── plumbing ─────────────────────────────────────────────────────────

    def _require_config(self):
        missing = [name for name, value in (
            ("INVENTRY_API_BASE_URL", self.base_url),
            ("INVENTRY_API_KEY", self.api_key),
            ("INVENTRY_PARTNER_SECRET", self.partner_secret),
        ) if not value]
        if missing:
            raise InVentryAPIError(
                "InVentry API is not configured: " + ", ".join(missing) + ". The API key comes "
                "from the InVentry console (Setup & Options -> Partner API); the partner secret "
                "is issued by InVentry Ltd."
            )

    def _headers(self):
        # Documented header names, sent lowercase exactly as written there.
        return {"apikey": self.api_key, "partnersecret": self.partner_secret}

    def _url(self, path):
        return self.base_url + "/" + str(path).lstrip("/")

    def _send(self, method, path, params=None, data=None, retries=3):
        self._require_config()
        url = self._url(path)
        last = None

        for attempt in range(1, retries + 1):
            if method == "GET":
                self.limiter.acquire()
            try:
                response = self.session.request(
                    method, url, headers=self._headers(), params=params, data=data,
                    timeout=self.timeout, verify=self.verify,
                )
            except requests.RequestException as exc:
                last = exc
                if attempt < retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise InVentryAPIError(f"InVentry API unreachable at {url}: {exc}") from exc

            if response.status_code == 429:
                # Documented for GET. Should not happen for POST, but honour it.
                wait = _retry_after(response, attempt)
                last = InVentryAPIError(f"Rate limited by InVentry ({url})")
                if attempt < retries:
                    time.sleep(wait)
                    continue
                raise last

            if response.status_code in (401, 403):
                raise InVentryAPIError(
                    f"InVentry rejected the credentials ({response.status_code}). Check the API key "
                    f"is still listed in the console's Partner API section and that the partner "
                    f"secret matches."
                )

            if response.status_code == 404:
                raise InVentryAPIError(
                    f"InVentry returned 404 for {url}. The endpoint paths are still unconfirmed - "
                    f"set INVENTRY_PATH_* from InVentry's Postman collection."
                )

            if response.status_code >= 500:
                last = InVentryAPIError(f"InVentry returned {response.status_code} for {url}")
                if attempt < retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise last

            if not response.ok:
                # Non-200 bodies carry a useful string, per the documentation.
                raise InVentryAPIError(
                    f"InVentry returned {response.status_code} for {url}: {response.text[:300]}"
                )

            return _decode(response, url)

        raise InVentryAPIError(f"InVentry API failed after {retries} attempts: {last}")

    def get(self, path, params=None):
        return self._send("GET", path, params=params)

    def post(self, path, data):
        """POST form-encoded values. Empty values are dropped, not sent blank."""
        body = {k: v for k, v in (data or {}).items() if v not in (None, "")}
        return self._send("POST", path, data=body)

    # ── personnel ────────────────────────────────────────────────────────

    def get_personnel(self):
        """All personnel records InVentry holds."""
        payload = self.get(cfg.INVENTRY_PATH_PERSONNEL)
        return _as_records(payload)

    def add_personnel(self, first_name, surname, email="", person_id="",
                      member_of_staff=True, extra=None):
        """Create a person. person_id is stored in InVentry's PersonID field.

        Returns the response dict; per the documentation it includes the ID of
        the newly created record.
        """
        data = {
            "FirstName": first_name,
            "Surname": surname,
            "EmailAddress": email,
            "PersonID": person_id,
            "MemberOfStaff": "1" if member_of_staff else "0",
        }
        data.update(extra or {})
        return self.post(cfg.INVENTRY_PATH_PERSONNEL_ADD, data)

    def update_personnel(self, inventry_id, **fields):
        data = {"ID": inventry_id}
        data.update(fields)
        return self.post(cfg.INVENTRY_PATH_PERSONNEL_UPDATE, data)

    # ── presence events ──────────────────────────────────────────────────

    def sign_in(self, inventry_id, when=None, location_id=None, reason=""):
        """Record an arrival for a person InVentry already knows."""
        return self.post(cfg.INVENTRY_PATH_SIGN_IN, {
            "ID": inventry_id,
            "EventType": cfg.INVENTRY_EVENT_TYPE_IN,
            "EventDateTime": format_datetime(when),
            "LocID": location_id if location_id is not None else cfg.INVENTRY_LOCATION_ID,
            "Reason": reason,
        })

    def sign_out(self, inventry_id, when=None, location_id=None, reason=""):
        """Record a departure."""
        return self.post(cfg.INVENTRY_PATH_SIGN_OUT, {
            "ID": inventry_id,
            "EventType": cfg.INVENTRY_EVENT_TYPE_OUT,
            "EventDateTime": format_datetime(when),
            "LocID": location_id if location_id is not None else cfg.INVENTRY_LOCATION_ID,
            "Reason": reason,
        })

    # ── convenience ──────────────────────────────────────────────────────

    def check(self):
        """Read-only connectivity check. Never writes."""
        people = self.get_personnel()
        on_site = [p for p in people if is_on_site(p)]
        return {
            "status": "ok",
            "base_url": self.base_url,
            "tls_verification": self.verify if self.verify is not False else "OFF (self-signed)",
            "personnel": len(people),
            "on_site": len(on_site),
            "with_our_person_id": len([p for p in people if _field(p, "PersonID")]),
            "warnings": list(self.warnings),
        }


def _retry_after(response, attempt):
    header = response.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    return 2 ** (attempt - 1)


def _decode(response, url):
    try:
        return response.json()
    except ValueError:
        text = (response.text or "").strip()
        if not text:
            return {}
        raise InVentryAPIError(f"InVentry returned non-JSON content for {url}: {text[:200]}")


def _as_records(payload):
    """Pull a list of records out of whatever shape the response uses."""
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("personnel", "data", "records", "items", "result", "results"):
            for actual in payload:
                if actual.lower() == key and isinstance(payload[actual], list):
                    return [p for p in payload[actual] if isinstance(p, dict)]
        if any(k.lower() in ("id", "firstname", "surname") for k in payload):
            return [payload]
    return []


def _field(record, name, default=""):
    """Case-insensitive field read - their casing is PascalCase but be lenient."""
    if not isinstance(record, dict):
        return default
    wanted = name.replace("_", "").lower()
    for key, value in record.items():
        if str(key).replace("_", "").lower() == wanted:
            return default if value is None else value
    return default


def is_on_site(record):
    """Is this person currently signed in, per InVentry's own last activity?"""
    activity = str(_field(record, "LastActivityType")).strip().upper()
    return activity in [v.upper() for v in cfg.INVENTRY_ACTIVITY_IN_VALUES]


def person_key(record):
    """Our identifier for an InVentry person: the PersonID we wrote."""
    return str(_field(record, "PersonID")).strip()


def inventry_id(record):
    return str(_field(record, "ID")).strip()
