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

THE FILE BROWSER IS NOT OPENED, FOUR FOLDERS ARE. /api/files and /api/file
read every configured share. On the public surface they are held to the live
enquiries, the completed AI briefs, the filed estimates and the filed parity
comparisons (approved_roots), so the drawings picker works on a phone, a
finished estimate and its comparison can be opened, and the rest of the shares
stay where they are. The manual estimates themselves are not opened from
outside: a comparison files its own copy of the manual sheet it used.

THE SELF-RUNNING SWITCH IS FOR THE NAMED ESTIMATORS (D-641). JG, 3 Nov 2026: "open the
self-running controls from outside... needs to run from the phone". Switching it on starts
the watcher working through the Live Enquiry sheet, which queues estimates, so it is held to
the people who may start a run (SDI_ESTIMATOR_OIDS), exactly as starting one is. Switching it
off lets the job in progress finish and queues nothing more. The watcher's own heartbeat
stays office-only, and stopping one running job (/{run}/abandon) is not on this list.

PARITY IS FOR THE NAMED ESTIMATORS (D-621). A filed comparison holds copies of
the manual costing sheets, so from outside the office everything under
/api/estimate/parity, reading included, and every file in the parity folder,
is held to SDI_ESTIMATOR_OIDS, the people who may start a run. Anyone else
signed in sees the rest of estimating as before.
"""
import ntpath
import os
import re

# The only POSTs an estimator may make from outside: start work, and ask about
# work already done.
PUBLIC_POST = (
    "/api/estimate",                  # start a run
    "/api/estimate/brief",            # start one from a completed brief
    "/api/estimate/tools/ask",        # questions answered from a filed record
    "/api/estimate/parity/job",       # compare one job with its manual estimate (D-619)
    "/api/estimate/parity/period",    # compare every job estimated in a period (D-619)
    "/api/estimate/parity/periods",   # Period A against Period B (D-621)
    "/api/estimate/parity/ask",       # a question about one filed comparison (D-628)
    "/api/estimate/self-running/start",   # the self-running switch, on (D-641)
    "/api/estimate/self-running/stop",    # and off (D-641)
)

# THE SELF-RUNNING SWITCH (D-641): allowed from outside, and held to the named estimators in
# app.py's guard because switching it on queues estimates.
SELF_RUNNING_POST = (
    "/api/estimate/self-running/start",
    "/api/estimate/self-running/stop",
)

# PARITY BY JOB NUMBER (D-619). JG, 1 Nov 2026: the comparison "in the web portal inside the
# network or on VPN, and also the phone or tablet with only wifi or data". It reads two filed
# spreadsheets and files both, with the report, under the parity folder; it never runs an
# estimate, releases or e-mails anything. It writes to the share, and what it files holds
# copies of the manual costing sheets, so running one AND reading what is filed are held to
# the named estimators (SDI_ESTIMATOR_OIDS), as starting a run is (D-621).
# The upload route, /api/estimate/parity, stays office-only (NEVER_PUBLIC_POST).
PARITY_POST = (
    "/api/estimate/parity/job",
    "/api/estimate/parity/period",
    "/api/estimate/parity/periods",
    "/api/estimate/parity/ask",
)
PARITY_PREFIX = "/api/estimate/parity"

# A QUESTION ABOUT ONE FINISHED ESTIMATE, FROM ITS E-MAIL (D-613). The finished-estimate
# e-mail's button opens /estimating/walkthrough/<token>, and its box asks here. It is the same
# kind of POST as /tools/ask: a question answered from a record already filed, never a run, a
# release or an e-mail. The token is the service's own, the shape estimate_walkthrough issues,
# so nothing else under /walkthrough/ is opened by this.
WALKTHROUGH_ASK = re.compile(r"/api/estimate/walkthrough/[A-Za-z0-9_-]{16,64}/ask")

# Named so a test can state what must never be on PUBLIC_POST, rather than the
# list being checked against itself.
NEVER_PUBLIC_POST = (
    "/api/estimate/release",
    "/api/estimate/release/withdraw",
    "/api/estimate/recipients",
    "/api/estimate/self-running/heartbeat",
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
# Where every run files its workbook, report and quotation - estimate_routes'
# OUTPUT_ROOT, under the same setting.
ESTIMATES_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed"
                     r"\AI Estimating\AISheets")
# Where every parity comparison is filed with both sheets and its report (D-619) -
# estimate_routes' PARITY_ROOT, under the same setting.
PARITY_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed"
                  r"\AI Estimating\parity")


def briefs_root() -> str:
    return (os.getenv("SDI_COMPLETED_AI_BRIEFS_ROOT", "") or BRIEFS_DEFAULT).strip()


def approved_roots() -> tuple:
    """The four trees that may be read from outside: the drawings waiting to be
    priced, the completed briefs, the filed estimates (30 October 2026: "we
    should be able to read all the directories with the live enquiry drawing
    packs and the estimates"), and the filed parity comparisons (D-619: "the
    parity reports that are available to be searched through in the web page and
    app"). Everything else on every share stays inside the office, whoever is
    asking."""
    return (briefs_root(),
            (os.getenv("SDI_LIVE_ENQUIRY_ROOT", "") or ENQUIRY_DEFAULT).strip(),
            (os.getenv("SDI_ESTIMATE_OUTPUT_ROOT", "") or ESTIMATES_DEFAULT).strip(),
            parity_root())


def parity_root() -> str:
    return (os.getenv("SDI_PARITY_ROOT", "") or PARITY_DEFAULT).strip()


def is_parity(path: str) -> bool:
    """A parity route: the comparisons, their search and their progress (D-621)."""
    path = str(path or "").rstrip("/")
    return path == PARITY_PREFIX or path.startswith(PARITY_PREFIX + "/")


def under_parity(asked: str) -> bool:
    """Is this path inside the parity folder?"""
    if not str(asked or "").strip():
        return False
    here = ntpath.normcase(ntpath.normpath(str(asked)))
    there = ntpath.normcase(ntpath.normpath(parity_root()))
    return here == there or here.startswith(there.rstrip("\\") + "\\")


def post_allowed(path: str) -> bool:
    """May this POST be made from outside the office?"""
    path = str(path or "").rstrip("/")
    return path in PUBLIC_POST or WALKTHROUGH_ASK.fullmatch(path) is not None


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
