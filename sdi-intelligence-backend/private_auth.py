"""Isolated, read-only Entra web authentication. Never imports shared auth/config."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
from uuid import UUID

import msal
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse

PREFIX = "/api/private-email"
CALLBACK = PREFIX + "/auth/callback"
COOKIE = "__Host-sdi-private-session"
FLOW_COOKIE = "__Host-sdi-private-flow"
# Mail.ReadWrite is what createReply needs to put a draft in the Drafts folder.
# It CANNOT send: sending is Mail.Send, a separate permission this app never asks
# for and refuses to hold. See NEVER below and GraphMailbox.create_reply.
SCOPES = ["User.Read", "Mail.ReadWrite"]
# Scopes that would make this something other than a drafting assistant: posting
# mail, or reaching a mailbox that is not the owner's own. A token carrying any of
# them is refused outright, however it came to be granted.
NEVER = ("Mail.Send", "Mail.Send.Shared", "Mail.ReadWrite.Shared", "Mail.Read.Shared")


GRAPH = "https://graph.microsoft.com/"


def _short(scope: str) -> str:
    """"https://graph.microsoft.com/Mail.ReadWrite" -> "Mail.ReadWrite"; a short
    name is returned unchanged. Entra uses both forms for the same permission."""
    return str(scope or "").rsplit("/", 1)[-1]


def _granted(result, cache):
    """The permissions a token actually carries, as short names.

    MSAL's answer leaves out "scope" when it serves a token from its cache: that
    field echoes what the identity provider said, and nothing was issued. The
    permissions are on the cached entry itself, under "target".

    Reading a missing "scope" as "this token has no permissions" refused every
    good token the cache ever served, and logged it as "holds []" - which reads
    like a consent that was never granted, and was chased as one for most of a
    day. An empty answer here still refuses the token; it just has to be empty
    because the permissions really are absent, not because we looked in the one
    place MSAL does not fill in.
    """
    said = str(result.get("scope") or "").split()
    if said:
        return {_short(s) for s in said}
    look = getattr(cache, "search", None) or getattr(cache, "find", None)
    if not callable(look):
        return set()
    try:
        entries = list(look(msal.TokenCache.CredentialType.ACCESS_TOKEN))
    except Exception:
        return set()
    # Every access token the cache holds for this registration. Wider than the
    # one token in hand, so it can only refuse where the exact answer would
    # allow - the safe direction for a check whose job is to refuse.
    held = set()
    for entry in entries:
        if isinstance(entry, dict):
            held |= {_short(s) for s in str(entry.get("target") or "").split()}
    return held


def _both_forms(scopes):
    """The same permissions written the two ways Microsoft writes them.

    Entra accepts either, and caches the token under whichever form it answered
    with. MSAL then matches a silent request against those cached strings
    literally: ask for "Mail.ReadWrite" when the cache says
    "https://graph.microsoft.com/Mail.ReadWrite" and MSAL reports no token at
    all, which is indistinguishable from no consent. We cannot reach inside
    MSAL's comparison, so ask it both ways and keep whichever it answers.
    """
    short = [_short(s) for s in scopes]
    return [short, [GRAPH + s for s in short]]


@dataclass(frozen=True)
class Settings:
    tenant: str
    client: str
    owner: str
    origin: str
    credential: str
    encryption_key: str
    database: str

    def validate(self):
        for value in (self.tenant, self.client, self.owner):
            if str(UUID(value)) != value:
                raise ValueError("Canonical tenant, client and owner UUIDs required")
        url = urlsplit(self.origin)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path or url.query or url.fragment):
            raise ValueError("An exact HTTPS origin, without a trailing slash, is required")
        if not self.credential or not self.database:
            raise ValueError("Private credential and database required")
        Fernet(self.encryption_key.encode())


class Store:
    """Encrypted payloads; separate connection per operation, atomic flow consumption."""
    def __init__(self, path, key):
        self.path = path
        self.cipher = Fernet(key.encode())
        with self.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS private_sessions (key TEXT PRIMARY KEY, payload BLOB, expires REAL)")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, key, payload, expires):
        blob = self.cipher.encrypt(json.dumps(payload).encode())
        with self.connection() as db:
            db.execute("DELETE FROM private_sessions WHERE expires <= ?", (time.time(),))
            db.execute("INSERT OR REPLACE INTO private_sessions VALUES (?, ?, ?)", (key, blob, expires))

    def get(self, key, consume=False):
        with self.connection() as db:
            if consume:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload, expires FROM private_sessions WHERE key=?", (key,)).fetchone()
            if consume or (row and row[1] <= time.time()):
                db.execute("DELETE FROM private_sessions WHERE key=?", (key,))
        if not row or row[1] <= time.time():
            return None
        try:
            return json.loads(self.cipher.decrypt(row[0])), row[1]
        except (InvalidToken, ValueError):
            return None

    def delete(self, key):
        with self.connection() as db:
            db.execute("DELETE FROM private_sessions WHERE key=?", (key,))


class PrivateAuth:
    def __init__(self, settings, factory=None):
        settings.validate()
        self.settings = settings
        self.store = Store(settings.database, settings.encryption_key)
        self.factory = factory or self._factory
        self.router = APIRouter(prefix=PREFIX + "/auth")
        self.router.add_api_route("/login", self.login, methods=["GET"])
        self.router.add_api_route("/callback", self.callback, methods=["GET"])
        self.router.add_api_route("/logout", self.logout, methods=["POST"])

    def _factory(self, cache):
        return msal.ConfidentialClientApplication(
            self.settings.client,
            authority="https://login.microsoftonline.com/" + self.settings.tenant,
            client_credential=self.settings.credential, token_cache=cache,
            timeout=15)

    def host_ok(self, request):
        # Proxy's TLS is terminated upstream. Never derive callback from forwarded headers.
        return request.headers.get("host", "").lower() == urlsplit(self.settings.origin).netloc.lower()

    def allowed(self, claims):
        return (claims.get("tid") == self.settings.tenant and
                claims.get("oid") == self.settings.owner and
                claims.get("aud") == self.settings.client)

    @staticmethod
    def key(raw):
        return "session:" + hashlib.sha256(raw.encode()).hexdigest()

    def session(self, request):
        raw = request.cookies.get(COOKIE, "")
        if not self.host_ok(request) or not raw:
            return None
        row = self.store.get(self.key(raw))
        return row if row and self.allowed(row[0].get("claims", {})) else None

    def current_user(self, request):
        row = self.session(request)
        if not row:
            return None
        c = row[0]["claims"]
        return {"kind": "user", "tid": c["tid"], "oid": c["oid"]}

    @staticmethod
    def _why(app, account):
        """MSAL's own reason for a silent refusal. For the log only, and never
        allowed to decide anything: a probe that fails tells us nothing."""
        probe = getattr(app, "acquire_token_silent_with_error", None)
        if not callable(probe):
            return ""
        try:
            answer = probe(SCOPES, account=account)
        except Exception as problem:
            return f"{type(problem).__name__}: {problem}"
        if not isinstance(answer, dict):       # a stand-in, under test
            return ""
        said = " ".join(str(answer.get(k, "")) for k in ("error", "error_description"))
        return said.strip()

    @staticmethod
    def _held(cache):
        """The permissions the cached access tokens are filed under - scope names
        only. No token material, no claims, nothing that identifies a person."""
        look = getattr(cache, "search", None) or cache.find
        try:
            tokens = list(look(msal.TokenCache.CredentialType.ACCESS_TOKEN))
        except Exception:
            return ""
        return "; ".join(sorted(
            " ".join(sorted(str(t.get("target", "")).split())) for t in tokens))

    def graph_token(self, request):
        # Every way out of here is a 403 that reads like a consent problem, so
        # each one says which it was. An expired session leaving no line at all
        # sent an afternoon into Entra and MSAL, when the answer was "sign in
        # again" - what the screen had been saying all along.
        row = self.session(request)
        if not row:
            print("[private-email] no usable session: the sign-in has expired, "
                  "or this is a different browser. Signing in again is the fix.",
                  flush=True)
            return None
        data, expires = row
        cache = msal.SerializableTokenCache()
        cache.deserialize(data["cache"])
        app = self.factory(cache)
        accounts = [a for a in app.get_accounts() if
                    a.get("local_account_id") == self.settings.owner and
                    a.get("realm") == self.settings.tenant]
        if len(accounts) != 1:
            print(f"[private-email] the session holds {len(accounts)} account(s) "
                  f"for this owner and tenant, and exactly one is required. "
                  f"The cache has {len(app.get_accounts())} in total.", flush=True)
            return None
        result = {}
        for asked in _both_forms(SCOPES):
            try:
                answer = app.acquire_token_silent(asked, account=accounts[0]) or {}
            except Exception as problem:
                print(f"[private-email] asking MSAL for a token raised "
                      f"{type(problem).__name__}: {problem}", flush=True)
                return None
            if answer.get("access_token"):
                result = answer
                break
        if not result:
            # Nothing came back at all, which is NOT the same as a token without
            # the permission - and the 403 it produces says "consent required",
            # which sent the first live sign-in looking in Entra at a consent
            # that was already granted. Say what MSAL actually objected to and
            # what its cache is holding, so the next look starts in the right place.
            print(f"[private-email] no token from the cache. msal: "
                  f"{self._why(app, accounts[0]) or 'no reason given'}; "
                  f"cache holds {self._held(cache) or 'no access token'}; "
                  f"asked for {sorted(_short(s) for s in SCOPES)}", flush=True)
            return None
        # Do not accept a token acquired for a broader feature's permissions. A
        # consent granted elsewhere, or widened later in Entra, must not quietly
        # arrive here as the ability to send mail or read somebody else's.
        #
        # ── COMPARED ON THE SHORT NAME, BECAUSE MICROSOFT USES BOTH ────────────
        # Entra returns a granted scope as either "Mail.ReadWrite" or the full
        # "https://graph.microsoft.com/Mail.ReadWrite", and which one you get is
        # not something this code can decide. Comparing the full string against
        # the short name we asked for made every real token look like it was
        # missing the permission - and the mocked tests, written in short form,
        # agreed with each other and not with Entra.
        scopes = _granted(result, cache)
        if not {_short(s) for s in SCOPES}.issubset(scopes) or scopes & {_short(n) for n in NEVER}:
            print(f"[private-email] token refused: holds {sorted(scopes)}, "
                  f"needs {sorted(_short(s) for s in SCOPES)}", flush=True)
            return None
        if cache.has_state_changed:
            data["cache"] = cache.serialize()
            self.store.put(self.key(request.cookies[COOKIE]), data, expires)
        return result.get("access_token")

    def login(self, request: Request):
        if not self.host_ok(request):
            raise HTTPException(403, "Use the configured HTTPS portal address")
        try:
            flow = self.factory(msal.SerializableTokenCache()).initiate_auth_code_flow(
                scopes=SCOPES, redirect_uri=self.settings.origin + CALLBACK,
                prompt="select_account")
            target = urlsplit(flow["auth_uri"])
            if target.scheme != "https" or target.hostname != "login.microsoftonline.com":
                raise ValueError("Unexpected identity provider")
            state = flow["state"]
        except Exception:
            raise HTTPException(502, "Private sign-in could not start")
        nonce = secrets.token_urlsafe(32)
        self.store.put("flow:" + state, {"flow": flow, "browser": nonce}, time.time() + 600)
        response = RedirectResponse(flow["auth_uri"], status_code=302, headers={"Cache-Control": "no-store"})
        response.set_cookie(FLOW_COOKIE, nonce, max_age=600, secure=True, httponly=True, samesite="lax", path="/")
        return response

    def callback(self, request: Request):
        if not self.host_ok(request):
            raise HTTPException(403, "Wrong portal host")
        state = request.query_params.get("state", "")
        row = self.store.get("flow:" + state, consume=True) if state else None
        nonce = request.cookies.get(FLOW_COOKIE, "")
        if not row or not nonce or not secrets.compare_digest(row[0]["browser"], nonce):
            raise HTTPException(400, "Sign-in expired or browser/state mismatch; start again")
        cache = msal.SerializableTokenCache()
        try:
            result = self.factory(cache).acquire_token_by_auth_code_flow(row[0]["flow"], dict(request.query_params))
        except Exception:
            raise HTTPException(401, "Private sign-in failed; start again")
        claims = result.get("id_token_claims", {})
        if ("error" in result or not self.allowed(claims) or
                claims.get("exp", 0) <= time.time()):
            raise HTTPException(403, "Only the configured ordinary account may use this assistant")
        # Bind a limited server-side session to this specific registration and owner.
        old = request.cookies.get(COOKIE)
        if old:
            self.store.delete(self.key(old))
        sid = secrets.token_urlsafe(32)
        lifetime = min(3600, int(claims["exp"] - time.time()))
        self.store.put(self.key(sid), {"claims": claims, "cache": cache.serialize()}, time.time() + lifetime)
        response = RedirectResponse(PREFIX + "/workspace", status_code=302, headers={"Cache-Control": "no-store"})
        response.set_cookie(COOKIE, sid, max_age=lifetime, secure=True, httponly=True, samesite="lax", path="/")
        response.delete_cookie(FLOW_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    def logout(self, request: Request):
        if (not self.host_ok(request) or request.headers.get("origin") != self.settings.origin or
                request.headers.get("x-sdi-private-action") != "1"):
            raise HTTPException(403, "Same-origin logout required")
        raw = request.cookies.get(COOKIE)
        if raw:
            self.store.delete(self.key(raw))
        response = JSONResponse({"signed_out": True}, headers={"Cache-Control": "no-store"})
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response
