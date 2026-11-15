"""The batch lists its own two folders, a stopped listing carries on, and nothing on the share changes.

JG, 15 Nov 2026, four hours into a refresh that had reached other customers' folders: "we only
need TTI indexed... why are we indexing all clients" and "you are not moving anything are you?
These folders can't be changed".

Three faults, one cause each:
  * the only index the batch could use was the one of every customer on the share;
  * the index was written once, at the end, so a listing that was stopped saved nothing;
  * folders were asked of the share one at a time, about 150 ms each over the VPN.
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


def _share(tmp_path: Path):
    """A share with the batch's client and another customer in each area."""
    design = tmp_path / "Design" / "Customers"
    proto = tmp_path / "Prototype"
    for area, client in ((design, "TTI"), (proto, "TTi")):
        for job in ("12181 - Demo", "12353 - Stand"):
            tech = area / client / job / f"{job[:5]}-Technical"
            tech.mkdir(parents=True)
            (tech / f"{job[:5]}-01-GA.pdf").write_text("ga")
            (tech / f"{job[:5]}-01-01.dxf").write_text("flat")
            (area / client / job / f"{job[:5]}-Creative" / "Maps").mkdir(parents=True)
        other = area / "Another Customer" / "9000 - Unit" / "9000-Technical"
        other.mkdir(parents=True)
        (other / "9000-01-GA.pdf").write_text("theirs")
    return design, proto


def _batch(monkeypatch, tmp_path: Path):
    design, proto = _share(tmp_path)
    monkeypatch.setenv("SDI_TTI_DESIGN_ROOT", str(design / "TTI"))
    monkeypatch.setenv("SDI_TTI_PROTOTYPE_ROOT", str(proto / "TTi"))
    monkeypatch.setenv("SDI_TTI_INDEX", str(tmp_path / "own" / "index.json.gz"))
    monkeypatch.setenv("SDI_DRAWING_INDEX", str(tmp_path / "all" / "index.json.gz"))
    monkeypatch.delenv("SDI_DRAWING_INDEX_MAX_HOURS", raising=False)
    monkeypatch.delenv("SDI_DRIVE_MAP", raising=False)
    for d in (tp._FILES, tp._MTIME, tp._SIZE):
        d.clear()
    return design, proto


# ── the batch's own index ────────────────────────────────────────────────────────────────
def test_refresh_index_lists_the_batchs_two_folders_and_no_other_customer(tmp_path, monkeypatch):
    design, proto = _batch(monkeypatch, tmp_path)
    asked = []
    real = di._list
    monkeypatch.setattr(di, "_list", lambda f: asked.append(str(f)) or real(f))
    said = []
    assert tp.refresh_scoped_index("TTI", say=said.append) == 0
    assert asked and not [a for a in asked if "Another Customer" in a], "another customer's folder was listed"
    idx = di.load(tmp_path / "own" / "index.json.gz")
    assert set(idx["roots"]) == {str(design / "TTI"), str(proto / "TTi")}
    assert not [k for k in idx["folders"] if "Another Customer" in k]
    assert any("readable" in line for line in said)
    assert not (tmp_path / "all").exists(), "the whole-share index was written by a batch refresh"


def test_the_batch_runs_on_its_own_index_with_no_whole_share_index_at_all(tmp_path, monkeypatch):
    design, proto = _batch(monkeypatch, tmp_path)
    tp.refresh_scoped_index("TTI", say=lambda _l: None)
    monkeypatch.setattr(tp, "list_folders", lambda *a, **k: pytest.fail("the share was listed live"))
    listings, source = tp.area_listings(design / "TTI", proto / "TTi")
    assert source.startswith("drawing index built") and "own two folders" in source
    found = tp.find_drawings("12181-01-GA", listings)
    assert Path(found["files"][0]).name == "12181-01-GA.pdf"


def test_a_stale_own_index_falls_to_a_fresh_whole_share_index(tmp_path, monkeypatch):
    design, proto = _batch(monkeypatch, tmp_path)
    own = tmp_path / "own" / "index.json.gz"
    di.refresh([design / "TTI", proto / "TTi"], own, now=time.time() - 100 * 3600)
    di.refresh([design, proto], tmp_path / "all" / "index.json.gz")
    monkeypatch.setattr(tp, "list_folders", lambda *a, **k: pytest.fail("the share was listed live"))
    _listings, source = tp.area_listings(design / "TTI", proto / "TTi")
    assert source.startswith("drawing index built") and "own two folders" not in source


