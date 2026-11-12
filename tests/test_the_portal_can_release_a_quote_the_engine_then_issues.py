"""The gate gets a key, and the key stops fitting when the price moves.

James Gray, 18 September 2026:

    "The portal must write the commercial-input completion and named release authorisation.
     Until then every quote correctly stays portal-only."

D-145 built the release model and nothing could open it. `commercial_inputs.complete` and
`quote_release.authorised_by` were read from the summary; nothing anywhere wrote either. Every
estimate produced a portal copy — correct, and permanently correct, which is a gate with no
key and eventually a gate somebody removes.

WHERE THE RECORD LIVES AND WHY NOT IN THE SUMMARY. The summary is a run artefact the engine
rewrites whole on every estimate, so an authorisation written into it is destroyed by the next
run of the same job. A person's decision is the opposite kind of fact: made once, outliving
the run it was made about. It sits beside the deliverables and is merged in when a quote is
built.

TWO HALVES THAT ARE NOT ON THE SAME MACHINE. The service holds the recipients, the SMTP
settings and the shares; the engine runs wherever a runner claimed the job — that separation
is the whole reason the runner exists. So the writer is in the service, the reader is in the
engine, the shape is the joint, and THIS FILE writes with one and reads with the other.

AND THE SIGNATURE IS BOUND TO WHAT IT SIGNED. Dave authorises 401912-02 at £149.87. A drawing
is revised, the job is re-estimated, the unit cost comes back £212.40 — and a record that says
only "Dave authorised this job" releases the new figure on the old signature. Nobody did
anything careless and a price goes out that nobody approved. So the figure is recorded, and a
job whose price has moved goes back to the portal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))

import quote_release as portal_side                                     # noqa: E402
from client_quote_html import generate_quote_files                      # noqa: E402
from quote_state import quote_state                                     # noqa: E402
from release_record import (apply_to_summary,                           # noqa: E402
                            read_release_record)

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


def _release(folder, unit=_UNIT, who="Dave Shepherd"):
    """The portal's half — the service writes this, on the machine that holds the share."""
    return portal_side.write_release_record(
        folder, _STEM, authorised_by=who, unit_gbp=unit, unit_cell="Estimate!M105",
        commercial_inputs={
            # EACH FIGURE NAMES WHERE IT CAME FROM. These are the only numbers on the estimate
            # with no drawing to check them against, which makes the reference the only
            # evidence there will ever be — so a value with no source does not complete.
            "margin": {"value": 0.25, "source": "SDI standard for this customer"},
            "delivery": {"value": 45.0, "source": "Tuffnells quote 18/09"},
            "packaging": {"value": 12.0, "source": "SDI Live"}})


# ── the joint: written by the service, read by the engine ───────────────────────────

def test_the_two_halves_write_and_read_the_same_record(tmp_path):
    written = _release(tmp_path)
    read = read_release_record(tmp_path, _STEM)
    assert read == written
    assert read["schema"] == "quote_release_record.v1"
    assert portal_side.RECORD_SCHEMA == read["schema"], "the two halves have drifted"


def test_the_record_sits_beside_the_deliverables_not_in_the_summary(tmp_path):
    """A re-run rewrites the summary whole. If the authorisation lived there it would be
    destroyed by the next estimate of the same job."""
    _release(tmp_path)
    assert (tmp_path / "401912-02_release.json").is_file()
    assert "quote_release" not in _summary()


# ── before and after ────────────────────────────────────────────────────────────────

def test_without_the_record_the_job_stays_in_the_portal(tmp_path):
    state = quote_state(apply_to_summary(_summary(), tmp_path, _STEM))
    assert state["customer_releasable"] is False
    assert {"commercial_inputs", "authorisation"} <= {b["gate"] for b in state["blocking"]}


def test_with_the_record_the_same_job_is_releasable(tmp_path):
    """THE KEY TURNING. Nothing about the estimate changed — only that a named person
    completed the inputs and released it."""
    _release(tmp_path)
    state = quote_state(apply_to_summary(_summary(), tmp_path, _STEM))
    assert state["customer_releasable"] is True, state["blocking"]
    assert state["authorisation"]["by"] == "Dave Shepherd"


