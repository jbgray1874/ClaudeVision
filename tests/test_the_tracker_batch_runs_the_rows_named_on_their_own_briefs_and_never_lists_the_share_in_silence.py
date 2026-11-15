"""THE TRACKER BATCH: THE ROWS NAMED, EACH ON ITS OWN BRIEF, AND NO SILENT LISTING (15 Nov 2026).

Three faults met on the conference tracker, each a generic rule:

  * A refresh that ran while the drawing share was away marked both drawing areas unreadable.
    The batch could not use the index, so it listed every folder of both areas itself, some
    230,000 over a VPN, printing nothing. One dry run sat for ten hours; a two-row run would
    have done the same. An index that exists and cannot be used now stops the batch with the
    reason and the remedy. --walk-live asks for the long listing by name, and it reports as
    it goes.
  * --rows took a range only, so approving rows 134 and 137 also ran 135 and 136, which had
    been held. It now takes the rows named.
  * One drawing on several rows was one run on the first row's brief. A booth is on six rows
    with different descriptions and feedback; five briefs were dropped. Rows whose words
    differ are separate estimates. Rows that ask for the same thing still share one run.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import tti_pricer as tp  # noqa: E402
from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _areas, _args  # noqa: E402


def _tracker(tmp_path, rows):
    """rows: (drawing, description, previous feedback, latest feedback, qty)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for col, head in {"B": "Item Description", "D": "Qty", "G": "Previous Feedback",
                      "H": "Latest Feedback - 11/11", "L": "Drawing Number", "P": "AICost"}.items():
        ws[f"{col}1"] = head
    for i, (drawing, desc, prev, latest, qty) in enumerate(rows, 2):
        ws[f"L{i}"], ws[f"B{i}"], ws[f"G{i}"], ws[f"H{i}"], ws[f"D{i}"] = drawing, desc, prev, latest, qty
    p = tmp_path / "tracker.xlsx"
    wb.save(p)
    return p


def _run(tmp_path, monkeypatch, lines, **kw):
    sheet = _tracker(tmp_path, lines)
    _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    portal = FakePortal()
    rep = tp.run_batch(_args(sheet, **kw), portal=portal, status_path=None, sleep=lambda s: None)
    return portal, rep


# ── EACH ROW ON ITS OWN BRIEF ──────────────────────────────────────────────────────────────
BOOTH = "12110-01-GA1"


def test_rows_of_one_drawing_with_different_words_are_separate_estimates(tmp_path, monkeypatch):
    portal, rep = _run(tmp_path, monkeypatch, [
        (BOOTH, "Soundproof booth", "", "add door seal", 1),
        (BOOTH, "Welding glove demo", "", "no glazing", 1)])
    assert len(portal.started) == 2, "the second row took the first row's price"
    briefs = [b["enquiry_brief"] for b in portal.started]
    assert "Soundproof booth" in briefs[0] and "door seal" in briefs[0]
    assert "Welding glove demo" in briefs[1] and "no glazing" in briefs[1]
    assert "Welding glove" not in briefs[0] and "door seal" not in briefs[1]
    assert all("own brief" in (r.get("own_brief") or "") for r in rep["rows"])
    assert "same_as_row" not in rep["rows"][1]


def test_a_change_in_either_feedback_column_alone_separates_the_rows(tmp_path, monkeypatch):
    portal, _rep = _run(tmp_path, monkeypatch, [
        (BOOTH, "Booth", "paint black", "", 2), (BOOTH, "Booth", "paint white", "", 2)])
    assert len(portal.started) == 2


def test_rows_that_ask_for_the_same_thing_still_share_one_run(tmp_path, monkeypatch):
    portal, rep = _run(tmp_path, monkeypatch, [
        (BOOTH, "Booth", "paint black", "seal", 2), (BOOTH, "booth ", "Paint  black", "seal", 2)])
    assert len(portal.started) == 1
    assert rep["rows"][1]["same_as_row"] == 2 and not rep["rows"][1].get("own_brief")


def test_the_same_words_at_another_quantity_are_one_run_with_that_quantity_as_a_break(tmp_path, monkeypatch):
    portal, _rep = _run(tmp_path, monkeypatch, [
        (BOOTH, "Booth", "", "seal", 1), (BOOTH, "Booth", "", "seal", 3)])
    assert portal.started[0]["quantity_breaks"] == [3]


def test_different_words_do_not_lend_each_other_quantity_breaks(tmp_path, monkeypatch):
    portal, _rep = _run(tmp_path, monkeypatch, [
        (BOOTH, "Booth", "", "seal", 1), (BOOTH, "Glove demo", "", "", 3)])
    assert [b["quantity_breaks"] for b in portal.started] == [[], []]


def test_run_keys_are_the_drawing_until_the_words_differ():
    rows = [{"drawing": "A-1", "description": "x"}, {"drawing": "A-1", "description": "x"},
            {"drawing": "B-2", "description": "p"}, {"drawing": "B-2", "description": "q"},
            {"drawing": "", "description": "no drawing"}]
    tp.assign_run_keys(rows)
    assert [r["run_key"] for r in rows] == ["A-1", "A-1", "B-2#1", "B-2#2", ""]
    assert [bool(r.get("scope_differs")) for r in rows] == [False, False, True, True, False]


