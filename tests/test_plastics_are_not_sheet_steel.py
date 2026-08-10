"""A plastic sheet part must not be costed at the steel rate.

Job 11650's side panels are PETG. PETG contains none of the tokens _is_board tested for
-- not POLY, not ACRYLIC, nothing -- so a 1250 x 525 plastic panel was classified as sheet
steel and priced at GBP 900/tonne: GBP 22.96 of a GBP 111 material total, on a part that is
not metal, with a figure that looks entirely plausible on the sheet. Its opposite hand went
unpriced.

POLYCARBONATE routed correctly the whole time because it happens to contain POLY, which is
what made the failure look like a one-off rather than a lexicon with a hole in it.

The obvious fix is a trap. document_builder._NON_METAL_KEYWORDS already knows PETG -- and
also contains "LED", for light panels. _is_board matches SUBSTRINGS, and "COLD ROLLED
STEEL" and "ANNEALED" both contain LED. Unioning those two sets would route mild steel into
the board block and cost it as plastic. The metal cases below exist to keep that fix from
being made.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wb_populate import _is_board, _is_timber                       # noqa: E402


# ── the live failure ────────────────────────────────────────────────────────────────
def test_petg_is_not_sheet_steel():
    assert _is_board("PETG"), \
        "a PETG panel classified as steel is priced at GBP 900/tonne"


@pytest.mark.parametrize("material", [
    "PETG", "PETG OR PC", "POLYCARBONATE", "ACRYLIC", "PERSPEX", "HIPS", "ABS",
    "PVC", "NYLON", "ACETAL", "DELRIN", "HDPE", "UHMW", "PMMA",
    "POLYPROPYLENE", "POLYSTYRENE", "FOAMEX",
])
def test_a_plastic_is_costed_as_other_sheet(material):
    assert _is_board(material), f"{material} would be priced as steel"


# ── the trap ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("material", [
    "MILD STEEL", "MILD STEEL [CR4]", "STAINLESS STEEL", "ALUMINIUM",
    "GALVANISED STEEL", "ZINTEC", "BRASS", "COPPER",
    # THE ONES THAT MATTER. Both contain "LED", which document_builder's non-metal
    # vocabulary holds for light panels. A future union of the two lists fails here.
    "COLD ROLLED STEEL", "HOT ROLLED MILD STEEL", "ANNEALED STAINLESS",
])
def test_a_metal_is_never_costed_as_other_sheet(material):
    assert not _is_board(material), \
        f"{material} routed to the board block -- metal priced as plastic"


def test_the_two_vocabularies_are_deliberately_separate():
    """document_builder answers 'does this text mention something non-metal'. wb_populate
    answers 'is this part made of plastic sheet'. Merging them looks like removing a
    duplicate and is how COLD ROLLED STEEL becomes a board part."""
    import wb_populate
    from document_builder import _NON_METAL_KEYWORDS

    assert "LED" in _NON_METAL_KEYWORDS, \
        "the hazard this separation exists for has gone -- re-read before merging"
    assert not any("LED" == t for t in wb_populate._PLASTIC_SHEET_TOKENS)
    assert any("LED" in m.upper() for m in ("COLD ROLLED STEEL", "ANNEALED STAINLESS"))


# ── timber still tells itself apart ─────────────────────────────────────────────────
@pytest.mark.parametrize("material", ["MDF", "PLYWOOD", "LAMINATED MDF", "MELAMINE", "OAK"])
def test_timber_is_still_board_and_still_timber(material):
    assert _is_board(material)
    assert _is_timber(material), \
        "a wooden crate is not made on the acrylic line, and the department name says so"


@pytest.mark.parametrize("material", ["PETG", "ACRYLIC", "POLYCARBONATE"])
def test_a_plastic_is_not_timber(material):
    assert _is_board(material) and not _is_timber(material)


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
