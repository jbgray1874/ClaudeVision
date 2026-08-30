"""One panel, made twice, is one purchase — so it gets one stock key.

11650-04'S SIDE PANELS CAME BACK ON TWO DIFFERENT SHEETS. 01A resolved to 2.2mm and
01A-HANDED to 2.0mm, each from its own SolidWorks model, and the job then bought a sheet at
GBP 84.10 for one hand and GBP 60.21 for the other — of the same panel, in the same material,
on the same machine, in the same week. Nothing on the estimate said the two rows were the same
article.

THE MIRROR RULE COULD NOT FIX THIS AND WAS RIGHT NOT TO. It submits material and gauge at
`mirror_of_measured` (75), which correctly loses to a model at 90. Read as "fill what the hand
is missing", that is exactly right — and the hands were not missing anything. They each had an
answer and the answers disagreed. Precedence arbitrates sources within ONE record; it has
nothing to say about two records that must agree by construction.

THAT IS THE WHOLE POINT OF THIS RULE. Two hands of one part are not two facts about two
articles. They are one fact read twice, and where the readings differ one of them is wrong —
so resolving it per record produces two confident answers and two purchase orders.

DECIDED BY SUPPORT ACROSS THE PAIR, NOT BY RANK. Rank already had its turn inside each record
and produced the disagreement. What breaks the tie is how many distinct readings, across both
hands, name each key. Where neither side has more, NOTHING MOVES and a person is asked: a pair
split two-against-two is a drawing problem, and inventing an answer would hide it.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drawing_job_merge as merge  # noqa: E402
import source_precedence as sp  # noqa: E402

MAT, GAUGE = "normalized_material", "normalized_thickness_mm"


def _part(pn, material, gauge, extra=()):
    p = {"part_number": pn}
    sp.apply_field(p, MAT, material, "solidworks_api")
    sp.apply_field(p, GAUGE, gauge, "solidworks_api")
    for (mv, gv), src in extra:
        if mv:
            sp.apply_field(p, MAT, mv, src)
        if gv:
            sp.apply_field(p, GAUGE, gv, src)
    return p


def _key(p):
    return (p.get(MAT), p.get(GAUGE))


def _pair_as_the_pack_reads():
    """11650-04 as the drawing actually issues it: one sheet covering both hands, so the
    title block is on the record of each, and the base carries the exported flat."""
    base = _part("11650-04-01A", "ABS", 2.2,
                 extra=[(("PETG", None), "drawing_deterministic"),
                        (("PETG", 2.0), "dxf_filename")])
    hand = _part("11650-04-01A-HANDED", "ABS", 2.0,
                 extra=[(("PETG", None), "drawing_deterministic")])
    return base, hand


# ── the defect, stated as the test ───────────────────────────────────────────────────

def test_the_two_hands_end_on_one_stock_key():
    base, hand = _pair_as_the_pack_reads()
    assert _key(base) != _key(hand), "the pair no longer splits; this test is blind"
    merge.settle_handed_pairs([base, hand])
    assert _key(base) == _key(hand) == ("PETG", 2.0)


def test_the_whole_key_moves_or_none_of_it_does():
    """Taking the material from one hand and the gauge from the other is how you arrive at a
    stock item nobody stocks — the defect `settle_companion_facts` exists for, one level up."""
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    assert _key(hand) in {("PETG", 2.0), ("ABS", 2.0)}, "a key was assembled from both hands"
    assert _key(hand) == _key(base)


def test_the_hand_that_moved_says_so_and_names_its_evidence():
    """Either mechanism may carry it — the pooled quorum where the pair's readings reach two,
    the key comparison where they do not — but a purchase key that changed must say so and
    name what changed it."""
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    flags = [f for f in hand.get("review_flags", []) if "HANDED PAIR" in f]
    assert flags, "a purchase key changed and nothing on the part says so"
    assert any("dxf_filename" in f or "11650-04-01A" in f for f in flags)


def test_what_it_displaced_is_kept():
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    said = {str(e["value"]) for e in sp.displaced_values(hand, MAT)}
    assert "ABS" in said, "the hand's own model reading was erased rather than overruled"


def test_the_report_names_the_pair_and_the_outcome():
    base, hand = _pair_as_the_pack_reads()
    out = merge.settle_handed_pairs([base, hand])
    assert out, "the pair was reconciled and the report says nothing"
    assert {o["outcome"] for o in out} <= {"pooled_quorum", "settled", "undecided"}
    assert any(o.get("value") == "PETG" or o.get("stock_key") == ["PETG", 2.0] for o in out)


# ── what it must NOT do ──────────────────────────────────────────────────────────────

def test_two_against_two_changes_nothing_and_asks():
    """A pair split evenly is a drawing problem. Picking a side would make the answer depend
    on which hand was read first, and hide the thing a person has to settle."""
    base = _part("02A", "ABS", 2.0)
    hand = _part("02A-HANDED", "PETG", 2.0)
    out = merge.settle_handed_pairs([base, hand])
    assert _key(base) == ("ABS", 2.0) and _key(hand) == ("PETG", 2.0)
    assert out and out[0]["outcome"] == "undecided"
    assert any("HANDED PAIR DISAGREES" in f for f in hand.get("review_flags", []))
    assert any("HANDED PAIR DISAGREES" in f for f in base.get("review_flags", []))


def test_a_mirror_is_not_a_second_opinion():
    """A COPY OF THE OTHER HAND CANNOT CORROBORATE IT. Mirroring writes the base's own reading
    onto the hand wearing a different source name; counted as independent, a wrong base becomes
    unanimous. Here the hand's measured DXF says PETG and the mirror has already carried the
    base's ABS onto its record — so ABS would show two voices where there is one reading seen
    twice, and would drag the hand off the only measurement in the pair."""
    base = _part("08A", "ABS", 2.0)
    hand = {"part_number": "08A-HANDED"}
    sp.apply_field(hand, GAUGE, 2.0, "dxf")
    sp.apply_field(hand, MAT, "ABS", "mirror_of_measured")
    sp.apply_field(hand, MAT, "PETG", "dxf")          # measured, and it wins on rank
    assert hand[MAT] == "PETG", "this test is looking at the wrong state"
    merge.settle_handed_pairs([base, hand])
    assert hand[MAT] == "PETG", "the mirror voted, and its own base outvoted a measurement"


def test_a_hand_is_stamped_with_its_own_reading_not_the_other_drawings():
    """Both hands read PETG, but from DIFFERENT sources — the base off its title block, the
    hand off the export it is cut from. Stamping the hand with the base's title block would
    credit a reading of the other drawing and lose the record that this hand was independently
    right, which is the thing a person checks when they disagree with the answer."""
    base = _part("09A", "ABS", 2.0, extra=[(("PETG", None), "drawing_deterministic")])
    hand = _part("09A-HANDED", "ABS", 2.0, extra=[(("PETG", None), "dxf_filename"),
                                                  (("PETG", None), "llm_extract")])
    # Three readings name PETG against two models. Two-against-two would correctly refuse to
    # move — the pair must be OUTWEIGHED, not merely contradicted.
    merge.settle_handed_pairs([base, hand])
    assert base[MAT] == hand[MAT] == "PETG"
    assert sp.source_of(base, MAT) == "drawing_deterministic"
    # The hand must name a source of ITS OWN. `drawing_deterministic` is the base's title
    # block and belongs to the other drawing; crediting it here would lose the record that
    # this hand was independently right.
    assert sp.source_of(hand, MAT) in {"dxf_filename", "llm_extract"}


def test_hands_that_already_agree_are_left_entirely_alone():
    """The common case, and it must cost nothing and add no flag."""
    base = _part("03A", "PETG", 2.0)
    hand = _part("03A-HANDED", "PETG", 2.0)
    assert merge.settle_handed_pairs([base, hand]) == []
    assert not base.get("review_flags") and not hand.get("review_flags")


def test_a_hand_whose_base_is_not_in_the_job_is_not_settled_against_nothing():
    hand = _part("04A-HANDED", "ABS", 2.0)
    assert merge.settle_handed_pairs([hand]) == []
    assert _key(hand) == ("ABS", 2.0)


def test_a_missing_half_of_a_key_is_a_gap_not_a_disagreement():
    """A hand with no gauge at all has not disagreed about one. Filling it is the mirror
    rule's job, at its own rank, and this must not do it by the back door at full strength."""
    base = _part("05A", "PETG", 2.0)
    hand = {"part_number": "05A-HANDED"}
    sp.apply_field(hand, MAT, "PETG", "solidworks_api")
    assert merge.settle_handed_pairs([base, hand]) == []
    assert hand.get(GAUGE) is None


