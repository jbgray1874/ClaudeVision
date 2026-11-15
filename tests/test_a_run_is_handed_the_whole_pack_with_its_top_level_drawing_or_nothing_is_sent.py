"""A RUN IS HANDED THE WHOLE PACK, WITH ITS TOP-LEVEL DRAWING, OR NOTHING IS SENT (15 Nov 2026).

12736-00-01, a tracker row. Discovery found the top-level assembly PDF. The pack saved in
Live Enquiry was called "unchanged" because its manifest listed the same files; the PDF itself
was not in the folder. The run was handed a path with nothing at it, the service skipped it, and
the estimate was made from the other sheets with a sub-assembly taken as the main drawing.
JG: "why are we missing the main PDF file in the drawing packs?"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pack_store as ps  # noqa: E402
import tti_pricer as tp  # noqa: E402
from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _areas, _args  # noqa: E402
from test_the_tracker_batch_runs_the_rows_named_on_their_own_briefs_and_never_lists_the_share_in_silence import _tracker  # noqa: E402

TOP = "12736-00-01"


def _pack(src: Path):
    src.mkdir(parents=True, exist_ok=True)
    members = []
    for drawing, name in ((TOP, f"{TOP}_DEMO ASSY_revB.pdf"), ("12736-01-101", "12736-01-101_Frame_revB.pdf"),
                          ("12736-01-102", "12736-01-102_Plate.dxf")):
        f = src / name
        f.write_text(drawing)
        members.append({"drawing": drawing, "files": [{"path": str(f), "format": f.suffix[1:],
                                                       "fingerprint": f"fp-{name}"}]})
    return {"drawing": TOP, "client": "TTI", "members": members}


def test_a_saved_pack_missing_a_file_is_not_called_unchanged_and_the_file_is_put_back(tmp_path):
    manifest = _pack(tmp_path / "W")
    first = ps.store(manifest, "TTI", root=tmp_path / "store")
    assert first["state"] == "new"
    top = Path(first["folder"]) / f"{TOP}_DEMO ASSY_revB.pdf"
    top.unlink()                                       # the manifest still lists it
    again = ps.store(manifest, "TTI", root=tmp_path / "store")
    assert again["state"] == "restored" and again["restored"] == [top.name] and top.is_file()
    assert ps.not_there(ps.stored_files(again, manifest)) == []
    saved = json.loads((Path(again["folder"]) / ps.MANIFEST).read_text())
    assert saved["stored"]["restored"] == [top.name], "the folder does not say what was put back"


def test_a_saved_pack_that_is_all_there_is_unchanged_and_nothing_is_copied(tmp_path):
    manifest = _pack(tmp_path / "W")
    first = ps.store(manifest, "TTI", root=tmp_path / "store")
    stamps = {p.name: p.stat().st_mtime_ns for p in Path(first["folder"]).iterdir()}
    again = ps.store(manifest, "TTI", root=tmp_path / "store")
    assert again["state"] == "unchanged" and "restored" not in again
    assert {p.name: p.stat().st_mtime_ns for p in Path(again["folder"]).iterdir()} == stamps


def test_a_file_that_cannot_be_put_back_is_an_error_not_a_quiet_gap(tmp_path):
    manifest = _pack(tmp_path / "W")
    first = ps.store(manifest, "TTI", root=tmp_path / "store")
    name = f"{TOP}_DEMO ASSY_revB.pdf"
    (Path(first["folder"]) / name).unlink()
    (tmp_path / "W" / name).unlink()                   # and it is no longer where it was found
    with pytest.raises(OSError):
        ps.store(manifest, "TTI", root=tmp_path / "store")


def test_the_top_level_drawing_must_be_among_the_files_handed_over(tmp_path):
    manifest = _pack(tmp_path / "W")
    files = [f["path"] for m in manifest["members"] for f in m["files"]]
    assert ps.top_level_absent(manifest, files) == ""
    assert ps.top_level_absent(manifest, files[1:]) == f"{TOP}_DEMO ASSY_revB.pdf"
    other = tmp_path / "W" / f"{TOP} rev C.pdf"         # a hand-made pack names its GA its own way
    other.write_text("x")
    assert ps.top_level_absent(manifest, files[1:] + [str(other)]) == ""


def test_a_pack_a_person_made_is_read_as_it_stands(tmp_path):
    manifest = _pack(tmp_path / "W")
    hand = tmp_path / "store" / "TTI" / TOP
    hand.mkdir(parents=True)
    (hand / "my own.dxf").write_text("x")
    (hand / "notes.txt").write_text("x")
    kept = ps.store(manifest, "TTI", root=tmp_path / "store")
    assert kept["state"] == "kept by hand"
    assert [Path(p).name for p in ps.stored_files(kept, manifest)] == ["my own.dxf"]


# ── the batch ─────────────────────────────────────────────────────────────────────────────
D = "TTI-10234"


def _batch(tmp_path, monkeypatch, portal):
    sheet = tmp_path / "tracker.xlsx"
    if not sheet.exists():
        _tracker(tmp_path, [(D, "Counter", "", "", 4)])
        _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    return tp.run_batch(_args(sheet, drawings_only=True), portal=portal, status_path=None,
                        sleep=lambda s: None)["rows"][0]


def test_a_row_whose_saved_pack_lost_a_file_is_sent_with_the_file_back_in_it(tmp_path, monkeypatch):
    first = FakePortal()
    _batch(tmp_path, monkeypatch, first)
    sent = [Path(p) for p in first.started[0]["files"]]
    assert sent and all(p.is_file() for p in sent)
    sent[0].unlink()
    portal = FakePortal()
    row = _batch(tmp_path, monkeypatch, portal)
    assert row["kept"]["state"] == "restored" and row["kept"]["restored"] == [sent[0].name]
    assert all(Path(p).is_file() for p in portal.started[0]["files"])


def test_a_row_whose_pack_cannot_be_made_whole_is_held_and_nothing_is_sent(tmp_path, monkeypatch):
    first = FakePortal()
    _batch(tmp_path, monkeypatch, first)
    folder = Path(first.started[0]["files"][0]).parent
    real = ps.store

    def lossy(manifest, client, *a, **k):               # the store says it is all there; it is not
        out = real(manifest, client, *a, **k)
        for p in folder.glob("*.pdf"):
            p.unlink()
        return out
    monkeypatch.setattr(ps, "store", lossy)
    portal = FakePortal()
    row = _batch(tmp_path, monkeypatch, portal)
    assert portal.started == [] and row["state"] == "held: pack not complete"
    assert "Nothing is queued" in row["why"] and ".pdf" in row["why"]

    def broken(*a, **k):
        raise OSError("the share went away")
    monkeypatch.setattr(ps, "store", broken)
    row = _batch(tmp_path, monkeypatch, portal)
    assert portal.started == [] and row["state"] == "held: pack not complete" and "share went away" in row["why"]
