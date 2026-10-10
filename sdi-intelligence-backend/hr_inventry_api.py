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

Endpoints, from InVentry's Postman collection (received 25 Sep 2026), all under
https://<host>:4816/PartnerAPI/ :

  GET   CheckAuth                                  credentials test
  GET   GetPersonnel/?IncludeNonStaff=true         the personnel list
  GET   GetLatestPersonnelActions?LastCollectionId= incremental action feed
  GET   GetSystemTime | GetDepartments | GetScanCodes | GetVisitors
  POST  AddPersonnel                               create a person
  POST  AddPersonnelAction                         SIGN IN / SIGN OUT
  POST  AddPersonnelScanCode

The collection is authoritative where it disagrees with the field-information
PDF, and it does disagree in ways that matter. The live personnel JSON uses
LastActivity (values "IN", "OUT" or null) and LastActivityDate - not
LastActivityType / LastActivityDateTime - plus LastEventLocation, PostCode and
CarReg. Datetimes come back as 2020-12-22T18:08:46.307 and the AddPersonnel
example sends 1983-07-08T00:00:00, so a "T" separator and no timezone.

Sign-in and sign-out are one call, AddPersonnelAction, taking PersonnelID,
ActionType ("IN"/"OUT"), and optionally ActionDateTime and ActionLocation.
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
    """InVentry's API could not be reached, or refused a call.

    ``status`` is the HTTP status where there was one, and None when the call
    never got a response. Callers use it to tell a rejected *request* from
    rejected *credentials*, which need opposite responses.
    """

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def rejected_the_request(exc):
    """True when InVentry refused this particular request's contents.

    Deliberately narrow. 401/403 mean the credentials are wrong, 404 the path
    is wrong, 429 that we are calling too fast, 5xx that InVentry is unwell -
    none of which a different request body would fix. What is left is the 4xx
    range that means "I will not accept what you sent".
    """
    status = getattr(exc, "status", None)
    return status is not None and 400 <= status < 500 and status not in (401, 403, 404, 429)


class PinnedCertAdapter(requests.adapters.HTTPAdapter):
    """Verify the certificate, but not the hostname on it.

    For a single pinned self-signed certificate this is not a downgrade: the
    pin already names one exact certificate, and hostname checking exists to
    stop a CA vouching for the wrong name. Here the certificate is its own CA.
    """

    def init_poolmanager(self, *args, **kwargs):
        kwargs["assert_hostname"] = False
        return super().init_poolmanager(*args, **kwargs)


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

    Their own examples use 1983-07-08T00:00:00 and their responses
    2020-12-22T18:08:46.307: a "T" separator and no timezone. Anything with a
    trailing Z or an offset is converted to naive UTC first.
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
    return value.strftime("%Y-%m-%dT%H:%M:%S")


