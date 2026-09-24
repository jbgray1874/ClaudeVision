"""One category code printed over several articles is several parts, not one.

12312-01-GA Rev B prints nine purchased lines as "P/P" (LED driver, LED tape, grommets, Velcro
loop and hook, two EPDM tapes, two cables) and two washers as "FIXING". Every stage keyed on
the code, so the book carried one "P/P — LED POWER DRIVER" x2 at £84.34 and one washer; the
tape, grommets, Velcro, EPDM, cables and the M6 washer had no line and no price.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import llm_full_extract as lfe                                    # noqa: E402
import route_compiler as rc                                       # noqa: E402
from part_identity import category_code_identities                # noqa: E402

PP = [("LED POWER DRIVER, 24v 2amp", 1), ("SUPER FLEXIBLE Z LED TAPE, 24v, 375cm", 1),
      ("SEMI BLIND RUBBER GROMMET [G10]", 3), ("25mm SELF-ADHESIVE VELCRO - LOOP", 1),
      ("25mm SELF-ADHESIVE VELCRO - HOOK", 1), ("10x3mm EPDM CLOSED CELL TAPE, 1230mm", 2),
      ("10x3mm EPDM CLOSED CELL TAPE, 300mm", 2), ("Power Cord UK Plug to C13 IEC", 1),
      ("Y Splitter extension Cable, Single C14 to Dual C13", 1)]
WASHERS = [("M6 WASHER", 4), ("M5 EXTERNALLY SERRATED WASHER", 2)]


def _extract():
    bom = [{"part_number": "P/P", "description": d, "qty": q, "is_bought_in": True,
            "material_family": "bought_in"} for d, q in PP]
    bom += [{"part_number": "FIXING", "description": d, "qty": q, "is_bought_in": True,
             "material_family": "bought_in"} for d, q in WASHERS]
    bom.append({"part_number": "12312-01-02M", "description": "DISPLAY BRACKET", "qty": 2,
                "material_family": "metal", "is_fabricated": True})
    return {"bom": bom, "assemblies": [
        {"part_number": "12312-01-GA", "children": [
            {"part_number": "12312-01 LIGHTING ASM", "qty": 1},
            {"part_number": "FIXING", "qty": 4}, {"part_number": "12312-01-02M", "qty": 2}]},
        {"part_number": "12312-01 LIGHTING ASM", "children": [{"part_number": "P/P", "qty": 1}]}]}


def test_each_article_gets_its_own_identity_and_keeps_the_printed_code():
    rows = _extract()["bom"]
    ids = category_code_identities(rows)
    pp = {ids[i] for i in range(len(PP))}
    assert len(pp) == 9 and all(i.startswith("P/P-") for i in pp)
    assert ids[len(PP)] != ids[len(PP) + 1]
    assert len(PP) + 2 not in ids, "a real code is never renamed"


def test_one_code_over_one_article_is_left_alone():
    rows = [{"part_number": "FIXING", "description": "M4 PEM STUD"},
            {"part_number": "FIXING", "description": "M4 PEM STUD"}]
    assert category_code_identities(rows) == {}


def test_the_extract_projects_every_article():
    job = lfe.normalize_job(_extract())
    codes = [p["part_number"] for p in job["parts"]]
    assert sum(c.startswith("P/P-") for c in codes) == 9
    assert sum(c.startswith("FIXING-") for c in codes) == 2
    assert all(p.get("printed_code") in ("P/P", "FIXING") for p in job["parts"]
               if "-" in p["part_number"] and not p["part_number"].startswith("12312"))


def test_the_graph_carries_every_article_at_its_own_quantity():
    for ext in (_extract(), lfe.normalize_job(_extract())):
        parts = [{"part_number": "12312-01-GA", "is_assembly_parent": True},
                 {"part_number": "12312-01 LIGHTING ASM", "is_assembly_parent": True},
                 {"part_number": "12312-01-02M", "description": "DISPLAY BRACKET"}]
        g = rc.build_part_graph(parts, ext)
        nodes = {n.part_number: n for n in g["nodes"]}
        pp = [c for c in nodes if c.startswith("P/P-")]
        assert len(pp) == 9, sorted(nodes)
        assert "P/P" not in nodes and "FIXING" not in nodes
        kids = {e.part_number: e.qty for e in nodes["12312-01 LIGHTING ASM"].children}
        grommet = next(c for c in kids if "GROMMET" in c)
        top = {e.part_number: e.qty for e in nodes["12312-01-GA"].children}
        assert top["FIXING-M6-WASHER"] == 4 and top["FIXING-M5-EXTERNALLY-SERRATED-WASHER"] == 2
        assert kids[grommet] == 3


def test_a_split_row_still_joins_its_own_minted_record_and_not_anothers():
    parts = [{"part_number": "A-GA", "is_assembly_parent": True},
             {"part_number": "BI-PEMSTUD", "description": "M4 PEM STUD", "page_roles": ["bought_in"]},
             {"part_number": "BI-WASHER", "description": "M6 WASHER", "page_roles": ["bought_in"]}]
    rows = [{"part_number": "FIXING", "description": "M4 PEM STUD", "quantity": 2, "bom_parent": "A-GA"},
            {"part_number": "FIXING", "description": "M6 WASHER", "quantity": 4, "bom_parent": "A-GA"},
            {"part_number": "FIXING", "description": "M5 EXTERNALLY SERRATED WASHER",
             "quantity": 2, "bom_parent": "A-GA"}]
    g = rc.build_part_graph(parts, {}, bom_rows=rows)
    al = g["aliases"]
    assert al.get("FIXING-M4-PEM-STUD") == "BI-PEMSTUD"
    assert al.get("FIXING-M6-WASHER") == "BI-WASHER"
    assert al.get("FIXING-M5-EXTERNALLY-SERRATED-WASHER") is None, "an M5 washer is not the M6 one"


def test_every_article_reaches_the_workbook_at_its_own_quantity():
    import wb_populate as wp
    summary = {
        "manufacturing_writeup": {"parts": [
            {"part_number": "12312-01-GA", "description": "HEADER", "is_assembly_parent": True},
            {"part_number": "12312-01 LIGHTING ASM", "description": "LIGHTING",
             "is_assembly_parent": True},
            {"part_number": "12312-01-02M", "description": "DISPLAY BRACKET", "quantity": 2}]},
        "llm_full_extract": _extract(),
        "document_analysis": {"bom_rows":
            [{"part_number": "P/P", "description": d, "quantity": q,
              "bom_parent": "12312-01 LIGHTING ASM"} for d, q in PP]
            + [{"part_number": "FIXING", "description": d, "quantity": q,
                "bom_parent": "12312-01-GA"} for d, q in WASHERS]},
        "estimate_summary": {}}
    rc.compile_route_without_pricing(summary)
    lines = {l["part_number"]: l for l in wp.canonicalise_part_estimates_for_workbook(summary, [])}
    pp = {c: l for c, l in lines.items() if c.startswith("P/P-")}
    assert len(pp) == 9, sorted(lines)
    grommet = next(l for c, l in pp.items() if "GROMMET" in c)
    assert float(grommet["quantity"]) == 3
    assert float(lines["FIXING-M6-WASHER"]["quantity"]) == 4
    assert float(lines["FIXING-M5-EXTERNALLY-SERRATED-WASHER"]["quantity"]) == 2
