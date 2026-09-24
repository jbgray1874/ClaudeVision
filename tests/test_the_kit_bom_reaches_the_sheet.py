"""What the 11650-06 kit BOM lists is what the sheet charges — the handed set, the M4 stud, the key.

The 04:22 run of 11650-06-GA (Rev B), traced through its own JSON, 24 Sep 2026:

  - the handed arm set (Mirror11650-03-GA, HANDED ARM x3) and its bracket (Mirror11650-03-02M
    x3) were DROPPED by the graph as "character interleave artefacts" — a mirror code is its
    base's characters in order, so it scans as two neighbouring rows zipped together — and the
    SolidWorks tree's Mirror11650-03-GA was filed as a "model variant" because it shares the
    slider with the plain arm set;
  - the kit's M4x12 PEM stud rows were poured into FIXING632 (PEM STUD M6 x 12mm): the thread
    size split into "M" and "4", the single letter was dropped, and PEM, STUD and 12 matched;
  - the Yiree key, asked as a purchase, was answered as a made part ("local sheet metal
    fabricator quotes", £65 each) and the cache held that answer still on every run.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator as E                                                # noqa: E402
import route_compiler as rc                                          # noqa: E402
from pricing_service import answers_a_purchase                       # noqa: E402


# ── the handed set ───────────────────────────────────────────────────────────────────────

def _kit():
    parts = [{"part_number": "11650-06-GA", "description": "KIT", "is_assembly_parent": True},
             {"part_number": "11650-03-GA", "description": "LH ARM ASSY",
              "is_assembly_parent": True},
             {"part_number": "Mirror11650-03-GA", "description": "HANDED ARM",
              "is_assembly_parent": True},
             {"part_number": "11650-03-02M", "description": "ARM"},
             {"part_number": "Mirror11650-03-02M", "description": "HANDED ARM BRACKET"}]
    rows = [{"part_number": p["part_number"], "quantity": 3, "bom_parent": "11650-06-GA"}
            for p in parts[1:]]
    return parts, rows


def test_a_mirror_code_is_never_read_as_two_rows_zipped():
    parts, rows = _kit()
    g = rc.build_part_graph(parts, {}, bom_rows=rows)
    dropped = [i.get("identity") for i in g.get("issues", [])
               if i.get("code") == "bom_row_interleave_artifact"]
    assert dropped == [], dropped
    assert {"MIRROR11650-03-GA", "MIRROR11650-03-02M"} <= set(g["records"])


def test_a_real_zipped_row_is_still_dropped():
    sq = rc._squashed
    assert rc._interleave_of(sq("1100997755-E0P2D-GM0"), sq("10975-02-G01"),
                             sq("10975 EPDM CLOSED CELL TAPE^10975-02-GA"), min_each=5)


def test_an_opposite_hand_tree_is_minted_not_filed_as_a_variant():
    from source_connectors.solidworks import NativeJob, apply_native_hierarchy_to_parts
    parts = [{"part_number": "11650-03-GA", "is_assembly_parent": True,
              "assembly_children": ["11650-03-01M", "11650-03-SA01"]},
             {"part_number": "11650-03-01M", "description": "SLIDER"},
             {"part_number": "11650-03-SA01", "description": "ARM ASSY"}]
    job = NativeJob(hierarchy={"Mirror11650-03-GA": [("11650-03-01M", 1.0)]}, found=True)
    apply_native_hierarchy_to_parts(parts, job)
    assert any(str(p.get("part_number")).upper() == "MIRROR11650-03-GA" for p in parts), \
        "the handed arm set was filed as a variant of the plain one"


def test_a_plain_second_tree_over_the_same_members_is_still_a_variant():
    from source_connectors.solidworks import NativeJob, apply_native_hierarchy_to_parts
    parts = [{"part_number": "7332-01-101", "is_assembly_parent": True,
              "assembly_children": ["7332-01-05M"]},
             {"part_number": "7332-01-05M", "description": "LEG"}]
    job = NativeJob(hierarchy={"7332-01-GA2": [("7332-01-05M", 2.0)]}, found=True)
    apply_native_hierarchy_to_parts(parts, job)
    assert not any(str(p.get("part_number")).upper() == "7332-01-GA2" for p in parts)


# ── the M4 stud ──────────────────────────────────────────────────────────────────────────

def _same(a, b):
    f = lambda d: E._bought_in_token_set({"description": d})       # noqa: E731
    return E._bought_in_same_item(f(a), f(b))


def test_an_m4_stud_is_not_an_m6_stud():
    assert not _same("M4x12mm THREADED PEM STUD", "PEM STUD M6 x 12mm")
    assert not _same("M5 SELF CLINCH NUT", "M4 SELF CLINCH NUT")


def test_the_same_thread_written_two_ways_is_still_one_item():
    assert _same("M6x12mm THREADED PEM STUD", "PEM STUD M6 x 12mm")
    assert _same("M5-2 SELF CLINCH NUT", "M5 SELF-CLINCH NUT")


# ── the key ──────────────────────────────────────────────────────────────────────────────

def test_a_purchase_answered_as_a_made_part_is_refused():
    made = {"found": True, "price_gbp": 65.0, "source_type": "llm_market_estimate",
            "verify_against": ["local sheet metal fabricator quotes", "Protolabs"]}
    bought = {"found": True, "price_gbp": 1.25, "source_type": "llm_market_estimate",
              "verify_against": ["RS Components", "Screwfix"],
              "item_priced": "Yiree Binding Screw, one screw"}
    assert not answers_a_purchase(made)
    assert answers_a_purchase(bought)


def test_words_describing_a_bought_item_do_not_refuse_it():
    """D-216: the 05:40 run left the M4 knob and PEM stud unpriced beside the key. What an
    item is FOR ("fastener for sheet metal", "CNC machined") is not who it is bought from."""
    pem = {"found": True, "price_gbp": 0.12, "verify_against": ["RS Components", "Essentra"],
           "price_basis": "self-clinching fastener for sheet metal, per stud",
           "item_priced": "M4x12 PEM stud"}
    knob = {"found": True, "price_gbp": 0.85, "supplier_name": "Elite Sourcing Solutions Ltd",
            "item_priced": "CNC machined knurled knob M4"}
    assert answers_a_purchase(pem) and answers_a_purchase(knob)


def test_the_kits_printed_count_lands_on_the_costed_stud():
    """The drawing prints the uncoded stud as FIXING; the record is BI-PEMSTUD (the shared
    naming rule). The 05:40 graph had FIXING 18 (costed by nothing) and BI-PEMSTUD 30."""
    parts = [{"part_number": "11650-06-GA", "is_assembly_parent": True},
             {"part_number": "11650-02-SA02", "is_assembly_parent": True},
             {"part_number": "11650-03-SA01", "is_assembly_parent": True},
             {"part_number": "11650-03-01M", "description": "SLIDER"},
             {"part_number": "11650-02-04M", "description": "TAB"},
             {"part_number": "BI-PEMSTUD", "description": "M4x12mm THREADED PEM STUD",
              "page_roles": ["bought_in"],
              "bom_parents": [{"parent": "11650-02-SA02", "qty": 2},
                              {"parent": "11650-03-SA01", "qty": 2},
                              {"parent": "11650-06-GA", "qty": 18}]}]
    pem = "M4x12mm THREADED PEM STUD"
    rows = [
        {"part_number": "11650-02-SA02", "quantity": 3, "bom_parent": "11650-06-GA", "bom_sheet": "K#0"},
        {"part_number": "11650-03-SA01", "quantity": 3, "bom_parent": "11650-06-GA", "bom_sheet": "K#0"},
        {"part_number": "FIXING", "description": pem, "quantity": 2, "bom_parent": "11650-02-SA02", "bom_sheet": "T#2"},
        {"part_number": "FIXING", "description": pem, "quantity": 2, "bom_parent": "11650-03-SA01", "bom_sheet": "A#1"},
        {"part_number": "11650-03-01M", "quantity": 2, "bom_parent": "11650-03-SA01", "bom_sheet": "A#1"},
        {"part_number": "11650-02-04M", "quantity": 2, "bom_parent": "11650-02-SA02", "bom_sheet": "T#2"},
        {"part_number": "FIXING", "description": pem, "quantity": 18, "bom_parent": "11650-06-GA", "bom_sheet": "K#1"},
        {"part_number": "11650-03-01M", "quantity": 12, "bom_parent": "11650-06-GA", "bom_sheet": "K#1"},
        {"part_number": "11650-02-04M", "quantity": 6, "bom_parent": "11650-06-GA", "bom_sheet": "K#1"}]
    g = rc.build_part_graph(parts, {}, bom_rows=rows)
    assert "FIXING" not in g["records"]
    assert g["quantities"]["BI-PEMSTUD"] == 18


def test_one_vague_code_over_two_different_items_stays_two():
    parts = [{"part_number": "A-GA", "is_assembly_parent": True},
             {"part_number": "BI-PEMSTUD", "description": "M4 PEM STUD", "page_roles": ["bought_in"]},
             {"part_number": "BI-KNURLEDKNOB", "description": "M4 KNURLED KNOB", "page_roles": ["bought_in"]}]
    rows = [{"part_number": "FIXING", "description": "M4 PEM STUD", "quantity": 2, "bom_parent": "A-GA"},
            {"part_number": "FIXING", "description": "M4 KNURLED KNOB", "quantity": 4, "bom_parent": "A-GA"}]
    g = rc.build_part_graph(parts, {}, bom_rows=rows)
    assert g["aliases"].get("FIXING") is None


def test_both_askers_apply_the_check():
    ps = (ROOT / "src" / "pricing_service.py").read_text(encoding="utf-8")
    es = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert 'if _spec.get("supply") == "bought_in" and not answers_a_purchase(result):' in ps
    assert '_spec["purchase_check"] = 1' in ps
    assert "from pricing_service import answers_a_purchase as _purchase" in es
