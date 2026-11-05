"""A décor named in several words is one name, and a class rate standing in for it says so (D-720).

11908-22-GA, 5 Nov 2026: three panels in 9 mm MDF laminated both sides, COLOUR: ALPINE NORDIC
OAK. The product reference asked the catalogue one word at a time, longest first, so ALPINE
answered and a 9 mm Alpine White board was taken for the product, at about £6.92 a square metre.
The rule: where the drawing names its décor in words and no code, a row is the product only when
it carries every word. Otherwise the class rows price it and the line says it is a substitute,
or the board is built from the drawn décor's laminate where SDI Live holds one (D-676).
Synthetic rows shaped like SDI Live's; made-up part numbers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as e                                                 # noqa: E402
from test_a_board_keeps_its_grade_and_decor_in_the_price import _Conn, _clear  # noqa: E402

DECOR = "ALPINE NORDIC OAK"
ALPINE_WHITE = ("MFMDF009", "9mm MFMDF 2800 x 2070 Alpine White", 40.11)
FACED_CLASS = [("MFMDF010", "9mm Melamine Faced MDF 2800 x 2070 White", 52.00),
               ("MFMDF011", "9mm Melamine Faced MDF 2800 x 2070 Grey", 56.00)]
NORDIC_ROW = ("MFMDF020", "9mm MFMDF 2800 x 2070 Alpine Nordic Oak", 95.00)


@pytest.fixture
def live(monkeypatch):
    import config
    held = {"rows": []}
    monkeypatch.setattr(config, "get_connection",
                        lambda timeout=20: _Conn(held["rows"]), raising=False)
    monkeypatch.setattr(e, "market_indication_for", lambda part, material: None)
    _clear()

    def _set(rows):
        _clear()
        held["rows"] = list(rows)
    yield _set
    _clear()


def _panel():
    return {"part_number": "T-01J", "normalized_material": "MDF", "colours": [DECOR],
            "normalized_finish": "LAMINATED", "normalized_thickness_mm": 9.0}


def test_one_word_of_the_decor_is_not_the_product(live):
    live([ALPINE_WHITE] + FACED_CLASS)
    r = e._resolve_board_sheet_rate_gbp_per_m2("MFMDF", 9.0, _panel())
    assert r is not None
    assert not r["product_reference_match"], "Alpine White is not Alpine Nordic Oak"
    # The class rows answer: Alpine White is an MFMDF row like any other, counted as the class.
    assert r["material_token"] != "ALPINE"


def test_a_row_carrying_the_whole_decor_is_the_product(live):
    live([ALPINE_WHITE, NORDIC_ROW] + FACED_CLASS)
    r = e._resolve_board_sheet_rate_gbp_per_m2("MFMDF", 9.0, _panel())
    assert r["product_reference_match"] is True
    assert [x["description"] for x in r["rows"]] == [NORDIC_ROW[1]]


def test_a_single_word_decor_is_probed_as_before(live):
    live([("MFMDF030", "9mm MFMDF 2800 x 2070 Minnesota Oak", 80.0)] + FACED_CLASS)
    part = dict(_panel(), colours=["MINNESOTA"])
    r = e._resolve_board_sheet_rate_gbp_per_m2("MFMDF", 9.0, part)
    assert r["product_reference_match"] is True


def test_the_substitute_is_declared_and_asked_where_no_laminate_builds_it(live, monkeypatch):
    live([ALPINE_WHITE] + FACED_CLASS)
    monkeypatch.setattr(e, "_constructed_faced_board", lambda *a, **k: None)
    part = dict(_panel(), blank_length_mm=340.0, blank_width_mm=290.0, quantity=1,
                textual_operations=["cnc_routing", "laminating"])
    e.estimate_material(part)
    sub = part.get("_faced_board_substitute")
    assert sub and sub["decor"].upper().startswith("ALPINE NORDIC OAK")
    assert any(str(f).startswith("SUBSTITUTE BOARD") for f in part.get("review_flags") or [])
    assert any("priced as generic MFMDF" in str(q.get("issue"))
               for q in part.get("manufacturing_questions") or [])
