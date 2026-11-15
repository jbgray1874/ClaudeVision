"""THE PACKS ALREADY CHECKED ARE PRICED WITHOUT LISTING THE SHARE (15 Nov 2026).

The pack check had resolved the packs and fingerprinted every file. The batch still refused to
start until a listing of every customer's folders had finished: hours over the VPN, for packs
already found. Given the pack check's report, the batch now prices those packs and no others,
each held unless the pack found again now is the same files with the same fingerprints. It
lists neither drawing area.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import tti_pricer as tp  # noqa: E402
from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _areas, _args  # noqa: E402
from test_the_tracker_batch_runs_the_rows_named_on_their_own_briefs_and_never_lists_the_share_in_silence import _tracker  # noqa: E402

GA, OTHER, UNCHECKED = "12353-13-GA", "12687-01-GA", "12999-01-GA"


def _manifest(tmp_path, drawing, prints=("sha1:" + "a" * 40, "sha1:" + "b" * 40)):
    d = tmp_path / "share" / drawing
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for n, fp in enumerate(prints):
        f = d / f"{drawing}-{n}.pdf"
        f.write_bytes(b"%PDF " + fp.encode())
        files.append({"path": str(f), "format": "pdf", "size": f.stat().st_size, "fingerprint": fp})
    return {"status": "complete", "drawing": drawing, "selected_folder": str(d), "candidates": [],
            "members": [{"drawing": drawing, "files": files}], "missing": [], "conflicts": [],
            "assumptions": [], "question": "", "price_ok": True}


def _report(tmp_path, packs):
    p = tmp_path / "packs-1" / "preflight.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"rows": [
        {"row": n, "drawing": d, "pack": ({"state": "resolved", "manifest": m} if m else {"state": "not_found"})}
        for n, (d, m) in enumerate(packs.items(), 2)]}), encoding="utf-8")
    return p


def _run(tmp_path, monkeypatch, lines, now, report):
    sheet = _tracker(tmp_path, lines)
    _areas(tmp_path, monkeypatch)
    monkeypatch.setenv("SDI_TTI_INPUTS", str(tmp_path / "inputs"))
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)

    def _no_listing(*a, **k):
        raise AssertionError("the drawing areas were listed")
    monkeypatch.setattr(tp, "area_listings", _no_listing)
    monkeypatch.setattr(tp, "list_folders", _no_listing)

    def _pack_for(drawing, listings, client):
        m = now.get(drawing)
        if not m:
            return {}, None
        return ({"area": "design", "match": "pack", "folder": m["selected_folder"],
                 "files": [f["path"] for x in m["members"] for f in x["files"]],
                 "technical": False, "newest": "", "other_folders": []}, m)
    monkeypatch.setattr(tp, "pack_for", _pack_for)
    monkeypatch.setattr(tp, "find_drawings", lambda d, l: {})
    monkeypatch.setattr(tp, "job_folders", lambda d, l: [])
    portal = FakePortal()
    rep = tp.run_batch(_args(sheet, checked_packs=str(report)), portal=portal, status_path=None,
                       sleep=lambda s: None)
    return portal, rep


def test_a_checked_pack_found_again_unchanged_is_priced_and_the_share_is_not_listed(tmp_path, monkeypatch, capsys):
    m = _manifest(tmp_path, GA)
    portal, rep = _run(tmp_path, monkeypatch, [(GA, "Stand", "", "", 25)], {GA: m}, _report(tmp_path, {GA: m}))
    assert len(portal.started) == 1
    assert "not listed" in capsys.readouterr().out
    assert "held" not in rep["rows"][0]["state"]


def test_a_pack_whose_file_changed_since_the_check_is_held_and_the_unchanged_one_still_runs(tmp_path, monkeypatch):
    was, same = _manifest(tmp_path, GA), _manifest(tmp_path, OTHER)
    report = _report(tmp_path, {GA: was, OTHER: same})
    now = json.loads(json.dumps(was))
    now["members"][0]["files"][1]["fingerprint"] = "sha1:" + "c" * 40
    portal, rep = _run(tmp_path, monkeypatch, [(GA, "Stand", "", "", 25), (OTHER, "Rack", "", "", 15)],
                       {GA: now, OTHER: same}, report)
    held = next(r for r in rep["rows"] if r["drawing"] == GA)
    assert held["state"] == "held: not the checked pack" and "changed since the check" in held["why"]
    assert [b for b in portal.started] and len(portal.started) == 1


def test_a_file_added_or_gone_since_the_check_is_held(tmp_path, monkeypatch):
    was = _manifest(tmp_path, GA)
    report = _report(tmp_path, {GA: was})
    fewer = json.loads(json.dumps(was))
    fewer["members"][0]["files"].pop()
    portal, rep = _run(tmp_path, monkeypatch, [(GA, "Stand", "", "", 25)], {GA: fewer}, report)
    assert not portal.started and "of the checked pack not in it now" in rep["rows"][0]["why"]


def test_a_row_the_check_did_not_resolve_is_held_even_though_a_pack_is_found_now(tmp_path, monkeypatch):
    ok, extra = _manifest(tmp_path, GA), _manifest(tmp_path, UNCHECKED)
    report = _report(tmp_path, {GA: ok, UNCHECKED: None})
    portal, rep = _run(tmp_path, monkeypatch, [(UNCHECKED, "Bay", "", "", 2)], {UNCHECKED: extra}, report)
    assert not portal.started
    assert "not one the pack check resolved" in rep["rows"][0]["why"]


def test_a_report_that_resolved_nothing_or_cannot_be_read_stops_the_batch(tmp_path):
    with pytest.raises(SystemExit, match="resolved no pack"):
        tp.load_checked_packs(_report(tmp_path, {GA: None}))
    with pytest.raises(SystemExit, match="could not be read"):
        tp.load_checked_packs(tmp_path / "nowhere.json")


def test_without_the_report_the_batch_still_asks_the_index(tmp_path, monkeypatch):
    sheet = _tracker(tmp_path, [(GA, "Stand", "", "", 25)])
    _areas(tmp_path, monkeypatch)
    called = []

    def _listing(*a, **k):
        called.append(1)
        raise tp.IndexNotUsable("the drawing index is stale")
    monkeypatch.setattr(tp, "area_listings", _listing)
    with pytest.raises(SystemExit):
        tp.run_batch(_args(sheet), portal=FakePortal(), status_path=None, sleep=lambda s: None)
    assert called
