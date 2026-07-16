"""
BrightHR client — pluggable auth + paginated employee fetch + normalisation.

VERIFY BEFORE PRODUCTION (BrightHR's public API is early-stage):
  1. BH_EMPLOYEE_URL — the exact employee endpoint + request shape.
  2. Response field names — normalise_employee() hedges common variants, but
     confirm against a real (sandbox) response.
  3. Auth: a client-credentials token has NO user context. BrightHR returns
     403 on endpoints that need user context — if you see 403, set
     BH_AUTH_MODE=pat and supply a Personal Access Token.
"""
import time
import requests

import hr_config as cfg


class BrightHRError(RuntimeError):
    pass


def _retry(fn, tries: int = 3, backoff: float = 2.0):
    last = None
    for i in range(tries):
        try:
            return fn()
        except (requests.RequestException, BrightHRError) as exc:
            last = exc
            if i < tries - 1:
                time.sleep(backoff * (i + 1))
    raise last


def get_access_token() -> str:
    """Return a bearer token according to BH_AUTH_MODE."""
    if cfg.BH_AUTH_MODE == "pat":
        if not cfg.BH_PAT or cfg.BH_PAT.startswith("<"):
            raise BrightHRError("BH_AUTH_MODE=pat but BH_PAT is empty.")
        return cfg.BH_PAT

    # client_credentials
    if not (cfg.BH_CLIENT_ID and cfg.BH_CLIENT_SECRET) or cfg.BH_CLIENT_ID.startswith("<"):
        raise BrightHRError("client_credentials selected but BH_CLIENT_ID / BH_CLIENT_SECRET missing.")
    payload = {
        "grant_type": "client_credentials",
        "client_id": cfg.BH_CLIENT_ID,
        "client_secret": cfg.BH_CLIENT_SECRET,
    }
    if cfg.BH_SCOPE:
        payload["scope"] = cfg.BH_SCOPE
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    def call():
        r = requests.post(cfg.BH_TOKEN_URL, data=payload, headers=headers, timeout=cfg.BH_TIMEOUT)
        if r.status_code != 200:
            raise BrightHRError(f"Token request failed: {r.status_code} {r.text[:300]}")
        return r.json().get("access_token")

    token = _retry(call)
    if not token:
        raise BrightHRError("No access_token in token response.")
    return token


def fetch_employees(token: str) -> list:
    """Pull ALL employees, paging until exhausted (adjust paging keys to match BrightHR)."""
    if not cfg.BH_EMPLOYEE_URL or cfg.BH_EMPLOYEE_URL.startswith("<"):
        raise BrightHRError("BH_EMPLOYEE_URL is not set — verify it against BrightHR's docs.")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    all_items, page, continuation_token = [], 1, None
    while page <= cfg.BH_MAX_PAGES:
        # BrightHR uses continuationToken cursor paging — pass token if we have one
        body = {}
        if continuation_token:
            body["continuationToken"] = continuation_token

        def call():
            r = requests.post(cfg.BH_EMPLOYEE_URL, json=body, headers=headers, timeout=cfg.BH_TIMEOUT)
            if r.status_code == 403:
                raise BrightHRError(
                    "403 Forbidden — token likely lacks user context. "
                    "Set BH_AUTH_MODE=pat and supply a Personal Access Token."
                )
            if r.status_code != 200:
                raise BrightHRError(f"Employee fetch failed (page {page}): {r.status_code} {r.text[:300]}")
            return r.json()

        data = _retry(call)
        items = data.get("items") or data.get("data") or data.get("employees") or []
        if not items:
            break
        all_items.extend(items)
        continuation_token = data.get("continuationToken")
        if not continuation_token:   # null = last page
            break
        page += 1
    return all_items


def normalise_employee(raw: dict) -> dict:
    """Map a BrightHR record to a stable shape, hedging camelCase / snake_case."""
    name = raw.get("name") or {}
    first = (name.get("givenName") or name.get("given_name") or raw.get("firstName") or "").strip()
    last = (name.get("familyName") or name.get("family_name")
            or raw.get("lastName") or raw.get("surname") or "").strip()
    email = (raw.get("email") or raw.get("emailAddress") or raw.get("workEmail") or "").strip()
    emp_id = str(raw.get("id") or raw.get("employeeId") or "").strip()
    meta = raw.get("_metadata") or {}
    terminated = bool(
        meta.get("isTerminated")
        or raw.get("isTerminated")
        or str(raw.get("employmentStatus", "")).lower() == "terminated"
    )
    return {"id": emp_id, "first_name": first, "surname": last, "email": email, "terminated": terminated}
