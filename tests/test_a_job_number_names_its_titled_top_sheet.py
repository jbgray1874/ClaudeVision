"""12645 DRS External Shelter: the top sheet is filed "12645 - DRS External Shelter V2 REVA.PDF"
and numbered in its title block "12645 - DRS EXTERNAL SHELTER V2". The portal refused "12645"
("does not name any drawing added here") because a bare job number failed the drawing-number
shape, and the engine could not have matched it either. The body sheet "12645-01GA" was also
called a single part, its GA glued to the number (D-311)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import product_identity as pi  # noqa: E402

FILES = ["12645 - DRS External Shelter V2 REVA.PDF", "12645-01GA_V2_REVA.PDF",
         "12645-02GA_REVA.pdf", "12645-03GA_REVA.pdf", "12645-01-01M.DXF"]


def test_the_job_number_names_the_shelter_and_the_rest_are_detail():
    r = pi.resolve_product("12645", FILES)
    assert r["status"] == "ok"
    assert r["match"]["number"] == "12645" and r["match"]["is_assembly"]
    assert {o["number"] for o in r["others"]} == {"12645-01GA", "12645-02GA", "12645-03GA"}


def test_the_engine_reads_the_title_block_spelling_the_same_way():
    assert pi.names_the_product("12645", "12645-DRS EXTERNAL SHELTER V2")
    assert pi.names_the_product("12645", "12645 - DRS EXTERNAL SHELTER V2")


def test_a_job_number_never_names_a_numbered_sub_sheet_or_part():
    assert not pi.names_the_product("12645", "12645-01GA")
    assert not pi.names_the_product("12645", "12645-01-01M")
    assert not pi.names_the_product("1264", "12645-DRS EXTERNAL SHELTER V2")


def test_a_ga_glued_to_the_number_is_an_assembly():
    assert pi.drawing_of_file("12645-01GA_V2_REVA.PDF")["is_assembly"]


def test_a_lone_number_is_not_a_drawing():
    assert pi.drawing_of_file("12645.pdf") == {}
    assert pi.drawing_of_file("12645 01.pdf") == {}


def test_a_top_sheet_with_nothing_under_it_is_not_called_an_assembly():
    r = pi.resolve_product("12645", ["12645 - DRS External Shelter V2 REVA.PDF"])
    assert r["status"] == "not_an_assembly"


def test_existing_spellings_still_name_their_sheets():
    assert pi.names_the_product("11650-06", "11650-06-GA")
    assert not pi.names_the_product("11650-06", "11650-06-SA01")
