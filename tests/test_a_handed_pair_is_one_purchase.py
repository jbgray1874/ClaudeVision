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


def test_the_hand_that_moved_says_so_and_names_the_other():
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    flags = [f for f in hand.get("review_flags", []) if "HANDED PAIR SETTLED" in f]
    assert flags, "a purchase key changed and nothing on the part says so"
    assert "11650-04-01A" in flags[0]


def test_what_it_displaced_is_kept():
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    said = {str(e["value"]) for e in sp.displaced_values(hand, MAT)}
    assert "ABS" in said, "the hand's own model reading was erased rather than overruled"


def test_the_report_names_the_pair_and_the_outcome():
    base, hand = _pair_as_the_pack_reads()
    out = merge.settle_handed_pairs([base, hand])
    assert out and out[0]["outcome"] == "settled"
    assert out[0]["part_number"] == "11650-04-01A-HANDED"
    assert out[0]["stock_key"] == ["PETG", 2.0]


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
    assert len(out) == 1 and again == []
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
    flag = [f for f in hand["review_flags"] if "HANDED PAIR SETTLED" in f][0]
    assert "2 against 1" in flag, flag


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
    for field in (MAT, GAUGE):
        assert sp.source_of(hand, field) != "solidworks_api", (
            f"{field} still belongs to the model on a hand the pair settled")
    assert sp.source_of(hand, MAT) == "mirror_of_measured"


def test_the_hand_that_won_keeps_its_own_provenance():
    """Only the hand that TOOK the pair's answer records that it took it. The winner reached
    this key through its own readings, and restamping it would erase the one record that can
    say where the key actually came from — leaving a pair whose stock key traces to nothing."""
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    assert sp.source_of(base, MAT) == "dxf_filename"
    assert sp.source_of(hand, MAT) == "mirror_of_measured"


def test_nothing_is_recorded_as_displaced_where_nothing_was():
    """Half a key usually already matches: both hands read 2.0mm and disagreed only about the
    material. The OWNER of that half still has to move — one purchase decision cannot be owned
    by two sources — but recording it as an overwrite would put a reading on the record that
    never lost anything, and `where_did_this_fact_come_from` would then show a gauge displaced
    by the value it already held."""
    base, hand = _pair_as_the_pack_reads()
    merge.settle_handed_pairs([base, hand])
    assert sp.source_of(hand, GAUGE) == "mirror_of_measured", (
        "the agreed half kept the model as its owner; this test is looking at the wrong state")
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


def test_the_merge_actually_settles_the_pairs():
    """BUILT IS NOT WIRED. The rule is worth nothing unless the merge runs it, and after the
    geometry rather than before: mirroring fills what a hand is MISSING, and settling only
    has meaning once both records are as complete as they are going to get."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src",
                            "drawing_job_merge.py"), encoding="utf-8").read()
    assert 'report["handed_pairs_settled"] = settle_handed_pairs(parts)' in src
    assert src.index('report["mirror_inherited"]') < src.index('report["handed_pairs_settled"]')
