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


# ── the 17:11 replay's four binds — that run's own record shapes, no new matchers ────────

def _live_seventeen_eleven_parts():
    """The costed population as the 17:11 log printed it — the records the binds must
    act on, not fixture-friendly reconstructions."""
    return [
        {"part_number": "10975-02-A01", "description": "L-STAND",
         "normalized_material": "ACRYLIC", "quantity": 1,
         "geometry_source": "dxf_flat_pattern", "geometry_reliability": 1.0,
         "geometry_rollup": {"estimated_cut_length_mm": 1937.07,
                             "estimated_hole_count": 0,
                             "estimated_bend_line_count": 2}},
        {"part_number": "10975-02-G01", "description": "GRAPHIC",
         "normalized_material": "PAPER", "quantity": 1,
         "page_roles": ["detail", "bought_in"]},
        {"part_number": "10975EPDMCLOSEDCELL",
         "description": "Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C LENGTH: 200.00",
         "normalized_material": "ACRYLIC", "quantity": 3},
        {"part_number": "1100997755-E0P2D-GM0", "description": "1Closed GRAPHIC",
         "quantity": 1, "page_roles": ["bought_in"]},
        {"part_number": "CELL TAPE^10975-02-",
         "description": "EPDM TAPE 25X1MM - TAPE 113C LENGTH: 220.00",
         "normalized_material": "ACRYLIC", "quantity": 3,
         "operations": ["handling"], "pages": [1]},
    ]


def test_the_live_tape_records_fold_to_one_line_with_the_length_decision():
    """Bind 2. p.1 says LENGTH 200, p.4 says 220 — two BOM tables naming one commodity.
    The graph aliased them for two runs while the sheet still priced both; the fold must
    reach the RECORDS: one tape line survives, the other's evidence lands on it, and the
    length disagreement is a recorded conflict, never a silent choice."""
    parts = _live_seventeen_eleven_parts()
    rc.apply_canonical_evidence_to_parts(parts)
    tapes = [p for p in parts if "EPDM" in str(p.get("description", "")).upper()
             or "TAPE" in str(p.get("part_number", "")).upper()]
    assert len(tapes) == 1, \
        f"one tape line, got {[p['part_number'] for p in tapes]}"
    survivor = tapes[0]
    conflicts = str(survivor.get("_bom_numeric_conflicts") or [])
    assert "200" in conflicts and "220" in conflicts, \
        f"the 200 vs 220 length fight must be recorded: {conflicts!r}"
    assert any("folded into this line" in str(f)
               for f in survivor.get("review_flags") or []), \
        "the fold leaves its evidence on the survivor"
    assert survivor.get("pages") == [1], \
        "the dropped record's page evidence must fill the survivor's gap"


def test_the_chimera_leaves_the_costed_population_not_only_the_graph():
    """Bind 1. The 17:11 log dropped 1100997755-E0P2D-GM0 twice and the Estimate sheet
    still carried it — the drop forgot the identity while the record stayed priced. The
    quarantine must remove the record itself."""
    parts = _live_seventeen_eleven_parts()
    rc.apply_canonical_evidence_to_parts(parts)
    assert not any(p.get("part_number") == "1100997755-E0P2D-GM0" for p in parts), \
        "the zipped BOM row must leave the population the sheet is built from"
    assert any(p.get("part_number") == "10975-02-G01" for p in parts), \
        "the real graphic survives"


def test_the_quarantine_reaches_every_list_and_keeps_the_evidence():
    """Bind 1, the post-reconciliation half: the dual-path reader re-adds the row to
    part_estimates AFTER the pre-cost purge, so the quarantine must take issues from the
    final recompile and clear BOTH lists — filing the record on the summary, never a
    silent delete."""
    issues = [{"code": "bom_row_interleave_artifact",
               "identity": "1100997755-E0P2D-GM0", "detail": "zipped"}]
    parts = [{"part_number": "1100997755-E0P2D-GM0", "description": "1Closed GRAPHIC"},
             {"part_number": "10975-02-G01", "description": "GRAPHIC"}]
    estimates = [{"part_number": "1100997755-E0P2D-GM0", "unit_estimate": 0.0},
                 {"part_number": "10975-02-G01", "unit_estimate": 0.0}]
    summary: dict = {}
    removed = rc.quarantine_interleave_artefacts([parts, estimates], issues,
                                                 summary=summary)
    assert len(removed) == 2
    assert [p["part_number"] for p in parts] == ["10975-02-G01"]
    assert [e["part_number"] for e in estimates] == ["10975-02-G01"]
    stored = summary.get("quarantined_interleave_artefacts") or []
    assert stored and stored[0]["part_number"] == "1100997755-E0P2D-GM0"
    assert stored[0]["reason"] == "bom_row_interleave_artifact"


