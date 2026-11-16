"""A prose fabrication word that names a part the job MAKES is not re-bought as a phantom.

8352 shipped BI-FOOTPLATE 'Foot Plate' at ~£14 on top of the fabricated 8352-01-02 'SCREW PLATE'
already costed in Sheet Steel. It survived two earlier guards:
  * the confidence gate priced it because the 2-token 'Foot Plate' matched an identically-worded
    historical 'foot plate' line at high (>= 0.8) Jaccard — a CONFIDENT match, not a weak one; and
  * the double-count guard missed it because it needs >= 2 shared tokens, and 'Foot Plate' shares
    only 'plate' with 'SCREW PLATE' — a single word.

The single word IS the collision. foot / plate / bracket / panel / frame / ... are the words for
things SDI MAKES; when an ambiguous fabrication-word item shares even ONE of them with a made
part's description, the job demonstrably fabricates that kind of part, and a dual-named part
('Foot Plate' vs 'SCREW PLATE') shares exactly that one word and nothing else. So an ambiguous
item colliding on a single fabrication word is surfaced as a query (no money), not invented into
the total. Whole-phrase overlap still catches a genuine second copy of any item, safe or not.

Keyed on the fabrication word, not on 'Foot Plate' or '8352-01-02', so every prose-heavy GA
inherits it. It stops inventing the money; it does not merge the two names into one node.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import bought_in_recogniser as bir  # noqa: E402


def _fab(*descs):
    return [bir._sig_token_set(d) for d in descs]


_8352_FAB = None


def setup_module(module):
    global _8352_FAB
    _8352_FAB = _fab("M10 HANK BUSH", "SCREW PLATE", "SHELF", "GUSSET", "HOOK", "TIMBER BACK PANEL")


def test_foot_plate_collides_with_the_fabricated_screw_plate():
    """THE 8352 CASE. 'Foot Plate' shares only 'plate' with 'SCREW PLATE' — one word — and that
    is now enough, because the job fabricates plates."""
    assert bir._collides_with_a_made_part("Foot Plate", True, _8352_FAB) is True


def test_the_genuine_bought_hardware_is_not_suppressed():
    """The other 8352 bought-ins are SAFE-headed (screw/nutsert) — they must still price, never
    be swept up by the single-word rule."""
    assert bir._collides_with_a_made_part("Self Tapping Screw", False, _8352_FAB) is False
    assert bir._collides_with_a_made_part("Button Head Screw", False, _8352_FAB) is False
    assert bir._collides_with_a_made_part("Flanged Nutsert", False, _8352_FAB) is False


def test_an_ambiguous_word_the_job_does_not_make_is_still_a_purchase():
    """The rule fires only on a REAL collision: if nothing fabricated shares the fabrication
    word, the prose item is a genuine buy and is priced."""
    assert bir._collides_with_a_made_part("Foot Plate", True, _fab("SHELF", "HOOK")) is False


def test_a_safe_headed_phrase_with_an_ambiguous_token_is_not_swept_up():
    """'Bracket Screw' is a screw (SAFE) that merely mentions a bracket — ambiguous=False, so the
    single-word branch never runs, and it prices even though the job makes brackets."""
    fab = _fab("MOUNTING BRACKET")
    assert bir._collides_with_a_made_part("Bracket Screw", False, fab) is False


def test_a_whole_phrase_copy_is_caught_for_any_item():
    """The >= 2-token overlap still catches a genuine second copy of the same description, safe or
    ambiguous — the single-word rule is an ADDITION, not a replacement."""
    assert bir._collides_with_a_made_part("Screw Plate", False, _8352_FAB) is True


def test_an_empty_phrase_or_no_made_parts_never_collides():
    assert bir._collides_with_a_made_part("", True, _8352_FAB) is False
    assert bir._collides_with_a_made_part("Foot Plate", True, []) is False


def test_the_single_word_rule_needs_the_ambiguous_flag():
    """Without the ambiguous flag, a lone fabrication-word overlap is NOT a collision — this is
    what keeps SAFE items priced. Same phrase, both flag values, opposite answers."""
    fab = _fab("SCREW PLATE")
    assert bir._collides_with_a_made_part("Foot Plate", True, fab) is True
    assert bir._collides_with_a_made_part("Foot Plate", False, fab) is False


def test_the_recogniser_passes_the_ambiguous_flag_to_the_guard():
    """Wired: the loop computes `ambiguous` and hands it to the guard, so a confident-match
    fabrication word can still be routed to the query branch."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "bought_in_recogniser.py"),
               encoding="utf-8").read()
    assert "already_fab = _is_already_fabricated(desc, ambiguous)" in src
    assert "_collides_with_a_made_part(phrase, ambiguous, fab_token_sets)" in src
