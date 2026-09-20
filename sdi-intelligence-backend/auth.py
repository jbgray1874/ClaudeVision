"""
SDI Intelligence — Microsoft Entra ID single sign-on.

Replaces the shared X-SDI-Key for anything a person touches. A shared key can
tell you that *someone* called an endpoint; it cannot tell you who. Every audit
trail this programme needs — "Nick changed P1001's next action at 08:47" —
depends on per-user identity, so identity comes before exposure.

Flow (OpenID Connect authorization code + PKCE, handled by MSAL):

    browser → /auth/login → login.microsoftonline.com → /auth/callback
            → server-side session → signed cookie holding only a session id

Tokens never reach the browser. The cookie carries a signed session id and
nothing else; claims and the MSAL token cache stay server-side.

Configuration (.env) — SSO is OFF until all four are set:

    SDI_TENANT_ID        Directory (tenant) ID from Entra
    SDI_CLIENT_ID        Application (client) ID of the app registration
    SDI_CLIENT_SECRET    Client secret value
    SDI_SESSION_SECRET   Any long random string (signs the cookie)

Optional:

    SDI_REDIRECT_URI     Default http://localhost:8071/auth/callback
    SDI_SESSION_HOURS    Session lifetime, default 10
    SDI_ALLOWED_GROUPS   Comma-separated group object IDs. Empty = any tenant user
    SDI_GRAPH_SCOPES     Space-separated delegated scopes, default "User.Read"
    SDI_COOKIE_SECURE    "no" only while testing over plain http on the intranet
    SDI_ALLOW_API_KEY    "yes" keeps X-SDI-Key working for scheduled scripts

Sessions are stored in SQLite (see session_store.py), encrypted under
SDI_SESSION_SECRET. They survive a restart and are shared by workers on the same
machine. Two hosts would need Redis instead — keep the same interface.

KNOWN LIMIT:
  * Group claims are omitted by Entra when a user is in more than ~200 groups
    (the "overage" case). SDI_ALLOWED_GROUPS would then deny a legitimate user.
    Left unhandled on purpose rather than silently letting them through.
"""

import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode, quote

import msal
import session_store
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from itsdangerous import URLSafeSerializer, BadSignature


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _flag(name: str, default: bool) -> bool:
    raw = _opt(name).lower()
    if not raw:
        return default
    return raw in ("1", "yes", "true", "on")


TENANT_ID = _opt("SDI_TENANT_ID")
CLIENT_ID = _opt("SDI_CLIENT_ID")
CLIENT_SECRET = _opt("SDI_CLIENT_SECRET")
SESSION_SECRET = _opt("SDI_SESSION_SECRET")

REDIRECT_URI = _opt("SDI_REDIRECT_URI", "http://localhost:8071/auth/callback")
SESSION_HOURS = int(_opt("SDI_SESSION_HOURS", "10") or 10)
ALLOWED_GROUPS = {g.strip() for g in _opt("SDI_ALLOWED_GROUPS").split(",") if g.strip()}
GRAPH_SCOPES = [s for s in _opt("SDI_GRAPH_SCOPES", "User.Read").split() if s]
COOKIE_SECURE = _flag("SDI_COOKIE_SECURE", True)
ALLOW_API_KEY = _flag("SDI_ALLOW_API_KEY", True)

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}" if TENANT_ID else ""
ENABLED = bool(TENANT_ID and CLIENT_ID and CLIENT_SECRET and SESSION_SECRET)

COOKIE_NAME = "sdi_session"
FLOW_COOKIE = "sdi_flow"

_serializer = URLSafeSerializer(SESSION_SECRET or "unconfigured", salt="sdi-session")

# Sessions live in SQLite (encrypted) so a restart does not sign everyone out.
_STORE = session_store.SessionStore(SESSION_SECRET) if SESSION_SECRET else None

# Short-lived auth-code state. This one stays in memory deliberately: it lives
# for the few seconds between /auth/login and /auth/callback, and losing it on a
# restart just means starting the sign-in again.
_FLOWS: dict[str, dict] = {}

router = APIRouter()


def _msal_app(cache: Optional[msal.SerializableTokenCache] = None):
    return msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET, token_cache=cache
    )


_last_reap = 0.0


def _reap() -> None:
    """Drop expired sessions and stale login attempts (at most once a minute)."""
    global _last_reap
    now = time.time()
    for fid in [f for f, v in _FLOWS.items() if v.get("_created", 0) < now - 900]:
        _FLOWS.pop(fid, None)
    if _STORE and now - _last_reap > 60:
        _last_reap = now
        _STORE.reap()


def current_user(request: Request) -> Optional[dict]:
    """The signed-in user, or None. Never raises — callers decide the response."""
    if not ENABLED:
        # SSO not configured: the service behaves as before, unauthenticated.
        return {"name": "Unauthenticated (SSO not configured)", "email": "",
                "oid": "", "kind": "anonymous"}

    _reap()
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        try:
            sid = _serializer.loads(raw)
        except BadSignature:
            sid = None
        if sid and _STORE:
            sess = _STORE.get(sid)
            if sess:
                return sess["claims"] | {"kind": "user"}

    # Machine callers (Task Scheduler, the estimating host) may still use the key.
    if ALLOW_API_KEY:
        import config
        key = request.headers.get("X-SDI-Key")
        if config.API_KEY and key == config.API_KEY:
            return {"name": "Service account (X-SDI-Key)", "email": "",
                    "oid": "", "kind": "machine"}
    return None


