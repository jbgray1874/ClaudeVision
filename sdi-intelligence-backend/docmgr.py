"""docmgr.py — the Document Manager API, called from the backend and only from the backend.

WHAT THIS IS FOR. Drawings for an estimate come from two places: the estimating share, browsed
by hand, and a Document Manager extract, which walks the SolidWorks references for a project
and writes a file pack. This is the second one. It asks DM to build the pack and reports where
it landed; the portal then merges those files into the Drawings panel by name, exactly as it
merges a hand-picked folder.

THE SECRET NEVER REACHES A BROWSER, WHICH IS THE POINT OF THE PROXY.

DM authenticates with a shared secret in an `X-API-Key` header. It is a single key covering
every call any consumer makes, so putting it in page JavaScript would hand every visitor the
ability to drive somebody else's CAD host. The portal therefore calls THIS module, and this
module holds the key from the service's own environment. That is the integration shape DM's
own guide asks for, and it is the reason the page has no DM credentials in it at all.

The key is never written to a log line, an error message or a run log. `_headers()` is the
only place it is read, and nothing here formats a header dict into a message.

HOW DM'S SIDE BEHAVES, which drives the shape of everything below:

  * `GET /health` takes NO key and reports `comAvailable`. DM drives SolidWorks over COM, so
    a host whose COM is down accepts an extract and then fails it. Checking first turns a
    ten-minute failure into an immediate sentence.
  * `POST /api/extract/files` returns **202 and a jobId**, not a pack. It is asynchronous
    because the work is minutes long.
  * `GET /api/jobs/{jobId}` is polled until `completed` or `failed`. On success the result
    carries `outputDir` and `fileCount`.
  * ONE HEAVY EXTRACT AT A TIME on that host. Two estimators pressing the button together is
    a queue, not a parallel run, and the second one waits.

Polling is done by the PAGE through our own routes, not in a blocking loop here: an extract
runs for minutes, and a request held open for minutes is one dropped connection away from
looking like a failure on work that is going perfectly well.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import config

# DM's own guide names these; accepting them means an estimator who has followed that guide
# does not have to learn a second set of names for the same two facts.
_ENV_BASE_ALIASES = ("DOCMGR_BASE_URL",)
_ENV_KEY_ALIASES = ("DOCMGR_ACCESS_SECRET",)

# An extract is minutes; a status call is instant. Separate timeouts because giving the quick
# call the slow one's patience means a dead host holds the page for a minute.
HEALTH_TIMEOUT = float(os.getenv("SDI_DM_HEALTH_TIMEOUT", "10"))
START_TIMEOUT = float(os.getenv("SDI_DM_START_TIMEOUT", "60"))
POLL_TIMEOUT = float(os.getenv("SDI_DM_POLL_TIMEOUT", "30"))


class DocMgrError(Exception):
    """Something an estimator can read. The route turns it into a 400 or 502."""


def base_url() -> str:
    for name in _ENV_BASE_ALIASES:
        v = (os.getenv(name) or "").strip()
        if v:
            break
    else:
        v = ""
    return ((getattr(config, "DM_API_BASE", "") or "").strip() or v).rstrip("/")


def api_key() -> str:
    for name in _ENV_KEY_ALIASES:
        v = (os.getenv(name) or "").strip()
        if v:
            break
    else:
        v = ""
    return (getattr(config, "DM_API_KEY", "") or "").strip() or v


def configured() -> bool:
    return bool(base_url() and api_key())


def _requests():
    try:
        import requests                                     # noqa: PLC0415
    except ImportError as exc:                              # pragma: no cover
        raise DocMgrError(
            "The 'requests' package is not installed in the service's environment, so the "
            "Document Manager cannot be called.") from exc
    return requests


def _headers() -> Dict[str, str]:
    """THE ONLY PLACE THE KEY IS READ. Nothing else in this module touches it, and nothing
    formats this dict into a message, so it cannot reach a log or an error by accident."""
    key = api_key()
    if not key:
        raise DocMgrError(
            "No Document Manager access secret is configured. Set SDI_DM_API_KEY (or "
            "DOCMGR_ACCESS_SECRET) in the service's .env — never in the page.")
    return {"X-API-Key": key, "Content-Type": "application/json"}


def _need_base() -> str:
    base = base_url()
    if not base:
        raise DocMgrError(
            "No Document Manager address is configured. Set SDI_DM_API_BASE (or "
            "DOCMGR_BASE_URL) to the API's base URL.")
    return base


def _explain(resp: Any, what: str) -> None:
    """Turn DM's status codes into sentences that name the fix.

    401 in particular: 'HTTP 401' sends somebody to the network. It is the shared secret,
    every time, and saying so saves the trip.
    """
    if resp.status_code == 401:
        raise DocMgrError(
            "The Document Manager refused our access secret (401). Check SDI_DM_API_KEY "
            "matches the secret its owner issued.")
    if resp.status_code == 404:
        raise DocMgrError(f"The Document Manager has no record of that {what} (404).")
    if resp.status_code >= 500:
        raise DocMgrError(
            f"The Document Manager failed while handling the {what} "
            f"(HTTP {resp.status_code}). Its host may need looking at.")
    if not resp.ok:
        body = ""
        try:
            body = str(resp.json())[:200]
        except Exception:                                   # noqa: BLE001
            body = (resp.text or "")[:200]
        raise DocMgrError(f"The Document Manager refused the {what} "
                          f"(HTTP {resp.status_code}). {body}".strip())


def health() -> Dict[str, Any]:
    """`GET /health` — no key, and the one call that says whether an extract can work at all.

    `comAvailable` false means DM cannot drive SolidWorks. An extract submitted then is
    accepted and fails later, so this is checked before every start.
    """
    requests = _requests()
    base = _need_base()
    try:
        resp = requests.get(f"{base}/health", timeout=HEALTH_TIMEOUT)
    except Exception as exc:                                # noqa: BLE001
        raise DocMgrError(
            f"The Document Manager at {base} could not be reached "
            f"({type(exc).__name__}). Its host must be online.") from exc
    _explain(resp, "health check")
    try:
        return dict(resp.json() or {})
    except Exception as exc:                                # noqa: BLE001
        raise DocMgrError(f"The Document Manager's health reply was not JSON.") from exc


def start_extract(project_number: str, *, customer: str = "",
                  assembly_folder: str = "") -> Dict[str, Any]:
    """`POST /api/extract/files` — ask for a pack. Returns DM's 202 body, including jobId.

    Only the three consumer parameters are sent. DM's advanced fields (exportScope,
    masterSelection, scanBoundary...) have server defaults its own guide calls right for most
    packs, and a setting we pass without understanding is a setting we cannot explain when a
    pack comes back wrong.
    """
    requests = _requests()
    base = _need_base()
    project = str(project_number or "").strip()
    if not project:
        raise DocMgrError("A project number is needed to ask the Document Manager for a pack.")

    # CHECKED BEFORE ASKING, because DM accepts the job either way. A COM failure surfaces
    # minutes later as a failed job with an error nobody reads as "the CAD host is down".
    hp = health()
    if hp.get("comAvailable") is False:
        raise DocMgrError(
            "The Document Manager host is up but cannot drive SolidWorks right now "
            f"(comAvailable=false{': ' + str(hp.get('comError')) if hp.get('comError') else ''}). "
            "An extract would be accepted and then fail, so it has not been sent.")

    body: Dict[str, Any] = {"projectNumber": project}
    if str(customer or "").strip():
        body["customer"] = str(customer).strip()
    if str(assembly_folder or "").strip():
        body["assemblyFolder"] = str(assembly_folder).strip()

    try:
        resp = requests.post(f"{base}/api/extract/files", headers=_headers(),
                             json=body, timeout=START_TIMEOUT)
    except Exception as exc:                                # noqa: BLE001
        raise DocMgrError(
            f"The Document Manager at {base} could not be reached "
            f"({type(exc).__name__}).") from exc
    _explain(resp, "extract request")
    try:
        out = dict(resp.json() or {})
    except Exception as exc:                                # noqa: BLE001
        raise DocMgrError("The Document Manager's reply to the extract was not JSON.") from exc

    if not out.get("jobId"):
        raise DocMgrError(
            "The Document Manager accepted the request but returned no job id, so there is "
            "nothing to follow. Its /docs page will show what it did return.")
    out["requested"] = body
    return out


def job(job_id: str) -> Dict[str, Any]:
    """`GET /api/jobs/{jobId}` — queued | running | completed | failed.

    Returned as DM gives it, plus a `finished` flag so the page has one thing to test rather
    than a list of status strings to keep in step with DM's.
    """
    requests = _requests()
    base = _need_base()
    jid = str(job_id or "").strip()
    if not jid:
        raise DocMgrError("No job id was given.")
    try:
        resp = requests.get(f"{base}/api/jobs/{jid}", headers=_headers(), timeout=POLL_TIMEOUT)
    except Exception as exc:                                # noqa: BLE001
        raise DocMgrError(
            f"The Document Manager at {base} could not be reached while checking the job "
            f"({type(exc).__name__}).") from exc
    _explain(resp, "job")
    try:
        out = dict(resp.json() or {})
    except Exception as exc:                                # noqa: BLE001
        raise DocMgrError("The Document Manager's job reply was not JSON.") from exc

    status = str(out.get("status") or "").lower()
    out["finished"] = status in {"completed", "failed"}
    out["ok"] = status == "completed"
    result = out.get("result") if isinstance(out.get("result"), dict) else {}
    out["output_dir"] = result.get("outputDir") or None
    out["file_count"] = result.get("fileCount")
    return out
