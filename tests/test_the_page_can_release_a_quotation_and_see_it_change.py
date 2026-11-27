"""The release form, and the rebuild that makes it visible.

James Gray, 18 September 2026: "The remaining work is usability and presentation: the portal
release form, plus fixing material labels for bought-in."

WITHOUT THE REBUILD THE FORM APPEARS TO DO NOTHING, and that is the failure worth guarding
against rather than the form's markup. The release record is read when a quote is BUILT — so
an estimator authorises a job, and goes on looking at a page headed PORTAL VIEW with a send
button that refuses to attach it. Everything is behaving correctly and the screen says the
opposite, which is how somebody concludes the control is broken and asks for it to be removed.

So the form records the decision and then rebuilds the quotation through the ENGINE'S OWN
generator — not a reimplementation of it — and relabels the file on screen, because the list
was built from the finished run and still names the file that has just been replaced.

AND THE FIGURE IS TYPED RATHER THAN PRE-FILLED. What is being authorised is a number, so the
person authorising it states it. The record binds to what they typed, so a typo, a stale page
or a workbook amended in between produces a quotation that stays in the portal — a double
entry, at the cost of one field.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))

PAGE = (ROOT / "sdi-intelligence-backend"
        / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")

_UNIT = 149.87
_STEM = "401912-02"


def _summary(unit=_UNIT):
    return {
        "job_output_stem": _STEM,
        "estimate_summary": {
            "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": unit},
            "estimate_workbook_inputs": {"assumed_job_quantity": 20},
            "part_estimates": [{"part_number": "401912-02-001", "quantity": 1}],
        },
        "final_estimate": {
            "totals": {"unit_cell": "Estimate!M105", "unit_cell_value": unit,
                       "unit_gbp": unit, "source": "excel_calculated"},
            "material_rows": [{"description": "401912-02-001 DIVIDER",
                               "part_number": "401912-02-001", "block": "steel",
                               "qty_per_unit": 1, "total_value_gbp": 62.0,
                               "charged_cell": "Estimate!M63", "supplier": "SDI Live"}],
            "labour_rows": [],
        },
        "invariants": {"violations": [], "may_quote_firm": True},
    }


# ── the CLI the rebuild runs ────────────────────────────────────────────────────────

def test_the_command_line_writes_the_engines_own_filename(tmp_path):
    """IT DID NOT, AND THAT WAS A HOLE.

    `main()` called `build_quote_html` and wrote to `<stem>_quote.html` unconditionally, so a
    portal working copy regenerated from the command line landed on the share under the
    RELEASED document's name. Two files that differ only in what is inside them is exactly
    what `_quote_PORTAL.html` exists to prevent, and the rebuild below runs this path.
    """
    import subprocess

    jp = tmp_path / "summary.json"
    jp.write_text(json.dumps(_summary()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "src" / "client_quote_html.py"),
         "--json", str(jp), "--out-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert (tmp_path / "401912-02_quote_PORTAL.html").is_file()
    assert not (tmp_path / "401912-02_quote.html").exists()


# ── the route ───────────────────────────────────────────────────────────────────────

@pytest.fixture()
def routes(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import estimate_routes
    monkeypatch.setattr(estimate_routes.config, "FILE_ROOTS", [str(tmp_path)], raising=False)
    monkeypatch.setattr(estimate_routes, "_check_key", lambda _k: None)
    return estimate_routes


def test_releasing_then_rebuilding_turns_the_portal_copy_into_the_document(routes, tmp_path):
    """The whole loop, through the real endpoints and the real generator."""
    jp = tmp_path / "summary.json"
    jp.write_text(json.dumps(_summary()), encoding="utf-8")

    first = routes.quote_regenerate(
        routes.RegenerateQuoteRequest(json_path=str(jp), folder=str(tmp_path)), None)
    assert first["released"] is False
    assert first["path"].endswith("_quote_PORTAL.html")

    routes.release(routes.ReleaseRequest(
        folder=str(tmp_path), stem=_STEM, authorised_by="Dave Shepherd",
        unit_gbp=_UNIT, unit_cell="Estimate!M105",
        commercial_inputs={
            "margin": {"value": 0.25, "source": "SDI standard for this customer"},
            "delivery": {"value": 45.0, "source": "Tuffnells quote 18/09"}}), None)

    second = routes.quote_regenerate(
        routes.RegenerateQuoteRequest(json_path=str(jp), folder=str(tmp_path)), None)
    assert second["released"] is True
    assert second["path"].endswith("401912-02_quote.html")
    assert 'content="customer"' in Path(second["path"]).read_text(encoding="utf-8")


def test_a_release_at_the_wrong_figure_leaves_it_in_the_portal(routes, tmp_path):
    """THE DOUBLE ENTRY. A typo, a stale page, or a workbook somebody amended in between."""
    jp = tmp_path / "summary.json"
    jp.write_text(json.dumps(_summary()), encoding="utf-8")
    routes.release(routes.ReleaseRequest(
        folder=str(tmp_path), stem=_STEM, authorised_by="Dave Shepherd",
        unit_gbp=148.97), None)          # digits transposed
    out = routes.quote_regenerate(
        routes.RegenerateQuoteRequest(json_path=str(jp), folder=str(tmp_path)), None)
    assert out["released"] is False
    assert out["path"].endswith("_quote_PORTAL.html")


def test_withdrawing_puts_it_back(routes, tmp_path):
    jp = tmp_path / "summary.json"
    jp.write_text(json.dumps(_summary()), encoding="utf-8")
    routes.release(routes.ReleaseRequest(
        folder=str(tmp_path), stem=_STEM, authorised_by="Dave Shepherd",
        unit_gbp=_UNIT), None)
    assert routes.quote_regenerate(
        routes.RegenerateQuoteRequest(json_path=str(jp), folder=str(tmp_path)),
        None)["released"] is True

    routes.release_withdraw(
        routes.ReleaseRequest(folder=str(tmp_path), stem=_STEM), None)
    assert routes.quote_regenerate(
        routes.RegenerateQuoteRequest(json_path=str(jp), folder=str(tmp_path)),
        None)["released"] is False


def test_the_rebuild_refuses_a_summary_outside_the_shares(routes, tmp_path):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        routes.quote_regenerate(
            routes.RegenerateQuoteRequest(json_path="/etc/passwd"), None)
    assert caught.value.status_code == 403


# ── the form ────────────────────────────────────────────────────────────────────────

def test_the_form_asks_for_a_name_and_the_figure_being_approved():
    assert 'id="relBy"' in PAGE and 'id="relUnit"' in PAGE and 'id="relInputs"' in PAGE
    assert "/api/estimate/release" in PAGE
    assert "/api/estimate/quote/regenerate" in PAGE


def test_the_form_derives_the_job_from_the_quotes_own_path():
    """Not from the job number. The runner's own `collect` records why: the quote is named
    from the job STEM and the workbook from the job NUMBER, so one matcher against two
    conventions files the wrong thing."""
    assert "_jobFromQuotePath" in PAGE
    assert "_quote(_[A-Za-z-]+)?" in PAGE, "the portal and LLM-only names must both match"


def test_the_tick_no_longer_decides_whether_a_quotation_may_be_sent():
    """It used to be the only thing standing between an unreleased quote and a customer. It
    now chooses WHICH files; the route reads the document's own declaration."""
    at = PAGE.index("box.checked =")
    assert "THE TICK CHOOSES WHICH FILES" in PAGE[at - 600:at]
    assert "Tick it only when the estimate is ready to leave the building." not in PAGE


def test_the_list_on_screen_is_relabelled_after_a_rebuild():
    """The deliverable list was built from the finished run and names the file that has just
    been replaced — leaving it has somebody tick a path that no longer exists, or the portal
    copy under its old name."""
    assert "refreshDeliverableList" in PAGE


def test_the_commercial_inputs_parser_keeps_an_unanswered_heading():
    """"delivery" with no figure is a real state — an input the estimator still owes — and the
    engine lists it as outstanding. Dropping it would silently release the job."""
    block = PAGE[PAGE.index("function _parseCommercialInputs"):]
    block = block[:block.index("\nfunction ")]
    assert "{value: null, source: \"\"}" in block
    assert re.search(r"split\(/\[\\n;\]\+/\)", block)


def test_the_commercial_inputs_parser_captures_where_the_figure_came_from():
    """`margin = 0.25 @ SDI Live`. The source is not decoration: these are the only figures on
    the estimate with no drawing to check them against."""
    block = PAGE[PAGE.index("function _parseCommercialInputs"):]
    block = block[:block.index("\nfunction ")]
    assert 'rest.indexOf("@")' in block
    assert "source: source" in block
