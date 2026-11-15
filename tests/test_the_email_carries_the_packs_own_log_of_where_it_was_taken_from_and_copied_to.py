"""THE E-MAIL CARRIES THE PACK'S OWN LOG (JG, 15 Nov 2026).

"we need to have all the logs in the html mail file - where they're specifically copied from - as
well as the actual copying of the files themselves and the identification of drawings that we
would ideally have."

Before this a tracker estimate's e-mail said "No pack manifest was saved with this job": the batch
never sent the pack's record with the job, so the e-mail could not say where a file came from,
where it was copied to, or what the drawings call for that was not found.
"""
from __future__ import annotations

import html as _html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pack_store as ps  # noqa: E402
import pack_used as pu  # noqa: E402
import tti_pricer as tp  # noqa: E402
from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _areas, _args  # noqa: E402
from test_the_tracker_batch_runs_the_rows_named_on_their_own_briefs_and_never_lists_the_share_in_silence import _tracker  # noqa: E402

TOP = "12736-00-01"


def _text(h):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


def _manifest(tmp_path):
    members = []
    for drawing, sub, name in ((TOP, "12736-00 General Assemblies", f"{TOP}_DEMO ASSY_revB.pdf"),
                               ("12736-01-101", "12736-01 Frame", "12736-01-101_Frame_revB.pdf")):
        f = tmp_path / "W" / "Prototype" / sub / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(drawing)
        members.append({"drawing": drawing, "revision": "B",
                        "files": [{"path": str(f), "format": "pdf", "fingerprint": name}]})
    return {"drawing": TOP, "client": "TTI", "status": "provisional", "members": members,
            "missing": ["12736-04-01M"], "discovery": "Design: 1 folder, no drawing files; Prototype: 3 folders",
            "taken_from": {"area": "prototype", "folder": str(tmp_path / "W" / "Prototype")}}


def _record(names):
    return {"run_id": "run1", "cad_inputs": {"read": list(names)}}


def test_the_block_says_where_it_looked_where_each_file_came_from_and_where_the_copy_went(tmp_path):
    m = _manifest(tmp_path)
    ps.store(m, "TTI", root=tmp_path / "K")
    kept = ps.store(m, "TTI", root=tmp_path / "K")                    # the run's own copy: v2
    m = dict(m, stored=kept)
    names = [Path(f["path"]).name for mm in m["members"] for f in mm["files"]]
    out = pu.section(_record(names), m)
    page, mail = _text(out["html"]), out["text"]
    for body in (page, mail):
        assert "Design: 1 folder, no drawing files; Prototype: 3 folders" in body
        assert f"Taken from the prototype area: {tmp_path / 'W' / 'Prototype'}" in body
        assert f"Copied to: {kept['folder']} (version 2), 2 file(s), at {kept['at']}" in body
        assert "copied from the drawing area again for this run" in body.lower()
        assert f"The copy before this one is kept, unaltered: {kept['previous']}" in body
        assert "The files came from 2 folders" in body
        assert "Drawings we would ideally have" in body and "12736-04-01M" in body
        assert str(tmp_path / "W" / "Prototype" / "12736-00 General Assemblies") in body
    assert "Copied from" in page and "COPIED FROM" in mail
    assert "No pack manifest was saved" not in page


def test_a_file_found_for_the_pack_and_not_given_to_the_run_is_named_in_red(tmp_path):
    m = _manifest(tmp_path)
    m = dict(m, stored=ps.store(m, "TTI", root=tmp_path / "K"))
    out = pu.section(_record(["12736-01-101_Frame_revB.pdf"]), m)        # the top-level PDF never arrived
    assert pu.NOT_PROVED in out["html"]
    assert f"FOUND FOR THE PACK AND NOT GIVEN TO THIS RUN (1): {TOP}_DEMO ASSY_revB.pdf" in _text(out["html"])
    whole = pu.section(_record([f"{TOP}_DEMO ASSY_revB.pdf", "12736-01-101_Frame_revB.pdf"]), m)
    assert "FOUND FOR THE PACK AND NOT GIVEN" not in whole["html"]


def test_a_run_with_no_pack_record_still_says_so(tmp_path):
    out = pu.section(_record(["a.pdf"]), {})
    assert "No pack manifest was saved with this job" in out["html"] and "Where this pack was taken from" not in out["html"]


def test_the_tracker_batch_sends_the_packs_record_with_the_job(tmp_path, monkeypatch):
    _tracker(tmp_path, [("TTI-10234", "Counter", "", "", 4)])
    _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    portal = FakePortal()
    tp.run_batch(_args(tmp_path / "tracker.xlsx", drawings_only=True), portal=portal, status_path=None,
                 sleep=lambda s: None)
    sent = portal.started[0]["pack_manifest"]
    assert sent["staged_from"] == "the TTI tracker batch" and sent["stored"]["state"] == "new"
    copies = sent["stored"]["copies"]
    assert copies and all(Path(c["from"]).is_dir() for c in copies)
    assert {c["file"] for c in copies} == {Path(p).name for p in portal.started[0]["files"]}
    assert str(sent["taken_from"]["folder"]) in {c["from"] for c in copies}


def test_a_pack_a_person_made_is_used_on_a_one_job_run_and_passed_over_by_a_batch(tmp_path):
    m = _manifest(tmp_path)
    hand = tmp_path / "K" / "TTI" / TOP
    hand.mkdir(parents=True)
    (hand / "my own.dxf").write_text("x")
    one = ps.store(m, "TTI", root=tmp_path / "K", honour_hand_made=True)
    assert one["state"] == "kept by hand" and one["folder"] == str(hand)
    batch = ps.store(m, "TTI", root=tmp_path / "K", honour_hand_made=False)
    assert Path(batch["folder"]).name == f"{TOP} v2" and batch["copied"] == 2
    assert sorted(p.name for p in hand.iterdir()) == ["my own.dxf"], "the hand-made folder was touched"