def test_the_generated_quote_becomes_the_customer_document(tmp_path):
    """End to end, through the file the engine actually writes."""
    jp = tmp_path / "summary.json"
    jp.write_text(json.dumps(_summary()), encoding="utf-8")

    before = Path(generate_quote_files(str(jp), out_dir=str(tmp_path), job_stem=_STEM))
    assert before.name == "401912-02_quote_PORTAL.html"
    # ── AND IT IS A FULLY PRICED PAGE, NOT A LIST OF GAPS ───────────────────────
    #
    # This job's estimate is complete — a traceable workbook total, every line priced. What
    # is outstanding is a PERSON's sign-off, so the working copy shows the estimator the
    # price as normal and carries no warning at all. The control is that the file is not
    # named, served or attached as the customer's document.
    _body = before.read_text(encoding="utf-8")
    assert "£" in _body, "a priced estimate must show its price to the estimator"
    for gone in ("PORTAL VIEW", "NOT FOR ISSUE", "do not issue", "not released"):
        assert gone.lower() not in _body.lower(), gone

    _release(tmp_path)
    after = Path(generate_quote_files(str(jp), out_dir=str(tmp_path), job_stem=_STEM))
    assert after.name == "401912-02_quote.html"
    body = after.read_text(encoding="utf-8")
    assert "£" in body, "the released document carries its price"
    assert 'content="customer"' in body, "the delivery routes read this declaration"


# ── and the signature covers what it signed ─────────────────────────────────────────

def test_a_reestimate_at_the_same_price_stays_released(tmp_path):
    """Re-running a job nobody changed must not cost the estimator their signature."""
    _release(tmp_path)
    assert quote_state(apply_to_summary(_summary(), tmp_path, _STEM))["customer_releasable"]


def test_a_reestimate_at_a_different_price_goes_back_to_the_portal(tmp_path):
    """THE STALE-SIGNATURE HAZARD. Nobody was careless and a price nobody approved goes out."""
    _release(tmp_path, unit=_UNIT)
    state = quote_state(apply_to_summary(_summary(unit=212.40), tmp_path, _STEM))
    assert state["customer_releasable"] is False
    said = [b["what"] for b in state["blocking"] if b["gate"] == "authorisation"]
    assert said and "149.87" in said[0] and "212.40" in said[0], said
    assert "Dave Shepherd" in said[0], "the estimator who signed it is named"


def test_a_rounding_difference_is_not_a_price_change(tmp_path):
    """Half a penny is two reads of one figure, not a change anybody made — the same
    tolerance `publishable_total` uses against the workbook cell."""
    _release(tmp_path, unit=_UNIT)
    assert quote_state(apply_to_summary(_summary(unit=_UNIT + 0.004),
                                        tmp_path, _STEM))["customer_releasable"]


def test_an_authorisation_needs_a_name(tmp_path):
    with pytest.raises(ValueError):
        portal_side.write_release_record(tmp_path, _STEM, authorised_by="  ", unit_gbp=_UNIT)


def test_an_authorisation_needs_the_figure_it_authorises(tmp_path):
    """Without it the record is the stale-signature hazard, permanently."""
    with pytest.raises(ValueError):
        portal_side.write_release_record(tmp_path, _STEM, authorised_by="Dave",
                                         unit_gbp=None)


def test_withdrawing_it_returns_the_job_to_the_portal(tmp_path):
    _release(tmp_path)
    assert portal_side.clear_release_record(tmp_path, _STEM) is True
    assert quote_state(apply_to_summary(_summary(), tmp_path, _STEM))[
        "customer_releasable"] is False


# ── and it fails closed, quietly ────────────────────────────────────────────────────

def test_a_corrupt_record_costs_the_run_nothing(tmp_path):
    """The estimate is still wanted. It simply comes out as the portal copy, which is where
    it would have been with no record at all."""
    (tmp_path / "401912-02_release.json").write_text("{not json", encoding="utf-8")
    assert read_release_record(tmp_path, _STEM) == {}
    state = quote_state(apply_to_summary(_summary(), tmp_path, _STEM))
    assert state["customer_releasable"] is False


def test_a_decision_already_on_the_summary_is_not_overwritten(tmp_path):
    """An estimator working in the current run wins over a file from an earlier one."""
    _release(tmp_path, who="Dave Shepherd")
    summary = _summary()
    summary["quote_release"] = {"authorised_by": "Tony Ford", "authorised_at": "2026-09-18"}
    apply_to_summary(summary, tmp_path, _STEM)
    assert summary["quote_release"]["authorised_by"] == "Tony Ford"


