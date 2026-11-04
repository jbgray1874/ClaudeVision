"""SDI SameDay on the phone: carried by SDI Intelligence at /sameday/.

"The app needs to work on the phone" - James Gray, 4 November 2026.

SameDay runs on this server at http://127.0.0.1:5020, which a phone outside the office cannot reach, and on http a
browser will not open the microphone. SDI Intelligence is already published through App Proxy: https, Microsoft
sign-in, reachable from any phone. So it carries SameDay too, at /sameday/ on its own address. That needs no new Entra
app, and over https the microphone works. The live voice itself goes from the phone straight to OpenAI (WebRTC), as it
does in the office; only SameDay's page and its own requests come through here.

WHO MAY USE IT. The house rule, as the rest of the portal: on the office network as now; from outside, anyone signed
in to SDI with their Microsoft account (SameDay is "for company general use"). Writes from outside must come from this
same address (an Origin check), like the estimating screen's. Nothing else of this portal is reachable through it.

WHAT SAMEDAY IS SENT. The request, and the address it was carried at (X-Forwarded-Prefix: /sameday) so its page asks
for "/sameday/api/..." rather than this portal's own "/api/...". Never this portal's sign-in cookie, never anyone's
key. SameDay sees the request come from this machine, so its team code is not asked: Microsoft sign-in has already
been asked instead, which is the stronger of the two.

SDI_SAMEDAY_ENABLED=no in .env takes it away again; SDI_SAMEDAY_UPSTREAM moves it (default http://127.0.0.1:5020).
"""
import os

import httpx
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import auth

PREFIX = "/sameday"
UPSTREAM = os.getenv("SDI_SAMEDAY_UPSTREAM", "http://127.0.0.1:5020").strip().rstrip("/")
METHODS = ["GET", "HEAD", "POST"]
# What SameDay needs to answer - nothing that identifies a session here.
SEND = ("content-type", "accept", "accept-language", "user-agent", "range", "if-none-match", "if-modified-since")
# What the browser needs back. Never Set-Cookie: SameDay's only cookie is its team code, not used here.
BACK = ("content-type", "content-disposition", "cache-control", "etag", "last-modified", "content-range",
        "accept-ranges", "expires", "service-worker-allowed", "location")
# A render is drawn in the background and the page asks how it is going, so no request here should be long;
# 170 s stays inside App Proxy's 180.
TIMEOUT = httpx.Timeout(170.0, connect=5.0)

DOWN_PAGE = """<!doctype html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SDI SameDay</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#F5F3EF;color:#17181B;
font:16px/1.5 system-ui,sans-serif}div{max-width:420px;margin:24px;padding:24px;background:#fff;border-radius:16px}
a{color:#C8102E}</style></head><body><div><h1>SameDay isn't answering</h1>
<p>It isn't running on the server just now, so nothing was lost - try again in a minute. If it stays like this,
tell James or Muhammad.</p><p><a href="/app/">Back to the apps</a></p></div></body></html>"""

_client = None


def _http():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    return _client


def is_public(request: Request) -> bool:
    return auth.request_host(request) in auth.PUBLIC_HOSTS


def refusal(request: Request):
    """None when this person may use SameDay through here, else the response that says why not."""
    public = is_public(request)
    user = auth.current_user(request)
    wants_page = request.method in ("GET", "HEAD") and "/api/" not in request.url.path
    if user is None:
        if wants_page:
            return auth.login_redirect(request)           # back to SameDay once signed in
        return JSONResponse(status_code=401, content={"error": "Signed out - open SameDay again from the app portal."})
    if public and (not auth.ENABLED or user.get("kind") != "user"):
        # Outside the office only a person signed in with their SDI account - never the service key, and never
        # anyone at all on a server where sign-in isn't set up.
        return JSONResponse(status_code=403, content={"error": "SameDay from outside the office needs your SDI sign-in."})
    if public and request.method not in ("GET", "HEAD"):
        host = request.headers.get("host", "").lower()
        origin = request.headers.get("origin", "").lower().rstrip("/")
        if origin != "https://" + host:
            return JSONResponse(status_code=403, content={"error": "Same-origin request required"})
    return None


def upstream_url(request: Request) -> str:
    """SameDay's own address for this request, exactly as the browser asked (still encoded)."""
    raw = request.scope.get("raw_path") or request.url.path.encode("utf-8")
    path = raw.decode("latin-1")[len(PREFIX):] or "/"
    if not path.startswith("/"):
        path = "/" + path
    q = request.url.query
    return UPSTREAM + path + ("?" + q if q else "")


def headers_out(request: Request, user: dict | None) -> dict:
    h = {k: v for k, v in request.headers.items() if k.lower() in SEND}
    h["X-Forwarded-Prefix"] = PREFIX
    h["X-Forwarded-Proto"] = "https" if is_public(request) else request.url.scheme
    if user and user.get("kind") == "user" and (user.get("email") or user.get("name")):
        h["X-SDI-User"] = str(user.get("email") or user.get("name"))[:120]   # who, for SameDay's own records
    return h


def headers_back(r: httpx.Response) -> dict:
    out = {k: v for k, v in r.headers.items() if k.lower() in BACK}
    for k in list(out):
        if k.lower() == "location" and out[k].startswith("/") and not out[k].startswith("//"):
            out[k] = PREFIX + out[k]
        if k.lower() == "service-worker-allowed":
            out[k] = PREFIX + "/"
    return out


def install(app):
    if os.getenv("SDI_SAMEDAY_ENABLED", "yes").strip().lower() in ("no", "0", "off", "false"):
        return

    @app.get(PREFIX, include_in_schema=False)
    def sameday_root(request: Request):
        q = request.url.query
        return RedirectResponse(url=PREFIX + "/" + ("?" + q if q else ""), status_code=308)

    @app.api_route(PREFIX + "/{rest:path}", methods=METHODS, include_in_schema=False)
    async def sameday(rest: str, request: Request):
        no = refusal(request)
        if no is not None:
            return no
        body = await request.body() if request.method == "POST" else None
        try:
            r = await _http().request(request.method, upstream_url(request),
                                      headers=headers_out(request, auth.current_user(request)), content=body)
        except httpx.HTTPError:
            if "/api/" in request.url.path:
                return JSONResponse(status_code=503, content={"error": "SameDay isn't answering on the server just now."})
            return HTMLResponse(DOWN_PAGE, status_code=503)
        return Response(content=r.content, status_code=r.status_code, headers=headers_back(r))
