"""A KEPT PACK ANSWERS THREE QUESTIONS AND NEVER FOLDS THEM INTO ONE (JG, 13 Nov 2026).

Four packs were kept in the drop-off that night. Three lacked IGS files the pack resolver had
listed: staging left them as "not a drawing file" and the copy said nothing. JG's safeguards:

  1. "supported by the engine" is not "read on this run": the per-file field is intended
     handling; what a run read comes from that run's record, separately.
  2. an unread IGS is not harmless because nothing reads IGS: either a native model of the
     same component was read on the run, or that component's coverage is unresolved.
  3. source-pack completeness, copy completeness and read coverage are three answers.
  4. a kept copy is repaired by a previewed, versioned recovery from verified sources; the
     original evidence is preserved and no estimate is rerun.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
sys.path.insert(0, str(ROOT / "src"))

import pack_dropoff as D  # noqa: E402
import pack_resolver  # noqa: E402
import pack_used as U  # noqa: E402

KEPT = ("70001-01-GA_revB.pdf", "70001-01-01M.DXF", "70001-01-02M.SLDPRT", "70001-01-03M.SLDPRT")


def _print(p: Path) -> str:
    st = p.stat()
    return pack_resolver.fingerprint(p, st.st_size, st.st_mtime)


def _world(tmp_path, monkeypatch, absent=("70001-01-02M.IGS", "70001-01-09M.igs"), **resolver):
    """A design-share folder, the staged pack made from it (IGS left behind, as on the
    night), and a drop-off to keep it in."""
    design = tmp_path / "design"
    design.mkdir()
    for n in KEPT + tuple(absent):
        (design / n).write_text("content of " + n)
    staged = tmp_path / "staging" / "A Customer" / "70001-01-GA"
    staged.mkdir(parents=True)
    for n in KEPT:
        (staged / n).write_text("content of " + n)
    files = [{"path": str(design / n), "fingerprint": _print(design / n)} for n in KEPT + tuple(absent)]
    (staged / D.MANIFEST).write_text(json.dumps(dict(
        {"status": "complete", "references_read": True,
         "members": [{"drawing": "70001-01-GA", "files": files}]}, **resolver)), encoding="utf-8")
    (tmp_path / "repo" / "chatgptdropoff").mkdir(parents=True)
    monkeypatch.delenv("SDI_PACK_DROPOFF_DIR", raising=False)
    return design, staged


def _save(tmp_path, staged, **kw):
    kw.setdefault("run_id", "run000000001")
    return D.save(staged, "A Customer", "70001-01-GA", tmp_path / "repo", **kw)


def _manifest(got) -> dict:
    return json.loads((Path(got["folder"]) / D.MANIFEST).read_text(encoding="utf-8"))


# ── 3. three answers ───────────────────────────────────────────────────────────────────────
def test_what_was_found_what_was_copied_and_what_was_read_are_three_answers(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    got = _save(tmp_path, staged, left_out=[{"path": "x/70001-01-02M.IGS",
                                             "reason": "not a drawing file (.IGS)"}])
    c = _manifest(got)["completeness"]
    assert set(c) == {"source_pack", "copy", "read"}
    assert c["source_pack"]["state"] == "complete"
    assert c["copy"]["state"] == "incomplete" and "70001-01-02M.IGS" in c["copy"]["because"][0]
    assert c["read"]["state"].startswith("not recorded yet")
    assert "complete" not in {k for k in _manifest(got) if k != "completeness"}, \
        "one flag for three questions is the thing this replaces"
    assert "NOT SHOWN COMPLETE" in D.said(got)


def test_every_absent_file_is_named_with_its_reason_or_the_lack_of_one(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    got = _save(tmp_path, staged, left_out=[{"path": "x/70001-01-02M.IGS",
                                             "reason": "not a drawing file (.IGS)"}])
    absent = {a["name"]: a["reason"] for a in _manifest(got)["not_in_this_copy"]}
    assert absent["70001-01-02M.IGS"] == "not a drawing file (.IGS)"
    assert "no reason was recorded" in absent["70001-01-09M.igs"]


def test_keeping_every_gathered_file_does_not_make_the_source_pack_complete(tmp_path, monkeypatch):
    """Copy complete; source pack not: a drawing was never found and an assembly never read."""
    _design, staged = _world(tmp_path, monkeypatch, absent=(), missing=["70001-01-15A"],
                             unread_assemblies=["SA01", "SA02"])
    c = _manifest(_save(tmp_path, staged))["completeness"]
    assert c["copy"]["state"] == "complete"
    assert c["source_pack"]["state"] == "incomplete"
    assert any("70001-01-15A" in b for b in c["source_pack"]["because"])
    assert any("SA01" in b for b in c["source_pack"]["because"])


def test_with_no_resolver_manifest_source_completeness_is_not_established(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch, absent=())
    (staged / D.MANIFEST).unlink()
    c = _manifest(_save(tmp_path, staged))["completeness"]
    assert c["source_pack"]["state"] == "not established"
    assert c["copy"]["state"] == "complete", "the contrasting answer beside it"


def test_a_whole_pack_wholly_copied_says_so_and_nothing_more(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch, absent=())
    got = _save(tmp_path, staged)
    c = _manifest(got)["completeness"]
    assert c["source_pack"]["state"] == "complete" and c["copy"]["state"] == "complete"
    assert "NOT SHOWN COMPLETE" not in D.said(got)


# ── 1. intended handling is not evidence of a read ─────────────────────────────────────────
def test_the_per_file_field_is_intended_handling_not_a_claim_it_was_read(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    files = _manifest(_save(tmp_path, staged))["files"]
    assert all("intended_handling" in f and "engine" not in f for f in files)
    assert D.intended_handling("a.SLDASM") == "read through SolidWorks"
    assert "does not read" in D.intended_handling("a.igs")


def test_the_drop_offs_idea_of_each_kind_of_file_is_the_engines_own():
    import cad_inputs as C
    assert set(D._ENGINE) == set(C.READ_NATIVELY) | set(C.READ_BY_SOLIDWORKS) | set(C.CONVERTIBLE)
    assert D._KEPT_NOT_READ == set(C.KNOWN_UNREAD)
    assert set(U._KEPT_NOT_READ) == set(C.KNOWN_UNREAD)


def _record(staged: Path, failed=()):
    return {"run_id": "run000000001", "job_folder": str(staged),
            "cad_inputs": {"folder": str(staged),
                           "read": ["70001-01-GA_revB.pdf", "70001-01-01M.DXF"],
                           "solidworks": ["70001-01-02M.SLDPRT", "70001-01-03M.SLDPRT"]},
            "solidworks_native": {"extract_reader": "solidworks",
                                  "extract_errors": [{"path": n, "errors": ["open under the same title"]}
                                                     for n in failed]}}


def _kept_with_note(tmp_path, staged, **kw):
    got = _save(tmp_path, staged, **kw)
    (staged / "PACK_DROPOFF.json").write_text(json.dumps(got), encoding="utf-8")
    return got


def test_what_a_run_read_is_written_from_its_own_record_under_its_run_id(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    got = _kept_with_note(tmp_path, staged)
    before = _manifest(got)
    line = U.record_read_evidence_safely(_record(staged, failed=["70001-01-03M.SLDPRT"]))
    after = _manifest(got)
    ev = after["read_on_runs"]["run000000001"]
    state = {f["file"]: f["state"] for f in ev["files"]}
    assert state["70001-01-GA_revB.pdf"] == "read" and state["70001-01-02M.SLDPRT"] == "read"
    assert state["70001-01-03M.SLDPRT"] == "NOT READ"
    assert after["completeness"]["read"]["state"] == "incomplete"
    assert after["files"] == before["files"] and after["runs"] == before["runs"], \
        "the evidence is added; what was kept is not rewritten"
    assert "read coverage incomplete" in line


# ── 2. an unread IGS is covered only by a native model that was read ───────────────────────
def test_an_igs_is_covered_where_its_native_model_was_read_and_unresolved_where_not(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    ev = U.read_evidence(_record(staged), list(KEPT) + ["70001-01-02M.IGS", "70001-01-09M.igs"])
    by = {f["file"]: f for f in ev["files"]}
    assert by["70001-01-02M.IGS"]["state"] == "not read; covered"
    assert "70001-01-02M.SLDPRT" in by["70001-01-02M.IGS"]["why"]
    assert by["70001-01-09M.igs"]["state"] == "NOT READ; COVERAGE UNRESOLVED"
    assert "no native model" in by["70001-01-09M.igs"]["why"]
    assert ev["coverage_unresolved"] == ["70001-01-09M.igs"] and ev["state"] == "incomplete"


def test_a_native_model_that_failed_does_not_cover_its_igs(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    ev = U.read_evidence(_record(staged, failed=["70001-01-02M.SLDPRT"]), ["70001-01-02M.IGS"])
    f = ev["files"][0]
    assert f["state"] == "NOT READ; COVERAGE UNRESOLVED" and "open under the same title" in f["why"]


def test_a_drawing_of_the_same_number_is_said_but_is_not_the_model(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    ev = U.read_evidence(_record(staged), ["70001-01-01M.igs"])
    f = ev["files"][0]
    assert f["state"] == "NOT READ; COVERAGE UNRESOLVED"
    assert "70001-01-01M.DXF" in f["why"] and "not the model" in f["why"]


def test_a_file_the_runs_record_never_mentions_is_no_record_not_read(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    ev = U.read_evidence(_record(staged), ["a drawing nobody listed.pdf"])
    assert ev["files"][0]["state"] == "NO RECORD" and ev["state"] == "incomplete"


def test_every_file_read_or_covered_is_complete_read_coverage(tmp_path, monkeypatch):
    """The contrasting case."""
    _design, staged = _world(tmp_path, monkeypatch)
    ev = U.read_evidence(_record(staged), list(KEPT) + ["70001-01-02M.IGS"])
    assert ev["state"] == "complete" and not ev["not_read"] and not ev["coverage_unresolved"]


def test_no_review_copy_means_nothing_is_written_and_nothing_is_said(tmp_path):
    assert U.record_read_evidence_safely({"job_folder": str(tmp_path)}) == ""


def test_the_run_writes_its_read_evidence_when_it_writes_its_note():
    code = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert code.index("_pack_note(_note, summary)") < code.index("_read_ev(summary)")


# ── 4. recovery: previewed, verified, versioned, original untouched ────────────────────────
def _snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_a_preview_changes_nothing_and_says_what_it_would_do(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    got = _save(tmp_path, staged)
    before = _snapshot(tmp_path / "repo")
    plan = D.recovery_plan(got["folder"])
    assert _snapshot(tmp_path / "repo") == before
    assert plan["ok"] and {a["name"] for a in plan["add"]} == {"70001-01-02M.IGS", "70001-01-09M.igs"}
    assert plan["would_create"].endswith(" v2") and not Path(plan["would_create"]).exists()


def test_recovery_makes_a_new_version_and_leaves_the_original_and_its_evidence_alone(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    got = _kept_with_note(tmp_path, staged)
    U.record_read_evidence_safely(_record(staged))
    original = Path(got["folder"])
    before = _snapshot(original)
    done = D.recover(original)
    assert _snapshot(original) == before, "the original pack or its manifest was written to"
    new = Path(done["created"])
    m = json.loads((new / D.MANIFEST).read_text(encoding="utf-8"))
    assert {p.name for p in new.iterdir()} == set(KEPT) | {"70001-01-02M.IGS", "70001-01-09M.igs", D.MANIFEST}
    assert m["recovery"]["recovered_from"] == original.name and m["version"] == 2
    assert m["runs"] == json.loads(before[D.MANIFEST])["runs"]
    assert "run000000001" in m["read_on_runs"], "the original run's evidence travels with it"
    added = [f for f in m["files"] if f.get("recovered")]
    assert len(added) == 2 and all(f["given_to_runs"].startswith("no") for f in added)
    assert m["completeness"]["copy"]["state"] == "complete"
    assert "No estimate was rerun" in m["recovery"]["note"]


def test_a_source_that_changed_or_went_is_not_recovered_and_is_said(tmp_path, monkeypatch):
    design, staged = _world(tmp_path, monkeypatch)
    got = _save(tmp_path, staged)
    (design / "70001-01-02M.IGS").write_text("a later revision of this model")
    (design / "70001-01-09M.igs").unlink()
    plan = D.recovery_plan(got["folder"])
    why = {c["name"]: c["why"] for c in plan["cannot"]}
    assert not plan["ok"] and not plan["add"]
    assert "changed since the pack was gathered" in why["70001-01-02M.IGS"]
    assert "not there now" in why["70001-01-09M.igs"]


def test_one_verified_and_one_not_recovers_the_one_and_keeps_naming_the_other(tmp_path, monkeypatch):
    design, staged = _world(tmp_path, monkeypatch)
    got = _save(tmp_path, staged)
    (design / "70001-01-09M.igs").unlink()
    done = D.recover(got["folder"])
    m = json.loads((Path(done["created"]) / D.MANIFEST).read_text(encoding="utf-8"))
    assert m["recovery"]["added"] == ["70001-01-02M.IGS"]
    assert [a["name"] for a in m["not_in_this_copy"]] == ["70001-01-09M.igs"]
    assert m["completeness"]["copy"]["state"] == "incomplete"


def test_a_kept_file_that_no_longer_matches_its_checksum_stops_recovery(tmp_path, monkeypatch):
    _design, staged = _world(tmp_path, monkeypatch)
    got = _save(tmp_path, staged)
    (Path(got["folder"]) / KEPT[0]).write_text("edited in the drop-off")
    plan = D.recovery_plan(got["folder"])
    assert not plan["ok"] and "no longer matches its recorded checksum" in plan["why"]


def test_a_pack_kept_before_this_change_can_still_be_recovered(tmp_path, monkeypatch):
    """Tonight's four packs: their manifests carry the resolver's listing but none of the
    new fields."""
    _design, staged = _world(tmp_path, monkeypatch)
    got = _save(tmp_path, staged)
    path = Path(got["folder"]) / D.MANIFEST
    old = json.loads(path.read_text(encoding="utf-8"))
    for k in ("completeness", "not_in_this_copy", "read_on_runs"):
        old.pop(k)
    for f in old["files"]:
        f.pop("intended_handling")
    path.write_text(json.dumps(old), encoding="utf-8")
    plan = D.recovery_plan(got["folder"])
    assert plan["ok"] and len(plan["add"]) == 2


def test_the_tool_previews_unless_told_to_apply(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / "tools"))
    import dropoff_recover as T
    _design, staged = _world(tmp_path, monkeypatch)
    got = _save(tmp_path, staged)
    before = _snapshot(tmp_path / "repo")
    assert T.main([got["folder"]]) == 0
    assert _snapshot(tmp_path / "repo") == before and "PREVIEW ONLY" in capsys.readouterr().out
    assert T.main([got["folder"], "--apply"]) == 0
    assert "CREATED" in capsys.readouterr().out


# ── and the cause: IGS models travel with the pack ─────────────────────────────────────────
def test_an_igs_model_is_staged_with_its_pack_and_an_unknown_file_is_still_left_and_said(tmp_path):
    import staging as S
    src = tmp_path / "src"
    src.mkdir()
    for n in ("70001-01-GA.pdf", "70001-01-01.IGS", "70001-01-02.iges", "notes.xyz"):
        (src / n).write_bytes(b"x")
    found, skipped = S._expand([str(src)])
    assert {"70001-01-01.IGS", "70001-01-02.iges"} <= {p.name for p in found}
    assert [Path(p).name for p, _why in skipped] == ["notes.xyz"]


def test_a_selection_of_nothing_but_igs_models_is_still_nothing_to_estimate(tmp_path):
    import staging as S
    src = tmp_path / "only models"
    src.mkdir()
    (src / "70002-01-01.igs").write_bytes(b"x")
    with pytest.raises(S.StagingError) as got:
        S.stage([str(src)], client="A Customer", drawing="70002-01-GA")
    assert "the engine can read" in str(got.value) and "70002-01-01.igs" in str(got.value)


def test_what_staging_left_is_handed_to_the_drop_off():
    code = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
    assert 'left_out=list((staged or {}).get("skipped") or [])' in code