# ── THE ROWS NAMED, AND NO OTHERS ──────────────────────────────────────────────────────────
def test_rows_are_a_range_a_list_or_both():
    assert tp.parse_rows("5-8") == [5, 6, 7, 8]
    assert tp.parse_rows("134,137") == [134, 137]
    assert tp.parse_rows(" 10, 114 ,134-136 ") == [10, 114, 134, 135, 136]
    assert tp.parse_rows("3") == [3] and tp.parse_rows("") == []
    for bad in ("x", "9-3", "0"):
        with pytest.raises(SystemExit):
            tp.parse_rows(bad)


def test_naming_two_rows_runs_those_two_and_not_the_rows_between(tmp_path, monkeypatch):
    rows = [(f"TTI-{n}", f"Item {n}", "", "", 1) for n in (10234, 20001, 20002, 20003)]
    portal, rep = _run(tmp_path, monkeypatch, rows, rows="2,5")
    assert [r["row"] for r in rep["rows"]] == [2, 5]
    assert [b["drawing_number"] for b in portal.started] == ["TTI-10234", "TTI-20003"]


def test_a_range_still_runs_every_row_in_it(tmp_path, monkeypatch):
    rows = [(f"TTI-{n}", f"Item {n}", "", "", 1) for n in (10234, 20001, 20002)]
    _portal, rep = _run(tmp_path, monkeypatch, rows, rows="2-3")
    assert [r["row"] for r in rep["rows"]] == [2, 3]


# ── AN INDEX THAT CANNOT BE USED STOPS THE BATCH ───────────────────────────────────────────
def _index(monkeypatch, tmp_path, *, readable, built_hours_ago=1.0):
    import drawing_index as di
    db = tmp_path / "index.sqlite"
    db.write_bytes(b"")
    monkeypatch.setattr(di, "settings", lambda env=None: {"path": tmp_path / "index.json.gz",
                                                          "max_hours": 26.0})
    monkeypatch.setattr(di, "db_path", lambda p: db)
    meta = {"built_at": time.time() - built_hours_ago * 3600}

    def _meta(_db):
        return dict(meta, roots={str(r): {"readable": readable} for r in _roots})
    _roots: list = []
    monkeypatch.setattr(di, "db_meta", _meta)
    monkeypatch.setattr(di, "db_folders_under", lambda _db, root: [])
    return _roots


def test_an_index_whose_areas_were_unreadable_stops_the_batch_and_says_how_to_mend_it(tmp_path, monkeypatch, capsys):
    design, proto, _tech = _areas(tmp_path, monkeypatch)
    _index(monkeypatch, tmp_path, readable=False).extend([design, proto])
    walked = []
    monkeypatch.setattr(tp, "list_folders", lambda root, *a, **k: walked.append(root) or [])
    with pytest.raises(SystemExit) as stop:
        tp.area_listings(design, proto)
    said = str(stop.value)
    assert "does not cover" in said and "drawing_index.py --build" in said and "--walk-live" in said
    assert walked == [], "the share was listed although the index could not be used"


def test_a_stale_index_stops_it_too(tmp_path, monkeypatch):
    design, proto, _tech = _areas(tmp_path, monkeypatch)
    _index(monkeypatch, tmp_path, readable=True, built_hours_ago=200).extend([design, proto])
    with pytest.raises(SystemExit) as stop:
        tp.area_listings(design, proto)
    assert "stale" in str(stop.value)


def test_walk_live_lists_the_areas_and_says_it_is_doing_so(tmp_path, monkeypatch, capsys):
    design, proto, _tech = _areas(tmp_path, monkeypatch)
    _index(monkeypatch, tmp_path, readable=False).extend([design, proto])
    listings, source = tp.area_listings(design, proto, walk_live=True)
    assert source.startswith("walked live") and listings[0][1], "the design area was not listed"
    assert "LISTING BOTH DRAWING AREAS LIVE" in capsys.readouterr().out


def test_a_fresh_index_that_covers_both_areas_is_used_and_nothing_is_listed(tmp_path, monkeypatch):
    design, proto, _tech = _areas(tmp_path, monkeypatch)
    _index(monkeypatch, tmp_path, readable=True).extend([design, proto])
    monkeypatch.setattr(tp, "list_folders", lambda *a, **k: pytest.fail("the share was listed"))
    _listings, source = tp.area_listings(design, proto)
    assert source.startswith("drawing index built")


def test_the_long_listing_reports_how_far_it_has_got(tmp_path, capsys):
    for n in range(7):
        (tmp_path / "area" / f"job{n}").mkdir(parents=True)
    got = tp.list_folders(tmp_path / "area", say_every=3)
    assert len(got) == 8
    out = capsys.readouterr().out
    assert "3 folder(s) so far" in out and "6 folder(s) so far" in out
