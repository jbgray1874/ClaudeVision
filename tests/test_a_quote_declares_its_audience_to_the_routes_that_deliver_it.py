"""The document says whether it may be sent, and every delivery route asks it.

James Gray, 18 September 2026:

    "Audit every customer delivery route—not only `main.py` email attachments. Print CSS and
     `_PORTAL` filenames deter misuse but are not the actual security boundary;
     download/share/export routes must enforce `customer_releasable`."

WHAT THE AUDIT FOUND. Three routes hand a file to somebody outside the engine, and the one
that actually sent quotations was open:

    main.py's attachment list           gated on `quote_state` (D-145)
    POST /estimate/{run_id}/email       gated by `choose_attachments`, WHICH THE EXPLICIT
      with no file list                 `include_quote` flag could override
    POST /estimate/{run_id}/email       NOT GATED AT ALL. "An explicit choice is a decision,
      with a file list from the page    quote included." A tick-box sent it.
    GET /api/file                       NOT GATED AT ALL. Takes a path, returns the file.

Nothing has leaked, and only because `_looks_provisional` is a keyword scan of the run's
console that ends in an unconditional `return True` — it holds every quote on every run. The
moment somebody made that honest, the second route had no check behind it.

WHY THE VERDICT TRAVELS IN THE DOCUMENT. The service has never read an estimate and should not
start: it has no engine, no summary and no costed record. Giving it one would put a second
opinion about the same question on the far side of a network boundary — the two-names fault,
with a firewall through the middle. So the quotation declares its audience in its head at the
moment the engine decides it, and the routes read the file they are about to hand over. A
record that refers to a file can be stale, can describe another run, or can be missing, and
every one of those ends in release. A file cannot disagree with itself.

THIS FILE IS THE JOINT. The engine writes the declaration and the service parses it, from two
checkouts that never import each other, so the wording is restated in both — which is exactly
how a fact acquires two names. Here a real quotation is rendered by `client_quote_html` and
read by `quote_release`, so the two halves cannot drift apart without this failing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))

import quote_release                                                    # noqa: E402
from client_quote_html import build_quote_html                          # noqa: E402
from quote_state import CUSTOMER, RELEASE_META, quote_state             # noqa: E402

_UNIT = 149.87


def _released():
    return {
        "job_output_stem": "401912-02",
        "estimate_summary": {
            "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": _UNIT},
            "estimate_workbook_inputs": {"assumed_job_quantity": 20},
            "part_estimates": [{"part_number": "401912-02-001", "quantity": 1}],
        },
        "final_estimate": {
            "totals": {"unit_cell": "Estimate!M105", "unit_cell_value": _UNIT,
                       "unit_gbp": _UNIT, "source": "excel_calculated"},
            "material_rows": [{"description": "401912-02-001 DIVIDER",
                               "part_number": "401912-02-001", "block": "steel",
                               "qty_per_unit": 1, "total_value_gbp": 62.0,
                               "charged_cell": "Estimate!M63", "supplier": "SDI Live"}],
            "labour_rows": [],
        },
        "invariants": {"violations": [], "may_quote_firm": True},
        "commercial_inputs": {"complete": True},
        "quote_release": {"authorised_by": "Dave Shepherd",
                          "authorised_at": "2026-09-18T15:40"},
    }


def _write(record, tmp_path, name="401912-02_quote.html", audience=None):
    html = build_quote_html(record, job_stem="401912-02", audience=audience)
    p = tmp_path / name
    p.write_text(html, encoding="utf-8")
    return str(p)


# ── the joint: what the engine writes is what the service reads ─────────────────────

def test_the_two_halves_use_the_same_word():
    """Restated in two checkouts that never import each other. This is the only thing
    stopping them drifting."""
    assert quote_release.RELEASE_META == RELEASE_META
    assert quote_release.CUSTOMER == CUSTOMER


def test_a_released_quotation_declares_itself_released(tmp_path):
    path = _write(_released(), tmp_path)
    assert quote_release.declared_audience(path) == "customer"
    assert quote_release.may_go_to_a_customer(path) is True


def test_an_unreleased_quotation_declares_itself_portal(tmp_path):
    path = _write({}, tmp_path, name="401912-02_quote_PORTAL.html")
    assert quote_release.declared_audience(path) == "portal"
    assert quote_release.may_go_to_a_customer(path) is False
    assert "commercial inputs" in quote_release.why_held(path)


def test_a_quotation_with_no_declaration_is_held(tmp_path):
    """Fail closed. One written before this existed, or assembled by hand, says nothing —
    and no verdict is not yes."""
    p = tmp_path / "10575-02_quote.html"
    p.write_text("<html><head><title>Quotation</title></head><body>£149.87</body></html>",
                 encoding="utf-8")
    assert quote_release.declared_audience(str(p)) is None
    assert quote_release.may_go_to_a_customer(str(p)) is False


def test_a_file_that_is_not_a_quotation_is_not_this_modules_business(tmp_path):
    """Holding the workbook or the report back would be the D-144 fault in a new place:
    internal documents go to estimators whatever the quote's state."""
    for name in ("401912-02.xlsx", "401912-02_report.html",
                 "401912-02_covering_email.html"):
        p = tmp_path / name
        p.write_text("x", encoding="utf-8")
        assert quote_release.may_go_to_a_customer(str(p)) is True, name