def test_a_pair_is_settled_once_not_once_per_direction():
    """Both records name each other in a job that holds both. Settling twice would displace
    the value it had just written and walk the key back and forth."""
    base, hand = _pair_as_the_pack_reads()
    out = merge.settle_handed_pairs([base, hand])
    again = merge.settle_handed_pairs([base, hand])
    assert out and again == [], "a second pass moved the key again"
    assert _key(base) == _key(hand) == ("PETG", 2.0)


def test_the_flag_counts_only_the_readings_that_are_actually_in_dispute():
    """A REPORTING RULE, NOT A DECIDING ONE — and my first test of it asserted the wrong
    thing, so a mutant that counted the agreed field passed. It cannot change the outcome: an
    agreed field holds the same value in both keys, so it adds the identical support to each
    side. What it changes is the number an estimator reads. Two readings on the base name PETG
    -- its title block and its export -- against one on the hand naming ABS; counting the gauge
    both hands agree on would print "4 against 3" and bury the disagreement in readings nobody
    disputes."""
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    flag = [f for f in hand["review_flags"] if "HANDED PAIR" in f][0]
    # Three independent readings name PETG across the pair -- the title block on each hand and
    # the export -- against two naming ABS, one model per hand. The mirror does not appear:
    # it is a copy of the base, not a second opinion.
    assert "3 independent sources" in flag, flag
    assert "mirror_of_measured" not in flag


