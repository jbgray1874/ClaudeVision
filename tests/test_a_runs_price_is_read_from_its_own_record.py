"""A run's price on Self-Running is its own, not the previous job's (JG, 11 Nov 2026).

The Latest runs list showed different jobs at identical prices: 6364-01 and 12674-01-GA both
£1,034.37, 12773-01-GA and 12674-01-GA both £696.18. The runner read the price from the first
.json in name order among the files it filed, and a JSON another job left in the checkout sorts
ahead of this run's own. The run's record is pinned beside its workbook last, so it is read first."""
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("sdi_estimate_runner_price", ROOT / "tools/runner/sdi_estimate_runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


def _write(folder: Path, name: str, unit: float, when: float) -> dict:
    p = folder / name
    p.write_text(json.dumps({"totals": {"unit_cost_gbp": unit}}), encoding="utf-8")
    os.utime(p, (when, when))
    return {"name": name, "path": str(p)}


def test_the_runs_own_pinned_record_is_read_before_any_other_json(tmp_path):
    other = _write(tmp_path, "12674-01-GA_20261111_120000_record.json", 1034.37, 1000.0)
    stray = _write(tmp_path, "0_walkthrough.json", 1034.37, 1500.0)
    own = _write(tmp_path, "6364-01_20261111_143000_record.json", 1383.58, 2000.0)
    order = [i["name"] for i in runner._price_jsons([other, stray, own, {"name": "book.xlsx", "path": "x"}])]
    assert order == [own["name"], other["name"], stray["name"]]


def test_the_price_sent_is_the_runs_own(tmp_path):
    other = _write(tmp_path, "12674-01-GA_20261111_120000_record.json", 1034.37, 1000.0)
    own = _write(tmp_path, "6364-01_20261111_143000_record.json", 1383.58, 2000.0)
    got = runner._unit_cost_from_deliverables([other, own])
    assert got == 1383.58
