r"""
test_the_model_is_found_under_the_name_the_engine_stores.py

THE INDEX IS KEYED ON WHAT THE FILE IS CALLED. THE LOOKUP ASKS FOR WHAT THE ENGINE STORED.

_native_match_index builds its tiers from the SolidWorks document title. _match_native is
handed a part whose `part_number` has already been through the pipeline — and
normalize_part_code rewrites several shapes on the way past:

    11650-04-01A-WALL  ->  11650-04-01A     (description bleed stripped)
    1450-GA-PANEL      ->  1450-GA
    9233-12-GA-UKM     ->  9233-12-GA
    1455-C GA          ->  1455-C-GA        (spaced GA joined)

On exactly those shapes the index is keyed one way and queried another, and neither the
exact, tail nor lead tier bridges it: the lead tier splits on " - " only, so a hyphenated
description yields no alias at all.

Four of eight realistic titles missed. A miss here has never been an error — the part simply
loses its flat pattern, its gauge, its bend count and its mass, and falls back to whatever
the drawing could be read for. It is the same shape as 11350 refusing its own extract and
pricing an arm by AI market estimate at 97% of the material total.

"BI-SCREW" was a fifth failure until part_identity stopped collapsing it to "BI" — the same
defect at the other end of the same join.

The fix indexes each title under the engine's own spelling too, asking the SAME function the
engine asks rather than adding another opinion about what a part number is. Ambiguity is
refused as it is in every other tier, and a key a real document already claims is never
overwritten — a part that owns its spelling outright keeps it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part_identity import normalize_part_code                       # noqa: E402
from source_connectors.solidworks import (                          # noqa: E402
    _match_native, _native_match_index,
)


def _index(*titles):
    job = SimpleNamespace(part_signals={t: None for t in titles}, bom=[], assembly_pns=[])
    return _native_match_index(job)


def _find(title, *titles):
    """Does a part stored under the engine's spelling of `title` reach the model?"""
    exact, tail, lead = _index(*(titles or (title,)))
    return _match_native({"part_number": normalize_part_code(title)}, exact, tail, lead)


# ── the four that were losing their model ──────────────────────────────────────

@pytest.mark.parametrize("title", [
    "11650-04-01A-WALL",
    "1450-GA-PANEL",
    "9233-12-GA-UKM",
    "1455-C GA",
])
def test_a_title_the_pipeline_rewrites_still_finds_its_model(title):
    assert _find(title) == title, (
        "the part loses its flat, gauge, bend count and mass, and says nothing")


def test_bi_screw_stays_found_now_that_it_is_not_collapsed_to_bi():
    """The same join, failing at the other end. Both halves have to hold."""
    assert _find("BI-SCREW") == "BI-SCREW"


# ── the tiers that already worked, unchanged ───────────────────────────────────

@pytest.mark.parametrize("title", [
    "12349-02-69-01A",
    "12552-01-01M",
    "2085-02 - Outer Tube",
])
def test_the_titles_that_already_matched_still_match(title):
    assert _find(title) == title


# ── and the ways this could put one part's geometry on another ─────────────────

def test_a_document_that_owns_a_spelling_outright_keeps_it():
    """1450-GA-PANEL normalises to 1450-GA. If 1450-GA is a real document in the job, it
    must not be displaced by the panel's alias — that is one part's geometry on another,
    which is what this whole builder exists to prevent."""
    exact, tail, lead = _index("1450-GA-PANEL", "1450-GA")
    assert _match_native({"part_number": "1450-GA"}, exact, tail, lead) == "1450-GA"


def test_two_titles_that_reduce_to_one_spelling_are_both_refused():
    """Ambiguity is dropped rather than resolved by luck of ordering, exactly as the tail
    and lead tiers drop it."""
    exact, tail, lead = _index("1450-GA-PANEL", "1450-GA-SHELF")
    assert _match_native({"part_number": "1450-GA"}, exact, tail, lead) is None


def test_a_part_the_job_does_not_have_still_matches_nothing():
    exact, tail, lead = _index("12552-01-01M")
    assert _match_native({"part_number": "99999-01-01M"}, exact, tail, lead) is None
