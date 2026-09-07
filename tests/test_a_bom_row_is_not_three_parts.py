"""10975-02, the A4 table-top graphic holder: a three-line acrylic job the engine turned
into nine lines and £163 of labour. Rev B's BOM is A01 (2 mm acrylic L-stand), G01 (paper
graphic) and EPDM tape ×3 — and the run produced the tape as three identities (one of them
welded and powder-coated at £120), a character-interleave chimera asking Tim to price a
part that does not exist, no Linebend for the two heat-bends, and a 2 mm part nested at
3 mm because the only DXF in the pack had no hyphens in its name.

These pin the four fixes James ranked before any re-run: legend text never mints
operations, a named consumable gets no fabrication route, one configured name is one
identity, gates that miss a record still look, punctuation-free DXF names still pair, and
the bend survives the reader that won.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import bought_in_policy as bp  # noqa: E402
import document_builder as db  # noqa: E402
import route_compiler as rc  # noqa: E402


# ── fix 1a · the specification legend is not work ────────────────────────────────────────

_PAGE = """VIEW A  CORNERS TO BE WELDED  SEE NOTE 3
FINISH SPECIFICATIONS:
- POWDERCOATING: BETWEEN 80 - 120 MICRON THICKNESS COVERAGE
- CHROME PLATING: NICKEL LAYER = 8 - 12 MICRON
CHINA MATERIAL SPECIFICATIONS:
- Q195 UP TO 3mm THICK FOR POWDER COATED STEEL
WELD SPECIFICATION:
- ALL WELDS TO BE TIG UNLESS STATED
- RESISTANCE WELDING WIRE TO WIRE
TIMBER PRODUCTS:
- FSC CERTIFIED
GLASS: NO GLASS TO BE SUPPLIED WITHOUT SAFETY FILM
WIRING: ALL ELECTRICAL CABLE AND WIRING TO BE RATED
DRAWN WILL.LEAR CHECKED JAKE MCKELVIE"""


def test_the_legend_is_removed_and_the_views_callout_survives():
    out = db._strip_specification_legend(_PAGE)
    assert "CORNERS TO BE WELDED" in out, "a genuine view callout must survive"
    assert "DRAWN WILL.LEAR" in out, "the title block fields survive"
    for boiler in ("ALL WELDS TO BE TIG", "POWDERCOATING", "Q195", "FSC CERTIFIED"):
        assert boiler not in out, f"legend text {boiler!r} must not reach the op scan"


def test_no_weld_phrase_survives_a_legend_only_page():
    out = db._strip_specification_legend(_PAGE.replace(
        "VIEW A  CORNERS TO BE WELDED  SEE NOTE 3\n", "")).upper()
    assert not any(p in out for p in db._ASSEMBLY_WELD_PHRASES)
    assert not any(p in out for p in db._ASSEMBLY_PC_PHRASES)


# ── fix 1b · a named consumable is bought, not made ──────────────────────────────────────

def test_epdm_tape_wearing_acrylic_is_still_bought_in():
    """The tape inherited the GA's ACRYLIC and classified as a leaf — then got welded,
    dressed and powder-coated. The description is the draughtsman's word for what it is."""
    tape = {"part_number": "10975EPDMCLOSEDCELL",
            "description": "Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C LEN",
            "normalized_material": "ACRYLIC"}
    assert "consumable" in bp.bought_in_reason(tape)
    assert bp.is_bought_in(tape)
    vhb = {"part_number": "VHB CLEAR FOAM TAPE - 19MM X 0.5MM",
           "description": "VHB Clear Foam Tape"}
    assert bp.is_bought_in(vhb)


def test_the_consumable_rule_never_claims_a_part_we_cut():
    steel = {"part_number": "7332-01-001", "description": "BASE PLATE",
             "normalized_material": "MILD STEEL", "flat_pattern_detected": True}
    assert bp.bought_in_reason(steel) == ""
    tapered = {"part_number": "12345-01-002", "description": "TAPERED BRACKET",
               "normalized_material": "MILD STEEL", "flat_pattern_detected": True}
    assert bp.bought_in_reason(tapered) == "", "TAPERED is not TAPE"
    drawn_tape_slot = {"part_number": "12345-01-03M",
                       "description": "PANEL WITH TAPE SLOT",
                       "flat_pattern_detected": True}
    assert bp.bought_in_reason(drawn_tape_slot) == "", \
        "fabrication evidence outranks the name"


# ── fix 2 · one configured name, one identity ────────────────────────────────────────────

def test_fragments_of_a_caret_name_alias_onto_it():
    full = "10975 EPDM CLOSED CELL TAPE^10975-02-GA"
    aliases = rc._raw_identity_aliases(
        {"CELL TAPE^10975-02-": {"description": "wrapped middle line"},
         "10975EPDMCLOSEDCELL": {"description": "squashed first line"}},
        {full: {"description": "EPDM TAPE 25X1MM - TAPE 113C"}})
    assert aliases.get("CELL TAPE^10975-02-") == full
    assert aliases.get("10975EPDMCLOSEDCELL") == full


