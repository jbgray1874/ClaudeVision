"""Is the person on a phone, or at a desk?

── WHY THIS IS A MODULE AND NOT THREE LINES IN app.py ───────────────────────
/estimating serves the full screen to a desk and the pocket page to a phone,
so this one answer decides which page an estimator gets. Get it wrong in the
generous direction and somebody at a desk loses the live log, the file browser
and the release button with no explanation; get it wrong in the mean direction
and the phone page nobody can find is the phone page nobody uses.

Middleware on a running service cannot be exercised in a test, and app.py
cannot even be imported without FastAPI installed - so a rule left in there is
a rule that drifts. This takes two strings and returns a bool, which means the
user-agents of the actual phones in the building can be put to it.

── WHAT IT DELIBERATELY DOES NOT DO ─────────────────────────────────────────
It does not look at screen width. A narrow window on a laptop is still a
laptop, and somebody who has dragged a browser half-way across a monitor has
not asked for a different app.
"""
import re

# Sent by Chromium browsers (Chrome, Edge, Samsung Internet, Android WebView).
# "?1" means the browser is telling us it is a mobile; "?0" means it is telling
# us it is not. Both are believed, because it is the browser answering about
# itself rather than us guessing from a string it made up.
HINT_YES = "?1"
HINT_NO = "?0"

# The fallback, for Safari and anything else that sends no hint.
#
#   iphone / ipod        iOS phones.
#   android.+mobile      Android PHONES only. Chrome on an Android TABLET sends
#                        "Android" with no "Mobile" - that is the documented way
#                        the two are told apart, and a tablet has room for the
#                        full screen.
#   the rest             Windows Phone, BlackBerry, Opera Mini. Rare to the
#                        point of nostalgia, and free to keep.
#
# "ipad" is NOT here, and that is on purpose twice over: an iPad has the room,
# and iPadOS reports itself as a Mac anyway, so matching it is not possible
# from the user-agent alone.
PHONE = re.compile(r"iphone|ipod|android.+mobile|windows phone|blackberry"
                   r"|iemobile|opera mini", re.I)


def is_a_phone(user_agent: str = "", mobile_hint: str = "") -> bool:
    """True for a phone, False for a desk, a tablet, or anything unreadable.

    `mobile_hint` is the Sec-CH-UA-Mobile header and wins when it says
    anything; `user_agent` is the fallback. An empty or unrecognised pair is
    False: the full screen is the one that can do everything, so not knowing
    means not taking anything away.
    """
    hint = (mobile_hint or "").strip()
    if hint == HINT_YES:
        return True
    if hint == HINT_NO:
        return False
    return bool(PHONE.search(user_agent or ""))
