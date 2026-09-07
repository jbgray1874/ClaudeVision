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
import costed_facts as cf  # noqa: E402
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


# ── the reviewers' acceptance points, round two ──────────────────────────────────────────

def test_two_bends_book_twice_the_per_bend_minutes():
    """A displayed Linebend must actually carry BOTH bends' minutes — a value that could
    be one bend's would under-charge, one that doubled would over-charge."""
    import config
    import estimator
    per_bend = float((getattr(config, "ACRYLIC_OP_DRIVERS", {}) or {})
                     .get("min_per_linebend", 1.0))
    part = {"part_number": "10975-02-A01", "description": "L-STAND",
            "normalized_material": "ACRYLIC", "quantity": 1,
            "overall_length_mm": 760.3, "overall_width_mm": 210.0,
            "material_thickness_mm": 2.0,
            "manufacturing_features": {"bend_count": 2},
            "native_flat_pattern": True}
    est = estimator.estimate_part(part, job_quantity=1)
    rt = (est.get("process_estimate") or {}).get("run_times_min_per_unit") or {}
    assert abs(rt.get("linebend", 0.0) - 2 * per_bend) < 0.01, \
        f"two bends must book 2 × {per_bend} min; booked {rt.get('linebend')}"


def test_unusual_supplier_codes_never_read_as_chimeras():
    """Character interleaving is a heuristic, so it must be proven against genuine odd
    codes, not only SDI-shaped ones."""
    sq = rc._squashed
    pool = ["10975-02-G01", "10975-02-GA", "79814P613",
            "10975 EPDM CLOSED CELL TAPE^10975-02-GA", "M8 FLANGED NUTSERT"]
    for supplier in ("79814P613", "M8X20-PAN-POZI-A2-70", "TAPE 113C-25X1-BLK",
                     "3M-VHB-4910F-19MM"):
        hit = any(rc._interleave_of(sq(supplier), sq(a), sq(b), min_each=5)
                  for a in pool for b in pool
                  if a != b and a != supplier and b != supplier)
        assert not hit, f"{supplier} must survive the chimera check"


def test_the_priced_project_number_row_folds_into_the_one_tape_line():
    """Sheet 1's row was minted as bare '10975' and PRICED, beside the caret part — the
    duplicate the first alias pass could not see. With the commodity description as the
    second witness it is one line; and where the two sheets' figures disagree (LENGTH
    200 vs 220), the conflict is recorded on the survivor, never chosen silently."""
    full = "10975 EPDM CLOSED CELL TAPE^10975-02-GA"
    host_rec = {"description": "EPDM TAPE 25X1MM - TAPE 113C LENGTH: 220.00"}
    aliases = rc._raw_identity_aliases(
        {"10975": {"description": "EPDM TAPE 25X1MM - TAPE 113C LENGTH: 200.00"}},
        {full: host_rec})
    assert aliases.get("10975") == full
    conflicts = host_rec.get("_bom_numeric_conflicts") or []
    assert conflicts and "200.00" in str(conflicts[0]["other"]) \
        and "220.00" in str(conflicts[0]["kept"])


def test_a_bare_project_number_with_a_different_description_stays_itself():
    full = "10975 EPDM CLOSED CELL TAPE^10975-02-GA"
    aliases = rc._raw_identity_aliases(
        {"10975": {"description": "DISPLAY STAND ASSEMBLY"}},
        {full: {"description": "EPDM TAPE 25X1MM"}})
    assert "10975" not in aliases


def test_a_gauge_disagreement_between_readers_is_a_decision():
    """Generic: the model said 3 mm, the DXF said 2 mm, and the rank-winner took it
    silently — on steel or acrylic alike that is a re-price nobody approved."""
    import source_precedence as sp
    part = {"part_number": "10975-02-A01"}
    sp.apply_field(part, "normalized_thickness_mm", 3.0, "solidworks_flat_pattern")
    sp.apply_field(part, "normalized_thickness_mm", 2.0, "dxf_filename")
    d = cf.thickness_conflict(part)
    assert d and d["kind"] == "manufacturing_decision"
    assert "3 mm" in d["issue"] and "2 mm" in d["issue"]
    agreed = {"part_number": "X"}
    sp.apply_field(agreed, "normalized_thickness_mm", 3.0, "solidworks_flat_pattern")
    sp.apply_field(agreed, "normalized_thickness_mm", 3.0, "dxf")
    assert cf.thickness_conflict(agreed) is None, "agreement is not a decision"


def test_text_cued_drilling_yields_to_a_measured_flat_with_no_hole_note():
    class _T:
        operation = "hole_machining"
        source = "drawing_notes"
    measured_no_holes = {"native_flat_pattern": True, "hole_sizes_mm": [],
                         "description": "L-STAND", "notes": "SHARP EDGES REMOVED"}
    assert rc._unsupported_drill_reason(_T(), measured_no_holes)
    noted = {"native_flat_pattern": True, "hole_sizes_mm": [],
             "description": "BRACKET", "notes": "DRILL 2 HOLES Ø5 AFTER FORMING"}
    assert rc._unsupported_drill_reason(_T(), noted) is None, \
        "a stated secondary-drilling note keeps the operation"
    unmeasured = {"description": "BRACKET", "notes": ""}
    assert rc._unsupported_drill_reason(_T(), unmeasured) is None, \
        "with nothing measured, text evidence stands"

    class _M(_T):
        source = "drawing_deterministic"
    assert rc._unsupported_drill_reason(_M(), measured_no_holes) is None, \
        "a measured claim is never second-guessed by this rule"


# ── the runtime names, exactly as the box spells them ────────────────────────────────────

