"""An ambiguous fabrication word priced on a weak match is queried, not invented into the total.

8352 shipped BI-FOOTPLATE 'Foot Plate' at ~£14 — about 30% of the £49.76 material total — on top
of 8352-01-08, a 50x25x3mm mild-steel part already costed in the Sheet Steel block. The pack
names that one part two ways: 'M10 HANK BUSH' on the BOM and 'FOOT PLATE' in the notes. The prose
recogniser read 'Foot Plate', and the token double-count guard could not see the collision — the
fabricated part's description shares no token with 'foot plate' — so an indicative historical
match invented a priced bought-in that double-counts a made-in part.

foot / plate / bracket / panel / frame / channel / rail / bar / cover / profile are the words for
things SDI MAKES (the AMBIGUOUS head-words). So one is PRICED from history only on a CONFIDENT
match (>= 0.8); a weak match on such a word is surfaced as a query with no money, because it is
far more likely a fabricated part under another name than a real purchase. SAFE head-words
(screw/bolt/castor/…) — the words for things SDI BUYS — are unaffected.

Keyed on the head-word class and the match confidence, not on 'Foot Plate' or '8352-01-08', so
every prose-heavy GA with an ambiguous fabrication word inherits it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import bought_in_recogniser as bir  # noqa: E402


def test_an_ambiguous_word_on_a_weak_match_is_withheld():
    """THE FOOTPLATE CASE. A fabrication word matched only weakly is not priced."""
    assert bir._should_withhold_ambiguous_price(True, 0.5) is True
    assert bir._should_withhold_ambiguous_price(True, 0.79) is True


def test_an_ambiguous_word_on_a_confident_match_is_still_priced():
    """A strong match to a real recurring purchase of that exact thing still prices — the gate
    refuses INVENTION, not a genuine confident history."""
    assert bir._should_withhold_ambiguous_price(True, 0.8) is False
    assert bir._should_withhold_ambiguous_price(True, 0.95) is False


def test_a_safe_head_word_is_never_gated_by_this_rule():
    """screw/bolt/castor/… name things SDI BUYS; a weak match on them is handled by the other
    guards, not withheld here — this rule must not touch the SAFE class."""
    assert bir._should_withhold_ambiguous_price(False, 0.5) is False
    assert bir._should_withhold_ambiguous_price(False, 0.0) is False


def test_a_missing_or_garbled_score_counts_as_weak():
    """No score, or an unparseable one, is treated as NOT confident — the safe direction is to
    query, never to price on evidence we cannot read."""
    assert bir._should_withhold_ambiguous_price(True, None) is True
    assert bir._should_withhold_ambiguous_price(True, "") is True
    assert bir._should_withhold_ambiguous_price(True, "x") is True
    assert bir._should_withhold_ambiguous_price(True, 0) is True


def test_the_threshold_is_the_same_one_the_label_uses():
    """The price-or-query decision and the confident/indicative label an estimator reads are the
    SAME threshold, so a line labelled 'indicative' is exactly one this rule would query — they
    cannot drift apart."""
    assert bir._CONFIDENT_MATCH_SCORE == 0.8
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "bought_in_recogniser.py"),
               encoding="utf-8").read()
    # The label uses the shared constant, not a bare 0.8 that could drift.
    assert 'match["match_score"] >= _CONFIDENT_MATCH_SCORE' in src


def test_the_ambiguous_head_words_are_the_fabrication_words():
    """The class this rule guards is exactly the make-or-buy words — the ones a wrong bought-in
    would double-count against a fabricated part."""
    for w in ("plate", "bracket", "foot", "panel", "frame", "channel", "rail", "bar"):
        assert w in bir._HEADWORDS_AMBIGUOUS
    # And the things SDI plainly buys are NOT in it — they must still price on any match.
    for w in ("screw", "bolt", "castor", "rivet", "nutsert"):
        assert w not in bir._HEADWORDS_AMBIGUOUS


def test_the_recogniser_applies_the_gate_before_pricing():
    """Wired, not merely defined: the pricing loop calls the predicate and drops the match to a
    query when it fires."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "bought_in_recogniser.py"),
               encoding="utf-8").read()
    assert "_should_withhold_ambiguous_price(ambiguous, match.get(\"match_score\"))" in src
    assert src.index("_should_withhold_ambiguous_price(ambiguous") < src.index("if match:\n"
        "                stub[\"unit_cost_gbp\"]")
