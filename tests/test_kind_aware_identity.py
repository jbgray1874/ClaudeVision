"""A bought-in can never absorb a fabricated leaf.

The material-suffix convention says "<code>M" is "<code>" cut in that material. That is a
claim about a part we MAKE. When the base code turns out to be a bought-in line, the
convention has matched a spelling and not a part, and following it hands the fabricated
leaf's identity — with its route and its measured blank — to something we purchase.

The alias pass that applies that convention received nothing but strings, so it could not
ask what the two codes were. It merged on spelling alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import route_compiler as rc  # noqa: E402


def _fabricated(**extra):
    part = {"part_number": "12392-02-01M", "description": "BACK PANEL",
            "blank_length_mm": 1435, "blank_width_mm": 130,
            "textual_operations": ["laser_cutting", "folding"]}
    part.update(extra)
    return part


def _bought(**extra):
    part = {"part_number": "12392-02-01", "description": "PANEL",
            "is_bought_in": True}
    part.update(extra)
    return part


# ---------------------------------------------------------------------------
# What a record IS
# ---------------------------------------------------------------------------
def test_measured_geometry_makes_a_record_fabricated():
    """Evidence outranks a flag. The geometry is an observation; the kind is a
    classification, and a classification does not un-cut a part."""
    assert rc._record_kind(_fabricated()) == "leaf"


def test_a_fabrication_route_makes_a_record_fabricated():
    assert rc._record_kind({"part_number": "X",
                            "textual_operations": ["laser_cutting", "folding"]}) == "leaf"


def test_a_bought_in_with_no_fabrication_evidence_stays_bought_in():
    assert rc._record_kind(_bought()) == "bought_in"


def test_an_assembly_is_an_assembly_before_anything_else():
    """A parent may inherit geometry from a child; it is still not a leaf."""
    assert rc._record_kind({"part_number": "X", "is_assembly_parent": True,
                            "blank_length_mm": 100, "blank_width_mm": 50}) == "assembly"


def test_an_unstated_record_abstains():
    assert rc._record_kind({"part_number": "X", "description": "THING"}) == ""


def test_a_bought_in_flag_does_not_survive_fabrication_evidence():
    """The asymmetry, stated. Calling a bought-in fabricated costs a route nobody books
    and an estimator can see. Calling a fabricated leaf bought-in deletes the cutting,
    folding and welding from a part we make, and nothing on the sheet says so."""
    part = _fabricated(is_bought_in=True)
    assert rc._record_kind(part) == "leaf"


# ---------------------------------------------------------------------------
# The merge itself
# ---------------------------------------------------------------------------
def _alias(records):
    refused = []
    out = rc._drawing_code_aliases(set(records), records, refused)
    return out, refused


def test_a_fabricated_leaf_is_not_aliased_onto_a_bought_in():
    records = {"12392-02-01M": _fabricated(), "12392-02-01": _bought()}
    aliases, refused = _alias(records)
    assert "12392-02-01M" not in aliases, "the leaf must keep its own identity"
    assert refused and refused[0]["identity"] == "12392-02-01M"
    assert refused[0]["identity_kind"] == "leaf"
    assert refused[0]["target_kind"] == "bought_in"


def test_the_convention_still_joins_two_records_of_the_same_kind():
    """Mutation guard. This is the join the convention exists for — 11350's five-item BOM
    compiling to seven nodes because the model's '-01M' never met the GA's '-01'. If this
    fails, the fix has broken the thing it was protecting."""
    records = {
        "11350-01-01M": _fabricated(part_number="11350-01-01M"),
        "11350-01-01": {"part_number": "11350-01-01", "description": "BAR",
                        "textual_operations": ["laser_cutting"]},
    }
    aliases, refused = _alias(records)
    assert aliases.get("11350-01-01M") == "11350-01-01"
    assert not refused


def test_an_unknown_kind_at_either_end_does_not_block_the_join():
    """Absence is silence. A record nobody classified must not veto a join the naming
    convention supports — the other tests still have to pass."""
    records = {"11350-01-01M": {"part_number": "11350-01-01M"},
               "11350-01-01": {"part_number": "11350-01-01"}}
    aliases, _refused = _alias(records)
    assert aliases.get("11350-01-01M") == "11350-01-01"


def test_a_spacing_variant_is_still_joined_across_the_same_kind():
    records = {"11350-01-02 MIR": _fabricated(part_number="11350-01-02 MIR"),
               "11350-01-02MIR": _fabricated(part_number="11350-01-02MIR")}
    aliases, _r = _alias(records)
    assert aliases.get("11350-01-02MIR") == "11350-01-02 MIR"


def test_a_spacing_variant_across_kinds_is_refused():
    records = {"11350-01-02 MIR": _bought(part_number="11350-01-02 MIR"),
               "11350-01-02MIR": _fabricated(part_number="11350-01-02MIR")}
    aliases, refused = _alias(records)
    assert "11350-01-02MIR" not in aliases
    assert refused


def test_calling_it_with_no_records_behaves_as_before():
    """The signature grew a default so every existing caller keeps working."""
    aliases = rc._drawing_code_aliases({"11350-01-01M", "11350-01-01"})
    assert aliases.get("11350-01-01M") == "11350-01-01"


# ---------------------------------------------------------------------------
# The refusal is reported
# ---------------------------------------------------------------------------
def test_a_refused_merge_reaches_the_graph_issues():
    """Silently not merging leaves an estimator looking at two rows with no idea why.
    Either the convention matched a spelling rather than a part, or one of the two
    records is classified wrongly — and both are worth knowing."""
    # build_part_graph takes the PART RECORDS, not a summary. Passing a summary produced
    # an empty graph and an empty issue list — a test that would have reported the wiring
    # as working while nothing ran.
    graph = rc.build_part_graph([_fabricated(), _bought()])
    issues = [i for i in (graph.get("issues") or [])
              if i.get("code") == "identity_merge_refused_across_kinds"]
    assert issues, "a declined join must be visible"
    assert "does not become one we purchase" in issues[0]["detail"]
