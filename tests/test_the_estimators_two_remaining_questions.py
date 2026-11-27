"""Two of the estimator's fifteen points that were still open on the 13 Sep pack.

    "Where did the price come from for Powder (Per Kilo)?"
    "Why is operation for glue 12349-02-69-01A only showing 1 minute (Where did this time
     come from)"

Both had answers the sheet did not give.

THE POWDER RATE HAS A NAME AGAINST IT and the line never said so. £4/kg is the SDI standard
powder rate confirmed by estimating — POWDER5, job 1282 — and the BOM row stated its coated
AREA and nothing about its rate. A figure whose source cannot travel with it reads as
invented however well evidenced it is, which is the whole reason the question was asked. The
provenance now lives in a field rather than a code comment, and the line prints it.

THE ONE MINUTE CAME FROM A GENERIC DEFAULT. ACRYLIC_OP_DRIVERS carries SDI's own figure,
reverse-engineered from the M18 workbook: 2.4 minutes per bonded assembly on a 30-minute
set-up, and its own note says glue and flame-polish are "ONE op per bonded/display assembly,
not per panel". The block that applies it is gated `not is_assembly_parent` — so the only
kind of part the driver exists for is the one kind it never reached, and 01A, seven bonded
panels, took LABOUR_RULES' flat 1.0 minute. The gate stays (it keeps laser and linebend off a
parent that cuts nothing); only the joining work, which is what an assembly actually does,
now reaches it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                           # noqa: E402
from estimator import estimate_process_times                            # noqa: E402


# ── the powder rate says where it came from ──────────────────────────────────────────────

def test_the_powder_rate_carries_its_source_in_a_field():
    """Not in a comment. A sheet cannot print a comment."""
    src = (config.POWDER_COSTING_POLICY or {}).get("powder_material_gbp_per_kg_source")
    assert src and "1282" in src, "the rate's provenance must travel with the rate"


def test_the_rate_and_the_constant_still_agree():
    """One number, from the book with a name against it."""
    assert config.POWDER_COST_PER_KG == (
        config.POWDER_COSTING_POLICY or {}).get("powder_material_gbp_per_kg")


def test_the_bom_line_names_the_rate_and_its_source():
    """The row the estimator asked about, as it will now read."""
    import re
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    assert re.search(r'at £\{_pk_rate:\.2f\}/kg', src), \
        "the powder line must state its £/kg, not only its area"
    assert "_pk_src" in src and "powder_material_gbp_per_kg_source" in src


# ── the bonded assembly is timed by the acrylic model ────────────────────────────────────

def _bonded_assembly(**over):
    part = {
        "part_number": "12349-02-69-01A",
        "description": "GRAVITY FEEDER FABRICATION",
        "normalized_material": "ACRYLIC",
        "is_assembly_parent": True,
        "textual_operations": ["glue"],
    }
    part.update(over)
    return part


def test_the_glue_on_a_bonded_acrylic_assembly_is_the_sdi_figure():
    """2.4 minutes per assembly, not the generic one minute."""
    out = estimate_process_times(_bonded_assembly())
    assert out["run_times_min_per_unit"]["glue"] == 2.4
    assert out["setup_times_min"]["glue"] == 30.0


def test_the_record_says_where_the_time_came_from():
    part = _bonded_assembly()
    estimate_process_times(part)
    assert any("SDI acrylic model" in str(f) for f in part.get("review_flags") or []), \
        "the estimator asked where the minute came from — the record has to answer"


def test_the_derived_totals_move_with_it():
    """unit_times_min and times_min are built before this runs and go stale otherwise."""
    out = estimate_process_times(_bonded_assembly(), quantity=7)
    assert out["unit_times_min"]["glue"] == 32.4          # 30 set-up + 2.4 run
    assert out["times_min"]["glue"] == 30.0 + 2.4 * 7


def test_a_steel_assembly_is_untouched():
    """The rule is about acrylic bonding, not about assemblies."""
    out = estimate_process_times(_bonded_assembly(normalized_material="MILD_STEEL"))
    assert out["run_times_min_per_unit"]["glue"] == 1.0


def test_an_assembly_with_no_glue_gains_none():
    """This retimes a glue op that is already there; it never adds one."""
    out = estimate_process_times(_bonded_assembly(textual_operations=["assembly"]))
    assert "glue" not in (out.get("run_times_min_per_unit") or {})


def test_an_acrylic_leaf_keeps_its_own_route():
    """A panel is not an assembly — its glue, if any, is the block's business, not this."""
    leaf = {"part_number": "12349-02-69-01A-01", "normalized_material": "ACRYLIC",
            "textual_operations": ["glue"], "normalized_thickness_mm": 2.0,
            "overall_length_mm": 770, "overall_width_mm": 130}
    out = estimate_process_times(leaf)
    assert (out.get("run_times_min_per_unit") or {}).get("glue") is not None
