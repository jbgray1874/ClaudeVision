"""Call install(app) from the portal composition root; disabled unless opted in."""
import os
from private_auth import PrivateAuth, Settings
from private_email import Policy
from private_email_routes import make_router


def install(app, env=None, factory=None):
    env = os.environ if env is None else env
    if env.get("SDI_PRIVATE_ENABLED", "").lower() != "yes":
        return None
    settings = Settings(*(env.get("SDI_PRIVATE_" + key, "") for key in (
        "TENANT_ID", "CLIENT_ID", "OWNER_ID", "ORIGIN", "CLIENT_SECRET",
        "ENCRYPTION_KEY", "SESSION_DB")))
    # ── DRAFTS ARE A SEPARATE SWITCH FROM THE APP ITSELF ────────────────────────
    # A draft is written into the owner's own Drafts folder for them to read, change
    # and send by hand. Nothing here sends: there is no send route and the token is
    # refused if it ever carries Mail.Send. The switch is its own setting so drafting
    # can be turned off without turning the assistant off, and a server asked for
    # drafts with nowhere to keep the pending approvals refuses to start.
    drafts = env.get("SDI_PRIVATE_DRAFTS", "").lower() == "yes"
    draft_db = env.get("SDI_PRIVATE_DRAFT_DB", "").strip()
    if drafts and not draft_db:
        raise RuntimeError("SDI_PRIVATE_DRAFTS=yes needs SDI_PRIVATE_DRAFT_DB: a path in the "
                           "same protected folder as the session database. It holds pending "
                           "reply text, so it must not sit in a web root or on a share.")
    auth = PrivateAuth(settings, factory=factory)
    app.include_router(auth.router)
    app.include_router(make_router(auth, Policy(settings.tenant, settings.owner, True),
                                   draft_db or None, settings.origin, drafts_enabled=drafts))
    return auth
