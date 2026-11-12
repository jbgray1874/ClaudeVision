"""The resolver's pack is checked against the Live Enquiry folder each job ran from (JG, 11 Nov 2026).

11896-04-00-GA's folder held the GA level only (assemblies, GA drawings) and none of its parts,
so every metal part ran with no gauge. A folder a person put together is the reference: a file
it holds that the resolver does not gather is a fault. A folder the resolver made shows what an
earlier run was given. Synthetic folders; no job's files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_compare as pc  # noqa: E402


def _touch(p: Path, size: int = 10) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p


def _manifest(*files, status="verified"):
    return {"status": status, "members": [{"drawing": "m", "files": [{"path": f"W:/x/{n}", "size": s}
                                                                      for n, s in files]}],
            "missing": [], "question": ""}


def test_a_persons_pack_shows_what_the_resolver_misses_and_adds(tmp_path):
    job = tmp_path / "M&S" / "12674-02-GA"
    _touch(job / "12674-02-GA_REV A.pdf", 10)
    _touch(job / "12674-01-02J_REV B.pdf", 10)            # the shared panel the person added
    _touch(job / "dxf" / "12674-02-01J.DXF", 10)
    got = _manifest(("12674-02-GA_REV A.pdf", 10), ("12674-02-01J.dxf", 99), ("12674-02-03J_REV A.pdf", 10))
    rows = pc.run(tmp_path, resolve=lambda d, c: got)
    (r,) = rows
    assert r["made_by"] == "person" and r["drawing"] == "12674-02-GA" and r["client"] == "M&S"
    assert r["missed"] == ["12674-01-02j_rev b.pdf"]
    assert r["added"] == ["12674-02-03j_rev a.pdf"]
    assert r["different_copy"] == ["12674-02-01j.dxf"]
    assert pc.verdict(r).startswith("MISSES 1 file")


def test_a_resolver_made_folder_and_its_versions_are_each_compared(tmp_path):
    base = tmp_path / "TTI" / "11896-04-00-GA"
    _touch(base / "11896-04-00-GA.SLDASM")
    (base / "pack_manifest.json").write_text(json.dumps({"stored": {"at": "2026-11-10T08:09:00"}}))
    v2 = tmp_path / "TTI" / "11896-04-00-GA v2"
    _touch(v2 / "11896-04-00-GA.SLDASM")
    _touch(v2 / "11896-04-01-01M.SLDPRT")
    got = _manifest(("11896-04-00-GA.SLDASM", 10), ("11896-04-01-01M.SLDPRT", 10), ("11896-04-01-01M_1.5mm MS_RevG.DXF", 10))
    calls = []
    rows = pc.run(tmp_path, resolve=lambda d, c: calls.append(d) or got)
    assert [Path(r["folder"]).name for r in rows] == ["11896-04-00-GA", "11896-04-00-GA v2"]
    assert calls == ["11896-04-00-GA"], "one drawing is resolved once for all its versions"
    assert rows[0]["made_by"] == "resolver" and rows[0]["made_at"] == "2026-11-10T08:09:00"
    assert len(rows[0]["added"]) == 2 and pc.verdict(rows[0]).startswith("now finds 2 more")
    assert rows[1]["made_by"] == "person"


def test_one_drawing_or_client_can_be_asked_for(tmp_path):
    _touch(tmp_path / "TTI" / "A-1" / "A-1.pdf")
    _touch(tmp_path / "M&S" / "B-2" / "B-2.pdf")
    assert [r["drawing"] for r in pc.run(tmp_path, drawing="B-2", resolve=lambda d, c: _manifest())] == ["B-2"]
    assert [r["client"] for r in pc.run(tmp_path, client="tti", resolve=lambda d, c: _manifest())] == ["TTI"]


def test_a_resolver_failure_is_said_not_raised(tmp_path):
    _touch(tmp_path / "TTI" / "A-1" / "A-1.pdf")

    def boom(d, c):
        raise RuntimeError("no index")
    (r,) = pc.run(tmp_path, resolve=boom)
    assert r["resolver_status"] == "error" and "no index" in r["question"]
    assert pc.verdict(r) == "resolver found no pack"


def test_a_pack_copied_in_yesterday_counts_as_yesterdays_whatever_its_files_dates(tmp_path):
    import os
    from datetime import datetime
    f = _touch(tmp_path / "M&S" / "12773-01-GA" / "12773-01-GA_REV C.pdf")
    old = datetime(2026, 3, 1).timestamp()
    os.utime(f, (old, old))                                     # the date it had on W:
    rows = pc.run(tmp_path, since=datetime(2026, 11, 10), resolve=lambda d, c: _manifest())
    assert [r["drawing"] for r in rows] == ["12773-01-GA"]


def test_the_same_files_is_not_called_a_match_when_the_parts_list_was_never_read():
    """11896-04-00-GA "matched" its own earlier pack on zero drawings read (12 Nov 2026)."""
    import pack_compare as pc
    base = {"made_by": "resolver", "missed": [], "added": [], "resolver_status": "provisional"}
    assert "NOT PROVED" in pc.verdict(dict(base, parts_list_read=False, resolver_missing=[]))
    assert "INCOMPLETE" in pc.verdict(dict(base, parts_list_read=True, resolver_missing=["X-01-01M"]))
    assert pc.verdict(dict(base, parts_list_read=True, resolver_missing=[])).startswith("same files as the earlier")
    assert pc.verdict(dict(base, made_by="person", parts_list_read=True, resolver_missing=[])).startswith("matches")
