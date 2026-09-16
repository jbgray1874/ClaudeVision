"""Three of the estimator's 7332-01 points: one op that should not be there, two the drawing
never mentions.

    "Line 103 - Tube Bending Op. – Not Required."
    "Line 67 / Line 100 – 0.9mm Steel Production use 1mm in Lieu – TBC"
    "Line 85 – Drawing doesn't annotate – material is brushed prior to sending to platers,
     op. for Manual Labour (Metal) 40 Minutes – Grey area as drawing only nominates a finish
     as Harrods01"

THE TUBE BEND COMES OFF, because nothing says it bends. tube_bending is not inferred from
geometry the way folding is — it arrives from the drawing READ, so a mention near a tube is
enough to charge the tube-bender, its rate and its 45-minute set-up. 7332-01-002 booked two
bends on a straight leg. The gate is the standard the fold rule already applies: any bend
evidence keeps the op, none of it takes the op off, out loud.

THE OTHER TWO ARE FLAGS AND NOT REWRITES. Each is something a person told us about one job,
neither is on the drawing, and acting on either silently would be this engine inventing a
spec — a substituted gauge nobody bought, or forty minutes of labour nobody asked for. Both
are raised where a person can rule, and the figures stay exactly as drawn.

None of this can reach a job with no tube, no thin-gauge steel and no plating.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from estimator import estimate_process_times                            # noqa: E402


def _tube(**over):
    part = {"part_number": "7332-01-002", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.2, "textual_operations": ["tube_bending", "handling"],
            "material_estimate": {"stock_form": "tube"}}
    part.update(over)
    return part


def _flags(part):
    return " ".join(str(f) for f in part.get("review_flags") or [])


# ── the tube bend that was not required ──────────────────────────────────────────────────

def test_a_straight_tube_is_not_charged_a_bend():
    part = _tube()
    out = estimate_process_times(part)
    assert "tube_bending" not in out["run_times_min_per_unit"]
    assert "tube_bending" not in (part.get("textual_operations") or [])
    assert "tube_bending" in (part.get("removed_operations") or [])


def test_it_says_why_and_what_would_bring_it_back():
    part = _tube()
    estimate_process_times(part)
    assert "nothing on this part states a bend" in _flags(part)
    assert "the drawing needs to say so" in _flags(part)


def test_any_evidence_of_a_bend_keeps_the_op():
    for ev in ({"manufacturing_features": {"bend_count": 2}},
               {"bend_count_dxf": 1},
               {"angles_deg": [90]},
               {"fold_count_textual": 3}):
        part = _tube(**ev)
        estimate_process_times(part)
        assert "tube_bending" in (part.get("textual_operations") or []), ev


# ── kept on a word alone, and still worth asking about ───────────────────────────────────
#
# "Line 103 - Tube Bending Op. – Not Required." The gate above only removes the op where
# NOTHING states a bend, and 7332-01-002 is the other case: the drawing text states one and
# no measurement backs it — no bend line in a DXF, no angle callout. The op stays, because
# the drawing did say something and deleting charged work on one estimator's disagreement
# with one drawing is how a rule stops describing anything. But the tube-bender is £32.84 an
# hour with a 45-minute set-up, and a word is weaker evidence than a measurement, so the
# weak case costs a sentence.

def test_a_bend_stated_in_words_only_is_charged_and_raised():
    part = _tube(fold_count_textual=2)
    estimate_process_times(part)
    assert "tube_bending" in (part.get("textual_operations") or [])   # still charged
    assert "CHARGED on the drawing's word alone" in _flags(part)
    assert "Confirm the leg actually bends" in _flags(part)


def test_a_measured_bend_is_not_second_guessed():
    """A DXF bend line or the model's own bend count IS the measurement. Flagging those
    would put a question on every bent tube in the shop, which is noise, not review.
    An angle callout is deliberately NOT in this list any more — on 7332-01-002 the 45s
    described the mitre saw cut, and Howard's answer was 'Not Required'."""
    for ev in ({"bend_count_dxf": 1},
               {"manufacturing_features": {"bend_count": 2}},
               {"bend_count_dxf": 2, "angles_deg": [45, 45]}):
        part = _tube(**ev)
        estimate_process_times(part)
        assert "tube_bending" in (part.get("textual_operations") or []), ev
        assert "word alone" not in _flags(part), ev