def require_user(request: Request) -> dict:
    """FastAPI dependency for API routes — 401 rather than a redirect."""
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def login_redirect(request: Request) -> RedirectResponse:
    """Send a browser to Entra, remembering where it was heading."""
    nxt = request.url.path
    if request.url.query:
        nxt += "?" + request.url.query
    return RedirectResponse(url="/auth/login?next=" + quote(nxt, safe=""), status_code=302)


def _claims_of(result: dict) -> dict:
    c = result.get("id_token_claims", {}) or {}
    return {
        "name": c.get("name") or c.get("preferred_username") or "Unknown",
        "email": c.get("preferred_username") or c.get("email") or "",
        "oid": c.get("oid", ""),
        "tid": c.get("tid", ""),
        "groups": c.get("groups", []),
    }


# ── Routes ───────────────────────────────────────────────────────────────────
@router.get("/auth/login")
def login(request: Request, next: str = "/"):
    if not ENABLED:
        raise HTTPException(status_code=503,
                            detail="SSO is not configured. See auth.py for the four required .env values.")
    try:
        flow = _msal_app().initiate_auth_code_flow(scopes=GRAPH_SCOPES, redirect_uri=REDIRECT_URI)
    except ValueError as exc:
        # Almost always a wrong SDI_TENANT_ID, or this host cannot reach
        # login.microsoftonline.com. Say which, rather than a stack trace.
        raise HTTPException(
            status_code=502,
            detail=("Could not reach Microsoft Entra for this tenant. Check SDI_TENANT_ID "
                    f"and that this server can reach login.microsoftonline.com. ({exc})"))
    flow["_created"] = time.time()
    flow["_next"] = next if next.startswith("/") else "/"   # never redirect off-site
    fid = secrets.token_urlsafe(24)
    _FLOWS[fid] = flow
    resp = RedirectResponse(url=flow["auth_uri"], status_code=302)
    resp.set_cookie(FLOW_COOKIE, fid, max_age=900, httponly=True,
                    secure=COOKIE_SECURE, samesite="lax", path="/")
    return resp


@router.get("/auth/callback")
def callback(request: Request):
    if not ENABLED:
        raise HTTPException(status_code=503, detail="SSO is not configured.")
    fid = request.cookies.get(FLOW_COOKIE)
    flow = _FLOWS.pop(fid, None) if fid else None
    if not flow:
        # Usually a stale browser tab or a restarted service — start again.
        return RedirectResponse(url="/auth/login", status_code=302)

    cache = msal.SerializableTokenCache()
    try:
        result = _msal_app(cache).acquire_token_by_auth_code_flow(flow, dict(request.query_params))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Sign-in failed: {exc}")

    if "error" in result:
        detail = result.get("error_description", result["error"])
        raise HTTPException(status_code=401, detail=f"Sign-in rejected: {detail[:300]}")

    claims = _claims_of(result)

    if ALLOWED_GROUPS:
        if not ALLOWED_GROUPS.intersection(claims.get("groups") or []):
            raise HTTPException(
                status_code=403,
                detail=("Your account is not in a group permitted to use SDI Intelligence. "
                        "If you believe it should be, the group must also be emitted as a "
                        "'groups' claim by the app registration."))

    sid = secrets.token_urlsafe(32)
    _STORE.put(sid, {"claims": claims, "cache": cache.serialize()},
               expires=time.time() + SESSION_HOURS * 3600)
    resp = RedirectResponse(url=flow.get("_next", "/"), status_code=302)
    resp.set_cookie(COOKIE_NAME, _serializer.dumps(sid), max_age=SESSION_HOURS * 3600,
                    httponly=True, secure=COOKIE_SECURE, samesite="lax", path="/")
    resp.delete_cookie(FLOW_COOKIE, path="/")
    return resp


@router.get("/auth/logout")
def logout(request: Request):
    raw = request.cookies.get(COOKIE_NAME)
    if raw and _STORE:
        try:
            _STORE.delete(_serializer.loads(raw))
        except BadSignature:
            pass
    # Sign out of Entra too, otherwise the next login silently reuses the session.
    post = str(request.base_url).rstrip("/") + "/"
    url = (f"{AUTHORITY}/oauth2/v2.0/logout?" + urlencode({"post_logout_redirect_uri": post})
           if ENABLED else "/")
    resp = RedirectResponse(url=url, status_code=302)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.get("/api/me")
def me(request: Request):
    user = current_user(request)
    if user is None:
        return JSONResponse(status_code=401, content={"signed_in": False,
                                                      "login_url": "/auth/login"})
    return {"signed_in": True, "sso_enabled": ENABLED, **user}


def graph_token(request: Request) -> Optional[str]:
    """A Graph access token for the signed-in user, refreshed silently if needed.

    Returns None when SSO is off, the session is gone, or the needed scope was
    never consented — callers must report that honestly rather than guess.
    """
    if not ENABLED:
        return None
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        sid = _serializer.loads(raw)
    except BadSignature:
        return None
    sess = _STORE.get(sid) if _STORE else None
    if not sess:
        return None

    cache = msal.SerializableTokenCache()
    cache.deserialize(sess["cache"])
    app = _msal_app(cache)
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
    if cache.has_state_changed:
        # A refreshed token must be persisted, or the next call refreshes again.
        _STORE.put(sid, {"claims": sess["claims"], "cache": cache.serialize()},
                   expires=sess["expires"])
    return result.get("access_token") if result else None
