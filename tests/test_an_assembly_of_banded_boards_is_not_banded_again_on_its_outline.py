"""AN ASSEMBLY OF BANDED BOARDS IS NOT BANDED AGAIN ON ITS OWN OUTLINE (11896-08-01-GA, 13 Nov 2026).

"EDGED ALL ROUND" is on the panel's title block and on its sub-assembly's. The edging line
read 24.659 m: the panel all round (6.718 m) plus the sub-assembly's outline all round, twice
(17.941 m). Reviewer: "Trace the edging multiplication"; "no duplicate material or operation
charges".
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import edge_banding as E  # noqa: E402

WORDS = ["EDGED ALL ROUND"]


def _job():
    return [{"part_number": "T-GA", "assembly_children": ["T-SA01", "T-09"]},
            {"part_number": "T-SA01", "quantity": 2, "assembly_children": ["T-01J"],
             "edging_route_words": WORDS, "overall_length_mm": 2367.0, "overall_width_mm": 2118.3},
            {"part_number": "T-01J", "quantity": 1, "edging_route_words": WORDS,
             "overall_length_mm": 2363.0, "overall_width_mm": 996.0},
            {"part_number": "T-09", "quantity": 1, "textual_operations": ["cnc_routing"]}]


def test_the_sub_assembly_is_banded_on_its_panel_not_on_itself():
    assert E.assemblies_banded_on_their_members(_job()) == {"T-SA01": ["T-01J"]}


def test_the_figure_in_the_record_was_the_panel_plus_the_assembly_twice():
    panel = 2 * (2363.0 + 996.0) / 1000.0
    outline = 2 * (2367.0 + 2118.3) / 1000.0
    assert round(panel * 1 + outline * 2, 3) == 24.659
    assert round(panel, 3) == 6.718


def test_an_assembly_whose_boards_are_not_banded_is_left_to_its_own_evidence():
    parts = _job(); parts[2].pop("edging_route_words")
    assert E.assemblies_banded_on_their_members(parts) == {}


def test_a_banded_board_with_no_children_is_never_set_aside():
    out = E.assemblies_banded_on_their_members(_job())
    assert "T-01J" not in out and "T-09" not in out and "T-GA" not in out


def test_an_assembly_of_sub_assemblies_looks_only_at_its_own_boards():
    parts = _job(); parts[0]["edging_route_words"] = WORDS
    assert "T-GA" not in E.assemblies_banded_on_their_members(parts)


def test_the_estimator_skips_the_assembly_and_says_where_the_edging_is():
    est = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    at = est.index("if _pn_e in _edged_by_members:")
    assert "continue" in est[at:at + 700] and "measured there" in est[at:at + 700]
    assert est.index("_edged_by_members = _on_members(parts)") < at