def test_both_halves_of_a_disagreeing_key_move_together():
    """THE GUARD MY FIRST FIXTURE COULD NOT EXERCISE. Where the hands differed only in
    material, moving the material alone happened to land on the right gauge anyway, so a
    mutant that moved one field passed. Here the hands disagree on BOTH — and taking the
    winner's material with the loser's gauge produces PETG at 3.0mm, which is exactly the
    unstocked pair this whole seam exists to prevent."""
    base = _part("06A", "ABS", 3.0)
    hand = _part("06A-HANDED", "ABS", 3.0)
    sp.apply_field(base, MAT, "PETG", "drawing_deterministic")
    sp.apply_field(base, MAT, "PETG", "dxf_filename")
    sp.apply_field(base, GAUGE, 2.0, "dxf_filename")
    # The base still reads 3.0 here: its export's 2.0 lost to its own model on rank, and the
    # companion rule that corrects that runs inside the settlement, not before it.
    assert _key(base) == ("PETG", 3.0) and _key(hand) == ("ABS", 3.0)
    # And the base must WIN it: two readings for its answer against the hand's one. Counting
    # the base's own rejected ABS as evidence for the hand handed this pair to the model.
    merge.settle_handed_pairs([base, hand])
    assert _key(base) == _key(hand) == ("PETG", 2.0), "half the key moved and half stayed"


