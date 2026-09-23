"""The portal says which drawing a run will price — before Run, with the engine's resolver.

James Gray, 23 Sep 2026: "we need to centre the job estimate around the drawing number
entered into the estimating portal." The 11650-02 run priced the cabinet top because that
is what 11650-02 names, and set Tim's kit aside; nobody could see it for forty minutes.
Review: "Use the engine's same product resolver to show the matched GA, title and revision
before Run. If the number matches none or more than one, ask the estimator to correct it;
do not silently choose a root. If it matches 02-GA while the pack also contains 06-GA, show
that distinction prominently without guessing which product they intended."
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import product_identity as pi                                        # noqa: E402
import route_compiler as rc                                          # noqa: E402

PACK = ["11650-02-GA TOP_revD.PDF", "11650-02-GA TOP_revD.DWG", "11650-03-GA ARM_revC.PDF",
        "11650-06-GA COFFRET HOSPITAL KIT_REVB.PDF", "11650-06-GA.SLDASM",
        "AC0706-03_Christmas 2024 Coffret Cabinet Hospital Kit_GA.PDF",
        "11650-03-01M_1.2MM MS_REVC.DXF", "11650-03-02M.SLDPRT"]


def test_the_kit_is_named_with_its_title_and_revision_and_the_others_are_listed():
    r = pi.resolve_product("11650-06-GA", PACK)
    assert r["status"] == "ok" and r["match"]["number"] == "11650-06-GA"
    assert r["match"]["revision"] == "B" and "COFFRET" in r["match"]["title"]
    assert {o["number"] for o in r["others"]} == {"11650-02-GA", "11650-03-GA"}


def test_the_cabinet_top_is_named_and_the_kit_is_shown_beside_it_without_a_guess():
    r = pi.resolve_product("11650-02", PACK)
    assert r["status"] == "ok" and r["match"]["number"] == "11650-02-GA"
    assert r["match"]["revision"] == "D"
    assert "11650-06-GA" in r["message"] and "If one of them is what ships" in r["message"]


def test_a_number_that_names_nothing_is_a_correction_not_a_choice():
    r = pi.resolve_product("AC0706-03", PACK)     # the Boots code: rule 5, never keyed off
    assert r["status"] == "none" and r["match"] is None
    assert "Type the one that is the product" in r["message"]


def test_two_spellings_of_one_drawing_are_one_drawing_not_a_choice():
    """The match is exact after a role word and revision are set aside, so two files can
    only both match when they ARE the same drawing — they are grouped, never offered as a
    choice. ("many" stays in the resolver as a guard; exact matching cannot reach it.)"""
    r = pi.resolve_product("12392-04", ["12392-04-GA Mod Bracket Set_revA.pdf",
                                        "12392 04 GA Other_revB.pdf"])
    assert r["status"] == "ok" and len(r["matches"]) == 1
    r = pi.resolve_product("12392-04", ["12392-04-GA Set_revA.pdf", "12392-04-ASSY Set_revA.pdf"])
    assert r["status"] == "ok"


def test_a_part_drawing_is_said_and_not_blocked():
    r = pi.resolve_product("11650-03-01M", PACK)
    assert r["status"] == "not_an_assembly" and "single part drawing" in r["message"]


def test_the_engine_and_the_portal_use_one_resolver():
    for d, i in [("11650-06", "11650-06-GA"), ("11650-06-GA Rev B", "11650-06-GA"),
                 ("11650-06", "11650-06-SA01"), ("11650-06-GA", "11650-06-GA2")]:
        assert rc._names_the_product(d, i) == pi.names_the_product(d, i)
    src = (ROOT / "src" / "route_compiler.py").read_text(encoding="utf-8")
    assert "from product_identity import names_the_product" in src


@pytest.fixture()
def api(tmp_path, monkeypatch):
    stub = types.ModuleType("config")
    stub.API_KEY = ""
    stub.FILE_ROOTS = [str(tmp_path)]
    monkeypatch.setitem(sys.modules, "config", stub)
    monkeypatch.syspath_prepend(str(ROOT / "sdi-intelligence-backend"))
    sys.modules.pop("estimate_routes", None)
    er = pytest.importorskip("estimate_routes",
                             reason="fastapi/pydantic not installed in this environment")
    return er, tmp_path


def test_the_service_reads_a_folder_and_answers_with_the_engines_resolver(api):
    er, tmp = api
    job = tmp / "11650-06-FragranceCoffret2025"
    job.mkdir()
    for n in PACK:
        (job / n).write_text("x")
    out = er.product_check(er.ProductCheckRequest(drawing_number="11650-02",
                                                  files=[str(job)]))
    assert out["status"] == "ok" and out["match"]["number"] == "11650-02-GA"
    assert any(o["number"] == "11650-06-GA" for o in out["others"])


def test_the_page_holds_run_on_none_or_many_and_asks_on_every_change():
    page = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
        encoding="utf-8")
    assert '"/api/estimate/product-check"' in page
    assert 'if(productBlocks())' in page
    assert 'productCheck.status === "none" || productCheck.status === "many"' in page
    assert 'drawing.addEventListener("input", checkProduct)' in page
    render = page[page.index("function renderFiles(){"):]
    assert "checkProduct()" in render[:2500], "adding or removing a drawing does not re-check"
