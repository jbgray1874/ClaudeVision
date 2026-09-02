r"""
test_parity_measures_the_estimate_not_its_own_parser.py

THE HARNESS THAT RAN ONCE, IN JULY, AND PRODUCED ONE LEDGER ROW.

Read again in September, it was measuring the wrong things in five ways at once:

  * it read `part_estimates` — the engine's blank-area arithmetic from BEFORE the workbook
    exists — against a manual sheet's nest-derived CELLS. On 12552 those two records of one
    fact are £49.76 and £136.32, and the £86.56 between them would have been reported as a
    lane gap;
  * it enumerated the Bill of Materials and stopped at the first "Wire"/"Sheet Steel" header,
    so four of five blocks and every labour row were compared as grand totals with no line to
    point at — and on 12552 the Sheet Steel block WAS the whole material gap;
  * its part-number rule was `\d{4,5}-\d{2}-[A-Z0-9.]+`, which turns 12349-02-69-01A into
    12349-02-69 — the same truncation fixed in the DXF parser, in a second regex that
    disagreed with the first;
  * it looked one way only, under a 50% match threshold, so an engine figure at 60% of manual
    counted as parity and a bounding box costed as a blank was invisible;
  * and neither side was ever summed and held against its own labelled totals.

That last one is the load-bearing fix, and it earned itself immediately: the first run of the
rebuilt parser against a real manual estimate reported material lines of £577.85 against a
stated £288.92 — the stated figure plus itself, because the last block ran to the next
header and swallowed the "Total Material Cost" row. The labour table did the same to
everything below it and came out four times over. Nothing else in this file would have
caught that; the reconciliation caught it on the first try.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import parity_check as pc                                          # noqa: E402


# ── one definition of what a block is ──────────────────────────────────────────

def test_the_block_shapes_come_from_the_module_that_already_reads_them():
    """A private second copy of the header maps is how two readers come to disagree about
    which column holds a cost — silently, in the one tool whose job is finding
    disagreements."""
    from wep_readback_from_xlsx import _SHEET_HEADER_KEYS, _MATERIAL_HEADER_KEYS
    assert pc.SHEET_KEYS is _SHEET_HEADER_KEYS
    assert pc.BOM_KEYS is _MATERIAL_HEADER_KEYS


def test_all_five_blocks_are_read_not_just_the_bill_of_materials():
    assert pc.BLOCK_ORDER == ["bom", "tube", "steel", "other_sheet"]


# ── one part-number rule ───────────────────────────────────────────────────────

def test_a_four_segment_number_is_not_truncated_to_its_parent():
    """The old PN_RE returned 12349-02-69 for this, so every fabrication keyed to its parent
    and fell into "engine-missing" at full value."""
    assert pc._key("12349-02-69-01A") == "12349-02-69-01A"


def test_it_uses_the_same_rule_the_engine_stores_parts_under():
    from part_identity import normalize_part_code
    for code in ("12349-02-69-04M", "BI-SCREW", "1455-C GA", "FIXING908"):
        assert pc._key(code) == normalize_part_code(code).upper()


# ── a block ends at its total ──────────────────────────────────────────────────

@pytest.mark.parametrize("label", [
    "Total Material Cost", "TOTAL LABOUR COST (Including Downtime)", " Sub Total ",
])
def test_a_total_row_closes_a_block(label):
    assert pc._is_total_row(label)


@pytest.mark.parametrize("label", ["TOTALISER BRACKET", "01-01M CROSS MEMBER",
                                   "Totally Enclosed Fan"])
def test_an_ordinary_part_name_does_not_close_a_block(label):
    assert not pc._is_total_row(label)


def test_the_known_limit_of_the_total_test_is_written_down():
    """A part legitimately named "Total ..." would close its block early. No SDI part is,
    and the alternative — matching only the three exact total labels — breaks the moment the
    template says "Sub Total" or "Total Material Cost (ex VAT)".

    Asserted rather than left as a comment, so if a job ever DOES carry such a part the
    failure arrives here with the reason attached instead of as a quiet short block."""
    assert pc._is_total_row("Total Width Bracket"), (
        "if this ever stops being true the rule was tightened; make sure the real total "
        "labels still close their blocks")


# ── reconcile before comparing ─────────────────────────────────────────────────

def _side(material_lines, labour_lines, stated_m, stated_l):
    return {"blocks": {"bom": material_lines, "tube": [], "steel": [], "other_sheet": []},
            "labour_rows": labour_lines,
            "totals": {"material": stated_m, "labour": stated_l, "unit": None},
            "headline": {"quantity": 1}, "problems": [], "path": __file__}


def test_a_side_whose_lines_sum_to_its_own_totals_balances():
    side = _side([{"total_value_gbp": 10.0}, {"total_value_gbp": 5.5}],
                 [{"total_value_gbp": 20.0}], 15.5, 20.0)
    r = pc.reconcile(side)
    assert r["balances"] and r["material_gap"] == 0.0 and r["labour_gap"] == 0.0


def test_a_side_that_swallowed_its_own_total_row_does_not_balance():
    """The defect this caught on its first real run: 288.92 of lines plus the 288.92 total
    row read as a line."""
    side = _side([{"total_value_gbp": 288.92}, {"total_value_gbp": 288.92}], [], 288.92, 0.0)
    r = pc.reconcile(side)
    assert not r["balances"]
    assert r["material_gap"] == -288.92


def test_the_report_refuses_to_stand_behind_an_unbalanced_parse():
    manual = _side([{"total_value_gbp": 100.0}], [], 50.0, 0.0)
    engine = _side([{"total_value_gbp": 50.0}], [], 50.0, 0.0)
    engine["basis"] = "final_estimate"
    text, _ = pc.build_report(manual, engine, "JOB")
    assert "does not sum to its own totals" in text
    assert "suspect until that is settled" in text


# ── signed, and both ways ──────────────────────────────────────────────────────

def _sides(manual_rows, engine_rows):
    m = _side([], [], None, None)
    e = _side([], [], None, None)
    m["blocks"]["steel"] = manual_rows
    e["blocks"]["steel"] = engine_rows
    e["basis"] = "final_estimate"
    return m, e


def test_the_engine_costing_MORE_than_the_manual_is_reported():
    """A bounding box costed as a blank is an OVER-charge, and the old report — headed
    "engine-missing / under-captured" — could not say so."""
    m, e = _sides([{"code": "01A", "total_value_gbp": 11.43}],
                  [{"code": "01A", "total_value_gbp": 86.40}])
    row = pc.compare_blocks(m, e)["steel"]["rows"][0]
    assert row["delta_gbp"] == pytest.approx(74.97)


def test_an_engine_figure_at_sixty_percent_of_manual_is_not_called_a_match():
    """The old 50% threshold declared this parity and contributed zero to the gap."""
    m, e = _sides([{"code": "03M", "total_value_gbp": 100.0}],
                  [{"code": "03M", "total_value_gbp": 60.0}])
    rows = pc.compare_blocks(m, e)["steel"]["rows"]
    assert rows and rows[0]["delta_gbp"] == pytest.approx(-40.0)


def test_a_line_only_one_side_has_is_named_as_such():
    m, e = _sides([{"code": "07M", "total_value_gbp": 12.0}], [])
    assert pc.compare_blocks(m, e)["steel"]["rows"][0]["only_on"] == "manual"


def test_rounding_noise_is_not_a_finding():
    m, e = _sides([{"code": "03M", "total_value_gbp": 10.00}],
                  [{"code": "03M", "total_value_gbp": 10.02}])
    assert pc.compare_blocks(m, e)["steel"]["rows"] == []


# ── the inputs, not just the money ─────────────────────────────────────────────

def test_two_wrong_inputs_that_cancel_are_still_reported():
    """The money agrees to the penny and the part is a different part. A £ delta says there
    is a problem; an input delta says what it is."""
    m, e = _sides([{"code": "04M", "total_value_gbp": 6.90, "gauge": 1.2,
                    "length_mm": 817.56}],
                  [{"code": "04M", "total_value_gbp": 6.90, "gauge": 6.0,
                    "length_mm": 817.56}])
    rows = pc.compare_blocks(m, e)["steel"]["rows"]
    assert rows, "a gauge read as 6mm against a drawing's 1.2 is invisible on money alone"
    assert rows[0]["inputs"][0]["field"] == "gauge"


def test_the_nest_is_compared_because_it_is_what_the_price_divides_by():
    m, e = _sides([{"code": "03M", "total_value_gbp": 17.22, "qty_per_sheet": 6}],
                  [{"code": "03M", "total_value_gbp": 17.22, "qty_per_sheet": 3}])
    assert pc.compare_blocks(m, e)["steel"]["rows"][0]["inputs"][0]["field"] == "nest"


# ── labour, split the way the quantity story splits ────────────────────────────

def test_labour_is_compared_by_department_and_by_setup_versus_run():
    m = _side([], [{"department": "FOLD", "total_value_gbp": 28.13, "setup_minutes": 30,
                    "dept_rate_gbp_per_hour": 40.47}], None, None)
    e = _side([], [{"department": "FOLD", "total_value_gbp": 5.52, "setup_minutes": 30,
                    "dept_rate_gbp_per_hour": 40.47}], None, None)
    out = pc.compare_labour(m, e)
    assert out["rows"][0]["department"] == "FOLD"
    assert out["rows"][0]["delta"] == pytest.approx(-22.61)
    assert out["manual_setup"] > 0 and out["engine_setup"] > 0


# ── the engine side reads the record that sums to its own sheet ────────────────

def test_it_prefers_final_estimate_and_says_so(tmp_path):
    p = tmp_path / "job.json"
    p.write_text(json.dumps({"final_estimate": {
        "totals": {"material_gbp": 94.11, "labour_gbp": 111.34, "unit_gbp": 220.91},
        "material_rows": [{"block": "steel", "part_code": "03M", "total_value_gbp": 17.22}],
        "labour_rows": [{"department": "FOLD", "total_value_gbp": 5.52}]}}), encoding="utf-8")
    got = pc.read_engine_json(p)
    assert "final_estimate" in got["basis"]
    assert got["totals"]["material"] == 94.11
    assert got["blocks"]["steel"][0]["code"] == "03M"


def test_a_run_with_no_read_back_is_compared_on_the_older_basis_and_flagged(tmp_path):
    """Not refused — a parity on the wrong basis is still worth something as long as nobody
    is allowed to mistake it for one on the right basis."""
    p = tmp_path / "job.json"
    p.write_text(json.dumps({"estimate_summary": {"part_estimates": [
        {"part_number": "03M", "material_estimate": {"extended_material_cost_gbp": 6.89}}]}}),
        encoding="utf-8")
    got = pc.read_engine_json(p)
    assert "part_estimates" in got["basis"]
    assert any("no final_estimate" in p for p in got["problems"])


# ── ledger hygiene ─────────────────────────────────────────────────────────────

def _row(job, material):
    return {"job": job, "job_date": "2026-09-02", "manual_material": material,
            "engine_material": material}


def test_running_a_parity_twice_does_not_count_the_job_twice(tmp_path):
    """The old ledger appended unconditionally, so every aggregate over it double-counted a
    job somebody had re-run — in the file that exists to be aggregated."""
    led = tmp_path / "ledger.csv"
    pc.append_ledger(str(led), _row("12349-02", 94.11))
    pc.append_ledger(str(led), _row("12349-02", 88.00))
    rows = list(csv.DictReader(led.open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["manual_material"] == "88.0", "the later run replaces the earlier"


def test_a_second_job_is_added_rather_than_replacing_the_first(tmp_path):
    led = tmp_path / "ledger.csv"
    pc.append_ledger(str(led), _row("12349-02", 94.11))
    pc.append_ledger(str(led), _row("12552-00", 541.42))
    assert {r["job"] for r in csv.DictReader(led.open(encoding="utf-8"))} == {
        "12349-02", "12552-00"}