def test_nobody_is_asked_for_the_phantoms_drawing():
    """The 17:11 blocker told Tim to chase Design for 1100997755-E0P2D-GM0's detail
    sheet. A quarantined chimera is not a missing drawing."""
    import invariants
    summary = {
        "document_analysis": {"bom_rows": [
            {"part_number": "1100997755-E0P2D-GM0", "description": "1Closed GRAPHIC",
             "quantity": 1},
        ]},
        "pages": [],
        "manufacturing_writeup": {"parts": []},
        "quarantined_interleave_artefacts": [
            {"part_number": "1100997755-E0P2D-GM0",
             "reason": "bom_row_interleave_artifact"}],
    }
    out = invariants.check_the_pack_contains_the_drawings_its_bom_names(summary)
    assert not any("1100997755" in str(v) for v in out), \
        f"the phantom must not raise a missing-drawing blocker: {out}"
    # And WITHOUT the quarantine record the same row still blocks — the skip is
    # evidence-gated, not a blanket pardon.
    summary.pop("quarantined_interleave_artefacts")
    out = invariants.check_the_pack_contains_the_drawings_its_bom_names(summary)
    assert any("1100997755" in str(v) for v in out)


def test_the_model_named_parent_is_minted_and_holds_only_real_children():
    """The GA is an assembly page, not a part record, so the model's three edges reported
    NOT APPLIED while every child they named sat in the job. The parent is minted from
    the model's own tree — but only when a child names an existing job part, and it holds
    only those children: a model in the folder that nothing claims stays out."""
    from types import SimpleNamespace
    import source_connectors.solidworks as sw
    parts = [
        {"part_number": "10975-02-A01", "description": "L-STAND"},
        {"part_number": "10975-02-G01", "description": "GRAPHIC"},
    ]
    job = SimpleNamespace(hierarchy={"10975-02-GA": [
        ("10975-02-A01", 1.0), ("10975-02-G01", 1.0), ("10975-02-X01", 1.0)]})
    stamped = sw.apply_native_hierarchy_to_parts(parts, job)
    ga = next((p for p in parts if p.get("part_number") == "10975-02-GA"), None)
    assert ga is not None, "the model's parent must gain a record to hold its children"
    assert ga.get("is_assembly_parent") and ga.get("is_sub_assembly")
    kids = {str(c).upper() for c in ga.get("assembly_children") or []}
    assert kids == {"10975-02-A01", "10975-02-G01"}, \
        f"only children that name job parts belong: {kids}"
    assert any(s.get("part_number") == "10975-02-GA" for s in stamped)
    # A tree whose children name NOTHING in the job mints nothing.
    lonely = [{"part_number": "7332-01-001"}]
    sw.apply_native_hierarchy_to_parts(
        lonely, SimpleNamespace(hierarchy={"9999-99-GA": [("9999-99-A01", 1.0)]}))
    assert len(lonely) == 1, "a foreign tree must not invent an assembly"


def test_scraping_on_acrylic_is_acrylic_bench_work_not_metal():
    """SCRAPED EDGES inferred a deburr, and deburr had no acrylic entry — a £31.18/hr
    Manual labour (Metal) row landed on an all-acrylic job beside the acrylic manual row.
    Same department now, so the two share one tooling group: one row, one set-up."""
    import wb_populate as wbp
    assert wbp._map_operation("deburring", True) == "Manual labour (Acrylic)"
    assert wbp._map_operation("deburr", True) == "Manual labour (Acrylic)"
    assert wbp._map_operation("deburring", False) == "Manual labour (Metal)", \
        "steel deburr stays on the metal bench"