def test_with_both_stale_the_batch_stops_and_names_the_two_folder_refresh(tmp_path, monkeypatch):
    design, proto = _batch(monkeypatch, tmp_path)
    long_ago = time.time() - 100 * 3600
    di.refresh([design / "TTI", proto / "TTi"], tmp_path / "own" / "index.json.gz", now=long_ago)
    di.refresh([design, proto], tmp_path / "all" / "index.json.gz", now=long_ago)
    monkeypatch.setattr(tp, "list_folders", lambda *a, **k: pytest.fail("the share was listed live"))
    with pytest.raises(SystemExit) as stop:
        tp.area_listings(design / "TTI", proto / "TTi")
    said = str(stop.value)
    assert "stale" in said and "tti_pricer.py --refresh-index" in said
    assert "drawing_index.py --build" not in said, "the remedy named is still the every-customer listing"
    assert "held 18 folder(s)" in said, said


def test_an_own_index_made_while_an_area_was_unreadable_is_not_used(tmp_path, monkeypatch):
    design, proto = _batch(monkeypatch, tmp_path)
    monkeypatch.setenv("SDI_TTI_PROTOTYPE_ROOT", str(tmp_path / "away" / "TTi"))
    said = []
    assert tp.refresh_scoped_index("TTI", say=said.append) == 2
    assert any("NOT READABLE" in line for line in said)
    with pytest.raises(SystemExit) as stop:
        tp.area_listings(design / "TTI", tmp_path / "away" / "TTi")
    assert "does not cover" in str(stop.value)


def test_the_command_line_refreshes_and_prices_nothing(tmp_path, monkeypatch, capsys):
    _batch(monkeypatch, tmp_path)
    monkeypatch.setattr(tp, "run_batch", lambda *a, **k: pytest.fail("a batch was started"))
    assert tp.main(["--refresh-index"]) == 0
    assert "two folders only" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        tp.main([])                                   # the contrast: pricing still needs its sheet


# ── a stopped listing carries on ─────────────────────────────────────────────────────────
class _Stopped(Exception):
    pass


_REAL_LIST = di._list


def _stop_after(monkeypatch, n: int):
    real = _REAL_LIST
    seen = []

    def _list(folder):
        if len(seen) >= n:
            raise _Stopped()
        seen.append(str(folder))
        return real(folder)
    monkeypatch.setattr(di, "_list", _list)
    return seen


def test_a_stopped_listing_saves_its_progress_and_the_next_lists_only_the_rest(tmp_path, monkeypatch):
    design, _proto = _share(tmp_path)
    p = tmp_path / "ix" / "index.json.gz"
    first = _stop_after(monkeypatch, 6)
    with pytest.raises(_Stopped):
        di.refresh([design], p, workers=1, save_every=2)
    assert di.partial_path(p).is_file() and not p.exists(), "no progress was kept, or it was kept as the index"
    second = _stop_after(monkeypatch, 10 ** 6)
    s = di.refresh([design], p, workers=1, save_every=2)
    assert s["last"]["resumed"] >= 4 and s["last"]["listed"] == len(second)
    assert not set(first[:4]) & set(second), "folders already saved were listed again"
    assert not di.partial_path(p).exists(), "the partial file outlived a completed listing"
    # the same share listed in one go holds exactly the same folders and files
    whole = tmp_path / "whole" / "index.json.gz"
    di.refresh([design], whole, workers=1)
    assert di.load(p)["folders"] == di.load(whole)["folders"]


def test_a_partial_file_is_never_an_index(tmp_path, monkeypatch):
    design, proto = _batch(monkeypatch, tmp_path)
    own = tmp_path / "own" / "index.json.gz"
    _stop_after(monkeypatch, 3)
    with pytest.raises(_Stopped):
        di.refresh([design / "TTI", proto / "TTi"], own, workers=1, save_every=1)
    part = di.partial_path(own)
    assert part.is_file()
    assert di.load(part) is None and di.load(own) is None
    assert not di.is_fresh(di.load(part), 26) and not di.db_path(own).exists()
    monkeypatch.undo()
    _batch_env = {"SDI_TTI_INDEX": str(own), "SDI_DRAWING_INDEX": str(tmp_path / "all" / "index.json.gz")}
    for k, v in _batch_env.items():
        os.environ[k] = v
    try:
        _listings, source = tp.area_listings(design / "TTI", proto / "TTi", walk_live=True)
    finally:
        for k in _batch_env:
            os.environ.pop(k, None)
    assert source == "walked live (no drawing index)", "a half-made listing was read as an index"


