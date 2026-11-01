"""Every parity route now files the line-by-line report (SCRUM-157, D-623).

The comparison in parity_compare is tested on its own. These tests are about where it lands:
the parity run writes it beside the money-cell bundle and opens it first, either comparison
failing leaves the other standing, the one-line answer comes from it when it read both unit
costs, and parity by job number files its quantities, lines, scope and revision.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("openpyxl")
import parity_job  # noqa: E402
import parity_run  # noqa: E402
from test_parity_compares_line_by_line import (AI_UNIT, MAN_UNIT, ai_summary,  # noqa: E402
                                               manual_workbook)


def _legacy(monkeypatch, *, fail: bool = False, unit=(500.0, 400.0)):
    """The money-cell generator and its page, stood in for: they are tested elsewhere, and the
    question here is only what happens beside them."""
    gen = types.ModuleType("estimate_full_parity_report")

    def generate_and_write(summary, manual, out_json, out_csv, read_via_excel=False):
        if fail:
            raise ValueError("no labelled money cells")
        bundle = {"rollup_unit_cost_comparison": {
                      "workbook_unit_cost_cached": unit[1],
                      "json_implied_unit_using_workbook_qty": unit[0],
                      "pct_variance": 25.0, "status": "fail", "workbook_unit_cost_cell": "L105"},
                  "status_counts": {"money_match": 4, "money_warning": 1, "money_fail": 2,
                                    "labour_route_match": 3, "labour_route_issues": 1},
                  "money_cell_comparisons": []}
        Path(out_json).write_text(json.dumps(bundle), encoding="utf-8")
        Path(out_csv).write_text("label,ai,manual\n", encoding="utf-8")
        return bundle, Path(out_json), Path(out_csv)
    gen.generate_and_write = generate_and_write
    page = types.ModuleType("parity_report_html")

    def generate_report_files(bundle_json, out_dir, job_stem):
        p = Path(out_dir) / f"{job_stem}.full_parity.html"
        p.write_text("<h1>money cells</h1>", encoding="utf-8")
        return str(p)
    page.generate_report_files = generate_report_files
    monkeypatch.setitem(sys.modules, "estimate_full_parity_report", gen)
    monkeypatch.setitem(sys.modules, "parity_report_html", page)


@pytest.fixture()
def pair(tmp_path):
    return (ai_summary(tmp_path / "12677.json"),
            manual_workbook(tmp_path / "12677-01-GA ISS 2.xlsx"), tmp_path / "out")


# ── the parity run ──────────────────────────────────────────────────────────────────────

def test_the_line_by_line_report_is_written_beside_the_bundle_and_opened_first(monkeypatch, pair):
    _legacy(monkeypatch)
    ai, manual, out = pair
    res = parity_run.run_parity(ai, manual, out_dir=out)
    assert Path(res["detail_json"]).is_file() and Path(res["detail_html"]).is_file()
    assert res["bundle_html"] == res["detail_html"]
    assert res["legacy_html"].endswith(".full_parity.html") and Path(res["legacy_html"]).is_file()
    assert Path(res["bundle_json"]).is_file()
    assert json.loads(Path(res["detail_json"]).read_text("utf-8"))["schema"] == "sdi_parity_detail.v1"


def test_the_answer_comes_from_the_line_by_line_reading_and_keeps_the_money_cell_counts(
        monkeypatch, pair):
    _legacy(monkeypatch)
    ai, manual, out = pair
    h = parity_run.run_parity(ai, manual, out_dir=out)["headline"]
    assert h["unit_cost_source"] == "line by line"
    assert h["ai_unit_cost_gbp"] == AI_UNIT and h["manual_unit_cost_gbp"] == MAN_UNIT
    assert h["gap_gbp"] == round(AI_UNIT - MAN_UNIT, 2)
    signed = round((AI_UNIT - MAN_UNIT) / MAN_UNIT * 100, 1)
    assert h["pct_signed"] == signed and h["pct_variance"] == abs(signed)
    assert h["money_match"] == 4 and h["labour_route_issues"] == 1
    assert h["ai_sell_gbp"] is not None and h["manual_sell_gbp"] is not None
    assert h["scope_counts"]["ai_only"] >= 1 and h["revision_differs"] is True


def test_a_money_cell_failure_still_files_the_line_by_line_report(monkeypatch, pair, capsys):
    _legacy(monkeypatch, fail=True)
    ai, manual, out = pair
    res = parity_run.run_parity(ai, manual, out_dir=out)
    assert res["bundle_json"] is None and res["legacy_html"] is None
    assert res["bundle_html"] == res["detail_html"] and Path(res["detail_html"]).is_file()
    assert "no labelled money cells" in res["errors"]["money_cells"]
    assert res["headline"]["manual_unit_cost_gbp"] == MAN_UNIT
    assert "line-by-line comparison carries on" in capsys.readouterr().out


def test_a_line_by_line_failure_leaves_the_money_cell_report_standing(monkeypatch, pair):
    _legacy(monkeypatch)
    import parity_compare

    def broken(*a, **k):
        raise KeyError("chain")
    monkeypatch.setattr(parity_compare, "compare", broken)
    ai, manual, out = pair
    res = parity_run.run_parity(ai, manual, out_dir=out)
    assert res["detail_json"] is None and res["bundle_html"] == res["legacy_html"]
    assert res["headline"]["ai_unit_cost_gbp"] == 500.0
    assert res["headline"]["unit_cost_source"] == "money cells"
    assert "chain" in res["errors"]["line_by_line"]


def test_both_failing_is_an_error_naming_both(monkeypatch, pair):
    _legacy(monkeypatch, fail=True)
    import parity_compare
    monkeypatch.setattr(parity_compare, "compare",
                        lambda *a, **k: (_ for _ in ()).throw(KeyError("chain")))
    ai, manual, out = pair
    with pytest.raises(RuntimeError) as e:
        parity_run.run_parity(ai, manual, out_dir=out)
    assert "Money cells" in str(e.value) and "Line by line" in str(e.value)


def test_unit_costs_the_line_by_line_reading_cannot_see_fall_back_to_the_money_cells(
        monkeypatch, pair):
    """A sheet whose value cache is empty: only Excel can fill it, and only the money-cell
    generator drives Excel."""
    _legacy(monkeypatch)
    ai, manual, out = pair
    import openpyxl
    wb = openpyxl.load_workbook(manual)
    ws = wb["Estimate"]
    ws["M26"] = None
    wb.save(manual)
    h = parity_run.run_parity(ai, manual, out_dir=out)["headline"]
    assert h["unit_cost_source"] == "money cells"
    assert h["ai_unit_cost_gbp"] == 500.0 and h["manual_unit_cost_gbp"] == 400.0


def test_the_command_line_names_the_line_by_line_report(monkeypatch, pair, capsys):
    _legacy(monkeypatch)
    ai, manual, out = pair
    monkeypatch.setattr(sys, "argv", ["parity_run", "--ai", str(ai), "--manual", str(manual),
                                      "--out-dir", str(out)])
    parity_run.main()
    assert "Line by line:" in capsys.readouterr().out


# ── parity by job number ────────────────────────────────────────────────────────────────

@pytest.fixture()
def shares(tmp_path, monkeypatch):
    for name, sub in (("SDI_MANUAL_ESTIMATES_ROOT", "Manual Estimates"),
                      ("SDI_ESTIMATE_OUTPUT_ROOT", "AISheets"), ("SDI_PARITY_ROOT", "parity")):
        monkeypatch.setenv(name, str(tmp_path / sub))
    return tmp_path


def _filed_run(shares: Path, units: int = 10, sweep=None) -> Path:
    folder = shares / "AISheets" / "Acme" / "12677-01-GA" / f"2026-10-31 11-00-00 ({units} off)"
    folder.mkdir(parents=True)
    (folder / "12677_20261031_110000.xlsx").write_text("book", encoding="utf-8")
    ai_summary(folder / "12677.json", qty=units, sweep=sweep)
    return folder / "12677_20261031_110000.xlsx"


def _sheet(shares: Path, qty: int = 10) -> Path:
    folder = shares / "Manual Estimates" / "2026" / "Acme" / "12677"
    folder.mkdir(parents=True)
    return manual_workbook(folder / "12677-01-GA ISS 2.xlsx", qty=qty)


def test_a_job_comparison_files_the_line_by_line_lines_scope_and_revision(monkeypatch, shares):
    _legacy(monkeypatch)
    _filed_run(shares)
    _sheet(shares)
    idx = parity_job.run_job("12677-01-GA")
    folder = Path(idx["folder"])
    assert idx["report_html"].endswith(".parity.html") and (folder / idx["report_html"]).is_file()
    assert (folder / idx["legacy_html"]).is_file() and (folder / idx["detail_json"]).is_file()
    assert idx["lines_from"] == "line by line"
    kinds = {x["kind"] for x in idx["lines"]}
    assert {"cost", "selling", "commercial"} <= kinds
    assert not any(x["kind"] == "cost" and x["label"] == "Sell price" for x in idx["lines"])
    delivery = next(x for x in idx["lines"] if x["label"] == "Delivery and carriage")
    assert delivery["manual"] == 40.0 and delivery["ai"] == 42.5 and delivery["cell"]
    assert idx["scope_counts"]["made_bought_differs"] >= 1
    assert idx["revision"]["differs"] is True
    assert idx["differences"] and all(d["anchor"] for d in idx["differences"])
    assert idx["outcome"] == idx["headline"]["status"]


def test_a_job_at_another_quantity_is_compared_at_the_manuals_from_the_sweep(monkeypatch, shares):
    _legacy(monkeypatch)
    _filed_run(shares, units=50, sweep={10: MAN_UNIT * 1.02, 50: 90.0})
    _sheet(shares, qty=10)
    idx = parity_job.run_job("12677-01-GA")
    q = idx["quantity"]
    assert q["ai_unit_at_manual_qty"] == round(MAN_UNIT * 1.02, 2) and q["compared_at"] == 10
    assert q["status_at_manual_qty"] == "match" == idx["outcome"]
    assert abs(q["pct_at_manual_qty"] - 2.0) < 0.11


def test_a_job_at_a_quantity_the_run_did_not_price_is_not_comparable(monkeypatch, shares):
    _legacy(monkeypatch)
    _filed_run(shares, units=50)
    _sheet(shares, qty=10)
    idx = parity_job.run_job("12677-01-GA")
    assert idx["outcome"] == "quantities differ" and not idx["quantity"]["comparable"]
    assert "re-run the estimate at 10 off" in idx["quantity"]["note"]


def test_the_period_statistics_count_every_gap_by_its_size():
    rows = [{"outcome": "match", "pct": -2.0}, {"outcome": "warning", "pct": 6.0}]
    s = parity_job.stats(rows)
    assert s["mean_abs_pct"] == 4.0 and s["median_abs_pct"] == 4.0