def test_the_pack_row_takes_the_family_of_the_parts_it_packs():
    """The assembly decision's representative was the bay root with no material, so the
    17:11 pack row priced as Assemble/pack (Metal) on an all-acrylic job."""
    import wb_populate as wbp
    estimates = {
        "10975": {},
        "10975-02-A01": {"normalized_material": "ACRYLIC"},
        "10975-02-G01": {"normalized_material": "PAPER"},
    }
    mat, is_acr = wbp._group_material_family(
        ["10975", "10975-02-A01", "10975-02-G01"], estimates, {}, "")
    assert is_acr, "no metal in the group and an acrylic member — the acrylic bench"
    assert mat, "the group must yield a material for the row description"
    # One steel member and the metal bench stands, exactly as every metal job prices today.
    estimates["BRACKET"] = {"normalized_material": "MILD STEEL"}
    _, is_acr = wbp._group_material_family(
        ["BRACKET", "10975-02-A01"], estimates, {}, "")
    assert not is_acr
    # A single part with its own stated material keeps its own answer.
    mat, is_acr = wbp._group_material_family(
        ["10975-02-A01"], estimates, {}, "MILD STEEL")
    assert mat == "MILD STEEL" and not is_acr


def test_a_variant_provenance_summary_carries_that_variants_totals():
    """The variants inherit the baseline's AI Provenance from the SaveAs, so the 50-off
    file audited itself against the 1-off headline. The overlay hands the sheet-writer
    the sweep's Excel-calculated figures without touching the run's own record."""
    import quantity_sweep as qs
    summary = {"estimate_summary": {"final_estimate": {"totals": {
        "material_gbp": 7.641, "labour_gbp": 56.2901, "unit_gbp": 68.7431}}},
        "other": "untouched"}
    row = {"quantity": 50, "material": 7.64, "labour": 3.92, "unit": 12.44}
    out = qs.variant_summary_with_totals(summary, row)
    got = out["estimate_summary"]["final_estimate"]["totals"]
    assert got["unit_gbp"] == 12.44 and got["labour_gbp"] == 3.92
    base = summary["estimate_summary"]["final_estimate"]["totals"]
    assert base["unit_gbp"] == 68.7431, "the run's own record must never be rewritten"
    assert qs.variant_summary_with_totals(summary, None) is summary
    import costed_facts as _cf
    assert _cf.job_totals(out)["unit_gbp"] == 12.44, \
        "the provenance writer reads job_totals — the overlay must reach it"


_P1_ROW = {"part_number": "10975 EPDM Closed",
           "description": "Cell Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C "
                          "LENGTH: 200.00"}


def test_bi_fragments_of_a_wrapped_bom_row_fold_into_the_line_that_owns_it():
    """08:08's new ghosts: the late BI- minting pass turned the wrap fragments 'Cell
    Tape' and 'Closed Cell Tape' into two PRICED lines beside the real tape — £6.80 of
    phantom material. A BI- code whose whole wording sits inside one raw BOM row another
    bought-in line claims is that row re-read, not a second purchase."""
    survivor = {"part_number": "10975",
                "description": "Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C "
                               "LENGTH: 200.00", "quantity": 3}
    parts = [survivor,
             {"part_number": "BI-CELLTAPE", "description": "Cell Tape"},
             {"part_number": "BI-CLOSEDCELLTAPE", "description": "Closed Cell Tape"}]
    estimates = [dict(p) for p in parts]
    summary: dict = {}
    folded = rc.fold_bom_row_fragments([parts, estimates], [_P1_ROW], summary=summary)
    assert folded == ["BI-CELLTAPE", "BI-CLOSEDCELLTAPE"], folded
    assert [p["part_number"] for p in parts] == ["10975"]
    assert len(estimates) == 1
    assert len(summary.get("folded_bom_row_fragments") or []) == 2
    assert sum("fragment of this line's own BOM row" in str(f)
               for f in survivor.get("review_flags") or []) == 2


def test_a_bi_line_with_its_own_standing_is_not_folded():
    """The fold is for wrap fragments only: a BI- line whose wording is NOT inside a
    claimed row, or whose would-be survivor is fabricated, stays a real line."""
    fabricated = {"part_number": "7332-01-001", "description": "FOOTPLATE BRACKET",
                  "flat_pattern_detected": True, "normalized_material": "MILD STEEL"}
    bi = {"part_number": "BI-FOOTPLATE", "description": "Footplate"}
    parts = [fabricated, bi]
    folded = rc.fold_bom_row_fragments(
        [parts], [{"part_number": "7332-01-001",
                   "description": "FOOTPLATE BRACKET WITH FOOTPLATE PAD FITTED"}])
    assert folded == [], "a fabricated claimant cannot absorb a purchase line"
    assert len(parts) == 2