def test_progress_of_another_listing_or_an_old_one_is_not_taken(tmp_path, monkeypatch):
    design, proto = _share(tmp_path)
    p = tmp_path / "ix" / "index.json.gz"
    _stop_after(monkeypatch, 4)
    with pytest.raises(_Stopped):
        di.refresh([design], p, workers=1, save_every=1)
    listed = _stop_after(monkeypatch, 10 ** 6)
    s = di.refresh([proto], p, workers=1)                       # other roots: nothing carried over
    assert not s["last"].get("resumed") and s["last"]["listed"] == len(listed)
    # an old one: kept progress is checked against each folder's own time, and a folder that
    # has changed since is listed again
    _stop_after(monkeypatch, 4)
    with pytest.raises(_Stopped):
        di.refresh([design], p, workers=1, save_every=1, full=True)
    changed = design / "TTI"
    (changed / "13000 - New Job").mkdir()
    later = time.time() + 60                      # the index keeps a folder's time to a tenth of a second
    os.utime(changed, (later, later))
    again = _stop_after(monkeypatch, 10 ** 6)
    s = di.refresh([design], p, workers=1, full=True, now=time.time() + 24 * 3600)
    assert str(changed) in again, "a folder changed since the stopped listing was taken as listed"
    assert any("13000 - New Job" in k for k in di.load(p)["folders"])


# ── several folders at once, the same index ──────────────────────────────────────────────
def test_one_worker_and_eight_make_the_same_index(tmp_path, monkeypatch):
    design, proto = _share(tmp_path)
    locked = design / "TTI" / "12353 - Stand" / "12353-Technical"
    real = di._list
    monkeypatch.setattr(di, "_list", lambda f: None if Path(f) == locked else real(f))
    out = {}
    for n in (1, 8):
        p = tmp_path / f"w{n}" / "index.json.gz"
        s = di.refresh([design, proto], p, depth=3, workers=n, now=1000.0)
        idx = di.load(p)
        out[n] = (idx["folders"], list(idx["folders"]), idx["roots"], s["last"]["unreadable"], s["last"]["listed"])
        assert s["last"]["workers"] == n
    assert out[1] == out[8]
    assert out[1][3] == 1 and str(locked) not in out[1][0], "the unreadable folder was not left out and counted"
    deepest = max(len(Path(k).relative_to(design).parts) for k in out[1][0] if k.startswith(str(design)))
    assert deepest == 3, "the depth limit was not kept"       # the share goes a level deeper (Creative/Maps)


def test_progress_is_said_and_saved_with_several_workers(tmp_path):
    design, proto = _share(tmp_path)
    p = tmp_path / "ix" / "index.json.gz"
    lines = []
    saves = []
    real = di.save_partial
    try:
        di.save_partial = lambda *a, **k: saves.append(1) or real(*a, **k)
        di.refresh([design, proto], p, workers=8, every=5, save_every=5, progress=lines.append)
    finally:
        di.save_partial = real
    assert len(lines) >= 2 and all("folder(s), listed" in line for line in lines)
    assert saves and not di.partial_path(p).exists()


def test_the_worker_count_is_a_setting_and_one_is_one_at_a_time(tmp_path, monkeypatch):
    design, _proto = _share(tmp_path)
    monkeypatch.setenv("SDI_DRAWING_INDEX_WORKERS", "1")
    assert di.refresh([design], tmp_path / "a" / "index.json.gz")["last"]["workers"] == 1
    monkeypatch.delenv("SDI_DRAWING_INDEX_WORKERS")
    assert di.refresh([design], tmp_path / "b" / "index.json.gz")["last"]["workers"] == 8


# ── nothing on the share changes ─────────────────────────────────────────────────────────
def _picture(root: Path):
    out = {}
    for d, dirs, files in os.walk(root):
        st = os.stat(d)
        out[d] = ("dir", st.st_mtime_ns, sorted(dirs), sorted(files))
        for f in files:
            fp = os.path.join(d, f)
            st = os.stat(fp)
            out[fp] = ("file", st.st_mtime_ns, st.st_size, Path(fp).read_bytes())
    return out


@pytest.mark.parametrize("workers", [1, 8])
def test_listing_creates_changes_and_deletes_nothing_under_the_share(tmp_path, monkeypatch, workers):
    share = tmp_path / "share"
    share.mkdir()
    design, proto = _batch(monkeypatch, share)
    monkeypatch.setenv("SDI_TTI_INDEX", str(tmp_path / "laptop" / "own" / "index.json.gz"))
    monkeypatch.setenv("SDI_DRAWING_INDEX", str(tmp_path / "laptop" / "all" / "index.json.gz"))
    monkeypatch.setenv("SDI_DRAWING_INDEX_WORKERS", str(workers))
    before = _picture(share)
    tp.refresh_scoped_index("TTI", say=lambda _l: None)                      # the batch's own listing
    di.refresh([design, proto], tmp_path / "laptop" / "all" / "index.json.gz", full=True)   # the full one
    _stop_after(monkeypatch, 3)
    with pytest.raises(_Stopped):                                            # and one that is stopped
        di.refresh([design], tmp_path / "laptop" / "stopped" / "index.json.gz", save_every=1, workers=1)
    monkeypatch.undo()
    tp.area_listings(design / "TTI", proto / "TTi", walk_live=True)          # and the live walk
    assert _picture(share) == before, "something under the share was created, changed or removed"
    assert (tmp_path / "laptop" / "own" / "index.json.gz").is_file()
