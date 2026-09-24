"""The portal's Drawing Number is the product; every other GA in the pack is detail.

James Gray, 23 Sep 2026, on the 11650-06 re-run: "Drawing Number on the portal is the
product. Every other GA in the folder is detail, counted only on a path from that product.
Do not treat 'two GAs in one enquiry' as two things that ship. That assumption is what
doubled SA02 / tabs / RSB / PEM."

The folder held the Coffret kit GA (11650-06-GA) and the cabinet-top GA (11650-02-GA). The
kit takes three of the top's RSB sub-assembly; the top's own BOM — its panels, its Ross
hardware, and one more SA02 — was costed as a second product beside the kit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                           # noqa: E402


def _pack():
    """11650-06 as the folder arrived: the kit GA and the cabinet-top GA, both unowned."""
    parts = [
        {"part_number": "11650-06-GA", "description": "COFFRET HOSPITAL KIT", "quantity": 1,
         "is_assembly_parent": True, "page_roles": ["assembly"]},
        {"part_number": "11650-02-GA", "description": "CABINET TOP", "quantity": 1,
         "is_assembly_parent": True, "page_roles": ["assembly"]},
        {"part_number": "11650-02-SA02", "description": "RSB SUB ASSY", "quantity": 1,
         "is_sub_assembly": True, "page_roles": ["assembly"]},
        {"part_number": "11650-02-03M", "description": "RSB PLATE", "quantity": 1,
         "page_roles": ["detail"]},
        {"part_number": "11650-02-04M", "description": "LOCKING TAB", "quantity": 2,
         "page_roles": ["detail"]},
        {"part_number": "11650-02-01M", "description": "TOP PANEL", "quantity": 1,
         "page_roles": ["detail"]},
        {"part_number": "ROSS-HINGE", "description": "ROSS HINGE", "quantity": 2,
         "page_roles": ["detail"]},
    ]
    extract = {"assemblies": [
        {"part_number": "11650-06-GA", "children": [
            {"part_number": "11650-02-SA02", "qty": 3}]},
        {"part_number": "11650-02-GA", "children": [
            {"part_number": "11650-02-SA02", "qty": 1},
            {"part_number": "11650-02-01M", "qty": 1},
            {"part_number": "ROSS-HINGE", "qty": 2}]},
        {"part_number": "11650-02-SA02", "children": [
            {"part_number": "11650-02-03M", "qty": 1},
            {"part_number": "11650-02-04M", "qty": 2}]},
    ]}
    return parts, extract


def test_without_a_declared_product_the_second_ga_ships_too():
    """THE FAULT, AS IT WAS. Nothing named the product, so both GAs cascaded: SA02 4 not 3,
    and the top's panel and Ross hinges were costed into a kit that has none."""
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract)
    assert sorted(g["top_assemblies"]) == ["11650-02-GA", "11650-06-GA"]
    assert g["quantities"]["11650-02-SA02"] == 4
    assert "ROSS-HINGE" in g["quantities"]


def test_the_declared_product_is_the_only_root():
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="11650-06")
    q = g["quantities"]
    assert g["top_assemblies"] == ["11650-06-GA"] and g["product_root"] == "11650-06-GA"
    assert q["11650-02-SA02"] == 3, q
    assert q["11650-02-03M"] == 3, q
    assert q["11650-02-04M"] == 6, q
    for gone in ("11650-02-GA", "11650-02-01M", "ROSS-HINGE"):
        assert gone not in q, f"{gone} is only under the other GA and was still costed"
    # The shared sub-assembly keeps only the product's parent.
    sa02 = next(n for n in g["nodes"] if n.part_number == "11650-02-SA02")
    assert sa02.parents == ["11650-06-GA"], sa02.parents


def test_what_was_set_aside_is_said_and_named():
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="11650-06-GA Rev B")
    issue = next(i for i in g["issues"] if i.get("code") == "outside_the_product")
    assert issue["root"] == "11650-02-GA" and issue["product"] == "11650-06-GA"
    assert sorted(issue["identities"]) == ["11650-02-01M", "11650-02-GA", "ROSS-HINGE"]