def test_matching_figures_with_extra_context_are_not_a_contradiction():
    """08:08 raised a phantom '200 vs 200' decision beside the real 200-vs-220 one: the
    survivor's own part prefix (10975) counted as a disagreeing figure. Only two sets
    that EACH hold a number the other lacks are two answers to one question."""
    assert not rc._numeric_sets_contradict({"10975", "200"}, {"200"})
    assert rc._numeric_sets_contradict({"10975", "200"}, {"220"})
    assert not rc._numeric_sets_contradict(set(), {"200"})
    # And through the live pass: same length twice, different spellings — no decision.
    host = {"description": "Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C LENGTH: 200.00"}
    aliases = rc._raw_identity_aliases(
        {"10975EPDMCLOSEDCELL": host,
         "CELL TAPE^10975-02-": {"description": "EPDM TAPE 25X1MM - TAPE 113C "
                                                "LENGTH: 200.00"}}, {})
    assert aliases.get("CELL TAPE^10975-02-") == "10975EPDMCLOSEDCELL"
    assert not host.get("_bom_numeric_conflicts"), \
        "agreement plus context is not a manufacturing decision"


def test_one_bench_visit_books_one_setup():
    """08:08 charged Manual labour (Acrylic) twice on A01 — the sequenced deburr and the
    sequence-less route rule each minted a group, two 15-minute set-ups for one visit to
    one bench. The sequence-less decision joins its department's existing group."""
    import wb_populate as wbp
    payload = {"nodes": [], "decisions": [
        {"decision_id": "d1", "operation": "deburring", "target_id": "10975-02-A01",
         "participants": ["10975-02-A01"], "status": "required", "scope": "part",
         "sequence": 20, "qty_per_unit": 1},
        {"decision_id": "d2", "operation": "manual_labour_acrylic",
         "target_id": "10975-02-A01", "participants": ["10975-02-A01"],
         "status": "required", "scope": "part", "sequence": None, "qty_per_unit": 1},
    ]}
    summary = {"estimate_summary": {"canonical_route_shadow": payload}}
    estimates = [{"part_number": "10975-02-A01", "normalized_material": "ACRYLIC",
                  "normalized_thickness_mm": 2.0}]
    groups = wbp.canonical_labour_groups(summary, estimates, 1)
    mana = [g for g in groups.values()
            if g.get("wb_op") == "Manual labour (Acrylic)"]
    assert len(mana) == 1, \
        f"one bench, one group; got {[g['group_key'] for g in groups.values()]}"
    assert set(mana[0]["decision_ids"]) == {"d1", "d2"}


def test_the_rows_own_ai_tag_keeps_the_market_warning_alive():
    """08:08: the sheet row said "[AI ESTIMATE - INDICATIVE, NOT A QUOTE]" while the part
    behind it, its provenance lost in the fold, classified 'source unrecorded' — so the
    headline stopped asking anyone to replace the figure. The row's own tag is a witness."""
    bare = {"part_number": "10975", "description": "EPDM TAPE"}
    tagged = cf._price_origin(bare, "bought_in", "bom", 4.37, 0.0, 13, False,
                              row_text="10975 Tape^10975-02-GA EPDM TAPE "
                                       "[AI ESTIMATE - INDICATIVE, NOT A QUOTE]")
    assert tagged["firmness"] == cf.INDICATIVE_MARKET, tagged
    plain = cf._price_origin(bare, "bought_in", "bom", 4.37, 0.0, 13, False,
                             row_text="10975 EPDM TAPE 25X1MM")
    assert plain["firmness"] != cf.INDICATIVE_MARKET, \
        "an untagged row must not invent a market classification"


def test_price_provenance_travels_with_the_fold():
    """The folded member carried the price_source; the survivor had a material_estimate of
    its own with none — and the generic fill-empty copy kept neither."""
    parts = [
        {"part_number": "10975EPDMCLOSEDCELL",
         "description": "Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C LENGTH: 200.00",
         "normalized_material": "ACRYLIC", "quantity": 3,
         "material_estimate": {"material": "EPDM"}},
        {"part_number": "CELL TAPE^10975-02-",
         "description": "EPDM TAPE 25X1MM - TAPE 113C LENGTH: 220.00",
         "normalized_material": "ACRYLIC", "quantity": 3,
         "material_estimate": {"cost_method": "llm_market_estimate",
                               "price_source": {"source_name": "xAI Grok LLM",
                                                "source_type": "market"}}},
    ]
    rc.apply_canonical_evidence_to_parts(parts)
    assert len(parts) == 1
    me = parts[0].get("material_estimate") or {}
    assert (me.get("price_source") or {}).get("source_name") == "xAI Grok LLM", \
        "the survivor must inherit the price provenance it lacked"