def test_a_mitred_square_leg_with_angle_callouts_gets_no_bend():
    """HOWARD'S EXACT CASE. 7332-01-002 is a 15.88 square section; its 45° callouts are
    the mitre cut. The tube-bender wraps round/oval tube to a radius — a square leg whose
    only evidence is angles comes off, saying what would bring it back."""
    part = _tube(section_stock={"a": 15.88, "b": 15.88, "t": 1.2},
                 angles_deg=[45.0, 45.0])
    estimate_process_times(part)
    assert "tube_bending" in (part.get("removed_operations") or [])
    f = _flags(part)
    assert "mitred" in f and "radius" in f
    assert "Not Required" in f, "his ruling is cited, so the rule shows its source"


def test_a_round_tube_with_a_radius_is_bent_without_a_question():
    """Round section + radius callout is what the bender exists for — the two things the
    rule requires, both present, no noise."""
    part = _tube(section_stock={"a": 12.7, "b": 12.7, "t": 1.2, "profile_form": "CHS"},
                 radii_mm=[50.0])
    estimate_process_times(part)
    assert "tube_bending" in (part.get("textual_operations") or [])
    assert "word alone" not in _flags(part)
    assert "removed" not in _flags(part)


def test_an_angle_on_a_round_tube_keeps_the_op_and_asks_for_the_radius():
    """A round tube CAN be what the angle describes — removing it on shape alone would
    delete real work. It stays, and the ask names what is missing."""
    part = _tube(section_stock={"a": 12.7, "b": 12.7, "t": 1.2, "profile_form": "CHS"},
                 angles_deg=[90.0])
    estimate_process_times(part)
    assert "tube_bending" in (part.get("textual_operations") or [])
    assert "round section, no radius" in _flags(part)


def test_a_removed_bend_is_not_also_queried():
    """The two states are exclusive: it either came off with its reason, or it stayed with
    its question. Both on one part would be the sheet arguing with itself."""
    part = _tube()
    estimate_process_times(part)
    assert "tube bending removed" in _flags(part)
    assert "word alone" not in _flags(part)


def test_a_part_with_no_tube_bend_op_is_untouched():
    part = {"part_number": "X", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "textual_operations": ["laser_cutting"]}
    estimate_process_times(part)
    assert not part.get("removed_operations")


# ── 0.9 mm: a confirmed production rule, costed at what the shop buys ────────────────────
#
# While Howard's "0.9mm Steel Production use 1mm in Lieu" was TBC, the engine flagged and
# costed as drawn. His 15 Sep reply confirmed the practice, so it is now a rule
# (config.PRODUCTION_MATERIAL_SUBSTITUTIONS): the substitute gauge is costed — 0.9 mm
# cannot be bought, and pricing a gauge the buyer cannot order under-charges the
# difference — with the drawn figure kept on the part and named in the flag. A person
# still outranks it: an estimator-confirmed thickness stands the rule down.

def test_a_zero_nine_gauge_is_costed_at_the_one_mm_the_shop_buys():
    from estimator import apply_production_substitutions
    part = {"part_number": "7332-01-008", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 0.9, "textual_operations": ["laser_cutting"]}
    apply_production_substitutions(part)
    assert part["normalized_thickness_mm"] == 1.0, "costed at what production buys"
    assert part["drawn_thickness_mm"] == 0.9, "the drawn figure is kept, not erased"
    sub = part["production_substitution"]
    assert sub["rule_id"] == "steel_0.9_to_1.0"
    assert "Howard Thurley" in sub["stated_by"]
    f = _flags(part)
    assert "COSTED AT 1 mm" in f and "drawn at 0.9 mm" in f
    assert "production rule" in f and "stands down" in f, \
        "the flag must say how a person overrides it"


