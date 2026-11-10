"""The drawing index holds every folder and drawing file of the design share on this machine, so
finding a job's drawings is a lookup, not a walk of W: (JG, 9 Nov 2026).

A refresh lists only folders whose modified time changed; an unreadable share keeps what was last
known; the TTI pricer reads the index when it is fresh and covers its folders, and walks live
otherwise, saying which.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawing_index as di  # noqa: E402
import tti_pricer as tp  # noqa: E402

WALL = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-wall.html").read_text(encoding="utf-8")
WALL_PY = (ROOT / "sdi-intelligence-backend" / "estimate_wall.py").read_text(encoding="utf-8")
SWEEP = (ROOT / "src" / "design_sweep.py").read_text(encoding="utf-8")


def _share(tmp_path: Path) -> Path:
    w = tmp_path / "Customers"
    job = w / "TTI" / "12181 - Sander Application Demo [Rome 2026]"
    (job / "Technical").mkdir(parents=True)
    (job / "Technical" / "12181-00-GA.pdf").write_text("ga")
    (job / "Technical" / "notes.txt").write_text("not a drawing")
    (w / "TTI" / "Archive" / "old job").mkdir(parents=True)
    (w / "TTI" / "Archive" / "old job" / "x.pdf").write_text("x")
    (w / "Boots" / "0358141 Unit").mkdir(parents=True)
    (w / "Boots" / "0358141 Unit" / "a.dxf").write_text("a")
    return w


def test_the_index_holds_every_drawing_and_keeps_archives_as_evidence_only(tmp_path):
    w = _share(tmp_path)
    s = di.refresh([w], tmp_path / "ix.json.gz")
    assert s["drawings"] == 3 and s["roots"][str(w)]["readable"]
    idx = di.load(tmp_path / "ix.json.gz")
    names = sorted(f.name for _folder, files in di.folders_under(idx, w) for f, _s, _m in files)
    assert names == ["12181-00-GA.pdf", "a.dxf"], "an archive is never offered as a candidate"
    every = sorted(f.name for _folder, files in di.folders_under(idx, w, include_archive=True) for f, _s, _m in files)
    assert every == ["12181-00-GA.pdf", "a.dxf", "x.pdf"], "but it is indexed, as evidence"
    assert di.is_archive(r"TTI\Archive\old job") and not di.is_archive(r"TTI\12181 Stand")


def test_a_second_refresh_lists_only_the_folder_that_changed(tmp_path):
    w = _share(tmp_path)
    p = tmp_path / "ix.json.gz"
    first = di.refresh([w], p)
    assert first["last"]["reused"] == 0
    tech = w / "TTI" / "12181 - Sander Application Demo [Rome 2026]" / "Technical"
    (tech / "12181-00-GA2.pdf").write_text("ga2")
    os.utime(tech, (time.time() + 5, time.time() + 5))
    again = di.refresh([w], p)
    assert again["last"]["listed"] == 1 and again["last"]["reused"] == first["folders"] - 1
    assert again["drawings"] == 4


def test_an_unreadable_share_keeps_what_was_last_known(tmp_path):
    w = _share(tmp_path)
    p = tmp_path / "ix.json.gz"
    di.refresh([w], p)
    gone = tmp_path / "moved"
    w.rename(gone)
    s = di.refresh([w], p)
    assert not s["roots"][str(w)]["readable"] and s["drawings"] == 3
    assert not di.covers(di.load(p), w / "TTI"), "an index over an unreadable share is not used for lookups"


def test_the_pricer_reads_a_fresh_index_and_walks_live_without_one(tmp_path, monkeypatch):
    w = _share(tmp_path)
    proto = tmp_path / "Prototype"
    (proto / "TTi").mkdir(parents=True)
    p = tmp_path / "ix.json.gz"
    monkeypatch.setenv("SDI_DRAWING_INDEX", str(p))
    tp._FILES.clear()
    _, how = tp.area_listings(w / "TTI", proto / "TTi")
    assert how == "walked live (no drawing index)"
    di.refresh([w, proto], p)
    tp._FILES.clear()
    listings, how = tp.area_listings(w / "TTI", proto / "TTi")
    assert how.startswith("drawing index built")
    f = tp.find_drawings("12181-00-GA", listings)
    assert f["match"] == "drawing number" and Path(f["files"][0]).name == "12181-00-GA.pdf"
    monkeypatch.setenv("SDI_DRAWING_INDEX_MAX_HOURS", "0")
    _, how = tp.area_listings(w / "TTI", proto / "TTi")
    assert how == "walked live (the drawing index is stale)"


def test_the_sweep_refreshes_the_index_and_the_wall_says_so():
    assert "di.refresh(icfg[\"roots\"]" in SWEEP and "--no-index" in SWEEP
    assert "drawing index ${ix.folders} folders" in WALL
    assert '"All systems normal"' in WALL_PY and "nominal" not in WALL_PY.lower()


# ── the lookup database and the quick refresh (10 Nov: 230,053 folders, ~10 hours to list) ──

import pack_resolver as pr  # noqa: E402


def test_an_existing_index_converts_to_the_lookup_database_without_listing_the_share(tmp_path):
    w = _share(tmp_path)
    p = tmp_path / "ix.json.gz"
    di.refresh([w], p)
    db = di.db_path(p)
    assert db.name == "ix.sqlite" and db.exists(), "a build writes the database too"
    db.unlink()
    n = di.build_db(di.load(p), db)
    assert n == 3 and di.db_meta(db)["built_at"] > 0
    rows = di.db_rows_for(db, "12181-00-GA")
    assert any(f.name == "12181-00-GA.pdf" for _p, files, _a in rows for f, _s, _m in files)
    assert {r[0].name for r in rows} >= {"Technical", "12181 - Sander Application Demo [Rome 2026]"}, \
        "the job's other folders come too"
    assert [f.name for f, _s, _m in di.db_lookup(db, "12181-00-GA")] == ["12181-00-GA.pdf"]
    assert di.db_lookup(db, "0123") == []


def test_the_quick_refresh_checks_the_top_levels_and_recent_folders_only(tmp_path):
    w = _share(tmp_path)
    p = tmp_path / "ix.json.gz"
    di.refresh([w], p)
    tech = w / "TTI" / "12181 - Sander Application Demo [Rome 2026]" / "Technical"
    old = time.time() - 200 * 86400
    os.utime(tech, (old, old))
    di.refresh([w], p, full=True)                       # the index now knows Technical as dormant
    (tech / "12181-00-GA3.pdf").write_text("new")
    os.utime(tech, (old, old))                          # a change the folder's date does not show
    quick = di.refresh([w], p, recent_days=90, top_levels=2)
    assert quick["last"].get("dormant", 0) >= 1 and quick["drawings"] == 3, "a dormant folder is not re-checked"
    full = di.refresh([w], p, full=True)
    assert full["drawings"] == 4, "the full listing catches it"


def test_the_folder_around_the_ga_is_relisted_live_so_a_new_file_is_never_missed(tmp_path, monkeypatch):
    w = _share(tmp_path)
    p = tmp_path / "ix.json.gz"
    monkeypatch.setenv("SDI_DRAWING_INDEX", str(p))
    monkeypatch.setenv("SDI_DRAWING_INDEX_ROOTS", str(w))
    di.refresh([w], p)
    tech = w / "TTI" / "12181 - Sander Application Demo [Rome 2026]" / "Technical"
    (tech / "12181-01-01M_Panel_RevA.DXF").write_text("added after the index")
    rows, source, lookup = pr.folders_for("12181-00-GA")
    names = {f.name for _p, files, _a in rows for f, _s, _m in files}
    assert "12181-01-01M_Panel_RevA.DXF" in names and "re-listed now" in source
    stale, _s, _l = pr.folders_for("12181-00-GA", live=False)
    assert "12181-01-01M_Panel_RevA.DXF" not in {f.name for _p, files, _a in stale for f, _s, _m in files}
