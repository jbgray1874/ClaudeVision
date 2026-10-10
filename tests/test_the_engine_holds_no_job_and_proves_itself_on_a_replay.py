"""D-454: no job in the engine's logic, one occurrence folded only as one, an assumption never
returned as a measurement, and a replay that runs a saved job to the report.

The reviewer's three findings on 6152309 — older 1282 part rules still live, a duplicate fold
that merged records under different parents, and "measured only" not enforced where the costed
blank was read back — and the request for a replay through the workbook's line list and the
report before another long run.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("SDI_OFFLINE", "1")

import blank_credibility as bc                                        # noqa: E402
import bay_rollup                                                     # noqa: E402
import part_identity as pi                                            # noqa: E402
import size_reading as sr                                             # noqa: E402


# ── 1. no job's codes in live logic ──────────────────────────────────────────────────

_CODE = re.compile(r"(?<![\w.])(?:\d{4,5}-(?:\d{2,3}[A-Z]?|GA|[A-Z]-?\d{0,3}|\d{2}-\d{2,3}[A-Z]?)"
                   r"|\d{4}(?=-GA))(?![\w])")
_CUSTOMER = re.compile(r"\b(M&S|MARKS\s*&|SPENCER|HARRODS|TESCO|BOOTS|TTI)\b")
# Data tables a person maintains on purpose, each scoped by its key so it cannot fire on another
# job or customer: estimator rulings for one job (rule type `job answer`), customer terms and
# standards (`customer term`), and the folder-name aliases that say which customer a folder is.
_SCOPED_TABLES = {("config.py", "JOB_DECISIONS"), ("config.py", "CUSTOMER_FINISH_STANDARDS"),
                  ("config.py", "CUSTOMER_COMMERCIAL_TERMS"),
                  ("live_enquiry_collector.py", "DEFAULT_CUSTOMER_ALIASES")}
_ENTRY_POINTS = ("main.py", "file_scan.py")


def _imports(tree: ast.AST) -> set:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def _live_modules() -> dict:
    src = ROOT / "src"
    trees = {}
    for p in src.glob("*.py"):
        if not p.is_file():
            continue
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                trees[p.stem] = (p, ast.parse(p.read_text(encoding="utf-8-sig")))
        except (SyntaxError, ValueError, OSError):
            continue
    live, todo = set(), [Path(e).stem for e in _ENTRY_POINTS]
    while todo:
        m = todo.pop()
        if m in live or m not in trees:
            continue
        live.add(m)
        todo.extend(_imports(trees[m][1]) - live)
    return {m: trees[m] for m in live}


def _logic_constants(tree: ast.AST):
    """String constants that DECIDE something: compared, used as a dict key, or a pattern."""
    scoped_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    scoped_lines.add((t.id, node.lineno, getattr(node, "end_lineno", node.lineno)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for n in [node.left, *node.comparators]:
                for c in ast.walk(n):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        yield c.lineno, c.value, "compared", scoped_lines
        elif isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    yield k.lineno, k.value, "dict key", scoped_lines
        elif isinstance(node, ast.Call) and node.args:
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in ("compile", "search", "match", "fullmatch", "findall", "sub", "finditer",
                        "startswith", "endswith"):
                for c in ast.walk(node.args[0]):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        yield c.lineno, c.value, name, scoped_lines


def test_no_live_module_decides_anything_on_a_job_code_or_a_customer_name():
    offenders = []
    for mod, (path, tree) in sorted(_live_modules().items()):
        for line, value, how, scoped in _logic_constants(tree):
            if not (_CODE.search(value) or _CUSTOMER.search(value.upper())):
                continue
            owner = next((name for name, a, b in scoped if a <= line <= b), "")
            if (path.name, owner) in _SCOPED_TABLES:
                continue
            offenders.append(f"{path.name}:{line} {how} {value[:60]!r}")
    assert not offenders, "job or customer literals deciding live logic:\n" + "\n".join(offenders)


def test_the_guard_sees_the_rules_it_replaced():
    bad = ast.parse('if pn == "1448-02":\n    pass\nT = {"1453-GA-C": 1}\nre.search(r"1450", x)\n')
    hits = [v for _, v, _, _ in _logic_constants(bad) if _CODE.search(v)]
    assert "1448-02" in hits and "1453-GA-C" in hits


def test_identity_is_read_by_shape():
    text = "4 9999-GA- C KICK ASSEMBLY 1 7 9999-C- GA HEADER 1 6 9999-GA- WALL LEG 2"
    assert pi.preprocess_bom_text(text) == ("4 9999-GA-C KICK ASSEMBLY 1 7 9999-C-GA HEADER 1 "
                                            "6 9999-GA WALL LEG 2")
    assert pi.resolve_estimate_code("4321-GA", "", ["4321-01C", "4320-01C"]) == "4321-01C"
    assert pi.resolve_estimate_code("54321-02-GA", "", ["54321-02-01M"]) == "54321-02-01M"
    assert pi.resolve_estimate_code("54321-02-GA", "", ["54321-02-01M", "54321-02-02M"]) is None
    assert pi.normalize_part_code("12345 GA") == "12345-GA"
    assert pi.split_catalogue_token("LOOM50CM") == "LOOM50CM", "a length is part of what is bought"
    assert pi.dxf_alias_target("1148") is None


def test_a_dxf_is_preferred_by_the_sizes_its_part_states():
    part = {"part_number": "X-01", "description": "BASE PLATE 650 WIDE"}
    assert pi.score_dxf_candidate(part, "a/BASE 650.dxf") > pi.score_dxf_candidate(part, "a/BASE 500.dxf")
    assert pi.score_dxf_candidate({"part_number": "X-01", "description": "PLATE"}, "a/X-01.dxf") == 2.0


def test_the_rollup_reads_the_hierarchy_not_a_code_shape():
    rows = [{"part_number": "77-101", "quantity": 1},
            {"part_number": "77-001", "quantity": 1, "bom_parent": "77-101"},
            {"part_number": "88-101", "quantity": 1}]
    kept = [r["part_number"] for r in bay_rollup.dedupe_weldment_parent_rows(rows)]
    assert kept == ["77-001", "88-101"], "a parent goes only where its own children are lines"
    assert bay_rollup.job_has_costing_root([{"part_number": "4444-GA"}], {})
    assert not bay_rollup.job_has_costing_root([{"part_number": "4444-GA", "bom_parent": "X"},
                                                 {"part_number": "X-1", "bom_parent": "4444-GA"}], {}), \
        "a GA listed as another's child is not the root"
    assert bay_rollup.job_has_costing_root([], {"canonical_route_shadow": {"product_root": "Z-GA"}})
    assert not bay_rollup.job_has_costing_root([{"part_number": "4444-01C"}], {})


# ── 2. one occurrence, folded only as one ────────────────────────────────────────────

def _coded(**kw):
    d = {"part_number": "FIXING M6x12mm", "description": "THREADED INSERT, HEADED HEX DRIVE",
         "quantity": 4}
    d.update(kw)
    return d


def _whole(**kw):
    d = {"part_number": "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "description": "",
         "quantity": 4}
    d.update(kw)
    return d


def test_the_same_item_under_two_parents_is_two_occurrences_and_is_not_folded():
    parts = [_coded(bom_parent="SA-03"), _whole(bom_parent="SA-04")]
    assert pi.fold_one_cell_duplicates(parts) == [] and len(parts) == 2


def test_one_occurrence_folds_and_every_parent_named_is_kept():
    coded = _coded(bom_parent="X-SA03")
    whole = _whole(bom_parents=[{"parent": "X-SA03", "qty": 4}, {"parent": "X-SA03.PDF", "qty": 4}])
    parts = [whole, coded]
    assert pi.fold_one_cell_duplicates(parts) == [(whole["part_number"], coded["part_number"])]
    assert parts == [coded]
    assert {e["parent"] for e in coded["bom_parents"]} >= {"X-SA03"}


def test_a_reading_with_no_parent_is_not_evidence_of_a_second_occurrence():
    parts = [_coded(bom_parent="X-SA03"), _whole()]
    assert len(pi.fold_one_cell_duplicates(parts)) == 1


def test_every_one_cell_site_asks_the_occurrence_too():
    import inspect
    import document_builder
    import file_scan
    import wb_populate
    for mod in (document_builder, file_scan, wb_populate):
        assert "same_bom_occurrence" in inspect.getsource(mod), mod.__name__


# ── 3. an assumption never comes back as a measurement ───────────────────────────────

def test_a_blank_is_measured_only_where_a_measuring_source_says_so():
    assert bc.blank_is_measured({"geometry_source": "dxf_flat_pattern"})
    assert not bc.blank_is_measured({"blank_length_mm": 500.0})
    assert not bc.blank_is_measured({"geometry_source": "dxf_flat_pattern", "blank_is_inferred": True})
    assert not bc.blank_is_measured({"blank_length_mm_source": "bounding_box_floor",
                                     "geometry_source": "dxf"})


def test_the_yardstick_takes_no_unmeasured_costed_blank_and_no_fallback_section_length():
    copy_of_an_assumption = {"part_number": "A", "material_estimate": {"blank_length_mm": 3000.0,
                                                                       "blank_width_mm": 200.0}}
    assert sr.measured_job_yardstick_mm([copy_of_an_assumption]) is None
    measured = dict(copy_of_an_assumption, geometry_source="dxf_flat_pattern")
    assert sr.measured_job_yardstick_mm([measured]) == 3000.0
    fallback_bar = {"part_number": "B", "_section_length_source": "max_dimension_fallback",
                    "material_estimate": {"stock_estimate": {"section_length_mm": 9106.0}}}
    assert sr.measured_job_yardstick_mm([fallback_bar]) is None
    stated_bar = dict(fallback_bar, _section_length_source="section_stock")
    assert sr.measured_job_yardstick_mm([stated_bar]) == 9106.0
    drawn = {"part_number": "C", "overall_length_mm": 1272.0}
    assert sr.measured_job_yardstick_mm([drawn]) == 1272.0, "a size the drawing states is evidence"


# ── 4. the replay and its gates ──────────────────────────────────────────────────────

def _saved_record():
    return {"job_number": "T-1", "pages": [], "document_analysis": {"bom_rows": []},
            "manufacturing_writeup": {"parts": [
                {"part_number": "P-1", "description": "PANEL", "quantity": 1,
                 "normalized_material": "MILD STEEL", "normalized_thickness_mm": 3.0,
                 "geometry_source": "dxf_flat_pattern", "page_roles": ["detail"],
                 "normalized_geometry": {"blank_length_mm": 500.0, "blank_width_mm": 300.0,
                                         "blank_area_mm2": 150000.0}}]},
            "estimate_summary": {"part_estimates": [
                {"part_number": "P-1", "quantity": 1},
                {"part_number": "BI-LATE", "description": "M6 NUT", "quantity": 4,
                 "is_bought_in": True, "page_roles": ["bought_in"], "bom_parent": "T-1-GA",
                 "unit_material_cost_gbp": 99.0, "cost_breakdown": {"stale": True}}]}}


def test_the_replay_recosts_every_record_and_late_records_without_their_old_price():
    import replay_saved_job as rsj
    out = rsj.replay(json.loads(json.dumps(_saved_record())), log=lambda *_: None)
    pes = {p["part_number"]: p for p in out["estimate_summary"]["part_estimates"]}
    assert (pes["P-1"].get("material_estimate") or {}).get("unit_material_cost_gbp")
    assert "BI-LATE" in pes and pes["BI-LATE"].get("unit_material_cost_gbp") != 99.0
    assert pes["BI-LATE"].get("bom_parent") == "T-1-GA", "where it was listed is kept"
    assert out.get("replayed_by") == "tools/replay_saved_job.py"


def test_the_replay_runs_the_same_pre_costing_function_as_the_run():
    import inspect
    import file_scan
    assert "pre_costing_passes(summary)" in inspect.getsource(file_scan._finalize_scan_summary)
    src = inspect.getsource(file_scan.pre_costing_passes)
    for step in ("_inherit_sheet_material_to_parts", "related_measured_blanks", "pack_model_material",
                 "fold_one_cell_duplicates", "apply_size_readings", "apply_cut_method_from_sheets"):
        assert step in src, step


def test_the_gates_check_a_provisional_figure_and_a_commercial_basis():
    from check_book_against_brief import check
    summary = {"manufacturing_writeup": {"parts": [
                   {"part_number": "W-3", "_blank_provisional": {"basis": "mass_implied_area",
                                                                "measured_mm": [2190.0],
                                                                "inferred_mm": [227.0]}}]},
               "estimate_summary": {"part_estimates": [
                   {"part_number": "W-3", "material_estimate": {"unit_material_cost_gbp": 10.5}}]},
               "commercial_lines": [
                   {"code": "DELIVERY", "basis_chosen": "the counted shipment at a researched unit rate",
                    "order_gbp_at_breaks": {1: 60.0, 5: 60.0, 50: 120.0}},
                   {"code": "PACKAGING", "basis_chosen": "SDI Live history only — weak comparability",
                    "order_gbp_at_breaks": {1: 10.0, 5: 50.0, 50: 500.0}}]}
    res = check(summary, {"provisional_material": {"W-3": {"min_unit_material_gbp": 5}},
                          "commercial_basis": ["DELIVERY", "PACKAGING"],
                          "commercial_breaks": [1, 5, 50]})
    got = {(r[0], r[1]): r[2] for r in res.rows}
    assert got[("provisional_material", "W-3")]
    assert got[("commercial_basis", "DELIVERY")]
    assert not got[("commercial_basis", "PACKAGING")], "weak history is not a justified basis"


def test_the_8188_08_gates_file_names_the_reviewers_gates():
    facts = json.loads((ROOT / "docs" / "briefs" / "8188-08.facts.json").read_text(encoding="utf-8"))
    assert facts["exactly_one_line"] == {"HEADED HEX DRIVE": 4}
    assert "8188-08-013" in facts["provisional_material"]
    assert facts["commercial_basis"] == ["PACKAGING", "DELIVERY"]
    assert facts["no_gauge_decision_on_assemblies"] is True
