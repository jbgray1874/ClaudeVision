"""A plural and a shop abbreviation match their root, so the same part is not missed twice.

The bought-in matcher, the BOM dedup, and the double-count guard all read one tokeniser
(_sig_token_set). It compared tokens by exact equality, so 'castors' never matched 'castor',
'brackets' never matched 'bracket', and 'galv'/'assy' never matched the spelled-out words the
historical descriptions actually carry — a recognised part could be priced twice, deduped
wrongly, or missed against history, purely on a plural or an abbreviation.

A deterministic normalisation now runs before the token filter: singularise a trailing plural
's' (guarding the words that merely END in s — stainless, brass, glass, boss, class — and never
below 4 chars), then expand a small curated abbreviation map. Applied identically to both sides,
so it can only unify equivalent descriptions, never collapse two genuinely different words. Pure
and deterministic, so a price built on a match still repeats every run. It improves all three
consumers at once because they share the tokeniser — keyed on nothing job-specific, so every
pack inherits it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import bought_in_recogniser as bir  # noqa: E402


# ── singularisation ────────────────────────────────────────────────────────────────────
def test_a_plural_loses_its_trailing_s():
    assert bir._singularize("castors") == "castor"
    assert bir._singularize("plates") == "plate"
    assert bir._singularize("bolts") == "bolt"
    assert bir._singularize("nuts") == "nut"


def test_a_word_that_merely_ends_in_s_is_not_mangled():
    """stainless / brass / glass / boss / class end in s but are not plurals — a double s is
    never stripped, so these survive intact and cannot be corrupted into a false match."""
    for w in ("stainless", "brass", "glass", "boss", "class"):
        assert bir._singularize(w) == w


def test_short_words_are_left_alone():
    """Below 4 chars, a trailing s is far more likely part of the word than a plural marker."""
    assert bir._singularize("gas") == "gas"
    assert bir._singularize("bus") == "bus"


# ── abbreviation expansion ─────────────────────────────────────────────────────────────
def test_a_curated_abbreviation_expands_to_the_spelled_out_word():
    assert bir._normalize_token("assy") == "assembly"
    assert bir._normalize_token("brkt") == "bracket"
    assert bir._normalize_token("galv") == "galvanised"
    assert bir._normalize_token("sst") == "stainless"


def test_a_plural_abbreviation_still_expands():
    """singularise-then-expand order means a plural shorthand resolves to the root word."""
    assert bir._normalize_token("brkts") == "bracket"


def test_an_unknown_word_passes_through_unchanged():
    assert bir._normalize_token("gusset") == "gusset"
    assert bir._normalize_token("hook") == "hook"


# ── the payoff: equivalent descriptions now share a token set ───────────────────────────
def test_a_plural_and_its_singular_produce_the_same_token_set():
    assert bir._sig_token_set("Castors") == bir._sig_token_set("Castor")
    assert bir._sig_token_set("M8 Brackets") == bir._sig_token_set("M8 Bracket")


def test_an_abbreviation_and_its_expansion_produce_the_same_token_set():
    assert bir._sig_token_set("Galv Bracket") == bir._sig_token_set("Galvanised Bracket")
    assert bir._sig_token_set("Assy") == bir._sig_token_set("Assembly")


def test_two_different_words_do_not_collapse_together():
    """The whole safety of a low-false-positive normaliser: it unifies a word with ITSELF in
    another form, never one word with a different one."""
    assert bir._sig_token_set("plate") != bir._sig_token_set("plane")
    assert bir._sig_token_set("bush") != bir._sig_token_set("brush")
    assert "stainless" in bir._sig_token_set("Stainless Steel Plate")


def test_the_match_score_rises_for_a_plural_variant():
    """The concrete recall gain: a phrase and a historical line that differ only by a plural now
    score as an exact token match instead of missing each other."""
    a = bir._sig_token_set("castor black")
    b = bir._sig_token_set("castors black")
    shared, union = a & b, a | b
    assert union and len(shared) / len(union) == 1.0


def test_normalisation_is_deterministic():
    """Reproducibility is a blocking invariant — the same input must tokenise identically every
    call, so a price built on a match cannot move between runs."""
    for s in ("Galv Brackets x4", "Assy Plates", "Stainless Washers"):
        assert bir._sig_token_set(s) == bir._sig_token_set(s)
