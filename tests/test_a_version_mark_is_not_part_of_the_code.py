"""12645 DRS External Shelter: the shelter sheet lists its body as "12645-01GA V2" and the body's
own drawing is numbered "12645-01GA". Without the version mark dropped, the body and its 32
lines linked to nothing and would have been set aside (D-310)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc  # noqa: E402


def test_the_body_links_to_the_shelter():
    edges = rc._bom_stated_edges(
        [{"part_number": "12645-01GA V2", "parent": "12645-DRS EXTERNAL SHELTER V2", "qty": 1}],
        {}, {"12645-01GA", "12645-DRS EXTERNAL SHELTER V2"})
    assert edges == [("12645-01GA", "12645-DRS EXTERNAL SHELTER V2", 1.0)]


def test_the_bare_code_is_offered_last():
    assert rc._code_spellings("12645-01GA V2")[-1] == "12645-01GA"
    assert rc._code_spellings("12645-01GA_V2 REV A")[-1] == "12645-01GA"
    assert rc._code_spellings("PANEL REV B")[-1] == "PANEL"


def test_a_hyphenated_or_embedded_v_is_part_of_the_code():
    assert rc._code_spellings("ABC-V2") == ["ABC-V2"]
    assert "SCREW" not in rc._code_spellings("SCREW V2A")


def test_the_bare_code_links_nothing_that_is_not_held():
    edges = rc._bom_stated_edges(
        [{"part_number": "12645-01GA V2", "parent": "12645-DRS EXTERNAL SHELTER V2", "qty": 1}],
        {}, {"12645-DRS EXTERNAL SHELTER V2"})
    assert "12645-01GA" not in {child for child, _, _ in edges}