def test_an_estimator_confirmed_gauge_stands_the_rule_down():
    """A person's ruling outranks a production rule — the answers file simply states
    thickness_mm and the substitution does not happen, saying so."""
    import source_precedence as sp
    from estimator import apply_production_substitutions
    part = {"part_number": "7332-01-008", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 0.9}
    sp.apply_field(part, "normalized_thickness_mm", 0.9, "estimator_confirmed")
    apply_production_substitutions(part)
    assert part["normalized_thickness_mm"] == 0.9
    assert not part.get("production_substitution")
    assert "stood down" in _flags(part)


def test_an_unconfirmed_rule_only_flags_and_costs_as_drawn(monkeypatch):
    """The TBC behaviour is not deleted — it is what any rule does until a person
    confirms it."""
    import config
    from estimator import apply_production_substitutions
    _tbc = [dict(config.PRODUCTION_MATERIAL_SUBSTITUTIONS[0], status="tbc")]
    monkeypatch.setattr(config, "PRODUCTION_MATERIAL_SUBSTITUTIONS", _tbc)
    part = {"part_number": "X", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 0.9}
    apply_production_substitutions(part)
    assert part["normalized_thickness_mm"] == 0.9
    assert "Costed AS DRAWN" in _flags(part)


def test_the_substitution_reaches_the_gauge_the_money_is_derived_from():
    """END TO END: estimate_part itself. The whole point of substituting before the mass
    and the laser read the gauge is that every downstream figure uses 1.0 mm."""
    import estimator
    part = {"part_number": "7332-01-008", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 0.9, "quantity": 1,
            "blank_length_mm": 200, "blank_width_mm": 100,
            "textual_operations": ["laser_cutting"]}
    estimator.estimate_part(part, job_quantity=6)
    assert part["normalized_thickness_mm"] == 1.0
    assert part["drawn_thickness_mm"] == 0.9


def test_the_substituted_gauge_survives_a_later_reading_and_yields_to_a_person():
    """THE 17:36 BOOK. It printed 0.9 mm on every line of 7332-01-008 with the rule in
    the build: the first cut wrote 1.0 straight into the field and recorded no source, so
    any later pass re-applying the drawing's own gauge could put 0.9 back. The rule is now
    a SOURCE of its own — above every reading, below a person."""
    import source_precedence as sp
    from estimator import apply_production_substitutions
    part = {"part_number": "7332-01-008", "normalized_material": "MILD_STEEL"}
    sp.apply_field(part, "normalized_thickness_mm", 0.9, "dxf_flat_pattern")
    apply_production_substitutions(part)
    assert part["normalized_thickness_mm"] == 1.0
    assert sp.source_of(part, "normalized_thickness_mm") == "production_substitution"
    # a later DXF / model / BOM-tree pass cannot revert it
    for later in ("dxf_flat_pattern", "solidworks_api", "bom_tree", "dxf_filename"):
        sp.apply_field(part, "normalized_thickness_mm", 0.9, later)
        assert part["normalized_thickness_mm"] == 1.0, later
    # a person can
    sp.apply_field(part, "normalized_thickness_mm", 0.9, "estimator_confirmed")
    assert part["normalized_thickness_mm"] == 0.9


def test_a_normal_gauge_says_nothing():
    from estimator import apply_production_substitutions
    for g in (0.7, 1.2, 1.5, 2.5):
        part = {"part_number": "X", "normalized_material": "MILD_STEEL",
                "normalized_thickness_mm": g, "textual_operations": ["laser_cutting"]}
        apply_production_substitutions(part)
        assert "in lieu" not in _flags(part), g
        assert part["normalized_thickness_mm"] == g


# ── whether the welds are dressed is the customer's standard, not the shop's guess ───────
#
# "M&S dress all seen welds; TTI none" — Howard Thurley, 15 Sep 2026. A fact about the
# CUSTOMER, kept as a rule with his name on it, never a price. It governs the engine's
# inference only: a drawing that states dressing is never overruled by a customer default,
# and a customer not in the table keeps the shop default exactly as before.

