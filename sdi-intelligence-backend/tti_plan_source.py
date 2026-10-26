"""Fetch Sue's Despatch Plan from SharePoint, as the person asking.

── WHY NOT A UNC SERVER SHARE ───────────────────────────────────────────────
The verified source is a SharePoint workbook, and a UNC path cannot be derived
from a SharePoint URL - constructing one would be a guess that looks right and
fails on the server. A synced copy would also need its freshness and the
service account's access established, neither of which has been.

── AS THE SIGNED-IN PERSON, NOT AS THE SERVICE ──────────────────────────────
The token comes from the portal's own delegated sign-in, so the workbook is
read with the rights of whoever is looking at the screen. Sue can read it
because Sue can read it; nobody inherits access from the service account, and
a person who loses access to the site loses it here the same afternoon. That
also means a failure is reported honestly rather than retried with wider
rights: a 403 here is a real answer about that person.

The site and the file are configuration. A request carries a date, so there is
no path, URL or site a caller can name.
"""
import os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
# Big enough for a despatch plan, small enough that one request cannot hold the
# service's memory. tracker_snapshot applies its own limit to what it parses.
MAX_BYTES = 30 * 1024 * 1024
TIMEOUT = 30


class PlanUnavailable(Exception):
    """Said plainly to the person, never a guess about why."""


def configured() -> bool:
    return bool(site() and file_path())


def site() -> str:
    """e.g. sdidisplays.sharepoint.com:/sites/SUESOSOD"""
    return (os.getenv("SDI_TTI_PLAN_SITE", "") or "").strip()


def file_path() -> str:
    """Path inside the site's default document library, e.g.
    General/TTI Delivery Schedule 2021 V3.xlsx"""
    return (os.getenv("SDI_TTI_PLAN_PATH", "") or "").strip().lstrip("/")


def _item_url(suffix: str = "") -> str:
    # Spaces and the like are escaped; the slashes between folders are not.
    return (f"{GRAPH}/sites/{site()}:/drive/root:/"
            f"{quote(file_path(), safe='/')}:{suffix}")


def fetch_plan(token: str, client=None) -> tuple:
    """(bytes, saved_at, version) for the configured workbook.

    `saved_at` is SharePoint's own lastModifiedDateTime - when the plan was
    last saved, not when this ran. An answer dated "now" about a workbook saved
    last Tuesday is the lie that matters in a despatch question.
    """
    if not configured():
        raise PlanUnavailable(
            "The Despatch Plan has not been configured. SDI_TTI_PLAN_SITE needs "
            "the site (sdidisplays.sharepoint.com:/sites/SUESOSOD) and "
            "SDI_TTI_PLAN_PATH the file within it.")
    if not token:
        raise PlanUnavailable(
            "Microsoft sign-in did not provide access to SharePoint. Sign in "
            "again; if it persists, a Sites.Read.All or Files.Read.All scope "
            "needs to be in SDI_GRAPH_SCOPES and consented.")
    headers = {"Authorization": "Bearer " + token}
    opened = client or httpx.Client(timeout=TIMEOUT)
    try:
        facts = opened.get(_item_url(), headers=headers,
                           params={"$select": "name,size,lastModifiedDateTime,eTag"})
        _complain(facts, "the plan")
        about = facts.json()
        size = int(about.get("size") or 0)
        if size > MAX_BYTES:
            raise PlanUnavailable(
                f"The Despatch Plan is {size // (1024 * 1024)}MB, larger than this "
                f"view will read. Open it in Excel.")
        body = opened.get(_item_url("/content"), headers=headers,
                          follow_redirects=True)
        _complain(body, "the plan's contents")
        data = body.content
        if len(data) > MAX_BYTES:
            raise PlanUnavailable("The Despatch Plan is larger than this view will read.")
    except httpx.HTTPError as problem:
        raise PlanUnavailable(
            f"SharePoint could not be reached just now ({type(problem).__name__}).")
    finally:
        if client is None:
            opened.close()
    return data, _when(about.get("lastModifiedDateTime")), str(about.get("eTag") or "")[:40]


def _complain(response, what: str) -> None:
    if response.status_code == 403:
        raise PlanUnavailable(
            f"Your account does not have access to {what} in SharePoint. This "
            f"reads the workbook as you, so this is about your access to the "
            f"site rather than about the app.")
    if response.status_code == 404:
        raise PlanUnavailable(
            f"SharePoint has no file at the configured location, so {what} could "
            f"not be read. The plan may have been renamed or moved.")
    if response.status_code == 401:
        raise PlanUnavailable("Microsoft sign-in has expired. Sign in again.")
    if response.status_code >= 300:
        raise PlanUnavailable(
            f"SharePoint refused to supply {what} ({response.status_code}).")


def _when(stamp) -> datetime:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        # Unknown beats wrong: the caller shows this as the plan's save time.
        return datetime.now(timezone.utc)
