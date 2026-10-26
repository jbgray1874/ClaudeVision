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
    auth = PrivateAuth(settings, factory=factory)
    app.include_router(auth.router)
    app.include_router(make_router(auth, Policy(settings.tenant, settings.owner, True),
                                  None, settings.origin, drafts_enabled=False))
    return auth