def _weldment(**over):
    part = {"part_number": "W1", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 2.0, "quantity": 1,
            "textual_operations": ["welding"]}
    part.update(over)
    return part


def test_the_standard_resolves_however_the_folder_spelled_the_customer():
    from estimator import customer_finish_standard
    for spelling in ("M&S", "Marks & Spencer Ltd", "marks and spencer"):
        std = customer_finish_standard(spelling)
        assert std and std["customer"] == "M&S" and std["dress_visible_welds"], spelling
    assert customer_finish_standard("TTI Group UK")["dress_visible_welds"] is False
    assert customer_finish_standard("Harrods") is None, "not listed means shop default"


def test_a_tti_weldment_is_not_charged_dressing_and_says_whose_rule_that_is():
    from estimator import customer_finish_standard
    part = _weldment(_customer_finish_standard=customer_finish_standard("TTI"))
    out = estimate_process_times(part, 6)
    assert "dress_welds" not in out["run_times_min_per_unit"]
    f = _flags(part)
    assert "TTI" in f and "no weld dressing" in f and "Howard Thurley" in f
    assert "drawing that states dressing would still be charged" in f


def test_an_ms_weldment_is_dressed_and_credits_the_standard():
    from estimator import customer_finish_standard
    part = _weldment(_customer_finish_standard=customer_finish_standard("M&S"))
    out = estimate_process_times(part, 6)
    assert "dress_welds" in out["run_times_min_per_unit"]
    assert "M&S dress all seen welds" in _flags(part)


def test_an_unknown_customer_keeps_the_shop_default():
    part = _weldment()
    out = estimate_process_times(part, 6)
    assert "dress_welds" in out["run_times_min_per_unit"]


def test_a_drawing_that_states_dressing_outranks_the_customer_default():
    """TTI's standard suppresses the INFERENCE. It does not delete work the drawing
    itself calls up — the drawing outranks a customer default."""
    from estimator import customer_finish_standard
    part = _weldment(textual_operations=["welding", "dress_welds"],
                     _customer_finish_standard=customer_finish_standard("TTI"))
    out = estimate_process_times(part, 6)
    assert "dress_welds" in out["run_times_min_per_unit"]


# ── a plated part packs twice, as two operations on two rows ─────────────────────────────
#
# "Two separate Operations this job, items need to be packed to send to platers before"
# the final pack — Howard Thurley, 15 Sep 2026, answering "say if you would rather see
# them split". One combined 12-minute figure was the right money and the wrong record:
# neither 4 nor 8 could be checked against it, and the route never said the part leaves
# the building in the middle.

def test_a_plated_part_books_two_pack_operations():
    part = _weldment(normalized_finish="PLATED",
                     textual_operations=["welding", "assembly"])
    out = estimate_process_times(part, 6)
    rt = out["run_times_min_per_unit"]
    assert rt.get("plater_pack") == 4.0, rt
    assert rt.get("handling") == 8.0, rt
    assert "plater_pack" in (part.get("inferred_operations") or []), \
        "the op is recorded, so the route compiler carries it to its own row"
    f = _flags(part)
    assert "two operations on two rows" in f
    assert "Two separate Operations this job" in f, "his words travel with the split"


def test_an_unplated_part_packs_once():
    part = _weldment(textual_operations=["welding", "assembly"])
    out = estimate_process_times(part, 6)
    assert "plater_pack" not in out["run_times_min_per_unit"]


def test_the_plater_pack_reaches_its_own_department_row():
    """Executed against the real maps: same PACM bench, its own row title suffix so two
    Assemble/pack rows do not read as a double-charge."""
    import wb_populate as wb
    import department_codes
    assert wb.OP_NAME_MAP["plater_pack"] == "Assemble/pack (Metal)"
    assert department_codes.code_for("plater_pack") == "PACM"
    desc = wb.labour_row_description("Assemble/pack (Metal)", "MILD STEEL", None,
                                     ["7332-01-101"], work_ops=["plater_pack"])
    assert "pack to plater" in desc
    plain = wb.labour_row_description("Assemble/pack (Metal)", "MILD STEEL", None,
                                      ["7332-01-101"], work_ops=["handling"])
    assert "pack to plater" not in plain, "the final pack keeps the plain title"