class InVentryAPI:
    """Thin wrapper over the InVentry Partner API."""

    def __init__(self, base_url=None, api_key=None, partner_secret=None,
                 verify=None, timeout=None, session=None, limiter=None,
                 check_hostname=None):
        self.base_url = (base_url if base_url is not None else cfg.INVENTRY_API_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else cfg.INVENTRY_API_KEY
        self.partner_secret = partner_secret if partner_secret is not None else cfg.INVENTRY_PARTNER_SECRET
        self.timeout = timeout or cfg.INVENTRY_API_TIMEOUT
        self.session = session or requests.Session()
        self.limiter = limiter if limiter is not None else RateLimiter()
        self.warnings = []
        # Set once InVentry has refused an ActionLocation - see add_action.
        self.action_location_dropped = False

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

        # Their certificate has no subjectAltName, so the hostname can never
        # match. Pinning the certificate and skipping the name check keeps the
        # connection verified; skipping it without a pin does not.
        self.check_hostname = (cfg.INVENTRY_API_CHECK_HOSTNAME
                               if check_hostname is None else check_hostname)
        if not self.check_hostname:
            if self.verify is False:
                self.warnings.append(
                    "INVENTRY_API_CHECK_HOSTNAME is off and no certificate is pinned, so "
                    "nothing about the server is being verified. Set INVENTRY_API_CA_BUNDLE."
                )
            else:
                if self.verify is True:
                    # Verifying against the public CA store without checking the
                    # name accepts ANY publicly-issued certificate for ANY domain.
                    # Turning the name check off is only sound with a pin.
                    self.warnings.append(
                        "INVENTRY_API_CHECK_HOSTNAME is off but no certificate is pinned: "
                        "the system CA store is being used, so any publicly-issued "
                        "certificate for any name would be accepted. Set "
                        "INVENTRY_API_CA_BUNDLE to InVentry's exported certificate."
                    )
                if hasattr(self.session, "mount"):
                    self.session.mount("https://", PinnedCertAdapter())

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

        # A placeholder pasted verbatim from instructions is otherwise
        # indistinguishable from a wrong credential: both come back as a 401,
        # and the real cause is a line in a file nobody is looking at. Note
        # .env takes the LAST of any duplicated key, so a pasted placeholder
        # silently wins over the correct value above it.
        placeholders = [name for name, value in (
            ("INVENTRY_API_BASE_URL", self.base_url),
            ("INVENTRY_API_KEY", self.api_key),
            ("INVENTRY_PARTNER_SECRET", self.partner_secret),
        ) if value.strip().startswith("<") and value.strip().endswith(">")]
        if placeholders:
            raise InVentryAPIError(
                f"{', '.join(placeholders)} still holds a placeholder, not a real value - "
                f"something like <paste it here> was copied into {cfg.ENV_FILE} literally. "
                f"Remove that line. If the setting appears twice, the LAST one is the one "
                f"being used."
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
            except requests.exceptions.SSLError as exc:
                if "not valid for" in str(exc) or "Hostname mismatch" in str(exc):
                    raise InVentryAPIError(
                        f"InVentry's certificate does not carry the name {self.base_url!r}. "
                        f"It is self-signed with CN=InVentry-PC and no subjectAltName, which "
                        f"modern TLS ignores, so no hostname will ever match. Keep "
                        f"INVENTRY_API_CA_BUNDLE pointed at the exported certificate and set "
                        f"INVENTRY_API_CHECK_HOSTNAME=false - the certificate is still verified, "
                        f"only its name is not. ({exc})"
                    ) from exc
                raise InVentryAPIError(
                    f"TLS failed talking to {url}: {exc}. If the certificate was re-exported, "
                    f"update INVENTRY_API_CA_BUNDLE."
                ) from exc
            except requests.RequestException as exc:
                last = exc
                if attempt < retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise InVentryAPIError(f"InVentry API unreachable at {url}: {exc}") from exc

            if response.status_code == 429:
                # Documented for GET. Should not happen for POST, but honour it.
                wait = _retry_after(response, attempt)
                last = InVentryAPIError(f"Rate limited by InVentry ({url})", status=429)
                if attempt < retries:
                    time.sleep(wait)
                    continue
                raise last

            if response.status_code in (401, 403):
                raise InVentryAPIError(
                    f"InVentry rejected the credentials ({response.status_code}). Check the API key "
                    f"is still listed in the console's Partner API section and that the partner "
                    f"secret matches.", status=response.status_code
                )

            if response.status_code == 404:
                raise InVentryAPIError(
                    f"InVentry returned 404 for {url}. The endpoint paths are still unconfirmed - "
                    f"set INVENTRY_PATH_* from InVentry's Postman collection.", status=404
                )

            if response.status_code >= 500:
                last = InVentryAPIError(f"InVentry returned {response.status_code} for {url}",
                                        status=response.status_code)
                if attempt < retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise last

            if not response.ok:
                # Non-200 bodies carry a useful string, per the documentation.
                raise InVentryAPIError(
                    f"InVentry returned {response.status_code} for {url}: {response.text[:300]}",
                    status=response.status_code
                )

            return _decode(response, url)

        raise InVentryAPIError(f"InVentry API failed after {retries} attempts: {last}",
                               status=getattr(last, "status", None))

    def get(self, path, params=None):
        return self._send("GET", path, params=params)

    def post(self, path, data):
        """POST form-encoded values. Empty values are dropped, not sent blank."""
        body = {k: v for k, v in (data or {}).items() if v not in (None, "")}
        return self._send("POST", path, data=body)

    # ── personnel ────────────────────────────────────────────────────────

    def check_auth(self):
        """Credentials test. GET CheckAuth - cheapest possible call."""
        return self.get(cfg.INVENTRY_PATH_CHECK_AUTH)

    def get_personnel(self, include_non_staff=None):
        """All personnel records. Returns a bare JSON list."""
        if include_non_staff is None:
            include_non_staff = cfg.INVENTRY_INCLUDE_NON_STAFF
        params = {"IncludeNonStaff": "true" if include_non_staff else "false"}
        return _as_records(self.get(cfg.INVENTRY_PATH_PERSONNEL, params=params))

    def get_latest_actions(self, last_collection_id=0):
        """Sign-in/out actions since a collection id - the incremental feed."""
        return _as_records(self.get(cfg.INVENTRY_PATH_LATEST_ACTIONS,
                                    params={"LastCollectionId": last_collection_id}))

    def get_system_time(self):
        """InVentry's own clock, for spotting clock skew against ours."""
        return self.get(cfg.INVENTRY_PATH_SYSTEM_TIME)

    def add_personnel(self, first_name, surname, email="", person_id="",
                      member_of_staff=True, extra=None):
        """Create a person. person_id goes in PersonID, for our own key.

        The response carries the new record's ID.
        """
        data = {
            "FirstName": first_name,
            "Surname": surname,
            "EmailAddress": email,
            "PersonID": person_id,
            "MemberOfStaff": "True" if member_of_staff else "False",
            "EnableRecord": "True",
        }
        data.update(extra or {})
        return self.post(cfg.INVENTRY_PATH_PERSONNEL_ADD, data)

    # ── presence: one call, AddPersonnelAction ───────────────────────────

    def add_action(self, personnel_id, action_type, when=None, location=None):
        """Record a sign-in or sign-out against an InVentry person.

        ``ActionLocation`` is the one field here we are not certain InVentry
        will accept. We send a distinctive value so we can recognise our own
        sign-ins later, but InVentry may require it to name a real location -
        and there is no Locations list in the console to add one to, so we
        cannot make it real. If they reject the request over it, dropping the
        field costs us safe sign-out; letting the call fail costs us the
        sign-in, and a missing sign-in is a person missing from a fire roll.
        So we drop the field and carry on.

        Dropped for the rest of the client's life, not just this call: once
        InVentry has refused it, retrying it 89 more times only doubles the
        writes.
        """
        wanted = cfg.INVENTRY_ACTION_LOCATION if location is None else location
        body = {
            "PersonnelID": personnel_id,
            "ActionType": action_type,
            "ActionDateTime": format_datetime(when) if when else "",
        }

        path = cfg.INVENTRY_PATH_PERSONNEL_ACTION
        if wanted and not self.action_location_dropped:
            try:
                return self.post(path, dict(body, ActionLocation=wanted))
            except InVentryAPIError as exc:
                # Only when InVentry refused the request itself. A 401 or a
                # timeout would come back exactly the same way without the
                # field, and retrying would just write nothing twice as slowly.
                if not rejected_the_request(exc):
                    raise
                refusal = exc

            # Without the field. Only if THIS succeeds was the field the
            # problem. If it fails too, the request was bad for another reason
            # - one malformed PersonnelID, say - and that error propagates with
            # the marker left on for everyone else. Concluding otherwise would
            # let a single bad record strip the marker from every remaining
            # sign-in in the run, and blame the wrong thing for it.
            result = self.post(path, body)
            self.action_location_dropped = True
            self.warnings.append(
                f"InVentry rejected AddPersonnelAction carrying "
                f"ActionLocation={wanted!r} ({refusal}), and accepted the same request "
                f"without it. It is omitted for the rest of this run. Sign-ins still work. "
                f"Automatic sign-out cannot be enabled, because it depends on recognising "
                f"our own marker in LastEventLocation."
            )
            return result

        return self.post(path, body)

    def sign_in(self, inventry_id, when=None, location=None, reason=""):
        return self.add_action(inventry_id, cfg.INVENTRY_EVENT_TYPE_IN,
                               when=when, location=location)

    def sign_out(self, inventry_id, when=None, location=None, reason=""):
        return self.add_action(inventry_id, cfg.INVENTRY_EVENT_TYPE_OUT,
                               when=when, location=location)

    # ── convenience ──────────────────────────────────────────────────────

    def check(self):
        """Read-only connectivity check. Never writes."""
        auth = self.check_auth()
        people = self.get_personnel()
        on_site = [p for p in people if is_on_site(p)]
        ours = [p for p in on_site if signed_in_by_us(p)]
        return {
            "status": "ok",
            "env_file": str(cfg.ENV_FILE) if cfg.ENV_FILE_FOUND else f"{cfg.ENV_FILE} (MISSING)",
            "base_url": self.base_url,
            "auth": auth if auth else "CheckAuth OK",
            "tls_verification": self.verify if self.verify is not False else "OFF (self-signed)",
            "personnel": len(people),
            "on_site": len(on_site),
            "on_site_signed_in_by_us": len(ours),
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
    """Is this person currently signed in, per InVentry's own last activity?

    The live field is LastActivity, holding "IN", "OUT" or null - not
    LastActivityType as the field-information PDF suggests.
    """
    activity = str(_field(record, "LastActivity")).strip().upper()
    return activity in [v.upper() for v in cfg.INVENTRY_ACTIVITY_IN_VALUES]


def last_location(record):
    """Where InVentry recorded the person's last event.

    Real values seen include "CONSOLE" and a location id. Our own sign-ins
    carry INVENTRY_ACTION_LOCATION, which is how we tell them apart from a
    sign-in made at reception.
    """
    return str(_field(record, "LastEventLocation")).strip()


def signed_in_by_us(record):
    """True when the person's last event looks like one we wrote."""
    marker = (cfg.INVENTRY_ACTION_LOCATION or "").strip()
    if not marker:
        return False
    return last_location(record).upper() == marker.upper()


def person_key(record):
    """Our identifier for an InVentry person: the PersonID we wrote."""
    return str(_field(record, "PersonID")).strip()


def inventry_id(record):
    return str(_field(record, "ID")).strip()
