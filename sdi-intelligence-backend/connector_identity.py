"""Who is calling an MCP connector, and whether they may.

Three things, kept apart on purpose:

  * `refusal` - the rules a signature cannot check: the right issuer, the
    right tenant, the scope, a client app we know, and a person rather than a
    daemon. A pure function of the claims, so it can be tested without
    minting a signed token or installing an MCP server.
  * `Verifier` - the signature, and then those rules.
  * `named_in` - that person is on the list for THIS app, by Entra object ID.

── WHY THE LAST CHECK IS NOT THE FIRST ──────────────────────────────────────
A valid SDI token is not permission. Everybody in the company can get one.
The web app's TTI view is gated by SDI_TTI_OIDS for exactly that reason, and a
voice assistant that skipped the same list would be a way round it - the
quiet kind, where nothing is refused and nobody notices the door.

── WHY THE CHECK IS AT THE TOOL ─────────────────────────────────────────────
Not on the portal card, not in the connector's description. A card is a link,
and a description is a sentence. The only place a refusal cannot be walked
past is immediately before the work.

── WHY THE MCP IMPORT IS LATE ───────────────────────────────────────────────
The rules above are the part worth testing, and the test machine does not have
an MCP server installed - so importing one at the top of this file would make
the rules untestable to spare one line further down. The import happens where
a token is actually wrapped.

── WHY THE AM CRM CONNECTOR DOES NOT USE THIS YET ───────────────────────────
voicecrm_connector.py carries its own copy of the same token check. It is
Nick's live service with no tests of its own, and moving its identity check
while building something else is how an afternoon gets spent on an outage
that had nothing to do with the work in hand. It should move onto this module
the next time it is opened deliberately, with tests written first.
"""
from __future__ import annotations

import asyncio
import os
import threading

import jwt


def issuers_for(tenant: str) -> list[str]:
    """Both spellings Entra uses. A token from the other one is a real token
    about a real person, and refusing it reads as a broken connector."""
    return [f"https://login.microsoftonline.com/{tenant}/v2.0",
            f"https://sts.windows.net/{tenant}/"]


def refusal(claims: dict, *, tenant: str, scope: str, clients=()) -> str:
    """Why this token is not acceptable, or "" if it is.

    Order matters only for the message; any one of them is a refusal.
    """
    known = {str(c).strip().lower() for c in clients if str(c).strip()}
    scopes = str(claims.get("scp", "")).split()
    client = str(claims.get("azp") or claims.get("appid") or "").lower()
    return ("issuer" if claims.get("iss") not in issuers_for(tenant) else
            "tenant" if claims.get("tid") != tenant else
            "scope" if scope not in scopes else
            "client" if known and client not in known else
            # No oid means an application token: a daemon, not a person. This
            # reads a live commercial tracker, so an unattributable read is
            # refused however valid the token is.
            "user" if not claims.get("oid") else "")


class Verifier:
    """Accepts only Entra access tokens issued by SDI's tenant for this API.

    Every refusal prints which check failed, and never the token: a connector
    that refuses silently is a connector nobody can get working.
    """

    def __init__(self, *, tenant: str, audiences, scope: str, clients=(),
                 jwks_url: str = "", label: str = "connector"):
        self.tenant = tenant
        self.audiences = [a for a in audiences if a]
        self.scope = scope
        self.clients = {str(c).strip().lower() for c in clients if str(c).strip()}
        self.label = label
        self.issuers = issuers_for(tenant)
        self._jwks = jwt.PyJWKClient(
            jwks_url or f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
            cache_keys=True, lifespan=3600)

    def check(self, token: str):
        from mcp.server.auth.provider import AccessToken     # see the note above
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"],
                                audience=self.audiences,
                                options={"require": ["exp", "iss", "aud"]})
        except Exception as exc:               # noqa: BLE001 - any doubt is a refusal
            print(f"[{self.label}.auth] refused: {type(exc).__name__}: "
                  f"{str(exc)[:160]}", flush=True)
            return None
        why = refusal(claims, tenant=self.tenant, scope=self.scope, clients=self.clients)
        if why:
            client = str(claims.get("azp") or claims.get("appid") or "").lower()
            print(f"[{self.label}.auth] refused: wrong {why} (client={client})", flush=True)
            return None
        scopes = str(claims.get("scp", "")).split()
        if self.audiences:
            scopes += [f"api://{self.audiences[0]}/{s}" for s in scopes if "/" not in s]
        return AccessToken(
            token=token, client_id=str(claims.get("azp") or claims.get("appid") or ""),
            scopes=scopes, expires_at=int(claims["exp"]), subject=claims["oid"],
            claims={k: claims.get(k) for k in
                    ("iss", "oid", "tid", "name", "preferred_username", "upn")})

    async def verify_token(self, token: str):
        return await asyncio.to_thread(self.check, token)


def person(token) -> dict:
    """The signed-in person, shaped like the web app's own user record."""
    claims = (getattr(token, "claims", None) or {}) if token is not None else {}
    email = claims.get("preferred_username") or claims.get("upn") or ""
    return {"name": claims.get("name") or email, "email": email,
            "oid": claims.get("oid", ""), "tid": claims.get("tid", ""),
            "kind": "user"}


def named_in(setting: str, user: dict) -> bool:
    """Is this person on `setting`'s list of Entra object IDs?

    An empty or unset list admits NOBODY. The alternative - an empty list
    meaning "everyone" - turns a missing line in a .env file into an open
    door, and that failure is silent on the day it happens.
    """
    named = {v.strip().lower() for v in os.getenv(setting, "").split(",") if v.strip()}
    return bool(named and user and str(user.get("oid") or "").lower() in named)


class GraphOnBehalfOf:
    """This person's Microsoft Graph token, from the token they presented.

    Their own delegated rights, exactly as the web app's sign-in has them, so
    SharePoint is read as them. Nobody inherits access from a service account,
    and a person who loses access to the site loses it here too.
    """

    def __init__(self, msal_app, scopes, label: str = "connector"):
        self._make = msal_app
        self._scopes = scopes
        self._label = label
        self._lock = threading.Lock()
        self._app = None

    def token_for(self, api_token: str) -> str | None:
        with self._lock:
            if self._app is None:
                self._app = self._make()
            result = self._app.acquire_token_on_behalf_of(api_token, scopes=self._scopes)
        if "access_token" not in result:
            print(f"[{self._label}.obo] no Graph token: {result.get('error')}: "
                  f"{str(result.get('error_description', ''))[:200]}", flush=True)
            return None
        return result["access_token"]
