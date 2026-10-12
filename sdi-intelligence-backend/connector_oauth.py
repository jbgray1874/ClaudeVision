"""
SDI Intelligence — sign-in front door for the tracker connector.

ChatGPT and Claude sign in to an MCP server the standard MCP way: they read
the server's own sign-in details, register themselves (dynamic client
registration) and send the person there. Microsoft Entra can't play that part
directly: it has no self-registration, and it refuses the "resource" parameter
MCP clients send (AADSTS9010010). So this module is the sign-in server ChatGPT
and Claude talk to, and it hands the actual sign-in to Entra:

    ChatGPT ─/register, /authorize─▶ here: "Connect SDI Tracker to ChatGPT?" (Continue)
                                     ─▶ Entra sign-in: account picker, MFA,
                                        assigned users only
    ChatGPT ◀──────── code ──────── here ◀─ /oauth/callback ─ Entra
    ChatGPT ─/token─▶ here ─▶ Entra token endpoint, with SDI's app secret

Nothing is minted here: the access token ChatGPT gets IS Entra's token for this
API, so the connector's checks (signature, tenant, audience, scope, client app)
and the on-behalf-of exchange for Graph are unchanged. The refresh token is
Entra's, tagged with the registered client; only this server can redeem it,
because only this server holds the app secret.

Who may register: any client, but only with a ChatGPT or Claude callback
address (SDI_CONNECTOR_REDIRECTS). Who may sign in: whoever Entra allows - the
"SDI Tracker for ChatGPT" enterprise application is assignment-only.

On when SDI_CONNECTOR_OAUTH_CLIENT and SDI_CONNECTOR_OAUTH_SECRET are set: the
"SDI Tracker for ChatGPT" app registration, which needs
<connector address>/oauth/callback as a Web redirect URI.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import os
import secrets
import threading
import time
from typing import Callable
from urllib.parse import urlencode

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams,
                                      AuthorizeError, RefreshToken, RegistrationError, TokenError,
                                      construct_redirect_uri)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

CALLBACK_PATH = "/oauth/callback"
CONSENT_PATH = "/oauth/consent"
# Where ChatGPT and Claude receive the sign-in result. A client registering any
# other callback address is refused.
DEFAULT_REDIRECTS = ("https://chatgpt.com/connector/oauth/",
                     "https://chatgpt.com/connector_platform_oauth_redirect",
                     "https://claude.ai/api/mcp/auth_callback",
                     "https://claude.com/api/mcp/auth_callback")
PENDING_SECONDS = 15 * 60     # from "Connect" to finishing the Microsoft sign-in
CODE_SECONDS = 5 * 60         # from the sign-in to ChatGPT collecting its token
MAX_CLIENTS = 500


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _page(title: str, text: str, status: int = 400) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>{html.escape(title)}</title><body style='font:16px system-ui;margin:2em;max-width:34em'>"
        f"<h2>{html.escape(title)}</h2><p>{html.escape(text)}</p>", status_code=status)


class FrontDoor:
    """The MCP SDK's authorization-server interface, delegating sign-in to Entra."""

    def __init__(self, *, public_url: str, tenant: str, client_id: str, client_secret: str,
                 api_scope: str, scope: str, verify: Callable[[str], AccessToken | None],
                 clients_file: str, redirects: tuple[str, ...] = DEFAULT_REDIRECTS):
        self.resource = public_url.rstrip("/")
        self.base = "/".join(self.resource.split("/", 3)[:3])        # https://host
        self.callback_url = self.base + CALLBACK_PATH
        self.client_id, self._secret = client_id, client_secret
        self.api_scope, self.scope = api_scope, scope
        # Everything a registered client may ask for; the Entra request is always the same.
        self.scopes = [scope, api_scope, "offline_access", "openid", "profile", "email"]
        self._verify = verify
        self._authority = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
        self._redirects = tuple(r for r in redirects if r)
        self._file = clients_file
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._codes: dict[str, tuple[AuthorizationCode, dict]] = {}
        self._clients = self._load()

    # ── registered clients (kept on disk, so a restart doesn't disconnect anyone) ──
    def _load(self) -> dict[str, OAuthClientInformationFull]:
        try:
            with open(self._file, encoding="utf-8") as f:
                rows = json.load(f)
            return {r["client_id"]: OAuthClientInformationFull.model_validate(r) for r in rows}
        except FileNotFoundError:
            return {}
        except Exception as exc:                          # noqa: BLE001 - start empty rather than not at all
            print(f"[connector.oauth] couldn't read {self._file} ({exc}); clients must reconnect", flush=True)
            return {}

    def _save(self) -> None:
        tmp = self._file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([c.model_dump(mode="json") for c in self._clients.values()], f, indent=1)
        os.replace(tmp, self._file)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in client_info.redirect_uris or []]
        bad = [u for u in uris if not u.startswith(self._redirects)]
        if not uris or bad:
            print(f"[connector.oauth] registration refused: callback {bad or 'missing'}", flush=True)
            raise RegistrationError("invalid_redirect_uri",
                                    "Only ChatGPT and Claude callback addresses can register.")
        client_info.scope = " ".join(self.scopes)
        with self._lock:
            self._clients[client_info.client_id] = client_info
            while len(self._clients) > MAX_CLIENTS:              # oldest first
                oldest = min(self._clients.values(), key=lambda c: c.client_id_issued_at or 0)
                self._clients.pop(oldest.client_id)
            self._save()
        print(f"[connector.oauth] registered client {client_info.client_name or '?'} "
              f"({client_info.client_id}) -> {uris[0]}", flush=True)

    # ── sign-in: ChatGPT -> here -> Entra -> here -> ChatGPT ──────────────────────
    def _reap(self) -> None:
        now = time.time()
        for k in [k for k, p in self._pending.items() if now - p["at"] > PENDING_SECONDS]:
            self._pending.pop(k, None)
        for k in [k for k, (c, _) in self._codes.items() if c.expires_at < now]:
            self._codes.pop(k, None)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource and params.resource.rstrip("/") not in (self.resource, self.base):
            raise AuthorizeError("invalid_target", f"This server signs in for {self.resource} only.")
        verifier = secrets.token_urlsafe(48)
        txn = secrets.token_urlsafe(32)
        with self._lock:
            self._reap()
            self._pending[txn] = {"client_id": client.client_id, "params": params, "verifier": verifier,
                                  "at": time.time(), "consented": False,
                                  "entra": self._entra_authorize_url(txn, verifier)}
        # Our own "allow?" page first: every registered client signs in as the same
        # SDI app, so Microsoft's sign-in alone can't tell the person which app is asking.
        return f"{self.base}{CONSENT_PATH}?" + urlencode({"t": txn})

    def _entra_authorize_url(self, txn: str, verifier: str) -> str:
        return f"{self._authority}/authorize?" + urlencode({
            "client_id": self.client_id, "response_type": "code", "response_mode": "query",
            "redirect_uri": self.callback_url, "scope": f"{self.api_scope} offline_access",
            "state": txn, "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
            # Always ask which account: a browser already signed in to another
            # Microsoft account (an admin account, say) would otherwise use it silently.
            "prompt": "select_account"})

    async def consent(self, request: Request) -> Response:
        """GET: which app wants the tracker, Allow / Cancel. POST (Allow): on to Microsoft."""
        form = await request.form() if request.method == "POST" else request.query_params
        txn = str(form.get("t") or "")
        with self._lock:
            p = self._pending.get(txn)
        if not p or time.time() - p["at"] > PENDING_SECONDS:
            return _page("Sign-in expired", "This sign-in link has expired or was already used. "
                         "Go back to ChatGPT (or Claude) and connect SDI Tracker again.")
        params: AuthorizationParams = p["params"]
        if request.method == "POST":
            if form.get("allow") != "yes":
                with self._lock:
                    self._pending.pop(txn, None)
                return RedirectResponse(construct_redirect_uri(
                    str(params.redirect_uri), state=params.state, error="access_denied",
                    error_description="Cancelled"), status_code=303)
            p["consented"] = True
            return RedirectResponse(p["entra"], status_code=303, headers={"Cache-Control": "no-store"})
        host = str(params.redirect_uri).split("/")[2]
        app = ("ChatGPT" if host.endswith("chatgpt.com") else "Claude" if host.startswith("claude.") else host)
        client = self._clients.get(p["client_id"])
        named = html.escape((client.client_name if client and client.client_name else "") or app)
        t = html.escape(txn)
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<title>Connect SDI Tracker</title>"
            "<body style='font:17px system-ui;margin:2em auto;max-width:30em;padding:0 1em'>"
            f"<h2>Connect SDI Tracker to {html.escape(app)}?</h2>"
            f"<p><b>{named}</b> (returning to <b>{html.escape(host)}</b>) is asking to look up and "
            "change your tracker records as you, under SDI's rules.</p>"
            "<p>Only continue if <b>you</b> just pressed Connect in your own "
            f"{html.escape(app)}. Next you'll choose your SDI Microsoft account.</p>"
            f"<form method=post><input type=hidden name=t value='{t}'>"
            "<button name=allow value=yes style='font:inherit;padding:.6em 1.4em;margin-right:1em'>Continue</button>"
            "<button name=allow value=no style='font:inherit;padding:.6em 1.4em'>Cancel</button></form>",
            headers={"X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'",
                     "Cache-Control": "no-store"})

    async def _entra_token(self, form: dict) -> tuple[int, dict]:
        return await self._post_token({**form, "client_id": self.client_id, "client_secret": self._secret})

    async def _post_token(self, data: dict) -> tuple[int, dict]:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(f"{self._authority}/token", data=data)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"error": "bad_response", "error_description": r.text[:200]}

    async def callback(self, request: Request) -> Response:
        q = request.query_params
        with self._lock:
            p = self._pending.pop(q.get("state") or "", None)
        if not p or not p["consented"] or time.time() - p["at"] > PENDING_SECONDS:
            return _page("Sign-in expired", "This sign-in link has expired or was already used. "
                         "Go back to ChatGPT (or Claude) and connect SDI Tracker again.")
        params: AuthorizationParams = p["params"]

        def back(**kw: str | None) -> RedirectResponse:
            return RedirectResponse(construct_redirect_uri(str(params.redirect_uri), state=params.state, **kw),
                                    status_code=302, headers={"Cache-Control": "no-store"})

        if q.get("error"):
            why = (q.get("error_description") or q["error"]).splitlines()[0][:300]
            print(f"[connector.oauth] Microsoft sign-in refused: {why}", flush=True)
            return back(error="access_denied", error_description=why)
        status, tok = await self._entra_token({
            "grant_type": "authorization_code", "code": q.get("code") or "",
            "redirect_uri": self.callback_url, "code_verifier": p["verifier"],
            "scope": f"{self.api_scope} offline_access"})
        if status != 200 or "access_token" not in tok:
            why = str(tok.get("error_description") or tok.get("error") or status).splitlines()[0][:300]
            print(f"[connector.oauth] token from Microsoft refused: {why}", flush=True)
            return back(error="access_denied", error_description=why)
        who = await asyncio.to_thread(self._verify, tok["access_token"])
        if who is None:                                   # the verifier has logged why
            return back(error="access_denied", error_description="That account can't use SDI Tracker.")
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._codes[code] = (AuthorizationCode(
                code=code, scopes=params.scopes or [self.scope], expires_at=time.time() + CODE_SECONDS,
                client_id=p["client_id"], code_challenge=params.code_challenge,
                redirect_uri=params.redirect_uri,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=params.resource, subject=who.subject), tok)
        email = (who.claims or {}).get("preferred_username") or (who.claims or {}).get("upn") or who.subject
        print(f"[connector.oauth] signed in: {email}", flush=True)
        return back(code=code)

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        entry = self._codes.get(authorization_code)
        return entry[0] if entry and entry[0].client_id == client.client_id else None

    def _issue(self, client_id: str, tok: dict) -> OAuthToken:
        rt = tok.get("refresh_token")
        return OAuthToken(access_token=tok["access_token"], expires_in=int(tok.get("expires_in") or 3600),
                          scope=self.scope, refresh_token=f"{client_id}~{rt}" if rt else None)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        with self._lock:
            entry = self._codes.pop(authorization_code.code, None)       # one use only
        if not entry:
            raise TokenError("invalid_grant", "authorization code already used")
        return self._issue(client.client_id, entry[1])

    # ── staying signed in ────────────────────────────────────────────────────────
    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> RefreshToken | None:
        owner, sep, entra_rt = refresh_token.partition("~")
        if not sep or not entra_rt or owner != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=owner, scopes=list(self.scopes))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull,
                                     refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        status, tok = await self._entra_token({
            "grant_type": "refresh_token", "refresh_token": refresh_token.token.partition("~")[2],
            "scope": f"{self.api_scope} offline_access"})
        if status != 200 or "access_token" not in tok:
            why = str(tok.get("error_description") or tok.get("error") or status).splitlines()[0][:300]
            print(f"[connector.oauth] refresh refused by Microsoft: {why}", flush=True)
            raise TokenError("invalid_grant", "Sign in again: " + why)
        if await asyncio.to_thread(self._verify, tok["access_token"]) is None:
            raise TokenError("invalid_grant", "That account can't use SDI Tracker.")
        return self._issue(client.client_id, tok)

    # ── every request to the tracker ─────────────────────────────────────────────
    async def load_access_token(self, token: str) -> AccessToken | None:
        return await asyncio.to_thread(self._verify, token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        return None          # revocation isn't offered; access is removed in Entra