# ── the acrylic peel allowance the shop says is not a thing ──────────────────────────────
#
# "Manual Labour Acrylic allowing – no additional op. on manual estimating sheet – is this
# Peel?" was the question, and Howard's answer names the rule: "Subjective – depends on
# component, peel may be incorporated into individual operations. Nothing fixed for this."
# A default the department itself calls not-fixed is the engine inventing a standing
# charge. Charged only where the drawing's own text states the work.

def _acrylic(**over):
    part = {"part_number": "7332-01-007", "description": "LENS",
            "normalized_material": "ACRYLIC", "normalized_thickness_mm": 3.0,
            "quantity": 2, "blank_length_mm": 300, "blank_width_mm": 200,
            "textual_operations": ["laser_cutting"]}
    part.update(over)
    return part


def test_an_acrylic_part_gets_no_default_peel_allowance():
    import estimator
    part = _acrylic()
    est = estimator.estimate_part(part, job_quantity=2)
    rt = (est.get("process_estimate") or {}).get("run_times_min_per_unit") or {}
    assert "manual_labour_acrylic" not in rt, rt
    f = _flags(part)
    assert "NO default handling/peel allowance charged" in f
    assert "Nothing fixed for this" in f, "his words travel with the decision"
    assert "state it with a time" in f, "the absence is reversible, and says how"


def test_a_drawing_that_states_the_peel_is_charged_for_it():
    import estimator
    part = _acrylic(process_notes=["PEEL PROTECTIVE FILM BOTH SIDES"])
    est = estimator.estimate_part(part, job_quantity=2)
    rt = (est.get("process_estimate") or {}).get("run_times_min_per_unit") or {}
    assert rt.get("manual_labour_acrylic"), rt
    assert "drawing's own text states it" in _flags(part)


def test_stainless_is_outside_what_howard_spoke_for():
    """0.9 mm stainless is a real buy. Widening a production fact past the person who
    stated it is the scoped-pilot-becoming-a-constant fault."""
    from estimator import apply_production_substitutions
    part = {"part_number": "X", "normalized_material": "STAINLESS_STEEL",
            "normalized_thickness_mm": 0.9}
    apply_production_substitutions(part)
    assert part["normalized_thickness_mm"] == 0.9
    assert not part.get("production_substitution")


# ── brushing before the platers: named, not added ────────────────────────────────────────

def test_a_plated_part_raises_the_brushing_nobody_drew():
    part = {"part_number": "7332-01-101", "normalized_material": "MILD_STEEL",
            "normalized_finish": "Harrods01", "textual_operations": ["handling"]}
    out = estimate_process_times(part)
    assert "brushes material before it goes to the platers" in _flags(part)
    assert "NOT costed here" in _flags(part)
    assert "manual_labour" not in out["run_times_min_per_unit"], "flagged, never added"


def test_an_unplated_part_raises_nothing():
    part = {"part_number": "12349-02-69-04M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.2, "normalized_finish": "powder coated",
            "textual_operations": ["handling"]}
    estimate_process_times(part)
    assert not (part.get("review_flags") or []), "a powder-coated part goes to no plater"


def test_the_whole_feeder_job_is_untouched_by_all_three():
    """12349-02 has no tube, no 0.9 mm steel and no plating. None of this can reach it."""
    for g, fin in ((1.2, "powder coated"), (1.5, "powder coated"), (5.0, "")):
        part = {"part_number": "12349-02-69-03M", "normalized_material": "MILD_STEEL",
                "normalized_thickness_mm": g, "normalized_finish": fin,
                "textual_operations": ["laser_cutting", "handling"]}
        estimate_process_times(part)
        assert not (part.get("review_flags") or []), (g, fin)
        assert not part.get("removed_operations"), (g, fin)