def test_the_set_aside_records_leave_the_costed_population():
    """The graph forgetting a node does not stop its RECORD being priced — the workbook is
    written from the records. They leave, and the summary keeps what left and why."""
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="11650-06")
    summary: dict = {}
    removed = rc.set_aside_outside_product(parts, g["issues"], summary=summary)
    assert sorted(p["part_number"] for p in removed) == [
        "11650-02-01M", "11650-02-GA", "ROSS-HINGE"]
    assert all(p["part_number"] not in {"ROSS-HINGE", "11650-02-01M"} for p in parts)
    assert {e["root"] for e in summary["set_aside_outside_product"]} == {"11650-02-GA"}


def test_a_number_that_names_nothing_stops_the_roll_up_and_says_so():
    """Rule 4: no guess. Two roots and a Drawing Number that is neither — the Boots code, say
    — rolls nothing up: an un-multiplied kit is visibly unfinished, a doubled one is not."""
    parts, extract = _pack()
    g = rc.build_part_graph(parts, extract, declared_product="AC0706-03")
    assert g["top_assemblies"] == [] and g["product_root"] == ""
    issue = next(i for i in g["issues"] if i.get("code") == "declared_product_not_resolved")
    assert issue["rolled_up"] is False and "NOTHING is rolled up" in issue["detail"]
    assert g["quantities"]["11650-02-SA02"] == 1        # its own drawing count, un-multiplied


def test_one_root_and_a_mismatched_number_costs_the_root_and_flags_it():
    """With one root there is nothing to choose between, so it cascades — and the mismatch is
    still on the record for the estimator to correct."""
    parts, extract = _pack()
    parts = [p for p in parts if p["part_number"] not in {"11650-02-GA", "11650-02-01M",
                                                          "ROSS-HINGE"}]
    extract["assemblies"] = [a for a in extract["assemblies"]
                             if a["part_number"] != "11650-02-GA"]
    g = rc.build_part_graph(parts, extract, declared_product="11650-99")
    assert g["top_assemblies"] == ["11650-06-GA"]
    assert g["quantities"]["11650-02-SA02"] == 3
    issue = next(i for i in g["issues"] if i.get("code") == "declared_product_not_resolved")
    assert issue["rolled_up"] is True


def test_a_number_never_names_a_part_of_the_product():
    assert rc._names_the_product("11650-06", "11650-06-GA")
    assert rc._names_the_product("11650-06 GA_RevB", "11650-06-GA")
    assert not rc._names_the_product("11650-06", "11650-06-SA01")
    assert not rc._names_the_product("11650-06-GA", "11650-06-GA2")
    assert not rc._names_the_product("AC0706-03", "11650-06-GA")


def test_the_declared_product_reaches_every_compile(monkeypatch):
    """Read from the summary first, the environment (set by --product) second."""
    monkeypatch.setenv("SDI_PRODUCT", "11650-06")
    assert rc.declared_product_of({}) == "11650-06"
    assert rc.declared_product_of({"declared_product": "12392-04-GA"}) == "12392-04-GA"
    monkeypatch.delenv("SDI_PRODUCT")
    assert rc.declared_product_of({}) == ""


