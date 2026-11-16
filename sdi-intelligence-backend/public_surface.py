"""What a named estimator may reach from outside the office.

Its own module so the boundary can be tested without starting the service: the
guard in app.py is middleware on a running app, and a rule nobody can exercise
in a test is a rule that drifts.

Two decisions live here, and they are the whole of the remote estimating
boundary.

READING AND DOING ARE DIFFERENT PERMISSIONS THAT SHARE A URL PREFIX. "Use the
estimating screen on a phone" and "release a quotation to a customer" are both
under /api/estimate, along with emailing a quote, changing who quotes are
emailed to, switching the self-running estimator on and off, and firing the
delivery-note splitter. Allowing the prefix allows all of it. So reads are
allowed by method and writes only where named below - and a POST added next
month is refused until somebody puts it on this list deliberately.

THE FILE BROWSER IS NOT OPENED, ONE FOLDER IS. /api/files and /api/file read
every configured share. On the public surface they are held to the approved
completed-AI-briefs tree, so the drawings picker still works on a phone and the
rest of the shares stay where they are.
"""
import ntpath
import os

# The only POSTs an estimator may make from outside: start work, and ask about
# work already done.
PUBLIC_POST = (
    "/api/estimate",                  # start a run
    "/api/estimate/brief",            # start one from a completed brief
    "/api/estimate/tools/ask",        # questions answered from a filed record
)

# Named so a test can state what must never be on PUBLIC_POST, rather than the
# list being checked against itself.
NEVER_PUBLIC_POST = (
    "/api/estimate/release",
    "/api/estimate/release/withdraw",
    "/api/estimate/recipients",
    "/api/estimate/self-running/start",
    "/api/estimate/self-running/stop",
    "/api/estimate/logistics/split-scans",
    "/api/estimate/override",
    "/api/estimate/parity",
)

# The same "Shared" prefix as the workbook template in app.py. Without it the
# folder is not there, and the failure reads as a share permission problem.
BRIEFS_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed"
                  r"\Live Enquiries\completed AI briefs")
ENQUIRY_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed"
                   r"\AI Estimating\Live Enquiry")


def briefs_root() -> str:
    return (os.getenv("SDI_COMPLETED_AI_BRIEFS_ROOT", "") or BRIEFS_DEFAULT).strip()


def approved_roots() -> tuple:
    """The two trees the scanner may browse: finished estimates, and the
    drawings waiting to be priced. Everything else on every share stays inside
    the office, whoever is asking."""
    return (briefs_root(),
            (os.getenv("SDI_LIVE_ENQUIRY_ROOT", "") or ENQUIRY_DEFAULT).strip())


def post_allowed(path: str) -> bool:
    """May this POST be made from outside the office?"""
    return str(path or "").rstrip("/") in PUBLIC_POST


def under_the_briefs(asked: str) -> bool:
    """Is this path inside the approved briefs folder, and nowhere else?

    Compared after normalising, so "\\\\host\\share\\a\\..\\b" and a trailing
    slash cannot walk out, and a sibling folder whose name merely STARTS with
    the root's name ("...completed AI briefs backup") is not inside it.

    ── ntpath, NOT os.path ────────────────────────────────────────────────────
    These are always Windows paths - UNC shares and drive letters - whatever
    machine is asking the question. os.path on Linux does not treat a backslash
    as a separator, so the rule would be right in production and untestable
    anywhere else, which is how two outages happened on 26 October 2026. Naming
    the flavour makes the answer the same on both.
    """
    if not str(asked or "").strip():
        return False
    here = ntpath.normcase(ntpath.normpath(str(asked)))
    for root in approved_roots():
        if not root:
            continue
        there = ntpath.normcase(ntpath.normpath(root))
        if here == there or here.startswith(there.rstrip("\\") + "\\"):
            return True
    return False