def test_the_report_tree_shows_no_phantom_members():
    """The report's hierarchy printed 1100997755-E0P2D-GM0 and the folded tape spelling as
    members with dashes in every column — graph edges with no line and no record behind
    them. A member is a line, not an edge."""
    import job_report_html as jrh
    summary = {
        "quarantined_interleave_artefacts": [
            {"part_number": "1100997755-E0P2D-GM0"}],
        "folded_bom_row_fragments": [{"part_number": "BI-CELLTAPE"}],
        "estimate_summary": {"canonical_route_shadow": {"nodes": [
            {"part_number": "10975-02-GA", "kind": "assembly", "parents": []},
            {"part_number": "10975-02-A01", "kind": "leaf", "parents": ["10975-02-GA"]},
            {"part_number": "1100997755-E0P2D-GM0", "kind": "bought_in",
             "parents": ["10975-02-GA"]},
            {"part_number": "BI-CELLTAPE", "kind": "bought_in",
             "parents": ["10975-02-GA"]},
        ]}},
        "manufacturing_writeup": {"parts": [
            {"part_number": "10975-02-GA", "description": "assembly"},
            {"part_number": "10975-02-A01", "description": "L-STAND"},
        ]},
    }
    record = {"lines": [
        {"part_number": "10975-02-GA", "identity": "10975-02-GA", "kind": "assembly"},
        {"part_number": "10975-02-A01", "identity": "10975-02-A01", "kind": "leaf",
         "charged_ext_gbp": 2.12},
    ], "run": {}}
    html = jrh._render_bom_tree(summary, record)
    assert "1100997755" not in html, "a quarantined edge must not render as a member"
    assert "BI-CELLTAPE" not in html, "a folded fragment must not render as a member"
    assert "10975-02-A01" in html


def test_a_variant_tab_scales_the_labour_rows_not_only_the_headline(tmp_path):
    """08:08's 50-off Explanation printed the 1-off £13.56 Linebend against its own £2.51
    labour total. Every term of the sheet's arithmetic is on the row, so the variant's
    rows are computed with the variant's quantity."""
    import json
    import openpyxl
    import estimate_explained
    wb = openpyxl.Workbook()
    wb.active.title = "Estimate"
    wb.active["D6"] = 50
    xlsx = tmp_path / "10975-02_qty50.xlsx"
    wb.save(xlsx)
    job = {"final_estimate": {
        "totals": {"material_gbp": 22.55, "labour_gbp": 40.38, "unit_gbp": 67.68},
        "labour_rows": [{"operation": "Linebend", "dept": "LINE",
                         "setup_minutes": 30, "batch_hours": 0.533333,
                         "dept_rate_gbp_per_hour": 25.43,
                         "total_value_gbp": 13.56}],
    }}
    jp = tmp_path / "10975-02.json"
    jp.write_text(json.dumps(job), encoding="utf-8")
    md = estimate_explained.build(
        xlsx, jp, totals_override={"quantity": 50, "baseline_quantity": 1,
                                   "material": 22.55, "labour": 2.51, "unit": 26.95})
    assert "13.56" not in md, "the baseline row money must not survive on a variant"
    # batch(50) = 0.5h set-up + 50 x 0.0333h run = 2.1667h; x £25.43 / 50 = £1.10/unit
    assert "1.10" in md, "the variant's own per-unit row money must be printed"
    assert "26.95" in md


def test_drill_yields_to_the_runs_own_geometry_rollup_keys():
    """Bind 3. The 17:11 record carries the count as geometry_rollup.estimated_hole_count
    on a dxf_flat_pattern read — the exact keys the £13.40 Drill line ignored."""
    class _T:
        operation = "hole_machining"
        source = "drawing_notes"
    live = {"geometry_source": "dxf_flat_pattern", "geometry_reliability": 1.0,
            "geometry_rollup": {"estimated_hole_count": 0,
                                "estimated_bend_line_count": 2},
            "description": "L-STAND"}
    assert rc._unsupported_drill_reason(_T(), live), \
        "zero measured holes on the flat and no note — the drill claim must fall"
    holed = dict(live, geometry_rollup={"estimated_hole_count": 4})
    assert rc._unsupported_drill_reason(_T(), holed) is None, \
        "measured holes keep the operation"
