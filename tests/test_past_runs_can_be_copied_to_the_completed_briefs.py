"""Runs already in AISheets can be copied to the completed AI briefs area, once each (D-617a).

JG, 1 Nov 2026: "yes, copy the six from 31 Oct."
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import copy_runs_to_briefs as tool  # noqa: E402


def _run(root, client, drawing, folder, workbook=True):
    d = root / client / drawing / folder
    d.mkdir(parents=True)
    (d / f"{drawing}_record.json").write_text("{}", encoding="utf-8")
    (d / f"{drawing}_report.html").write_text("<p>", encoding="utf-8")
    if workbook:
        (d / f"{drawing}_20261031.xlsx").write_bytes(b"PK")
    return d


def _tree(tmp_path):
    a = tmp_path / "AISheets"
    _run(a, "M&S", "12678-01-GA", "2026-10-31 19-16-33 (1 off)")
    _run(a, "M&S", "12677-01-GA", "2026-10-31 20-41-02 (1 off)")
    _run(a, "M&S", "12676-01-GA2", "2026-10-31 20-05-10 (1 off)", workbook=False)
    _run(a, "M&S", "11908-22-GA", "2026-10-30 09-00-00 (1 off)")
    _run(a, "Pixel", "TG_Standalone", "2026-10-31 04-57-00 (1 off)")
    (a / "M&S" / "12678-01-GA" / "notes").mkdir()
    return a, tmp_path / "briefs"


def test_the_preview_picks_the_finished_runs_of_that_client_and_day(tmp_path):
    a, b = _tree(tmp_path)
    runs = tool.plan(a, b, "M & S", date(2026, 10, 31), date(2026, 10, 31))
    copy = {(r["drawing"], r["folder"].name) for r in runs if r["action"] == "copy"}
    assert copy == {("12678-01-GA", "2026-10-31 19-16-33 (1 off)"),
                    ("12677-01-GA", "2026-10-31 20-41-02 (1 off)")}
    why = {r["drawing"]: r["why"] for r in runs if r["action"] == "skip"}
    assert why["12676-01-GA2"].startswith("no workbook in the folder")
    assert why["11908-22-GA"] == "outside the dates asked for"
    assert why["TG_Standalone"] == "another client"
    assert not b.exists(), "a preview copies nothing"


def test_apply_copies_each_run_once_with_the_runners_folder_rules(tmp_path, capsys):
    a, b = _tree(tmp_path)
    args = ["--aisheets", str(a), "--briefs", str(b), "--client", "M&S",
            "--from", "2026-10-31", "--to", "2026-10-31"]
    assert tool.main(args) == 0
    assert "2 run(s) to copy. Nothing was copied: add --apply" in capsys.readouterr().out
    assert tool.main(args + ["--apply"]) == 0
    one = b / "M&S" / "12678-01-GA" / "2026-10-31 19-16-33 v1 (1 off)"
    assert sorted(p.name for p in one.iterdir()) == [
        "12678-01-GA_20261031.xlsx", "12678-01-GA_record.json", "12678-01-GA_report.html"]
    assert (b / "M&S" / "12677-01-GA" / "2026-10-31 20-41-02 v1 (1 off)").is_dir()
    capsys.readouterr()
    assert tool.main(args + ["--apply"]) == 0
    again = capsys.readouterr().out
    assert "0 run(s) to copy" in again and "already copied to" in again
    assert len(list((b / "M&S" / "12678-01-GA").iterdir())) == 1, "never twice"


def test_a_later_live_run_of_the_same_pack_is_v2(tmp_path):
    a, b = _tree(tmp_path)
    tool.main(["--aisheets", str(a), "--briefs", str(b), "--client", "M&S",
               "--drawing", "12677-01-GA", "--apply"])
    import sdi_estimate_runner as runner
    nxt = runner.archive_folder(b / "M&S" / "12677-01-GA", "2026-11-01 10-00-00", 1)
    assert nxt.name == "2026-11-01 10-00-00 v2 (1 off)"


def test_an_unreachable_aisheets_says_so(tmp_path, capsys):
    assert tool.main(["--aisheets", str(tmp_path / "nowhere"), "--briefs", str(tmp_path)]) == 2
    assert "AISheets is not reachable" in capsys.readouterr().out
