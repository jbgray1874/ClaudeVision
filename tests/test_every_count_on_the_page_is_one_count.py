"""Every count on the page is one count, read from one record.

12173-02 Card Spinner (M&S), report of 1 Oct 2026. One page stated the same facts several
ways and none of them added up:

  * "25 to settle: 2 + 1 + 7 + 10 + 5 + 11" — a headline of 25 rows over a phrase summing to
    36, because failing checks and sizes assumed from a render were counts kept beside the
    Decisions list, not rows of it;
  * 12 failing checks in the bullets, section 2 and section 13, 11 in the banner — one was
    already Decisions row 2, and nothing said so;
  * "20 could not be run" for twenty findings of a check that DID run and needs a ruling, and
    "out of 45" counting findings against check functions;
  * "See section 8" and "listed in section 8" for checks that are section 13;
  * section 8 "Decisions needing resolution: none" over ten operations nothing claimed;
  * the Summary card cut its seventh reason; the workbook banner sent the reader to a list
    of 60 questions for a tally of 25; section 14 listed 17 of its 25;
  * "Not linked, so not priced: FIXING 1180" beside FIXING1180 charged on the sheet;
  * "No double-counting found" beside one screw on two lines;
  * bought-ins counted 7, 12 and 10 on one page.

Synthetic inputs only; the job's facts are in the docstrings.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf                                                 # noqa: E402
import invariants as inv                                                  # noqa: E402
import job_report_html as J                                               # noqa: E402
import route_compiler as rc                                               # noqa: E402


# ── the fixture the banner-tally tests use: TOP -> BODY -> 01M charged; a stated shutter ──

def _node(pn, kind, children=(), aliases=(), qty=1.0, parents=()):
    return {"part_number": pn, "kind": kind, "qty_per_unit": qty,
            "children": [{"part_number": c, "qty": 1.0} for c in children],
            "parents": list(parents), "evidence": {"raw_aliases": list(aliases)}}


def _charged(pn, gbp=5.0, **extra):
    p = {"part_number": pn, "quantity": 1, "unit_total_cost_gbp": gbp,
         "extended_total_cost_gbp": gbp,
         "material_estimate": {"cost_per_part_gbp": gbp, "unit_material_cost_gbp": gbp}}
    p.update(extra)
    return p


def _summary(nodes, parts, bom_rows=(), root="P-TOP", decisions=()):
    return {"document_analysis": {"bom_rows": list(bom_rows)},
            "estimate_summary": {
                "estimate_status": "ok",
                "part_estimates": parts,
                "canonical_route_shadow": {"schema": "priced_route.v1", "product_root": root,
                                           "top_assembly": root, "nodes": nodes,
                                           "decisions": list(decisions)}}}


TOP = _node("P-TOP", "assembly", children=("P-BODY", "WIDGET SHUTTER"))
BODY = _node("P-BODY", "assembly", children=("P-01M",))
PANEL = _node("P-01M", "leaf", parents=("P-BODY",))
SHUTTER = dict(_node("WIDGET SHUTTER", "leaf", qty=2.0),
               evidence={"raw_aliases": [], "bom_stated": True})


def _unowned(target="P-BODY", op="deburring"):
    return inv._violation(
        "canonical_route_decision_unverified", inv.BLOCKING,
        f"Route decision d1 for {op} on {target} is UNOWNED: nothing in this pack says who "
        f"performs it. ASK WHO PERFORMS THIS.",
        decision_id="d1", operation=op, target_id=target, conflicts=[])


def _with_checks(s, violations, run=("a", "b")):
    blocking = [v for v in violations if v["severity"] == inv.BLOCKING]
    unverified = [v for v in violations if v["severity"] == inv.UNVERIFIED]
    s["invariants"] = {"violations": violations, "blocking": len(blocking),
                       "unverified": len(unverified),
                       "may_quote_firm": not (blocking or unverified),
                       "checks_run": list(run)}
    return s


def _nums(phrase):
    return [int(n) for n in re.findall(r"(?:^|\+ )(\d+) ", phrase.split(";")[0])]


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# ── 0.0 the headline is the sum of its phrase, and the rows of its table ─────────────────

def test_a_failing_check_is_a_row_so_the_headline_adds_up():
    s = _summary([TOP, BODY, PANEL, SHUTTER], [_charged("P-01M")])
    _with_checks(s, inv.check_every_reached_bom_item_is_accounted_for(s) + [_unowned()])
    job = cf.costed_job(s)
    o = cf.outstanding_summary(job)
    # the shutter (missing price, its check netted) + the unowned route decision (a row)
    assert sum(_nums(o["phrase"])) == o["total"] == len(job["decisions_required"]) == 2
    row = next(d for d in job["decisions_required"] if d["kind"] == "consistency_check")
    assert row["part"] == "P-BODY" and row["check_code"] == "canonical_route_decision_unverified"
    assert row["owner"] == "estimator" and "ASK WHO" not in row["issue"]
    assert job["schema"] == "costed_job.v2"
    assert job["release"]["blocking_checks"] == 1 and job["release"]["outstanding"] == 2


def test_a_job_whose_only_open_item_is_a_failing_check_says_so_everywhere():
    s = _summary([dict(TOP, children=[{"part_number": "P-BODY", "qty": 1.0}]), BODY, PANEL],
                 [_charged("P-01M")])
    _with_checks(s, [inv._violation("geometry_unreconciled", inv.BLOCKING,
                                    "P-01M geometry does not reconcile.", parts=["P-01M"])])
    job = cf.costed_job(s)
    assert J._release_words(job, s)[1] == ("Not for release — 1 to settle: "
                                           "1 consistency finding failed")
    assert "not itemised here" not in J._render_decisions(job)
    verdict = J._render_verdict(J._extract_headline(s), J._extract_drawing_quality(s), False, s)
    assert "Still to settle: 1 — 1 consistency finding failed" in verdict


def test_an_engine_fault_is_owned_by_the_engine_from_config():
    s = _summary([dict(TOP, children=[{"part_number": "P-BODY", "qty": 1.0}]), BODY, PANEL],
                 [_charged("P-01M")])
    _with_checks(s, [inv._violation("removed_identity_on_the_sheet", inv.BLOCKING,
                                    "X is on the sheet.", identities=["X"])])
    row = next(d for d in cf.costed_job(s)["decisions_required"]
               if d["kind"] == "consistency_check")
    assert row["owner"].startswith("engine")


def test_a_record_saved_before_v2_still_adds_up():
    o = cf.outstanding_summary({"schema": "costed_job.v1",
                                "decisions_required": [{"kind": "market_figure", "part": "X",
                                                        "gbp_at_stake": 1.0}],
                                "release": {"draft": True, "blocking_checks": 7,
                                            "sizes_assumed": 4}})
    assert o["total"] == 12 == sum(_nums(o["phrase"])) and o["in_table"] == 1


def test_a_size_assumed_from_a_render_is_a_row():
    flag = "CONCEPT: size assumed from the render — confirm 600 x 400 x 18mm before release"
    s = _summary([dict(TOP, children=[{"part_number": "P-BODY", "qty": 1.0}]), BODY, PANEL],
                 [_charged("P-01M", review_flags=[flag])])
    job = cf.costed_job(s)
    rows = [d for d in job["decisions_required"] if d["kind"] == "size_assumed"]
    assert [d["part"] for d in rows] == ["P-01M"] and flag in rows[0]["assumption"]
    o = cf.outstanding_summary(job)
    assert "1 size assumed from a render" in o["phrase"] and o["total"] == sum(_nums(o["phrase"]))


# ── 0.1 the netting is narrow, marked, and stated ─────────────────────────────────────────

def test_only_the_same_question_is_netted_and_the_netting_is_said():
    s = _summary([TOP, BODY, PANEL, SHUTTER], [_charged("P-01M")])
    _with_checks(s, inv.check_every_reached_bom_item_is_accounted_for(s) + [_unowned()])
    job = cf.costed_job(s)
    fc = cf.failing_checks_summary(job)
    assert (fc["total"], fc["itemised"], fc["added"]) == (2, 1, 1)
    shutter = next(d for d in job["decisions_required"] if d["part"] == "WIDGET SHUTTER")
    assert shutter["also_failing_check"] == "reached_bom_item_unaccounted"
    assert any("already listed as a missing price" in r for r in job["release"]["reasons"])
    txt = _text(J.build_report_html(s))
    assert txt.count("already listed as a missing price") >= 3   # summary, verdict, checks
    assert "no open question" not in txt


_MARKET = {"cost_source": "market_ai_indicative",
           "material_estimate": {"unit_material_cost_gbp": 5.0,
                                 "cost_method": "market_ai_indicative"}}


def test_an_engine_fault_naming_a_listed_part_is_not_netted_away():
    s = _summary([dict(TOP, children=[{"part_number": "P-BODY", "qty": 1.0}]), BODY, PANEL],
                 [_charged("P-01M", **_MARKET)])
    _with_checks(s, [inv._violation("priced_identity_outside_published_graph", inv.BLOCKING,
                                    "P-01M is priced outside the graph.",
                                    identities=["P-01M"])])
    ds = cf.costed_job(s)["decisions_required"]
    assert any(d["kind"] == "market_figure" and d["part"] == "P-01M" for d in ds)
    assert any(d["kind"] == "consistency_check"
               and d["check_code"] == "priced_identity_outside_published_graph" for d in ds)


# ── 0.2 the stripped spelling, and one kind table that sorts the record once ─────────────

def test_a_labelled_row_joins_its_reached_part():
    src = {"canonical_route_shadow": {"product_root": "P-GA", "nodes": [
        {"part_number": "P-GA", "kind": "assembly", "children": [{"part_number": "LOW068"}]},
        {"part_number": "LOW068", "kind": "bought_in", "children": [], "evidence": {}}]},
        "document_analysis": {"bom_rows": [{"part_number": "VITAL PARTS: LOW068",
                                            "quantity": 2, "description": "x",
                                            "bom_sheet": "P-GA.pdf#0"}]}}
    assert cf.stated_rows_not_carried(src) == []


def test_every_kind_the_record_emits_has_words_and_a_rank():
    for k in ("missing_price", "stated_not_carried", "labour_not_on_sheet", "provisional_price",
              "market_figure", "quantity_check", "manufacturing_decision", "indicative_rate",
              "consistency_check", "ruling", "size_assumed"):
        assert k in J._DECISION_KIND_WORDS and k in J._DECISION_ORDER


def test_money_not_in_the_unit_is_listed_first():
    s = _summary([dict(TOP, children=[{"part_number": "P-BODY", "qty": 1.0}]), BODY, PANEL],
                 [_charged("P-01M", **_MARKET)],
                 bom_rows=[{"part_number": "N1", "quantity": 3, "description": "NUT"}])
    kinds = [d["kind"] for d in cf.costed_job(s)["decisions_required"]]
    assert kinds[0] == "stated_not_carried" and "market_figure" in kinds
    html = J._render_decisions(cf.costed_job(s))
    assert html.index("Stated, not carried") < html.index("Market figure")


# ── 0.3 one registry for every section number ────────────────────────────────────────────

def test_references_point_at_the_sections_that_hold_them():
    s = _summary([TOP, BODY, PANEL, SHUTTER], [_charged("P-01M")])
    _with_checks(s, [_unowned()])
    html = J.build_report_html(s)
    txt = _text(html)
    heads = {n for n, _t in re.findall(r"<h2>(\d+[a-z.0-9]*) &nbsp;([^<]+)</h2>", html)}
    assert "See section 13" in txt and "listed in section 13" in txt
    assert "section 8." not in txt and "See section 8" not in txt
    mains = sorted(int(n) for n in heads if n.isdigit())
    assert mains == list(range(1, len(mains) + 1)), mains           # no gap, even with no keys
    for m in re.findall(r"[Ss]ection (\d+[a-z]?(?:\.\d)?)", txt):
        assert m.rstrip(".") in heads or m.split(".")[0] in heads, m


def test_documents_written_before_the_report_cite_its_registry():
    import estimate_explained as ee
    assert ee._report_section("explained") == f"section {J._SECTIONS['explained'][0]}"


# ── 0.4 section 8 counts what is open, by the check's own predicates ─────────────────────

def _route_summary(decisions):
    return _summary([dict(TOP, children=[{"part_number": "P-BODY", "qty": 1.0}]), BODY, PANEL],
                    [_charged("P-01M")], decisions=decisions)


def test_an_unowned_operation_is_not_a_single_strongest_source():
    s = _route_summary([{"decision_id": "d1", "operation": "deburring", "target_id": "P-BODY",
                         "status": "unverified", "source": "", "source_rank": 0}])
    html = J.build_report_html(s)
    assert "Decisions needing resolution" not in html
    assert "single strongest source" not in html
    assert re.search(r"nothing in the pack claims them</b></td><td><b>1</b>", html)


def test_a_settled_tie_is_informational_and_a_plain_route_is_still_sound():
    s = _route_summary([{"decision_id": "d1", "operation": "folding", "target_id": "P-01M",
                         "status": "required", "contested": True, "settled_by_key": "rank",
                         "source": "dxf", "source_rank": 80}])
    html = J.build_report_html(s)
    assert "single strongest source" not in html
    assert "Ties the arbiter settled</b></td><td><b>1</b>" in html
    plain = J.build_report_html(_route_summary([{
        "decision_id": "d1", "operation": "folding", "target_id": "P-01M",
        "status": "required", "source": "dxf", "source_rank": 80}]))
    assert "single strongest source" in plain


# ── 0.5 a ruling is not a check that could not run ───────────────────────────────────────

def test_a_ruling_is_counted_apart_and_becomes_a_row():
    ruling = inv._violation(
        "operation_charged_on_a_parent_and_its_child", inv.UNVERIFIED,
        "welding is charged on P-BODY and separately on P-01M. An estimator must rule; "
        "the engine cannot.", operation="welding", assembly="P-BODY", descendants=["P-01M"],
        needs_ruling=True)
    unrun = inv._violation("material_disagreement", inv.UNVERIFIED,
                           "the summary could not be read, so this check verified nothing")
    s = _route_summary([])
    _with_checks(s, [ruling, unrun])
    html = J.build_report_html(s)
    assert "1 finding(s) need a ruling and 1 could not be run" in html
    assert "2 could not be run" not in html
    assert "Needs a ruling" in html and "Not run" in html
    job = cf.costed_job(s)
    assert [d["kind"] for d in job["decisions_required"]].count("ruling") == 1


def test_a_ruling_on_the_same_part_and_operation_nets_onto_its_decision():
    ruling = inv._violation(
        "operation_charged_on_a_parent_and_its_child", inv.UNVERIFIED, "x. y.",
        operation="welding", assembly="P-BODY", descendants=["P-01M"], needs_ruling=True)
    s = _route_summary([{"decision_id": "w1", "operation": "welding", "target_id": "P-BODY",
                         "status": "required", "source": "inference", "evidence": ""}])
    _with_checks(s, [ruling])
    job = cf.costed_job(s)
    assert not any(d["kind"] == "ruling" for d in job["decisions_required"])
    weld = next(d for d in job["decisions_required"] if d["kind"] == "manufacturing_decision")
    assert weld["also_ruled_by_check"] == "operation_charged_on_a_parent_and_its_child"


def test_a_readers_question_naming_the_operations_takes_the_ruling():
    ruling = inv._violation(
        "operation_charged_on_a_parent_and_its_child", inv.UNVERIFIED, "x. y.",
        operation="dress_welds", assembly="P-BODY", descendants=["P-01M"], needs_ruling=True)
    q = {"issue": "Is P-BODY welded itself?", "assumption": "a", "action": "b",
         "operations": ["welding", "dress_welds"]}
    s = _route_summary([])
    s["estimate_summary"]["part_estimates"].append(
        {"part_number": "P-BODY", "quantity": 1, "manufacturing_questions": [q]})
    _with_checks(s, [ruling])
    ds = cf.costed_job(s)["decisions_required"]
    assert not any(d["kind"] == "ruling" for d in ds)
    assert next(d for d in ds if d["issue"] == q["issue"])["also_ruled_by_check"]


def test_the_check_says_it_needs_a_ruling_and_the_run_counts_checks():
    s = {"estimate_summary": {"canonical_route_shadow": {}}}
    r = inv.check_job(s, write_back=False)
    assert all(v.get("check") for v in r["violations"])
    assert r["rulings"] + r["not_run"] == r["unverified"]
    assert isinstance(r["checks_with_findings"], int)


# ── 0.6 the Summary card keeps every reason ──────────────────────────────────────────────

def test_the_summary_card_never_drops_a_reason():
    rec = {"release": {"draft": True, "reasons": [f"reason {i}" for i in range(6)]
                       + ["1 parts-list row(s) stated and not carried"]},
           "decisions_required": [{"kind": "stated_not_carried", "part": "N"}],
           "lines": [], "gaps": {}, "run": {}}
    html = J._render_summary({}, rec, {"quantity": 1}, {})
    assert html.count("<li>") >= 7 and "stated and not carried" in html
    many = "9 line(s) carry no price: " + ", ".join(f"P{i}" for i in range(9))
    assert J._clip_names(many) == "9 line(s) carry no price: P0, P1, P2, P3, P4, P5 and 3 more"


# ── 0.7 a tally that could not see the checks says so; the banner points at its list ─────

def test_a_tally_made_before_the_checks_says_so_and_still_adds_up():
    s = _summary([TOP, BODY, PANEL, SHUTTER], [_charged("P-01M")])
    o = cf.outstanding_summary(cf.costed_job(s))
    assert "consistency checks had not run" in o["phrase"]
    assert sum(_nums(o["phrase"])) == o["total"]
    _with_checks(s, [])
    assert "had not run" not in cf.outstanding_summary(cf.costed_job(s))["phrase"]


def test_the_workbook_banner_points_at_the_list_with_the_same_count(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    import main
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["H4"] = "PROVISIONAL — 3 ESTIMATOR INPUTS REQUIRED (see OUTSTANDING ESTIMATOR INPUTS below)"
    ws["C40"] = ("OUTSTANDING ESTIMATOR INPUTS (3) — this sheet is NOT a price until these "
                 "are filled")
    path = tmp_path / "book.xlsx"
    wb.save(path)
    s = _summary([TOP, BODY, PANEL, SHUTTER], [_charged("P-01M")])
    main._rewrite_estimate_banner(path, s)
    ws2 = openpyxl.load_workbook(path)["Estimate"]
    o = cf.outstanding_summary(s)
    assert f"{o['total']} to settle" in ws2["H4"].value
    assert "OUTSTANDING ESTIMATOR INPUTS" not in ws2["H4"].value
    assert "AI Explanation" in ws2["H4"].value
    assert ws2["C40"].value.startswith("OUTSTANDING ESTIMATOR INPUTS (3)")
    assert "questions from the drawings" in ws2["C40"].value


# ── 0.8 section 14 lists every row it counts ─────────────────────────────────────────────

def test_the_settle_block_lists_every_decision():
    import estimate_explained as ee
    rec = {"schema": "costed_job.v2", "release": {"draft": True},
           "decisions_required": [
               {"kind": "missing_price", "part": "A", "issue": "A has no line"},
               {"kind": "stated_not_carried", "part": "B", "issue": "B stated"},
               {"kind": "quantity_check", "part": "C", "issue": "C qty"},
               {"kind": "market_figure", "part": "D", "issue": "D market",
                "gbp_at_stake": 1.0}]}
    o = cf.outstanding_summary(rec)
    lines = ee._settle_block(rec, o)
    rows = [l for l in lines if re.match(r"\| \d+ \|", l)]
    assert len(rows) == o["total"] == 4
    assert any("| B |" in l for l in rows) and any("Stated, not carried" in l for l in rows)
    only_qty = {"schema": "costed_job.v2", "release": {},
                "decisions_required": [{"kind": "quantity_check", "part": "C", "issue": "q"}]}
    assert ee._settle_block(only_qty)


# ── 1.0 / 1.1 a second spelling of a reached part is named as one ────────────────────────

def _graph(extra=()):
    parts = [{"part_number": "J-02-GA", "is_assembly_parent": True},
             {"part_number": "J-03-GA", "is_sub_assembly": True},
             {"part_number": "FIXING1180", "description": "M6 x 30mm COUNTERSUNK BOLT (BZP)",
              "quantity": 4, "textual_operations": ["deburring", "wire_forming"]}]
    extract = {"bom": [{"part_number": "FIXING 1180", "description": "M6x30mm COUNTERSUNK BOLT",
                        "qty": 4, "is_bought_in": True}] + list(extra),
               "assemblies": [{"part_number": "J-02-GA",
                               "children": [{"part_number": "J-03-GA", "qty": 1}]}]}
    rows = [{"part_number": "FIXING1180", "quantity": 4, "bom_parent": "J-03-GA"}]
    return rc.build_part_graph(parts, extract, rows, known_assemblies=["J-02-GA", "J-03-GA"],
                               declared_product="J-02")


def test_a_spacing_variant_of_a_reached_part_is_not_unlinked():
    g = _graph(extra=[{"part_number": "XYZ999", "description": "ORPHAN", "qty": 1,
                       "is_bought_in": True},
                      {"part_number": "FIXING-1180", "description": "X", "qty": 1,
                       "is_bought_in": True}])
    unlinked = {x for i in g["issues"] if i["code"] == "not_linked_to_the_product"
                for x in i["identities"]}
    assert "FIXING 1180" not in unlinked
    assert {"XYZ999", "FIXING-1180"} <= unlinked          # a hyphen is not a space
    sec = next(i for i in g["issues"] if i["code"] == "second_spelling_of_a_reached_part")
    assert sec["target"] == "FIXING1180" and sec["kinds"]


def test_the_scope_line_names_the_spelling_not_a_missing_price():
    g = _graph()
    s = {"declared_product": "J-02", "estimate_summary": {"canonical_route_shadow": {
        "declared_product": "J-02", "product_root": g["product_root"], "issues": g["issues"],
        "nodes": [vars(n) for n in g["nodes"]]}}}
    text = " ".join(rc.product_scope_sentences(s))
    assert "not priced: FIXING 1180" not in text
    assert "FIXING 1180 is another spelling of FIXING1180" in text and "made or bought" in text


def test_an_older_record_reads_the_same():
    s = {"declared_product": "J-02", "estimate_summary": {"canonical_route_shadow": {
        "declared_product": "J-02", "product_root": "J-02-GA",
        "issues": [{"code": "not_linked_to_the_product",
                    "identities": ["FIXING 1180", "XYZ999"]}],
        "nodes": [{"part_number": "J-02-GA"}, {"part_number": "FIXING1180", "evidence": {}}]}}}
    sc = rc.product_scope(s)
    assert sc["unlinked"] == ["XYZ999"]
    assert sc["spelled_twice"][0]["carried_as"] == "FIXING1180"


def test_a_record_under_the_second_spelling_is_still_set_aside_and_says_why():
    g = _graph()
    parts = [{"part_number": "FIXING1180"}, {"part_number": "FIXING 1180"}]
    s = {}
    rc.set_aside_outside_product(parts, g["issues"], summary=s)
    assert [p["part_number"] for p in parts] == ["FIXING1180"]
    assert s["set_aside_outside_product"][0]["reason"] == "second_spelling_of_a_reached_part"


def _payload():
    return {"product_root": "A-GA", "nodes": [{"part_number": "A-GA", "evidence": {}},
                                              {"part_number": "FIXING1180", "evidence": {}}]}


def test_a_late_line_spelled_with_a_space_is_its_nodes_line():
    pe = [{"part_number": "FIXING 1180", "quantity": 4}]
    s = {}
    assert rc.set_aside_late_lines(pe, _payload(), s) == []
    assert pe[0]["part_number"] == "FIXING1180" and pe[0]["printed_code"] == "FIXING 1180"
    assert not s.get("set_aside_outside_product")


def test_a_second_spelling_beside_the_nodes_line_is_a_duplicate_not_unlinked():
    pe = [{"part_number": "FIXING1180", "quantity": 4}, {"part_number": "FIXING 1180",
                                                         "quantity": 4}]
    s = {}
    rc.set_aside_late_lines(pe, _payload(), s)
    assert [p["part_number"] for p in pe] == ["FIXING1180"]
    e = s["set_aside_outside_product"][0]
    assert e["reason"] == "second_spelling_of_a_reached_part" and e["same_as"] == "FIXING1180"


def test_a_hyphen_variant_is_still_not_linked_and_the_graph_set_aside_stays_exact():
    pe = [{"part_number": "FIXING-1180", "quantity": 4}]
    s = {}
    rc.set_aside_late_lines(pe, _payload(), s)
    assert pe == [] and s["set_aside_outside_product"][0]["reason"] == "not_linked_to_the_product"
    parts = [{"part_number": "FIXING1180", "quantity": 4}]
    rc.set_aside_outside_product(parts, [{"code": "not_linked_to_the_product", "root": "",
                                          "identities": ["FIXING 1180"]}], summary={})
    assert [p["part_number"] for p in parts] == ["FIXING1180"]


# ── 1.2 "no double-counting" only where it is established ────────────────────────────────

SCREW = "Ø3.5x12mm PAN HEAD MULTI-PURPOSE SCREW"


def _dc(items, viol=None):
    parts = [{"part_number": pn, "description": d, "quantity": q,
              "material_estimate": {"unit_material_cost_gbp": 1.0}} for pn, d, _k, q in items]
    nodes = [{"part_number": pn, "kind": k, "parents": ["X-201"], "qty_per_unit": q,
              "evidence": {}} for pn, _d, k, q in items]
    s = {"estimate_summary": {"part_estimates": parts, "estimate_status": "ok",
                              "canonical_route_shadow": {"nodes": nodes, "issues": []}}}
    if viol is not None:
        s["invariants"] = {"may_quote_firm": not viol, "blocking": 0,
                           "unverified": len(viol), "violations": list(viol)}
    return s


def test_one_purchase_under_two_codes_is_not_sound():
    s = _dc([("BI-SCREW", SCREW, "bought_in", 16),
             ("FIXING-3.5-X12MM-PAN-HEAD", SCREW, "bought_in", 16)], viol=[])
    st = cf.double_count_status(s)
    assert st["state"] == "found"
    assert st["same_item_pairs"][0]["identities"] == ["BI-SCREW", "FIXING-3.5-X12MM-PAN-HEAD"]
    html = J._render_whats_right(s, J._extract_cost_streams(s))
    assert "No double-counting found" not in html and "Possibly counted twice" in html


def test_opposite_hands_are_not_a_pair():
    s = _dc([("X-04-02M", "SIDE PANEL", "leaf", 8), ("X-04-02M-H", "SIDE PANEL", "leaf", 8)],
            viol=[])
    assert cf.double_count_status(s)["state"] == "clear"


def test_an_unrun_parent_child_check_withholds_the_all_clear_and_the_verdict_agrees():
    s = _dc([("K1", "KNOB", "bought_in", 1)],
            viol=[{"code": "operation_charged_on_a_parent_and_its_child",
                   "severity": "unverified", "message": "m"}])
    assert cf.double_count_status(s)["state"] == "not_established"
    assert "No double-counting found" not in J._render_whats_right(s, J._extract_cost_streams(s))
    verdict = J._render_verdict(J._extract_headline(s), J._extract_drawing_quality(s), False, s)
    assert "nothing is counted twice" not in verdict and "not ruled out" in verdict


def test_a_blocking_double_count_is_found_and_an_unrelated_crash_is_not():
    s = _dc([("K1", "KNOB", "bought_in", 1)],
            viol=[{"code": "two_roots_price_the_same_members", "severity": "blocking"}])
    assert cf.double_count_status(s)["state"] == "found"
    s2 = _dc([("K1", "KNOB", "bought_in", 1)],
             viol=[{"code": "check_failed", "severity": "unverified",
                    "check": "check_prices_are_firm"}])
    assert cf.double_count_status(s2)["state"] == "clear"


# ── 1.3 the bought-in population, counted once ───────────────────────────────────────────

def test_every_bought_in_count_on_the_page_is_one_count():
    parts = [
        {"part_number": "BI-SCREW", "description": "SCREW A", "quantity": 16, "supplier": "S",
         "cost_source": "udef_catalogue", "material_estimate": {"unit_material_cost_gbp": 0.01}},
        {"part_number": "FIXING125", "description": "GLIDE", "quantity": 4, "supplier": "S",
         "cost_source": "udef_catalogue", "material_estimate": {"unit_material_cost_gbp": 0.22}},
        {"part_number": "P/P", "description": "BEARING", "quantity": 1, "supplier": "web",
         "cost_source": "market_ai_indicative", "normalized_material": "MILD STEEL",
         "material_source": "title_block",
         "material_estimate": {"unit_material_cost_gbp": 11.95,
                               "cost_method": "market_ai_indicative"}},
        {"part_number": "THUM620", "description": "THUMBSCREW", "quantity": 2, "supplier": "S",
         "cost_source": "udef_catalogue", "material_estimate": {"unit_material_cost_gbp": 0.3}},
        {"part_number": "PACKAGING", "description": "Packaging", "quantity": 1,
         "_commercial_placeholder": True, "cost_source": "market_ai_indicative",
         "material_estimate": {"unit_material_cost_gbp": 72.0,
                               "cost_method": "market_ai_indicative"}}]
    nodes = [{"part_number": p["part_number"], "kind": "bought_in", "parents": ["A-GA"],
              "qty_per_unit": p["quantity"], "evidence": {}} for p in parts[:3]]   # THUM: none
    s = {"estimate_summary": {"part_estimates": parts, "estimate_status": "ok",
                              "canonical_route_shadow": {"nodes": nodes, "issues": []}},
         "invariants": {"may_quote_firm": True, "blocking": 0, "unverified": 0,
                        "violations": []}}
    t, rec = cf.bought_in_tally(s), cf.costed_job(s)
    assert sorted(t["bought_in"]) == ["BI-SCREW", "FIXING125", "P/P", "THUM620"]
    streams = {x["name"]: x["count"] for x in J._extract_cost_streams(s)}
    assert streams["Bought-in items"] == len(t["bought_in"]) == 4
    assert streams.get("Commercial lines") == 1
    assert sorted(t["bought_in_market"] + t["commercial_market"]) == \
        sorted(rec["gaps"]["indicative_market"])
    html = J._render_whats_right(s, J._extract_cost_streams(s))
    assert "4 bought-in part(s)" in html
    assert "1 on a researched market price, not a catalogue (P/P)" in html


# ── 3.6 findings and checks, each in its own unit ────────────────────────────────────────

def test_section_thirteen_counts_findings_against_findings_and_checks_against_checks():
    s = _summary([TOP, BODY, PANEL, SHUTTER], [_charged("P-01M")])
    v = inv.check_every_reached_bom_item_is_accounted_for(s) + [_unowned()]
    for x in v:
        x["check"] = ("check_every_reached_bom_item_is_accounted_for"
                      if x["code"].startswith("reached") else "check_canonical_route_shadow")
    _with_checks(s, v, run=[f"c{i}" for i in range(45)])
    sec = _text(J._invariants_section(s))
    assert "2 consistency finding(s) failed" in sec and "from 2 of the 45 checks" in sec
    assert "out of 45" not in sec and "already Decisions required" in sec