def test_the_name_decides_what_to_inspect_and_never_what_to_send(tmp_path):
    """A name is a fine way to pick which files to look at — the worst it can do is look at
    one too many — and a hopeless way to decide whether one may go out. So a file NAMED like
    the released document is still held when its head says portal."""
    path = _write({}, tmp_path, name="401912-02_quote.html")
    assert quote_release.looks_like_a_quote(path) is True
    assert quote_release.may_go_to_a_customer(path) is False


# ── the routes ──────────────────────────────────────────────────────────────────────

def test_the_attachment_chooser_holds_an_unreleased_quote_even_when_asked(tmp_path):
    """`include_quote` is a REQUEST. Release is a PERMISSION. The gate goes first."""
    import estimate_email
    held_path = _write({}, tmp_path, name="401912-02_quote_PORTAL.html")
    keep, held = estimate_email.choose_attachments(
        [{"path": held_path}], provisional=False, include_quote=True)
    assert keep == []
    assert held and held[0]["path"] == held_path


def test_the_attachment_chooser_sends_a_released_quote_when_asked(tmp_path):
    """The control — a gate that refuses everything is not a gate."""
    import estimate_email
    ok_path = _write(_released(), tmp_path)
    keep, held = estimate_email.choose_attachments(
        [{"path": ok_path}], provisional=False, include_quote=True)
    assert keep == [ok_path], held


def test_the_send_route_filters_an_explicit_file_list():
    """THE HOLE THIS AUDIT WAS FOR.

    It read "An explicit choice is a decision, quote included" and sent the list untouched.
    Checked on the route's source because the send itself needs SMTP, a live run and a
    recipient — but on the one line that decides, and the behaviour underneath it is proved
    by the two tests above, which run.
    """
    src = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(
        encoding="utf-8")
    at = src.index("    if chosen:")
    window = src[at:at + 1400]
    assert "quote_release.may_go_to_a_customer" in window, (
        "an explicit file list still bypasses the release gate")
    assert "paths, held = chosen, []" not in window


def test_the_file_route_will_not_hand_an_unreleased_quote_over_as_a_download():
    """`GET /api/file` takes a path and returns a file, so a quotation is just another path.

    The estimator keeps their page — refusing outright would break `portal_editable`, which is
    a promise — so it is still served and still renders. What it may not do is arrive as a
    saved document.
    """
    src = (ROOT / "sdi-intelligence-backend" / "app.py").read_text(encoding="utf-8")
    at = src.index("def get_file(")
    window = src[at:at + 3000]
    assert "quote_release.may_go_to_a_customer" in window
    assert "X-SDI-Quote-Held" in window
    # And the estimator still gets the page: the gate forces inline, it does not 403.
    assert "inline = True" in window
    assert "HTTPException(status_code=403" not in window.split("looks_like_a_quote")[1][:400]


def test_every_route_that_delivers_a_file_is_covered():
    """THE AUDIT ITSELF, kept as a test so a new route has to be added here deliberately.

    A file leaves this system three ways. If a fourth appears and nobody thinks about release,
    this is where it should be noticed — the check is crude on purpose: any NEW handler that
    returns a FileResponse or attaches paths has to be looked at by a person.
    """
    app_src = (ROOT / "sdi-intelligence-backend" / "app.py").read_text(encoding="utf-8")
    routes_src = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(
        encoding="utf-8")
    known_file_responses = {
        "app.py": app_src.count("FileResponse("),
        "estimate_routes.py": routes_src.count("FileResponse("),
    }
    # app.py: /api/file (gated), plus the four static pages — the portal, the estimating
    # page, the guide and the brand logo, none of which is a deliverable.
    assert known_file_responses["app.py"] == 5, (
        f"a new file-serving route appeared in app.py ({known_file_responses['app.py']} "
        f"FileResponse calls, was 5) — does it need the release gate?")
    # estimate_routes.py: the drawings-print PDF, which is a drawing pack and not a quotation.
    assert known_file_responses["estimate_routes.py"] == 1, (
        f"a new file-serving route appeared in estimate_routes.py — does it need the gate?")


def test_the_engine_side_still_agrees_with_the_document(tmp_path):
    """The declaration is not a second opinion: it is the same fact, written down. If
    `quote_state` and the meta tag could ever disagree, the routes would be enforcing
    something nothing else believes."""
    for record, expected in ((_released(), True), ({}, False)):
        path = _write(record, tmp_path, name=f"j{expected}_quote.html")
        assert quote_state(record)["customer_releasable"] is expected
        assert quote_release.may_go_to_a_customer(path) is expected
