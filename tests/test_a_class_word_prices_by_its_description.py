"""FIXING is a drawer; the screw's identity is in the description, so that is what prices it.

WHAT REACHED THE ESTIMATOR. 12349-02's fastener lines carry class words in the code column —
FIXING, STD PART, P/P — and real parts in the description: an M4x10 flange button screw Tim
has in his own book at 2.48p, a 3.5x19 wood screw, a PD.2120. Every one of them arrived as
"MATERIAL UNPRICED: enter a unit rate", because the only description route into UDEF was the
whole drawing sentence as a verbatim LIKE substring — and "M4x10mm" is not a substring of
"M4 x 10mm".

THE CONTRACT (set on 12 Sep): a class-word code is not a catalogue key; match UDEF on the
description; a hit puts the price AND the catalogue row's code where the estimator can see
it; a miss stays a labelled line, never a silent zero; and a real code — FIXING2841 — still
matches by code first.

The decision rules are pure functions, so they are tested here without a database; the
arm's placement (code first, recall gated to bought lines) is tested through a fake
connection that records every query it is asked.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pricing_service as ps                                            # noqa: E402


def _row(code, desc, price, supplier="Catalogue Supplier"):
    """A row in the exact shape every UDEF query in pricing_service selects."""
    return (code, desc, supplier, price, "each", None, None, None, None)


TIM_M4 = _row("FIXING2813", "M4 x 10mm FLANGE BUTTON HEAD SCREW,BLACK", 0.0248)
M4_X16 = _row("FIXING2900", "M4 x 16mm FLANGE BUTTON HEAD SCREW,BLACK", 0.0310)
WOODSCREW = _row("FIXING0740", "3.5 X 19 WOOD SCREW ZINC", 0.0080)
PALLET_WRAP = _row("PACK0055", "PD.2120 PALLET WRAP ROLL", 4.1500)


# ── the size is the identity ──────────────────────────────────────────────────────────────

def test_tims_m4_screw_prices_off_its_description():
    """The exact line off 12349-02, spaces and all, against Tim's catalogue spelling."""
    row, why = ps.choose_udef_description_row(
        "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK", [TIM_M4, M4_X16, WOODSCREW])
    assert row is TIM_M4, why
    assert not why


def test_a_terser_drawing_wording_still_lands():
    """Drawings say less than catalogues. The row may carry MORE words, never other ones."""
    row, _ = ps.choose_udef_description_row(
        "M4 x 10 FLANGE BUTTON BLACK", [TIM_M4, M4_X16])
    assert row is TIM_M4


def test_an_m4x10_is_never_priced_as_an_m4x16():
    """Every word matches; only the size differs. Words must not outvote a stated size."""
    row, why = ps.choose_udef_description_row(
        "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK", [M4_X16])
    assert row is None
    assert "words and stated sizes" in why


def test_the_wood_screw():
    row, _ = ps.choose_udef_description_row("3.5 x 19mm WOOD SCREW", [WOODSCREW, TIM_M4])
    assert row is WOODSCREW


def test_a_bare_reference_matches_on_its_digits():
    """P/P against 'PD.2120' — no words at all, just the supplier's own reference."""
    row, _ = ps.choose_udef_description_row("PD.2120", [PALLET_WRAP, TIM_M4])
    assert row is PALLET_WRAP


# ── refusals: the miss must be a decision, not an accident ────────────────────────────────

def test_survivors_that_disagree_on_price_are_refused():
    a = _row("FIXING0100", "NYLON WASHER FORM A", 0.0100)
    b = _row("FIXING0101", "NYLON WASHER FORM A LARGE", 0.0500)
    row, why = ps.choose_udef_description_row("NYLON WASHER", [a, b])
    assert row is None
    assert "disagree on price" in why and "FIXING0100" in why


def test_survivors_that_agree_on_price_are_not_an_ambiguity():
    a = _row("FIXING0100", "NYLON WASHER FORM A", 0.0100)
    b = _row("FIXING0102", "NYLON WASHER FORM A BAGGED", 0.0100)
    row, _ = ps.choose_udef_description_row("NYLON WASHER", [a, b])
    assert row is not None


