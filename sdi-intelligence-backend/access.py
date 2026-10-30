"""Who may use one app: named people, or anyone in a named Entra group.

── WHY THIS EXISTS ──────────────────────────────────────────────────────────
Every gated app in the portal had the same four lines: read a setting, split
it on commas, compare the signed-in person's object ID. That works, and it
means IT adds a person by editing a file on the server and restarting the
service - for every app, every person, every time. Somebody joins Customer
Services and three settings need a 36-character id pasted into them before
they can do their job.

So a setting may now hold GROUP object IDs as well as people's. Put "SDI
Estimators" in SDI_ESTIMATOR_OIDS once, and from then on IT adds people to
that group in Entra, where they already manage access to everything else.
Nothing is deployed, nothing is restarted, and nobody has to find an object
ID on a Tuesday.

── WHAT HAS NOT CHANGED ─────────────────────────────────────────────────────
An existing list of people's object IDs keeps working exactly as it did, and
an EMPTY list still admits nobody. The alternative - empty meaning everyone -
turns a missing line in a .env file into an open door, silently, on the day
it happens.

── THE ONE THING TO KNOW BEFORE USING GROUPS ────────────────────────────────
A group only works if the sign-in actually carries it. Entra omits the
`groups` claim unless the app registration is configured to emit it, so until
that is done every token says `"groups": []` and a group id in a setting
matches nobody. `why_refused` says which of those two it is, because
"somebody is not in the group" and "the group never arrives" look identical
from the outside and need different people to fix them.

Entra also omits the claim entirely for a user in more than about 200 groups.
That person would be refused rather than let through, which is the safe way
round and is the same limit auth.SDI_ALLOWED_GROUPS already carries.
"""
from __future__ import annotations

import os


# ── EVERY APP KEEPS ITS OWN DOOR ────────────────────────────────────────────
# There is deliberately NO portal-wide "anyone in this group" fallback. These
# apps are not interchangeable: TTI Despatch is somebody's live commercial
# tracker, the systems console shows a log, the estimating screen starts work
# that costs money. An app with an empty list admits nobody, and stays that way
# until it is given its own list.
#
# What changes is what a list may CONTAIN. One Entra group id in
# SDI_TTI_OIDS - "SDI TTI Despatch" - and Customer Services is managed in
# Entra from then on: no object IDs to find, no .env to edit, no restart, and
# the app is no less restricted than it was.


def listed(setting: str, env=None) -> set:
    """The ids named in one setting, lowered. People's, groups', or both."""
    source = os.environ if env is None else env
    return {v.strip().lower()
            for v in str(source.get(setting, "") or "").split(",") if v.strip()}


def may_use(setting: str, user, env=None) -> bool:
    """Is this signed-in person allowed by `setting`?

    True when their own object ID is named, or when any group they are in is.
    With nothing named anywhere, False for everybody.
    """
    named = listed(setting, env)
    if not named or not isinstance(user, dict):
        return False
    if user.get("kind") != "user":
        # A service principal or an API key is not a person. These apps read
        # live commercial data, so a read nobody can be named for is refused.
        return False
    if str(user.get("oid") or "").lower() in named:
        return True
    return bool(named.intersection(
        {str(g).lower() for g in (user.get("groups") or []) if str(g).strip()}))


def why_refused(setting: str, user, env=None) -> str:
    """A sentence for the person, saying which wall they hit.

    Four of them, because they need four different things done:
      * nobody is named at all        - the app is not set up
      * they are not a person         - a key or a service, not an account
      * groups are named but absent   - the registration is not emitting them
      * they are simply not on it     - ask IT to be added
    """
    named = listed(setting, env)
    if not named:
        return (f"{setting} is empty, so nobody can use this yet. It takes Entra "
                f"object IDs, comma separated - people's, or a GROUP's, which is "
                f"usually the one to use: name the group once here and add people "
                f"to it in Entra from then on.")
    if not isinstance(user, dict) or user.get("kind") != "user":
        return ("This needs a signed-in person. A service account or an API key "
                "cannot be named on the list.")
    carried = {str(g).lower() for g in (user.get("groups") or []) if str(g).strip()}
    if not carried and len(named) > 0:
        return ("You are signed in and not on the list. If access here is by "
                "group, note that this sign-in carried no group at all - Entra "
                "only sends them when the app registration is set to emit a "
                "'groups' claim, so a group on the list would match nobody. "
                "Check which account you are signed in as at /api/me.")
    return ("You are signed in, but this account is not on the list and nor is "
            "any group it belongs to. Check which account you are signed in as "
            "at /api/me - an admin account is a different account from the "
            "ordinary one - and ask IT to add it.")