# ── the endpoint ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def routes(tmp_path, monkeypatch):
    """The service's routes, with `tmp_path` as the only share it may write to.

    THE SHARE IS PATCHED ON THE MODULE THE ROUTE ACTUALLY HOLDS, not on whatever `import
    config` resolves to here. Both halves of this system have a module called `config` and
    both are on the path in this suite — in production the service runs alone and the question
    does not arise, but a test that patches the wrong one passes alone and fails beside its
    neighbours, which is how an afternoon goes.
    """
    pytest.importorskip("fastapi")
    import estimate_routes
    monkeypatch.setattr(estimate_routes.config, "FILE_ROOTS", [str(tmp_path)],
                        raising=False)
    monkeypatch.setattr(estimate_routes, "_check_key", lambda _k: None)
    return estimate_routes


def test_the_release_endpoint_refuses_a_folder_outside_the_shares(routes):
    """It writes to disk from a path in a request, so this is the same containment rule every
    other route on this service follows."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        routes.release(routes.ReleaseRequest(folder="/etc", stem=_STEM,
                                             authorised_by="Dave", unit_gbp=_UNIT), None)
    assert caught.value.status_code == 403


def test_the_endpoint_will_not_record_an_unsigned_or_unpriced_release(tmp_path, routes):
    from fastapi import HTTPException
    estimate_routes = routes

    for bad in ({"authorised_by": "", "unit_gbp": _UNIT},
                {"authorised_by": "Dave", "unit_gbp": None}):
        with pytest.raises(HTTPException) as caught:
            estimate_routes.release(
                estimate_routes.ReleaseRequest(folder=str(tmp_path), stem=_STEM, **bad), None)
        assert caught.value.status_code == 400

    out = estimate_routes.release(
        estimate_routes.ReleaseRequest(folder=str(tmp_path), stem=_STEM,
                                       authorised_by="Dave Shepherd", unit_gbp=_UNIT), None)
    assert out["ok"] is True
    assert read_release_record(tmp_path, _STEM)["quote_release"]["authorised_by"] == \
        "Dave Shepherd"


# ── and a figure with nothing behind it is not a completed input ────────────────────

def test_a_commercial_input_with_no_source_does_not_release_it(tmp_path):
    """James Gray, 18 Sep 2026: "commercial inputs should ultimately record a
    source/reference alongside the value... so a completed input remains traceable to SDI
    Live, a supplier quote, or evidenced research."

    THE PRICING WATERFALL REACHING THE LAST FIELDS THAT ESCAPED IT. Every other number on the
    estimate names where it came from. These were the one place a figure could be typed and
    released with nothing behind it.
    """
    portal_side.write_release_record(
        tmp_path, _STEM, authorised_by="Dave Shepherd", unit_gbp=_UNIT,
        commercial_inputs={"delivery": 45.0})          # a figure, and nothing behind it
    state = quote_state(apply_to_summary(_summary(), tmp_path, _STEM))
    assert state["customer_releasable"] is False
    said = [b["what"] for b in state["blocking"] if b["gate"] == "commercial_inputs"]
    assert said and "delivery" in said[0] and "no source" in said[0], said
    assert state["commercial_inputs"]["unsourced"] == ["delivery"]


def test_an_input_with_no_figure_says_something_different(tmp_path):
    """"Still open" sends somebody looking for a figure that is already there. The two states
    are different jobs and the sentence says which."""
    portal_side.write_release_record(
        tmp_path, _STEM, authorised_by="Dave Shepherd", unit_gbp=_UNIT,
        commercial_inputs={"delivery": {"value": None, "source": ""}})
    state = quote_state(apply_to_summary(_summary(), tmp_path, _STEM))
    said = [b["what"] for b in state["blocking"] if b["gate"] == "commercial_inputs"]
    assert said and "still open" in said[0]


def test_a_sourced_figure_completes(tmp_path):
    """The control."""
    portal_side.write_release_record(
        tmp_path, _STEM, authorised_by="Dave Shepherd", unit_gbp=_UNIT,
        commercial_inputs={"delivery": {"value": 45.0, "source": "Tuffnells quote 18/09"}})
    assert quote_state(apply_to_summary(_summary(), tmp_path, _STEM))["customer_releasable"]