def test_a_class_word_alone_matches_nothing():
    """'FIXING' as the whole description is the placeholder case — nothing to match ON."""
    row, why = ps.choose_udef_description_row("FIXING", [TIM_M4, WOODSCREW])
    assert row is None
    assert "nothing distinctive" in why


def test_a_zero_priced_catalogue_row_cannot_win():
    """UDEF's catch-all rows are priced £0.00; they blinded the code arm once already."""
    free = _row("FIXING", "M4 x 10mm FLANGE BUTTON HEAD SCREW,BLACK", 0.0)
    row, _ = ps.choose_udef_description_row(
        "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK", [free])
    assert row is None


def test_class_words_carry_no_matching_signal():
    """'WOOD SCREW' must not reach a machine screw on the strength of the word SCREW."""
    machine = _row("FIXING0500", "M3 x 6 MACHINE SCREW POZI", 0.0050)
    row, _ = ps.choose_udef_description_row("3.5 x 19 WOOD SCREW", [machine])
    assert row is None


# ── what SQL is asked about: words, because words survive re-spacing ──────────────────────

def test_anchor_tokens_prefer_words_over_dimensions():
    toks = ps.udef_anchor_tokens("M4x10mm FLANGE BUTTON HEAD SCREW, BLACK")
    assert toks and all(t.isalpha() for t in toks)
    assert "FLANGE" in toks and "BUTTON" in toks


def test_anchor_tokens_fall_back_to_reference_digits():
    assert ps.udef_anchor_tokens("PD.2120") == ["2120"]


# ── placement: code first, recall only for bought lines ──────────────────────────────────

class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._result = []

    def execute(self, query, params=None):
        self._conn.executed.append((query, list(params or [])))
        self._result = []
        if "TOP 40" in query:                                # the description-recall arm
            self._result = list(self._conn.candidates)
        elif "CASE WHEN" in query and params:                # the combined code/desc query
            code = str(params[0] or "").upper()
            hit = self._conn.by_code.get(code)
            if hit:
                self._result = [hit]

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)

    def close(self):
        pass


class _Conn:
    def __init__(self, by_code=None, candidates=None):
        self.by_code = {k.upper(): v for k, v in (by_code or {}).items()}
        self.candidates = candidates or []
        self.executed = []

    def cursor(self):
        return _Cursor(self)

    def close(self):
        pass


def _service(conn):
    return ps.PricingService(conn=conn)


def test_a_real_code_still_matches_by_code_first():
    real = _row("FIXING2841", "M6 x 16 SOCKET CAP SCREW BZP", 0.0400)
    conn = _Conn(by_code={"FIXING2841": real}, candidates=[TIM_M4])
    anchor = _service(conn)._get_udef_anchor(
        {"part_number": "FIXING2841", "description": "M6 x 16 SOCKET CAP SCREW BZP"})
    assert anchor and anchor["unit_price_gbp"] == 0.0400
    assert anchor["confidence"] > 0.7                        # an exact code, not a recall
    assert not any("TOP 40" in q for q, _ in conn.executed), \
        "the description recall ran although the code had already answered"


def test_a_fixing_line_prices_and_names_its_catalogue_row():
    """The whole contract in one pass: class-word code, description hit, SKU on the line."""
    conn = _Conn(candidates=[TIM_M4, M4_X16])
    anchor = _service(conn)._get_udef_anchor(
        {"part_number": "FIXING", "description": "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK"})
    assert anchor and anchor["unit_price_gbp"] == 0.0248
    assert anchor["matched_part_code"] == "FIXING2813"
    assert anchor["supplier_name"].startswith("FIXING2813 — "), \
        "the SKU must reach the supplier cell — the code cell only says FIXING"
    assert anchor["matched_on"] == "description"


def test_a_fabricated_part_never_borrows_a_catalogue_price():
    """This method runs for every part on the job. A bracket with a distinctive name must
    not be priced off the one catalogue row that happens to fit it."""
    lookalike = _row("MISC0900", "MDF PACKER 18MM", 1.25)
    conn = _Conn(candidates=[lookalike])
    anchor = _service(conn)._get_udef_anchor(
        {"part_number": "12349-02-69-04M", "description": "MDF PACKER 18MM"})
    assert anchor is None
    assert not any("TOP 40" in q for q, _ in conn.executed), \
        "description recall must not run for a part with its own real code"