def test_a_short_or_unrelated_code_is_not_swallowed():
    full = "10975 EPDM CLOSED CELL TAPE^10975-02-GA"
    aliases = rc._raw_identity_aliases(
        {"10975": {"description": "the project number is not a fragment"},
         "10975-02-A01": {"description": "L-STAND",
                          "normalized_geometry": {"blank_length_mm": 760.0,
                                                  "blank_width_mm": 210.0}}},
        {full: {"description": "EPDM TAPE"}})
    assert "10975" not in aliases, "five characters is not identity"
    assert "10975-02-A01" not in aliases, "a real part is not a fragment"


# ── fix 3 · a gate that cannot find the record still looks ───────────────────────────────

def test_the_gate_lookup_finds_the_record_under_its_fuller_name():
    records = {"10975 EPDM CLOSED CELL TAPE^10975-02-GA":
               {"normalized_material": "EPDM"}}
    hit = rc._record_by_squashed_key(records, "CELL TAPE^10975-02-")
    assert hit and hit["normalized_material"] == "EPDM"
    assert rc._record_by_squashed_key(records, "10975") is None, "too short"
    two = dict(records)
    two["CELL TAPE^10975-02-GA EXTRA"] = {}
    assert rc._record_by_squashed_key(two, "CELL TAPE^10975-02-") is None, \
        "two candidates is ambiguity, not a match"


# ── the chimera · a zipped BOM row is not a part ─────────────────────────────────────────

def test_the_interleave_chimera_is_recognised_and_real_codes_are_not():
    sq = rc._squashed
    whole = sq("1100997755-E0P2D-GM0")
    assert rc._interleave_of(whole, sq("10975-02-G01"),
                             sq("10975 EPDM CLOSED CELL TAPE^10975-02-GA"), min_each=5)
    ids = ["10975-02-G01", "10975-02-GA", "10975-02-A01",
           "10975 EPDM CLOSED CELL TAPE^10975-02-GA"]
    for real in ("7332-01-101-PLATE", "10975-02-A01"):
        assert not any(
            rc._interleave_of(sq(real), sq(a), sq(b), min_each=5)
            for a in ids for b in ids
            if a != b and a != real and b != real), f"{real} must never read as a chimera"


# ── fix 4a · a hyphen-less DXF name still pairs ──────────────────────────────────────────

def test_the_punctuation_free_dxf_filename_pairs_with_its_part(tmp_path):
    import shutil
    import drawing_job_merge as djm
    src = os.path.join(os.path.dirname(__file__), "fixtures",
                       "1097502A01_2mm_ACRY_Rev_B.DXF")
    dxf = tmp_path / "1097502A01_2mm_ACRY_Rev_B.DXF"
    shutil.copy(src, dxf)
    summary = {"manufacturing_writeup": {"parts": [
        {"part_number": "10975-02-A01", "description": "L-STAND",
         "normalized_material": "ACRYLIC"},
        {"part_number": "10975-02-G01", "description": "GRAPHIC"},
    ]}}
    out = djm.augment_summary_with_dxf(summary, [str(dxf)])
    report = out.get("dxf_augmentation") or {}
    matched = [m for m in report.get("matched", [])
               if str(m.get("part_number", "")).upper() == "10975-02-A01"]
    assert matched, f"the A01 flat must pair: {report.get('unmatched_dxf')}"
    part = out["manufacturing_writeup"]["parts"][0]
    assert part.get("dxf_source_file"), "the pairing must reach the part record"
    assert part.get("bend_count_dxf") == 2, "the BENDLINES layer must be counted"
    # And the count reaches the money: the re-estimate books Linebend, never Fold.
    for e in (out.get("estimate_summary") or {}).get("part_estimates") or []:
        if e.get("part_number") == "10975-02-A01":
            rt = (e.get("process_estimate") or {}).get("run_times_min_per_unit") or {}
            assert rt.get("linebend"), f"ops booked: {sorted(rt)}"
            assert "folding" not in rt


# ── fix 4b · the bend survives the reader that won ───────────────────────────────────────

def test_acrylic_bends_fall_back_when_the_flat_pattern_published_none():
    import estimator
    part = {"part_number": "10975-02-A01", "description": "L-STAND",
            "normalized_material": "ACRYLIC", "quantity": 1,
            "overall_length_mm": 760.3, "overall_width_mm": 210.0,
            "material_thickness_mm": 2.0,
            "manufacturing_features": {"bend_count": 2},
            "native_flat_pattern": True}
    est = estimator.estimate_part(part, job_quantity=1)
    rt = (est.get("process_estimate") or {}).get("run_times_min_per_unit") or {}
    assert rt.get("linebend"), \
        f"two heat-bends must book Linebend; ops booked: {sorted(rt)}"
    assert "folding" not in rt and "fold" not in rt


def test_a_model_that_measured_zero_bends_stays_flat():
    import estimator
    part = {"part_number": "10975-02-Z01", "description": "FLAT LENS",
            "normalized_material": "ACRYLIC", "quantity": 1,
            "overall_length_mm": 300.0, "overall_width_mm": 210.0,
            "material_thickness_mm": 2.0,
            "native_flat_solid": True,
            "manufacturing_features": {"bend_count": 0},
            "angles_deg": [90.0],
            "native_flat_pattern": True}
    est = estimator.estimate_part(part, job_quantity=1)
    rt = (est.get("process_estimate") or {}).get("run_times_min_per_unit") or {}
    assert not rt.get("linebend"), "a measured-flat part must not grow a bend from text"
