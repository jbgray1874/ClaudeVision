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
    """Said plainly to the person, never a guess about why.

    `reason` is "access" when the answer is about this person's own access to
    the plan, so a screen can say what to do next rather than only that it
    failed: Liam and Callum, who are on the TTI list for the drawings and not
    on Sue's site, saw an error on every despatch tab and nothing else.
    """

    def __init__(self, message: str, reason: str = ""):
        super().__init__(message)
        self.reason = reason


def configured() -> bool:
    return bool(site() and file_path())


def site() -> str:
    """e.g. sdidisplays.sharepoint.com:/sites/SUESOSOD"""
    return (os.getenv("SDI_TTI_PLAN_SITE", "") or "").strip()


def file_path() -> str:
    """Path inside the site's default document library, e.g.
    General/TTI Delivery Schedule 2021 V3.xlsx"""
    return (os.getenv("SDI_TTI_PLAN_PATH", "") or "").strip().lstrip("/")


# The resolved site id, kept for the life of the process. It is an identifier,
# not a credential, and resolving it on every question would be a second round
# trip to Microsoft for an answer that does not change.
_RESOLVED: dict = {}


def _site_id(opened, headers) -> str:
    """Resolve "host:/sites/NAME" to the site's id, once.

    ── WHY THIS IS A SEPARATE CALL ────────────────────────────────────────────
    The obvious URL chains two colon-paths - /sites/host:/sites/NAME: followed
    by /drive/root:/file: - and Graph answers 400 Bad Request, because the
    colon form may appear once per URL. A 400 reads like a refusal and sent the
    first live attempt looking at SharePoint permissions that were fine.
    """
    known = _RESOLVED.get(site())
    if known:
        return known
    answer = opened.get(f"{GRAPH}/sites/{site()}", headers=headers,
                        params={"$select": "id"})
    _complain(answer, "the SharePoint site")
    found = str(answer.json().get("id") or "")
    if not found:
        raise PlanUnavailable("SharePoint did not recognise the configured site. "
                              "SDI_TTI_PLAN_SITE should read like "
                              "sdidisplays.sharepoint.com:/sites/SUESOSOD.")
    _RESOLVED[site()] = found
    return found


def _item_url(site_id: str, suffix: str = "") -> str:
    # Spaces and the like are escaped; the slashes between folders are not.
    return (f"{GRAPH}/sites/{site_id}/drive/root:/"
            f"{quote(file_path(), safe='/')}:{suffix}")


def fetch_plan(token: str, client=None, known_version: str = "") -> tuple:
    """(bytes, saved_at, version) for the configured workbook.

    `saved_at` is SharePoint's own lastModifiedDateTime - when the plan was
    last saved, not when this ran. An answer dated "now" about a workbook saved
    last Tuesday is the lie that matters in a despatch question.

    `known_version` is an eTag the caller already has a parsed copy of. When it
    still matches, the bytes are returned as None and the download is skipped.
    The metadata request happens either way and is made with THIS person's
    token, so it is still their access that decides whether they get an answer
    - the saving is a download and a parse, never a permission check.
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
        here = _site_id(opened, headers)
        facts = opened.get(_item_url(here), headers=headers,
                           params={"$select": "name,size,lastModifiedDateTime,eTag"})
        _complain(facts, "the plan")
        about = facts.json()
        version = str(about.get("eTag") or "")[:40]
        if known_version and version and version == known_version:
            return None, _when(about.get("lastModifiedDateTime")), version
        size = int(about.get("size") or 0)
        if size > MAX_BYTES:
            raise PlanUnavailable(
                f"The Despatch Plan is {size // (1024 * 1024)}MB, larger than this "
                f"view will read. Open it in Excel.")
        body = opened.get(_item_url(here, "/content"), headers=headers,
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
    return data, _when(about.get("lastModifiedDateTime")), version


def _complain(response, what: str) -> None:
    if response.status_code == 403:
        raise PlanUnavailable(
            f"Your account does not have access to {what} in SharePoint. This "
            f"reads the workbook as you, so this is about your access to the "
            f"site rather than about the app.", reason="access")
    if response.status_code == 404:
        # SharePoint answers "not found", not "no access", to someone who may
        # not see a file - so this is usually access, and saying only "moved"
        # sent people looking for a file that was exactly where it should be.
        raise PlanUnavailable(
            f"SharePoint did not find {what} for your account. Usually that means "
            f"your account cannot open it - SharePoint says 'not found' rather than "
            f"'no access' - and otherwise the plan has been renamed or moved.",
            reason="access")
    if response.status_code == 401:
        raise PlanUnavailable("Microsoft sign-in has expired. Sign in again.")
    if response.status_code == 400:
        # Not a refusal. The request was built wrongly, and saying "refused"
        # sends somebody to check permissions that are fine.
        raise PlanUnavailable(
            f"Microsoft could not understand the request for {what} (400). That is "
            f"this app's address for the workbook, not your access - check "
            f"SDI_TTI_PLAN_SITE and SDI_TTI_PLAN_PATH.")
    if response.status_code >= 300:
        raise PlanUnavailable(
            f"SharePoint refused to supply {what} ({response.status_code}).")


def _when(stamp) -> datetime:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        # Unknown beats wrong: the caller shows this as the plan's save time.
        return datetime.now(timezone.utc)
