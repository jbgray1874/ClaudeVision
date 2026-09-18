"""Whether a quotation on the share may go to a customer — read from the document itself.

James Gray, 18 September 2026:

    "Print CSS and `_PORTAL` filenames deter misuse but are not the actual security boundary;
     download/share/export routes must enforce `customer_releasable`."

THE FILENAME IS A LABEL AND A LABEL IS NOT A GATE. `..._quote_PORTAL.html` stops somebody
picking the wrong file out of a folder listing, which is a real failure and worth preventing,
and it stops nothing at all once a path is in a request. The print stylesheet is the same kind
of thing: it makes the easy wrong move harder and it is one Ctrl+P dialog away from being
irrelevant. Both are worth keeping and neither is the boundary.

THE BOUNDARY IS HERE, ON THE ROUTES THAT HAND THE FILE OVER, and there are three:

    POST /estimate/{run_id}/email      the automatic send when a run finishes
    POST /estimate/{run_id}/email      the same route with an explicit file list from the page
    GET  /api/file                     download, view, share — anything with the path

The second of those was open. Its code read:

    if chosen:
        # An explicit choice is a decision, quote included.
        paths, held = chosen, []

— so a tick-box on the page sent the quotation past the only gate there was, and the gate it
went past (`_looks_provisional`) is a keyword scan of the run's console that returns True
unconditionally. Nothing has leaked, because that hard True holds everything; the moment it
became honest there would have been no check left.

AND THIS SERVICE STILL DOES NOT READ AN ESTIMATE. It has no engine, no summary and no costed
record, and giving it one would put a second opinion about the same question on the other side
of a network boundary — the two-names fault with a firewall through the middle. Instead the
quotation declares its own audience in its head, written by `quote_state.release_meta_tag` at
the moment the engine decided it, and this reads the file it is about to hand over.

The check is therefore on the ARTEFACT, not on a record that refers to it. A record can be
stale, can describe a different run, or can be missing, and every one of those failure modes
ends in release. A file cannot disagree with itself.

FAIL CLOSED, INCLUDING ON A FILE WITH NO DECLARATION. A quotation written before this existed,
or one somebody assembled by hand, carries no meta tag — and "no verdict" is not "yes". The
cost of holding one back is an email asking for it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

# Must match `src/quote_state.py`. Restated rather than imported: this service runs from its
# own checkout and importing the engine to read one meta tag would drag the whole estimator in.
# `test_a_quote_declares_its_audience_to_the_routes_that_deliver_it` renders a real quotation
# with the engine and parses it with this module, so the two cannot drift.
RELEASE_META = "sdi-quote-release"
CUSTOMER = "customer"
PORTAL = "portal"

# Enough to reach the head of any document this engine writes. A quotation's <head> is inside
# the first kilobyte; reading 64 KB costs nothing and survives somebody adding a font block.
_HEAD_BYTES = 64 * 1024

_META = re.compile(
    r"""<meta[^>]*\bname\s*=\s*["']?""" + RELEASE_META + r"""["']?[^>]*>""",
    re.IGNORECASE)
_CONTENT = re.compile(r"""\bcontent\s*=\s*["']([^"']*)["']""", re.IGNORECASE)

# What a quotation is called, in every form this engine writes: the released document, the
# portal working copy, and a measurement run's marked file.
_QUOTE_NAME = re.compile(r"_quote(_[A-Za-z-]+)?\.html?$", re.IGNORECASE)


def looks_like_a_quote(path: Any) -> bool:
    """Whether this path is one of our quotation documents at all.

    Deliberately by NAME, which is the opposite of how the release verdict is read. A name is
    a fine way to decide which files to inspect — the worst it can do is inspect one file too
    many — and a hopeless way to decide whether one may be sent.
    """
    return bool(_QUOTE_NAME.search(Path(str(path or "")).name))


def declared_audience(path: Any) -> Optional[str]:
    """`customer`, `portal`, or None when the file declares nothing (or cannot be read)."""
    try:
        with open(str(path), "rb") as fh:
            head = fh.read(_HEAD_BYTES).decode("utf-8", "replace")
    except OSError:
        return None
    found = _META.search(head)
    if not found:
        return None
    content = _CONTENT.search(found.group(0))
    value = (content.group(1) if content else "").strip().lower()
    return value if value in (CUSTOMER, PORTAL) else None


def may_go_to_a_customer(path: Any) -> bool:
    """The gate. Only a quotation that declares itself released may leave the building.

    Anything that is not a quotation is not this module's business and passes — the workbook,
    the report and the covering note are internal documents with their own rules, and holding
    them back would be the D-144 fault in a new place.
    """
    if not looks_like_a_quote(path):
        return True
    return declared_audience(path) == CUSTOMER


def why_held(path: Any) -> str:
    """The sentence a person reads when a file was held back."""
    declared = declared_audience(path)
    if declared == PORTAL:
        return ("this is the portal working copy — the estimator has not completed the "
                "commercial inputs and authorised release")
    if declared is None:
        return ("this quotation does not declare that it was released for customer issue, "
                "so it is held")
    return "this quotation is not released for customer issue"
