"""A material the model carries only as a library appearance does not overrule the drawing.

SolidWorks hands a part's material back two ways through one API field, and they are not equal
evidence. An EXPLICIT custom property is the spec the designer typed — what the part is bought
to. The library-APPLIED material is the appearance/simulation template the model happens to
carry, frequently a default nobody revisited: "Plain Carbon Steel" on a part the drawing calls
MDF, a birch-faced-ply visual on a panel the title block calls MDF. Both used to enter the
waterfall at rank 90 (solidworks_api), indistinguishable, so a bare library appearance overruled
the drawing's own material callout.

The analyser now tags which kind it read (_material_and_source), the connector submits an
applied-library material under a weaker source (solidworks_applied_material, rank 68), and the
waterfall does the rest: an applied-library material loses to the drawing's callout (70) but
still fills a gap when the drawing says nothing, and beats everything reasoned. A typed custom
property is unchanged — it stays the strongest model source. An extract taken before the tag
existed carries no applied-material observation and behaves exactly as before, so nothing
regresses until the analyser is re-run.

The COM calls that populate the analyser's property store cannot be exercised without a
SolidWorks seat; the DECISION they feed (_material_and_source) is pure and is proven here in
full, and the whole connector-side arbitration is proven end to end on synthetic extracts.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "solidworks"))

from source_connectors import solidworks as sw  # noqa: E402
from source_precedence import apply_field, source_of, rank, MEASURED_SOURCES  # noqa: E402
import sw_native_analyse as swa  # noqa: E402


# ── the analyser's pure provenance split (no SolidWorks needed) ────────────────────────
def test_a_typed_custom_property_is_tagged_a_spec():
    assert swa._material_and_source({"Material": "Plain Carbon Steel"}, "AISI 304") == \
        ("Plain Carbon Steel", "custom_property")


def test_a_material_only_in_the_applied_field_is_tagged_a_library_appearance():
    assert swa._material_and_source({}, "Birch") == ("Birch", "applied_library")
    assert swa._material_and_source({"Description": "bracket"}, "MDF") == ("MDF", "applied_library")


def test_a_model_with_no_material_at_all_names_nothing():
    assert swa._material_and_source({}, "") == ("", "")
    assert swa._material_and_source({}, None) == ("", "")


def test_a_custom_property_under_any_alias_is_a_spec():
    """The spec can be typed under Material Spec / Grade etc., not just 'Material'."""
    assert swa._material_and_source({"Material Spec": "6082 T6"}, "x") == \
        ("6082 T6", "custom_property")
    assert swa._material_and_source({"Grade": "S275"}, "x") == ("S275", "custom_property")


# ── the waterfall rank the whole fix rests on ──────────────────────────────────────────
def test_the_applied_material_ranks_below_the_drawing_and_above_the_pdf():
    """THE ORDER. An applied library material sits under the drawing's word and over the PDF's
    inferred overall — below a spec, above a guess."""
    assert rank("solidworks_applied_material") < rank("drawing_deterministic")
    assert rank("solidworks_applied_material") < rank("title_block")
    assert rank("solidworks_applied_material") < rank("dxf_filename")
    assert rank("solidworks_applied_material") > rank("pdf_overall_dims")
    assert rank("solidworks_applied_material") < rank("solidworks_api")


def test_the_applied_material_is_a_reading_not_a_guess():
    """It came off the model, so reports mark it measured — it is weaker than a spec, not
    reasoned."""
    assert "solidworks_applied_material" in MEASURED_SOURCES


def test_the_token_maps_applied_only_to_the_weaker_source():
    assert sw._material_source_token(sw.NativePart("P", material="Birch",
                                                   material_source="applied_library")) == \
        "solidworks_applied_material"
    assert sw._material_source_token(sw.NativePart("P", material="Birch",
                                                   material_source="custom_property")) == \
        "solidworks_api"
    # An older extract that never recorded provenance stays at full model rank.
    assert sw._material_source_token(sw.NativePart("P", material="Birch")) == "solidworks_api"


# ── the connector, end to end on synthetic extracts ────────────────────────────────────
def _apply_full(sw_material, material_source, drawing_mat="MDF",
                drawing_src="drawing_deterministic"):
    rs = {"material": sw_material}
    if material_source:
        rs["material_source"] = material_source
    job = sw.normalize_native_extract([{"title": "P1", "doctype": 1, "route_signals": rs}])
    part = {"part_number": "P1"}
    if drawing_mat is not None:
        apply_field(part, "normalized_material", drawing_mat, drawing_src)
    out = sw.apply_native_to_pre_estimate([part], job)
    return part, out


def _apply(sw_material, material_source, drawing_mat="MDF", drawing_src="drawing_deterministic"):
    part, _out = _apply_full(sw_material, material_source, drawing_mat, drawing_src)
    return part.get("normalized_material"), source_of(part, "normalized_material")


def test_an_applied_ply_does_not_overrule_a_drawing_mdf():
    """THE 8352-SHAPED CASE. Drawing says MDF, model carries a birch-ply appearance -> MDF."""
    assert _apply("Birch", "applied_library") == ("MDF", "drawing_deterministic")


def test_a_typed_ply_spec_does_overrule_the_drawing_mdf():
    """When the designer TYPED the ply, it is the spec and wins — the split only demotes an
    appearance, never a stated material."""
    mat, src = _apply("Birch", "custom_property")
    assert mat == "TIMBER" and src == "solidworks_api"


def test_an_applied_material_still_fills_an_empty_material():
    """No drawing callout at all: the appearance is the best evidence in the pack, so it is
    adopted — at its own weaker rank, so a later drawing read could still correct it."""
    mat, src = _apply("Birch", "applied_library", drawing_mat=None, drawing_src=None)
    assert mat == "TIMBER" and src == "solidworks_applied_material"


def test_an_applied_steel_default_does_not_overrule_a_drawing_board():
    """The commonest wrong default — 'Plain Carbon Steel' left on a board — no longer flips a
    board part to steel across the family line, because a bare appearance is not evidence of
    family. And the disagreement is SURFACED, not silently dropped: routing the applied-only
    material through the ranked-submit branch records the conflict the estimator needs to see,
    where the cross-family override branch would have tried, failed on rank, and said nothing."""
    part, out = _apply_full("Plain Carbon Steel", "applied_library")
    assert part.get("normalized_material") == "MDF"
    assert source_of(part, "normalized_material") == "drawing_deterministic"
    # The conflict was recorded — a counter and a review flag naming both sides.
    assert out.get("material_conflict", 0) >= 1
    assert any("library appearance" in f.lower()
               for f in part.get("review_flags", []))


def test_a_typed_steel_spec_does_overrule_a_drawing_board_across_families():
    """A TYPED steel spec still wins the cross-family override — the spec is authoritative."""
    mat, src = _apply("Plain Carbon Steel", "custom_property")
    assert mat == "MILD_STEEL" and src == "solidworks_api"


def test_a_legacy_extract_without_provenance_is_unchanged():
    """An extract taken before the tag existed carries no material_source; it must behave
    exactly as before — full model rank, SW overrides — so re-running is the only thing that
    turns the new behaviour on. Zero regression."""
    mat, src = _apply("Birch", None)
    assert mat == "TIMBER" and src == "solidworks_api"


# ── wiring ─────────────────────────────────────────────────────────────────────────────
def test_the_analyser_records_provenance_on_the_signal():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "solidworks",
                            "sw_native_analyse.py"), encoding="utf-8").read()
    assert "material_source: str = \"\"" in src
    assert "sig.material, sig.material_source = _material_and_source(props, _applied)" in src


def test_the_connector_submits_by_provenance():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "source_connectors",
                            "solidworks.py"), encoding="utf-8").read()
    assert "material_source=str(rs.get(\"material_source\") or \"\")" in src
    assert "_material_source_token(nat)" in src
