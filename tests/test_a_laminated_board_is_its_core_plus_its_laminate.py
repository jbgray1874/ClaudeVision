"""A laminated board is its core plus its laminate (JG, 10 Nov 2026, 12674-01-GA: "price them as
core board plus walnut laminate"). A finished thickness that is a stock board plus 0.8 mm laminate
on two faces, or failing that one, is that core; the GA's FINISH reaches board parts that state
none; the laminate is charged on those faces; nothing unexplained is forced to a board."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import applied_finish as af                                        # noqa: E402
import laminated_board as lb                                       # noqa: E402

GA_PAGE = {"pdfplumber_text": "SPECIFICATION: MATERIAL: SEE PART DRAWINGS FINISH: WALNUT LAMINATE "
                              "COLOUR: REF: TBC GENERAL TOLERANCES"}


@pytest.mark.parametrize("finished,core,faces", [(19.6, 18.0, 2), (31.6, 30.0, 2), (12.8, 12.0, 1)])
def test_a_finished_thickness_is_a_stock_core_plus_laminate(finished, core, faces):
    assert lb.core_of(finished) == {"core_mm": core, "faces": faces, "laminate_mm": 0.8}


def test_a_stock_board_or_an_unexplained_thickness_is_left_alone():
    assert lb.core_of(18.0) is None
    assert lb.core_of(43.6) is None


def test_the_gas_finish_is_read_from_its_title_block_text():
    assert lb.stated_finish([GA_PAGE]) == "WALNUT LAMINATE"
    assert lb.stated_finish([{"pdfplumber_text": "FINISH: RAL 9005 POWDER COAT COLOUR: BLACK"}]) == ""


def _parts():
    return [{"part_number": "X-04J", "normalized_material": "MDF", "normalized_thickness_mm": 31.6},
            {"part_number": "X-02J", "normalized_material": "MDF", "normalized_thickness_mm": 43.6},
            {"part_number": "X-08M", "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 2.0}]


def test_board_parts_take_the_core_and_the_laminate_and_say_so():
    parts = _parts()
    said = lb.apply(parts, [GA_PAGE])
    div, side, steel = parts
    assert div["normalized_thickness_mm"] == 30.0 and div["finished_thickness_mm"] == 31.6
    assert div["applied_finish_faces"] == 2 and div["surface_finish"] == "WALNUT LAMINATE"
    assert div["laminated_construction"]["provisional"] is True
    assert side["normalized_thickness_mm"] == 43.6, "not forced to a board"
    assert any("no stock board" in f for f in side["flags"])
    assert "surface_finish" not in steel, "a steel part takes no laminate"
    assert any("30 mm board + 0.8 mm laminate on 2 faces" in s for s in said)


def test_a_part_with_its_own_other_finish_is_not_given_the_gas():
    parts = [{"part_number": "X-09J", "normalized_material": "MDF", "normalized_thickness_mm": 18.0,
              "surface_finish": "SPRAY PAINT RAL 9010"}]
    lb.apply(parts, [GA_PAGE])
    assert parts[0]["surface_finish"] == "SPRAY PAINT RAL 9010"


def test_the_laminate_is_charged_on_the_faces_the_construction_states():
    part = {"part_number": "X-04J", "surface_finish": "WALNUT LAMINATE", "applied_finish_faces": 2}
    est = af.applied_finish_estimate(part, 1000.0, 500.0, 1)
    line = est["finishes"][0]
    assert line["finish_code"] == "LAMINATE"
    assert line["faces"] == 2 and line["area_m2_per_part"] == 1.0