def test_the_lettered_detail_code_parses_from_every_real_spelling():
    """James's staging folder: '10975-02-A01_2mm ACRY_Rev B.DXF' — hyphens intact. The miss
    had three stacked causes, each pinned here: the decimal-thickness pre-join ate
    'A01_2mm' into 'A01.2mm'; the descriptive-word trim dropped letter-first details
    (G01 truncated to the parent 10975-02); and config's pattern list knew only
    digit-first codes. Every older convention must still parse identically."""
    from pathlib import Path
    import dxf_reader
    import drawing_job_merge as djm
    expect = {
        "10975-02-A01_2mm ACRY_Rev B.DXF": "10975-02-A01",
        "10975-02-G01.SLDPRT": "10975-02-G01",
        "7332-01-002_3mm MS_Rev K.DXF": "7332-01-002",
        "9376-01-001_MS_1_5mm_revL.DXF": "9376-01-001",
        "12349-02-69-01A_2mm_revA.DXF": "12349-02-69-01A",
        "9233-12-GA_UK_MW_Dressing_Kit_2020.DXF": "9233-12-GA",
    }
    for name, pn in expect.items():
        assert djm.part_number_from_dxf_path(Path(name)) == pn, name
    parsed = dxf_reader._parse_filename(Path("10975-02-A01_2mm ACRY_Rev B.DXF"))
    assert parsed["part_number"] == "10975-02-A01"
    assert parsed["thickness_mm"] == 2.0, "the 2 mm gauge token must survive the parse"
    # The GA drawing-sheet export is NOT a flat: it parses no part and must stay
    # unmatched rather than pairing with anything or minting an orphan.
    assert djm.part_number_from_dxf_path(
        Path("0355255 - A4 Table Top Graphic Holder - 10975_REV B.DXF")) is None


def test_the_hyphenated_runtime_name_pairs_end_to_end(tmp_path):
    import shutil
    import drawing_job_merge as djm
    src = os.path.join(os.path.dirname(__file__), "fixtures",
                       "1097502A01_2mm_ACRY_Rev_B.DXF")
    dxf = tmp_path / "10975-02-A01_2mm ACRY_Rev B.DXF"
    shutil.copy(src, dxf)
    summary = {"manufacturing_writeup": {"parts": [
        {"part_number": "10975-02-A01", "description": "L-STAND",
         "normalized_material": "ACRYLIC"},
        {"part_number": "10975-02-GA", "description": "L-STAND ASSEMBLY",
         "is_assembly_parent": True},
    ]}}
    out = djm.augment_summary_with_dxf(summary, [str(dxf)])
    report = out.get("dxf_augmentation") or {}
    matched = [m for m in report.get("matched", [])
               if str(m.get("part_number", "")).upper() == "10975-02-A01"]
    assert matched, f"unmatched: {report.get('unmatched_dxf')}"
    part = out["manufacturing_writeup"]["parts"][0]
    assert part.get("bend_count_dxf") == 2
    assert str(part.get("dxf_source_file") or "").startswith("10975-02-A01")


def test_one_flat_matches_and_the_drawing_export_is_excluded_with_a_reason(tmp_path):
    """James's acceptance row, verbatim: stage BOTH real DXFs — exactly one manufacturing
    flat matches; the 0355255 export is recognised as a drawing of the part (content
    evidence: its dimension entities), never as a second flat and never as a bare
    'no part number' gap."""
    import shutil
    import drawing_job_merge as djm
    fx = os.path.join(os.path.dirname(__file__), "fixtures")
    flat = tmp_path / "10975-02-A01_2mm ACRY_Rev B.DXF"
    export = tmp_path / "0355255 - A4 Table Top Graphic Holder - 10975_REV B.DXF"
    shutil.copy(os.path.join(fx, "1097502A01_2mm_ACRY_Rev_B.DXF"), flat)
    shutil.copy(os.path.join(fx, "0355255 - A4 Table Top Graphic Holder - 10975_REV B.DXF"),
                export)
    summary = {"manufacturing_writeup": {"parts": [
        {"part_number": "10975-02-A01", "description": "L-STAND",
         "normalized_material": "ACRYLIC"},
        {"part_number": "10975-02-GA", "description": "L-STAND ASSEMBLY",
         "is_assembly_parent": True},
    ]}}
    out = djm.augment_summary_with_dxf(summary, [str(flat), str(export)])
    report = out.get("dxf_augmentation") or {}
    matched_pns = {str(m.get("part_number", "")).upper()
                   for m in report.get("matched", []) if m.get("part_number")}
    assert matched_pns == {"10975-02-A01"}, f"exactly one flat: {matched_pns}"
    skipped = [s for s in report.get("skipped", [])
               if s.get("reason") == "drawing_export_not_a_flat"]
    assert skipped and "dimension" in str(skipped[0].get("detail", "")), \
        f"the export must carry its content evidence: {report.get('skipped')}"
    assert not any("0355255" in str(u.get("path", ""))
                   for u in report.get("unmatched_dxf", [])), \
        "the export is a recognised kind of file, not an unmatched gap"


def test_the_gauge_conflict_is_visible_whichever_side_wins():
    """Matching the DXF restores the 2 mm EVIDENCE — it must not silently settle the
    gauge. Whichever reader wins the rank fight, the disagreement stays a decision."""
    import source_precedence as sp
    dxf_won = {"part_number": "10975-02-A01"}
    sp.apply_field(dxf_won, "normalized_thickness_mm", 2.0, "dxf_filename")
    sp.apply_field(dxf_won, "normalized_thickness_mm", 3.0, "solidworks_flat_pattern")
    d = cf.thickness_conflict(dxf_won)
    assert d and "2 mm" in d["issue"] and "3 mm" in d["issue"]