# ── the identity exit criterion, in code ─────────────────────────────────────────────
#
# Three clauses, and the pair ending on one key is only the first. A pair can agree on
# (material, gauge) and still be bought twice if the two records reach the catalogue by
# different keys; and a hand can carry the settled value while its record still says the
# model owns it, which is a lie about where the money came from and re-opens the argument
# the next time anything submits at rank 75.

def test_the_two_hands_reach_the_catalogue_by_the_same_key():
    """THE RATE KEY, NOT JUST THE FIELDS. The lookup is keyed on
    (_sheet_catalogue_token(material), round(gauge, 1)) — so two hands can hold equal-looking
    values and still land on different cache entries if either half normalises differently.
    This is the clause that actually decides whether the pair is bought once."""
    import estimator
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    keys = {(estimator._sheet_catalogue_token(p[MAT]), round(float(p[GAUGE]), 1))
            for p in (base, hand)}
    assert len(keys) == 1, f"the hands reach the catalogue by different keys: {keys}"


def test_the_two_hands_price_at_the_same_sheet_rate(monkeypatch):
    """The commercial statement of the same thing, and the number Tim reads. GBP 84.10 against
    GBP 60.21 for one panel made twice is the defect; one rate for both is the fix."""
    import estimator
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_CACHE[("PETG", 2.0)] = 9.63
    monkeypatch.setattr(estimator, "market_indication_for", lambda part, material: None)
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    rates = set()
    for p in (base, hand):
        p.update({"quantity": 1, "blank_length_mm": 1250.0, "blank_width_mm": 525.0,
                  "material_estimate": {}, "manufacturing_interpretation": {}})
        rates.add(estimator.estimate_material(p).get("sheet_price_gbp"))
    estimator._SHEET_RATE_CACHE.clear()
    assert len(rates) == 1 and rates != {None}, f"the pair split across sheet prices: {rates}"


def test_the_model_no_longer_owns_the_key_on_a_hand_that_was_settled():
    """A hand carrying the settled VALUE while its record still names the model as the source
    is a lie about where the money came from — and worse, it leaves a rank-90 owner on a datum
    the pair overruled, so the next pass to submit at rank 75 is refused all over again."""
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    # A HALF THE PAIR OVERRULED. Where the pair overturned a reading, the source that lost
    # must not still own the datum -- otherwise the record claims the model's authority for a
    # value the pair set aside, and the next submission at a lower rank is refused all over
    # again. A half the record already had RIGHT keeps its own honest provenance: the hand's
    # model said 2.0 and 2.0 won, so the model may keep it.
    assert sp.source_of(hand, MAT) != "solidworks_api", (
        "the material still belongs to the model on a hand the pair overruled")
    assert hand[MAT] == "PETG"


def test_the_hand_that_won_keeps_its_own_provenance():
    """Only the hand that TOOK the pair's answer records that it took it. The winner reached
    this key through its own readings, and restamping it would erase the one record that can
    say where the key actually came from — leaving a pair whose stock key traces to nothing."""
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    assert sp.source_of(base, MAT) == "dxf_filename"
    # And the hand carries ITS OWN reading of PETG, not the base's. Stamping it with the other
    # drawing's title block would lose the record that this hand was independently right.
    assert sp.source_of(hand, MAT) in {"drawing_deterministic", "dxf_filename"}


def test_nothing_is_recorded_as_displaced_where_nothing_was():
    """Half a key usually already matches: both hands read 2.0mm and disagreed only about the
    material. The OWNER of that half still has to move — one purchase decision cannot be owned
    by two sources — but recording it as an overwrite would put a reading on the record that
    never lost anything, and `where_did_this_fact_come_from` would then show a gauge displaced
    by the value it already held."""
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    assert hand[GAUGE] == 2.0, "this test is looking at the wrong state"
    assert not [e for e in sp.displaced_values(hand, GAUGE)
                if sp._same_value(e.get("value"), hand[GAUGE])], (
        "the gauge was logged as displaced by the value it already held")
    # The material DID lose something, and that must still be on the record — otherwise this
    # passes by the mechanism never having run.
    assert [e for e in sp.displaced_values(hand, MAT) if str(e.get("value")) == "ABS"]