def test_the_runner_passes_the_portal_drawing_number():
    sys.path.insert(0, str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner as runner
    cmd = runner.engine_command(ROOT, Path("python"), Path("job"), 2, "Boots",
                                product="11650-06")
    assert cmd[cmd.index("--product") + 1] == "11650-06"
    assert "--product" not in runner.engine_command(ROOT, Path("python"), Path("job"), 2,
                                                    "Boots")


def test_the_quote_is_titled_by_the_product_not_the_sheet_the_model_read():
    """Rule 5. The last run was titled AC0706-05 — the extender set's sheet."""
    from client_quote_html import _drawing_identity
    summary = {
        "llm_full_extract": {"drawing_info": {
            "drawing_number": "11650-06-SA01", "title": "AC0706-05 END PANEL GF CONVERSION",
            "revision": "A"}},
        "estimate_summary": {"canonical_route_shadow": {
            "product_root": "11650-06-GA", "top_assembly": "11650-06-GA",
            "top_assemblies": ["11650-06-GA"],
            "nodes": [{"part_number": "11650-06-GA",
                       "description": "COFFRET HOSPITAL KIT"}]}},
    }
    number, rev, product = _drawing_identity(summary, "11650-06-FragranceCoffret2025")
    assert number == "11650-06-GA", number
    assert "AC0706-05" not in f"{number} {rev} {product}"
    assert "COFFRET" in str(product).upper(), product


# ── 23 Sep 2026, the 11650-02 run: charged only on a path from the product ──────────────
#
# "Every charged material, bought-in item and labour operation must have an identifiable
# path back to" the product. The first cut set aside only what ANOTHER GA reached; a Yiree
# row (x4 at £126.04) and a minted "End Panel" (£943.42), joined to nothing, were charged
# to the cabinet top — £1,505 of a £1,956 unit.

def _pack_with_orphans():
    parts, extract = _pack()
    parts += [
        {"part_number": "YIREE CODE-DWG491667", "description": "YIREE CODE - DWG491667",
         "quantity": 4, "page_roles": ["bought_in"]},
        {"part_number": "BI-ENDPANEL", "description": "End Panel", "quantity": 1,
         "page_roles": ["bought_in"], "source": "prose_recogniser_layer2"},
        {"part_number": "PACKAGING", "description": "Packaging", "quantity": 1,
         "_commercial_placeholder": True},
    ]
    return parts, extract


def test_a_line_nothing_links_to_the_product_is_not_charged_and_is_named():
    parts, extract = _pack_with_orphans()
    g = rc.build_part_graph(parts, extract, declared_product="11650-02")
    q = g["quantities"]
    assert "YIREE CODE-DWG491667" not in q and "BI-ENDPANEL" not in q, q
    issue = next(i for i in g["issues"] if i.get("code") == "not_linked_to_the_product")
    assert {"YIREE CODE-DWG491667", "BI-ENDPANEL"} <= set(issue["identities"])
    summary: dict = {}
    rc.set_aside_outside_product(parts, g["issues"], summary=summary)
    assert all(p["part_number"] not in {"YIREE CODE-DWG491667", "BI-ENDPANEL"} for p in parts)
    reasons = {e["part_number"]: e["reason"] for e in summary["set_aside_outside_product"]}
    assert reasons["BI-ENDPANEL"] == "not_linked_to_the_product"


def test_an_order_level_line_is_never_scoped_out():
    parts, extract = _pack_with_orphans()
    g = rc.build_part_graph(parts, extract, declared_product="11650-02")
    rc.set_aside_outside_product(parts, g["issues"])
    assert any(p["part_number"] == "PACKAGING" for p in parts)


def test_the_wrong_drawing_number_is_pointed_out():
    """11650-06-GA takes 3 of 11650-02-SA02: a run named 11650-02 has priced a component
    drawing and set aside the thing that ships. The page says so first."""
    parts, extract = _pack()
    compiled = rc.compile_job_route(parts, extract, declared_product="11650-02")
    lines = rc.product_scope_sentences(
        {"estimate_summary": {"canonical_route_shadow": compiled}})
    assert lines[0].startswith("Priced as 11650-02-GA")
    assert any("11650-06-GA is also in the pack and shares" in t
               and "Check the Drawing Number names the one that ships" in t for t in lines), lines
    # Stated as a fact to weigh, never as an instruction to switch.
    assert not any("should be" in t for t in lines), lines


def test_a_line_minted_after_the_graph_is_scoped_at_write_out():
    payload = {"product_root": "11650-06-GA",
               "nodes": [{"part_number": "11650-06-GA"},
                         {"part_number": "11650-04-03A",
                          "evidence": {"raw_aliases": ["11650-04-03A PETG"]}}]}
    lines = [{"part_number": "11650-04-03A PETG"}, {"part_number": "BI-LATEPANEL"},
             {"part_number": "DELIVERY"}]
    removed = rc.set_aside_late_lines(lines, payload)
    assert [p["part_number"] for p in removed] == ["BI-LATEPANEL"]
    assert [p["part_number"] for p in lines] == ["11650-04-03A PETG", "DELIVERY"]
    # No declared product: nothing changes.
    lines2 = [{"part_number": "BI-LATEPANEL"}]
    assert rc.set_aside_late_lines(lines2, {"nodes": payload["nodes"]}) == []


def test_an_assemblys_own_bom_row_counts_as_already_on_the_bom():
    """The £943.42 'End Panel' was minted because the recogniser's 'already on the BOM' list
    held part records only, and 06-SA01 is an assembly row. BOM rows and assemblies now count."""
    import bought_in_recogniser as bir
    assert bir._phrase_already_in_bom("End Panel",
                                      ["END PANEL GF CONVERSION PANEL SET AC0706-05"])
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    call = src.index("_det_items = recognise_bought_in_in_prose(")
    widen = src.index("for _row in _bom_like:")
    assert widen < call and "_existing_descs.add(_rd)" in src[widen:call]


def test_the_report_leads_with_what_was_priced():
    import job_report_html as jr
    parts, extract = _pack()
    compiled = rc.compile_job_route(parts, extract, declared_product="11650-02")
    html_ = jr._render_product_scope({"estimate_summary": {"canonical_route_shadow": compiled}})
    assert "What this estimate prices" in html_ and "11650-06-GA" in html_
    assert jr._render_product_scope({}) == ""


def test_the_revision_is_the_products_own_sheets():
    """The 11650-02 run printed '11650-02-GA Rev B': B is the kit's revision from another
    title block; the top's own drawing is 11650-02-GA TOP_revD.PDF."""
    from client_quote_html import _drawing_identity
    summary = {
        "llm_full_extract": {"drawing_info": {"drawing_number": "11650-02-GA",
                                              "title": "TOP", "revision": "B"}},
        "job_source_pdfs": [{"name": "11650-06-GA COFFRET HOSPITAL KIT_REVB.PDF"},
                            {"name": "11650-02-GA TOP_revD.PDF"}],
        "estimate_summary": {"canonical_route_shadow": {
            "product_root": "11650-02-GA", "top_assembly": "11650-02-GA",
            "nodes": [{"part_number": "11650-02-GA", "description": "TOP"}]}},
    }
    number, rev, _ = _drawing_identity(summary, "11650-02")
    assert number == "11650-02-GA" and rev.upper().endswith("D"), (number, rev)


# ── 23 Sep 2026, the 15:45 11650-02 run: real parts caught by the not-linked rule ─────────

def _top_and_kit_as_the_tables_read():
    """The extract placed 02-SA02 under the kit only; BOTH GAs' own tables list it."""
    parts = [
        {"part_number": "11650-06-GA", "description": "COFFRET HOSPITAL KIT", "quantity": 1,
         "is_assembly_parent": True},
        {"part_number": "11650-02-GA", "description": "TOP ASSEMBLY", "quantity": 1,
         "is_assembly_parent": True},
        {"part_number": "11650-02-SA02", "description": "TOP RSB", "quantity": 1,
         "is_sub_assembly": True},
        {"part_number": "11650-02-03M", "description": "RSB PLATE", "quantity": 1},
        {"part_number": "ROSS HANDLING-TS-15M5X10", "description": "ROSS HANDLING - TS-15M5X10",
         "quantity": 2, "page_roles": ["bought_in"]},
    ]
    extract = {"assemblies": [
        {"part_number": "11650-06-GA", "children": [{"part_number": "11650-02-SA02", "qty": 3}]},
        {"part_number": "11650-02-SA02", "children": [{"part_number": "11650-02-03M", "qty": 1}]},
    ]}
    rows = [
        {"part_number": "11650-02-SA02", "quantity": 3, "bom_parent": "11650-06-GA"},
        {"part_number": "11650-02-SA02", "quantity": 1, "bom_parent": "11650-02-GA"},
        {"part_number": "ROSS HANDLING - TS-15M5X10", "quantity": 2, "bom_parent": "11650-02-GA"},
    ]
    return parts, extract, rows


def test_a_part_on_two_general_arrangements_tables_is_linked_under_both():
    """The top lost its RSB sub-assembly: the table-stated edge was refused because the
    extract had placed the part under the kit."""
    parts, extract, rows = _top_and_kit_as_the_tables_read()
    g = rc.build_part_graph(parts, extract, rows, ["11650-02-GA", "11650-06-GA"],
                            declared_product="11650-02")
    assert g["quantities"].get("11650-02-SA02") == 1, g["quantities"]
    assert g["quantities"].get("11650-02-03M") == 1
    g = rc.build_part_graph(parts, extract, rows, ["11650-02-GA", "11650-06-GA"],
                            declared_product="11650-06-GA")
    assert g["quantities"].get("11650-02-SA02") == 3 and g["quantities"]["11650-02-03M"] == 3


def test_a_row_restating_a_sub_assemblys_part_on_its_parent_is_still_refused():
    """The protection that stays: an exploded table on the kit's GA lists the RSB plate the
    kit already reaches THROUGH 02-SA02 — linking it again would count it twice."""
    parts, extract, rows = _top_and_kit_as_the_tables_read()
    rows.append({"part_number": "11650-02-03M", "quantity": 3, "bom_parent": "11650-06-GA"})
    g = rc.build_part_graph(parts, extract, rows, ["11650-02-GA", "11650-06-GA"],
                            declared_product="11650-06-GA")
    assert g["quantities"]["11650-02-03M"] == 3, g["quantities"]


def test_a_spaced_hyphen_is_the_same_code():
    """The Ross handles fell off the top: linked as 'ROSS HANDLING - TS-15M5X10', costed as
    'ROSS HANDLING-TS-15M5X10', and the second read as not linked."""
    assert rc.clean_part_number("ROSS HANDLING - TS-15M5X10") == "ROSS HANDLING-TS-15M5X10"
    parts, extract, rows = _top_and_kit_as_the_tables_read()
    g = rc.build_part_graph(parts, extract, rows, ["11650-02-GA", "11650-06-GA"],
                            declared_product="11650-02")
    assert g["quantities"].get("ROSS HANDLING-TS-15M5X10") == 2, g["quantities"]
    unlinked = [i for i in g["issues"] if i.get("code") == "not_linked_to_the_product"]
    assert not any("ROSS" in x for i in unlinked for x in i["identities"])


def test_the_hint_names_the_shared_sub_assembly_not_a_fastener():
    parts, extract, rows = _top_and_kit_as_the_tables_read()
    compiled = rc.compile_job_route(parts, extract, rows, ["11650-02-GA", "11650-06-GA"],
                                    declared_product="11650-02")
    lines = rc.product_scope_sentences({"estimate_summary": {"canonical_route_shadow": compiled}})
    assert any("shares 11650-02-SA02 with 11650-02-GA" in t for t in lines), lines


def test_the_m4_pem_is_never_the_m6_pem():
    """The 15:45 hint said the kit uses FIXING632 — the M6x12 PEM — where the kit's own table
    lists the M4x12 PEM under the stem code FIXING. Pinned with the rows as the tables read
    them: two studs, two identities, two counts, whichever product is named."""
    parts = [
        {"part_number": "11650-06-GA", "quantity": 1, "is_assembly_parent": True},
        {"part_number": "11650-02-GA", "quantity": 1, "is_assembly_parent": True},
        {"part_number": "11650-02-SA01", "quantity": 1, "is_sub_assembly": True},
        {"part_number": "11650-02-SA02", "quantity": 1, "is_sub_assembly": True},
        {"part_number": "FIXING632", "description": "M6x12mm THREADED PEM STUD", "quantity": 4,
         "page_roles": ["bought_in"]},
        {"part_number": "FIXING", "description": "M4x12mm THREADED PEM STUD", "quantity": 2,
         "page_roles": ["bought_in"]},
        {"part_number": "FIXING65", "description": "M5 SELF-CLINCH NUT, BZP", "quantity": 2},
    ]
    rows = [
        {"part_number": "11650-02-SA01", "quantity": 1, "bom_parent": "11650-02-GA"},
        {"part_number": "11650-02-SA02", "quantity": 1, "bom_parent": "11650-02-GA"},
        {"part_number": "FIXING632", "description": "M6x12mm THREADED PEM STUD", "quantity": 4,
         "bom_parent": "11650-02-SA01"},
        {"part_number": "FIXING65", "description": "M5 SELF-CLINCH NUT, BZP", "quantity": 2,
         "bom_parent": "11650-02-SA01"},
        {"part_number": "FIXING", "description": "M4x12mm THREADED PEM STUD", "quantity": 2,
         "bom_parent": "11650-02-SA02"},
        {"part_number": "11650-02-SA02", "quantity": 3, "bom_parent": "11650-06-GA"},
        {"part_number": "FIXING", "description": "M4x12mm THREADED PEM STUD", "quantity": 18,
         "bom_parent": "11650-06-GA"},
    ]
    for product in ("11650-02", "11650-06-GA"):
        g = rc.build_part_graph(parts, {}, rows, ["11650-02-GA", "11650-06-GA"],
                                declared_product=product)
        assert "FIXING" not in (g.get("aliases") or {}), g.get("aliases")
        assert "FIXING632" not in (g["children"].get("11650-06-GA") or set())
    g = rc.build_part_graph(parts, {}, rows, ["11650-02-GA", "11650-06-GA"],
                            declared_product="11650-02")
    assert g["quantities"]["FIXING632"] == 4 and g["quantities"]["FIXING"] == 2


def test_the_title_is_the_products_own_file_label_not_a_sub_assemblys_title_block():
    """16:49: the header read 'END PANEL GF CONVERSION PANEL SET' (06-SA01's title block) and
    the scope line read an engine note. The product's file names it COFFRET HOSPITAL KIT."""
    from client_quote_html import _drawing_identity
    summary = {
        "llm_full_extract": {"drawing_info": {"drawing_number": "11650-06-GA", "revision": "B",
                                              "title": "END PANEL GF CONVERSION PANEL SET"}},
        "job_source_pdfs": [{"name": "11650-06-GA COFFRET HOSPITAL KIT_REVB.PDF"},
                            {"name": "11650-02-GA TOP_revD.PDF"}],
        "estimate_summary": {"canonical_route_shadow": {
            "product_root": "11650-06-GA", "declared_product": "11650-06-GA",
            "top_assembly": "11650-06-GA", "issues": [],
            "nodes": [{"part_number": "11650-06-GA",
                       "description": "assembly (from the SolidWorks model's own tree)"}]}},
    }
    number, rev, title = _drawing_identity(summary, "11650-06")
    assert number == "11650-06-GA" and "COFFRET HOSPITAL KIT" in str(title).upper(), title
    lines = rc.product_scope_sentences(summary)
    assert lines[0].startswith("Priced as 11650-06-GA (COFFRET HOSPITAL KIT)"), lines


def test_a_mirror_the_bom_lists_on_its_own_line_is_not_folded_into_its_base():
    """11650-06: the kit BOM prints 'Mirror11650-03-GA' HANDED ARM x3 and
    'Mirror11650-03-02M' x3. The mirror rule fell back onto the base part (it looked only for
    the drawing's '<code> MIR' spelling), and the handed arm set was merged into the plain
    one — 3 arms costed where the kit has 6. 11350's case (no separate listing in the model's
    spelling) still joins."""
    ids = {"11650-03-SA01", "MIRROR11650-03-SA01", "11650-03-02M", "MIRROR11650-03-02M"}
    assert rc._drawing_code_aliases(ids).get("MIRROR11650-03-SA01") == "11650-03-SA01"
    assert rc._drawing_code_aliases(
        ids, listed={"MIRROR11650-03-SA01", "MIRROR11650-03-02M"}) == {}
    assert rc._drawing_code_aliases(
        {"11350-01-02 MIR", "MIRROR11350-01-02M", "11350-01-02"},
        listed={"11350-01-02 MIR", "11350-01-02"}) == {"MIRROR11350-01-02M": "11350-01-02 MIR"}
