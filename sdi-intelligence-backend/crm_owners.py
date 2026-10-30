"""Which owner's records a signed-in person sees in AM CRM.

── WHY THIS IS ITS OWN MODULE ───────────────────────────────────────────────
voicecrm.py imports httpx and FastAPI, so it cannot be imported in a test on a
machine that lacks them - and this is the last rule in the app that should go
unexercised.

SDI_VOICECRM_OWNER is ONE value, read once at startup. For a one-person pilot
that was right. The moment a second person signs in it is wrong in the worst
way available: they do not see "nothing", they see the FIRST person's accounts,
with nothing on screen to say the rows are not theirs. Four people were about
to be given access, one of them the Sales Director. Handing somebody another
person's pipeline labelled as their own is not a missing feature - it is a
false statement about whose numbers they are reading, and through ChatGPT's
voice mode there is not even a screen to notice it on.

So the mapping is from a person's SIGN-IN NAME to their owner token in the
tracker:

    SDI_VOICECRM_OWNERS=nick.garrish@sdidisplays.co.uk=NG,kayleigh.thornhill@wearesdi.com=KT

── THE SIGN-IN NAME, WHICH IS NOT ALWAYS THE E-MAIL ADDRESS ─────────────────
Look at that example: two domains. Nick's mailbox is @wearesdi.com, but he
signs in as nick.garrish@sdidisplays.co.uk - an account from before the
rebrand. The app identifies people by the token's preferred_username, which
is the SIGN-IN name, so that is what has to go here.

On 30 October this was written with his e-mail address instead. The setting
looked right, every check that compared the setting with itself passed, and
Nick - the pilot's own user - was locked out of his own records with "your
records aren't mapped yet". Check-Entra-Access.ps1 caught it by asking Entra.
Run it after any change to this setting.

ALL_RECORDS ("*") means every row, for the people whose job is the whole
pipeline rather than a queue:

    ...,andy.baxter@wearesdi.com=*

── WHY A LIST OF PEOPLE AND NOT AN ENTRA GROUP ──────────────────────────────
Every other app here moved to groups, and this one should not. A group answers
"may this person in?". That is not the question. The question is "which
initials are theirs in the tracker" - a fact about the person that no group
membership can carry. The group still decides who may open the app at all.
"""
ALL_RECORDS = "*"


def parse(setting: str) -> dict[str, str]:
    """Read the mapping. Anything unparseable is skipped, not fatal.

    A typo in one pair must not read as "nobody sees anything": that would
    take the app away from everybody at once, over a stray comma, with the
    cause nowhere on screen.
    """
    out: dict[str, str] = {}
    for pair in str(setting or "").split(","):
        email, _, token = pair.partition("=")
        email, token = email.strip().lower(), token.strip()
        if email and token:
            out[email] = token
    return out


def owner_for(user, mapping: dict[str, str], fallback: str | None) -> str | None:
    """The owner token whose rows this person sees, or None for nobody's.

    `fallback` is used ONLY when the mapping is empty - that is the running
    pilot, unchanged, so deploying this changes nothing until somebody writes
    the setting.

    Once the mapping exists, a person who is not in it gets None, which means
    "show them nothing and say why". It never means `fallback`: a silent
    fallback is indistinguishable, on screen, from "these are your records",
    and that is the bug this module exists to prevent rather than a safety net
    for it.
    """
    if not mapping:
        return fallback
    if not isinstance(user, dict):
        return None
    return mapping.get(str(user.get("email") or "").strip().lower()) or None


def sees_everything(owner: str | None) -> bool:
    return owner == ALL_RECORDS