def test_a_hand_the_pair_left_alone_keeps_its_own_provenance():
    """The converse, so the clause above cannot be satisfied by stamping every hand. A pair
    that already agreed was never settled, and its sources must still be its own."""
    base = _part("07A", "PETG", 2.0)
    hand = _part("07A-HANDED", "PETG", 2.0)
    merge.settle_handed_pairs([base, hand])
    assert sp.source_of(hand, MAT) == "solidworks_api"


# ── one notion of identity, and it is wired ──────────────────────────────────────────

def test_pairing_uses_the_same_identity_the_mirror_rule_uses():
    """A second way of deciding what pairs with what would be a dual path in the very rule
    that exists to stop records drifting apart."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src",
                            "drawing_job_merge.py"), encoding="utf-8").read()
    body = src[src.index("def handed_pairs("):src.index("def settle_handed_pairs(")]
    assert "mirror_base" in body and "_own_number_key" in body
    assert src.count("def handed_pairs(") == 1


def test_every_place_that_mirrors_also_settles_the_pair():
    """THE GUARD THAT WOULD HAVE CAUGHT THREE COMMITS OF DEAD CODE.

    Pair settlement was wired into `augment_summary_with_dxf`, and the portal path calls
    `apply_mirror_geometry` from file_scan directly and never reaches that function. So
    pair-scoped arbitration shipped, passed its guards, ran on nobody's job, and four rounds
    of diagnosis went into asking why a rule that never executed had not changed anything.

    The old guard asserted the call existed in drawing_job_merge.py. It did. It was also
    useless — TEST THE CALLER, NOT THE HELPER, which is a defect family this codebase has a
    name for and I walked into anyway.

    So the rule is stated over EVERY call site in the tree: mirroring changes what a hand
    holds, and settling is what reconciles the pair afterwards. A file that does one without
    the other has half the mechanism, and half of this mechanism is exactly the failure it
    exists to prevent."""
    import glob
    root = os.path.join(os.path.dirname(__file__), "..")
    offenders = []
    for path in glob.glob(os.path.join(root, "src", "*.py")):
        if os.path.basename(path).startswith("_") or not os.path.isfile(path):
            continue        # scratch probes are not the pipeline, and one "*.py" is a folder
        text = open(path, encoding="utf-8", errors="replace").read()
        # A call, not the definition and not an import line.
        calls = [ln for ln in text.splitlines()
                 if "apply_mirror_geometry(" in ln
                 and not ln.strip().startswith(("def ", "from ", "import "))]
        if calls and "settle_handed_pairs(" not in text:
            offenders.append(os.path.basename(path))
    assert not offenders, (
        "these files mirror a hand and never settle the pair, so the hand keeps whatever the "
        "mirror copied onto it and no pooled evidence is ever counted: " + ", ".join(offenders))


def test_the_portal_path_settles_the_pair():
    """Named explicitly, because the generic guard above passes the moment ANY mention of
    settle_handed_pairs appears in a file — and this is the one path a real job takes."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "file_scan.py"),
               encoding="utf-8").read()
    assert "settle_handed_pairs(summary[\"manufacturing_writeup\"][\"parts\"])" in src
    assert src.index("apply_mirror_geometry(summary") < src.index("settle_handed_pairs(summary")


def test_the_merge_actually_settles_the_pairs():
    """BUILT IS NOT WIRED. The rule is worth nothing unless the merge runs it, and after the
    geometry rather than before: mirroring fills what a hand is MISSING, and settling only
    has meaning once both records are as complete as they are going to get."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src",
                            "drawing_job_merge.py"), encoding="utf-8").read()
    assert 'report["handed_pairs_settled"] = settle_handed_pairs(parts)' in src
    assert src.index('report["mirror_inherited"]') < src.index('report["handed_pairs_settled"]')
