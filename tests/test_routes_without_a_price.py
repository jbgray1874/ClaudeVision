"""The route decisions for a pack nobody costed — and the proof they are not a lesser answer.

THE ASK. Estimating want the BOM and the route out of a pack WITHOUT running an estimate, because
most of the time the question is "what is in this and what work does it need", not "what does it
cost". The obvious worry about answering that without costing is that you get an approximation.

YOU DO NOT, AND THIS FILE IS THE EVIDENCE. compile_job_route takes parts, BOM rows, drawing
numbers and page owners, and NO PRICES. On a costed job, project_priced_route runs after it and
drops every non-required decision from `priced_route_rows` — but it copies `decisions` through
untouched. So the decision list a costed run publishes and the decision list here are the same
list, from the same compiler, on the same evidence.

What is genuinely missing is only ever about money, and it is NAMED rather than left as an empty
key: priced_route_rows, and the two issue codes that compare a decision against a legacy cost.

The other thing worth writing down, because it was the assumption going in and it was wrong: this
is NOT the fast path. The 7332-01 timing table puts the cost in the readers — extract_pdf_summary
141s, invariants 80s, augment_with_dxf 70s — against write_outputs and deliverables at under two
seconds each. Skipping the costing saves very little time. What it buys is an answer on a pack
that has never been estimated, with no price source, no Excel and no workbook.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bom_and_route_extract as bre                                      # noqa: E402
import route_compiler as rc                                             # noqa: E402


def _leg() -> dict:
    """7332-01's tube leg, as the READERS leave it — stock_form and textual_operations both
    come off the drawing and the DXF, not out of the costing."""
    return {"part_number": "7332-01-002", "description": "LEG - 12.7 x 1.2 CHS TUBE",
            "normalized_material": "MILD STEEL", "quantity": 2, "stock_form": "tube",
            "section_stock": {"a": 12.7, "b": 12.7, "t": 1.2, "profile_form": "CHS",
                              "length_mm": 1400.0},
            "textual_operations": ["folding", "tubebend"]}


def _summary() -> dict:
    return {
        "job_number": "7332-01",
        "manufacturing_writeup": {"parts": [_leg()]},
        "document_analysis": {"bom_rows": [
            {"part_number": "7332-01-002", "description": "LEG", "quantity": 2,
             "material_text": "MS CHS 12.7x1.2", "source": "bom_table", "source_page": 3}]},
    }


# ── it compiles at all, with nothing priced ───────────────────────────────────────────


def test_the_compiler_needs_no_prices():
    """The whole feature rests on this. compile_job_route's signature takes no costs, and the
    decisions it returns are reached from stock form and the operations stated on the drawing."""
    import inspect
    params = list(inspect.signature(rc.compile_job_route).parameters)
    for money in ("prices", "costs", "part_estimates", "rates"):
        assert money not in params, f"compile_job_route takes {money}"


def test_it_does_not_need_the_costing_pass_to_have_run_first():
    """estimate_part classifies AND prices. The compiler needs the classification — stock_form
    and textual_operations — and those come from the readers, so a pack that was never costed
    still compiles. Proven by never calling estimate_part."""
    decisions = rc.compile_job_route([_leg()], {})["decisions"]
    by_op = {}
    for d in decisions:
        by_op.setdefault(d["operation"], []).append(d)
    assert "tubebend" in by_op and "folding" in by_op
    assert all(d["status"] == "required" for d in by_op["tubebend"])
    assert by_op["folding"][0]["status"] == "not_applicable"
    assert "tube" in str(by_op["folding"][0].get("reason") or "").lower()


def test_the_payload_says_it_was_not_costed():
    payload = rc.compile_route_without_pricing(_summary())
    assert payload["mode"] == "uncosted"
    assert payload["mode"] != "shadow", (
        "'shadow' means compiled BESIDE the legacy costs for comparison — there is nothing "
        "here to compare against, and borrowing the word would claim there was")


def test_what_is_absent_is_named_rather_than_empty():
    """An absent key reads as "none found". An empty list with a reason reads as what it is."""
    payload = rc.compile_route_without_pricing(_summary())
    assert payload["priced_route_rows"] == []
    assert "nothing was priced" in payload["not_computed"]["priced_route_rows"]
    assert "legacy_cost_checks" in payload["not_computed"]


def test_it_publishes_where_every_reader_already_looks():
    """canonical_route_shadow under estimate_summary — the same place a costed run writes it,
    so every consumer works unchanged. Writing it somewhere new would mean the extract, the
    audit and the report each needing to know which kind of run produced the record."""
    summary = _summary()
    rc.compile_route_without_pricing(summary)
    assert summary["estimate_summary"]["canonical_route_shadow"]["mode"] == "uncosted"
    assert len(bre.route_payloads(summary)) == 1


# ── and the extract reads it correctly ────────────────────────────────────────────────


def test_the_extract_calls_it_a_pack_read_and_never_says_charged():
    summary = _summary()
    rc.compile_route_without_pricing(summary)
    declared = bre.source_declaration(summary)
    assert declared["source"] == "pack_read"
    assert declared["charged_is_meaningful"] is False
    rows = bre.route_sheet(summary)
    assert rows, "the pack states operations and the sheet must show them"
    for row in rows:
        assert "charged" not in row


def test_a_ruled_out_operation_still_appears_with_its_reason():
    """THE POINT OF THE SHEET. "folding: not possible on stock form tube" is the answer to a
    question an estimator would otherwise have to ask, and dropping non-required decisions
    would leave the sheet looking like the compiler never considered it."""
    summary = _summary()
    rc.compile_route_without_pricing(summary)
    folding = [r for r in bre.route_sheet(summary) if r["operation"] == "folding"]
    assert folding, "a ruled-out decision is still a decision"
    assert folding[0]["required by the route"] == "no"
    assert "not physically possible" in folding[0]["why"]


def test_the_bom_comes_through_the_same_extract():
    summary = _summary()
    rc.compile_route_without_pricing(summary)
    rows = bre.bom_sheet(summary)
    assert len(rows) == 1
    assert rows[0]["part_number"] == "7332-01-002"
    assert rows[0]["read_by"] == "bom_table"


def test_an_empty_pack_compiles_to_nothing_rather_than_raising():
    """It is reached from a button on the estimating page."""
    payload = rc.compile_route_without_pricing({"job_number": "x"})
    assert payload["counts"]["decisions"] == 0
    assert payload["mode"] == "uncosted"


# ── the finding this turned up, recorded rather than quietly fixed ────────────────────


def test_one_operation_on_one_part_is_one_row():
    """WAS AN xfail, NOW THE RULE. The compiler emits a decision per piece of EVIDENCE, so
    7332-01-002's tube bend arrived twice — once for "the drawing states a bend and the stock
    form is tube" and once for "textual_operations on existing part record". One bend,
    corroborated twice, printed as two rows; and on a sheet an estimator reads, two rows means
    two setups. Not specific to the uncosted path — the same compiler feeds a costed run, which
    is how 27 decisions against 12 labour rows became an argument."""
    summary = _summary()
    rc.compile_route_without_pricing(summary)
    rows = bre.route_sheet(summary)
    bends = [r for r in rows
             if r["operation"] == "tubebend" and r["part_or_assembly"] == "7332-01-002"]
    assert len(bends) == 1, f"{len(bends)} rows for one bend on one part"
