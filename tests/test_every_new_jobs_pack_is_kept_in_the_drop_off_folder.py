"""EVERY NEW JOB'S DRAWING PACK IS ALSO KEPT IN THE DROP-OFF FOLDER (JG and the reviewer, 12 Nov 2026).

    <drop-off>\\<client>\\<drawing> - <job title>\\  the pack the estimate was given + pack_manifest.json

Client and job folders are made when missing. It is the exact staged pack. Sub-folders keep
their place. An unchanged pack is reused; a changed one is a new version beside the earlier
one. The manifest records sources, revisions, fingerprints, runs and what is missing or
unread. The folder, or the failure, is said in the run log and the covering note.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "src"))

import pack_dropoff as D  # noqa: E402
import pack_used  # noqa: E402

NAMES = ("12345-01-GA_revB.pdf", "12345-01-01M.DXF", "12345-01-02M.SLDPRT", "Layout notes.pdf")


def _staged(tmp_path):
    s = tmp_path / "staging" / "A Customer" / "12345-01-GA"
    (s / "sheets").mkdir(parents=True)
    for n in NAMES + ("CONCEPT_DOCUMENT.json", "ENQUIRY_BRIEF.txt"):
        (s / n).write_text(n)
    (s / "sheets" / "12345-01-01M.DXF").write_text("a second file of the same name")
    (s / "pack_manifest.json").write_text(json.dumps({
        "status": "provisional", "references_read": True, "missing": ["12345-01-09M"],
        "unread_assemblies": ["12345-01-SA01"]}))
    return s


def _drop(tmp_path, monkeypatch):
    d = tmp_path / "repo" / "chatgptdropoff"
    d.mkdir(parents=True)
    monkeypatch.delenv("SDI_PACK_DROPOFF_DIR", raising=False)
    return d


def _save(tmp_path, staged, **kw):
    kw.setdefault("run_id", "run000000001")
    kw.setdefault("title", "TV Wall Speaker Version")
    return D.save(staged, "A Customer", "12345-01-GA", tmp_path / "repo", **kw)


def test_client_and_job_folders_are_made_and_hold_the_exact_staged_pack(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    got = _save(tmp_path, _staged(tmp_path))
    dest = drop / "A Customer" / "12345-01-GA - TV Wall Speaker Version"
    assert got["saved"] and got["state"] == "new" and Path(got["folder"]) == dest
    kept = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert kept == sorted(NAMES + ("sheets/12345-01-01M.DXF", "pack_manifest.json"))
    assert (dest / "sheets" / "12345-01-01M.DXF").read_text() == "a second file of the same name"
    assert (dest / "12345-01-01M.DXF").read_text() == "12345-01-01M.DXF", "same name, both kept"


def test_the_manifest_says_where_each_file_came_from_and_what_the_pack_lacks(tmp_path, monkeypatch):
    _drop(tmp_path, monkeypatch)
    got = _save(tmp_path, _staged(tmp_path),
                sources={"12345-01-ga_revb.pdf": r"\\share\Design\A\12345-01-GA_revB.pdf"},
                revision_of=lambda n: "B" if "revB" in n else "")
    m = json.loads((Path(got["folder"]) / "pack_manifest.json").read_text())
    ga = next(f for f in m["files"] if f["name"] == "12345-01-GA_revB.pdf")
    assert ga["source_path"].endswith("12345-01-GA_revB.pdf") and ga["revision"] == "B"
    assert len(ga["sha256"]) == 64 and ga["size"] > 0
    assert m["runs"][0]["run_id"] == "run000000001" and m["version"] == 1
    assert m["missing"] == ["12345-01-09M"] and m["unread_assemblies"] == ["12345-01-SA01"]
    assert m["parts_list_read"] is True and m["client"] == "A Customer"


def test_an_unchanged_pack_is_reused_and_the_new_run_is_added(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    s = _staged(tmp_path)
    first = _save(tmp_path, s)
    again = _save(tmp_path, s, run_id="run000000002")
    assert again["state"] == "unchanged" and again["folder"] == first["folder"]
    assert [p.name for p in (drop / "A Customer").iterdir()] == ["12345-01-GA - TV Wall Speaker Version"]
    runs = json.loads((Path(first["folder"]) / "pack_manifest.json").read_text())["runs"]
    assert [r["run_id"] for r in runs] == ["run000000001", "run000000002"]


def test_a_changed_pack_is_a_new_version_and_the_earlier_pack_is_untouched(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    s = _staged(tmp_path)
    first = _save(tmp_path, s)
    (s / "12345-01-GA_revB.pdf").write_text("a later issue")
    (s / "12345-01-02M.SLDPRT").unlink()
    second = _save(tmp_path, s, run_id="run000000002", title="A different title")
    assert second["state"] == "new version" and second["version"] == 2
    assert Path(second["folder"]).name == "12345-01-GA - TV Wall Speaker Version v2", "the job keeps its name"
    assert (Path(first["folder"]) / "12345-01-GA_revB.pdf").read_text() == "12345-01-GA_revB.pdf"
    assert (Path(first["folder"]) / "12345-01-02M.SLDPRT").exists()
    m = json.loads((Path(second["folder"]) / "pack_manifest.json").read_text())
    assert m["earlier_versions"] == ["12345-01-GA - TV Wall Speaker Version"]
    back = _save(tmp_path, _staged(tmp_path / "again"), run_id="run000000003")
    assert back["state"] == "unchanged" and back["folder"] == first["folder"], "the first pack again is the first pack"
    assert len(list((drop / "A Customer").iterdir())) == 2


def test_another_job_whose_number_starts_the_same_is_not_this_job(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    s = _staged(tmp_path)
    _save(tmp_path, s)
    D.save(s, "A Customer", "12345-01-GA2", tmp_path / "repo", run_id="r2")
    assert sorted(p.name for p in (drop / "A Customer").iterdir()) == [
        "12345-01-GA - TV Wall Speaker Version", "12345-01-GA2"]


def test_a_machine_with_no_drop_off_folder_keeps_none_and_none_is_made(tmp_path, monkeypatch):
    monkeypatch.delenv("SDI_PACK_DROPOFF_DIR", raising=False)
    got = _save(tmp_path, _staged(tmp_path))
    assert not got["saved"] and "no drop-off folder" in got["why"] and D.said(got) == ""
    assert not (tmp_path / "repo").exists()


def test_it_can_be_pointed_elsewhere_or_switched_off(tmp_path, monkeypatch):
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", str(other))
    assert _save(tmp_path, _staged(tmp_path))["saved"]
    assert (other / "A Customer").is_dir()
    monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", "off")
    assert D.root(tmp_path / "repo") is None


def test_a_copy_that_fails_never_stops_the_job_and_is_said_plainly(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    (drop / "A Customer").write_text("a file where the client folder should be")
    got = _save(tmp_path, _staged(tmp_path))
    assert got["saved"] is False and got["why"]
    assert D.said(got).startswith("WARNING: the review copy of this pack was NOT saved")


def test_the_note_names_the_drop_off_folder_or_flags_the_failure(tmp_path):
    record = {"job_folder": str(tmp_path),
              "cad_inputs": {"folder": str(tmp_path), "read": ["12345-01-GA_revB.pdf"]}}
    ok = {"saved": True, "folder": r"C:\ClaudeVision\chatgptdropoff\TTI\11896-02-01-GA", "state": "new", "files": 4}
    (tmp_path / "PACK_DROPOFF.json").write_text(json.dumps(dict(ok, said=D.said(ok))))
    assert pack_used._drop_off_beside(record)["saved"] is True
    s = pack_used.section(record)
    assert r"chatgptdropoff\TTI\11896-02-01-GA" in s["text"] and "chatgptdropoff" in s["html"]
    bad = {"saved": False, "why": "PermissionError: denied"}
    (tmp_path / "PACK_DROPOFF.json").write_text(json.dumps(dict(bad, said=D.said(bad))))
    s = pack_used.section(record)
    assert "NOT saved to the drop-off folder" in s["text"] and "NOT saved" in s["html"]


def test_the_note_section_is_really_exercised_by_the_test_above(tmp_path):
    """Guard: the conditional asserts above must not pass by the section being empty."""
    record = {"job_folder": str(tmp_path),
              "cad_inputs": {"folder": str(tmp_path), "read": ["12345-01-GA_revB.pdf"]}}
    assert pack_used.gather(record)["rows"], "the record shape used above yields rows"


def test_one_call_serves_the_page_self_running_and_tti_after_the_run_exists():
    src = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    call = src.index('_run_log_drop_off(run, folder, client, drawing, str(req.job_title or ""), _sources,')
    assert src.index("run = Run(run_id=uuid.uuid4().hex[:12], client=client, drawing_number=drawing,") < call, \
        "the run id is known, so the manifest can name it"
    assert src.index('_pack_manifest = Path(folder) / "pack_manifest.json"') < call
    assert "job_title: Optional[str] = None" in src
    tti = (ROOT / "src" / "tti_pricer.py").read_text(encoding="utf-8")
    assert "--server" in tti, "a TTI batch queues through the service, so it is covered by the same call"


def test_the_suite_never_writes_into_the_checkouts_own_drop_off():
    assert 'monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", "off")' in (ROOT / "tests" / "conftest.py").read_text()


def test_client_folders_under_the_drop_off_are_never_committed():
    out = subprocess.run(["git", "check-ignore", "chatgptdropoff/A Customer/12345-01-GA/x.SLDPRT"],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, "drawings are customer data"


# ── through the service, as a job is queued ─────────────────────────────────────────────

import pytest  # noqa: E402


@pytest.fixture()
def er(monkeypatch, tmp_path):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    import estimate_routes
    estimate_routes._RUNS.clear()
    estimate_routes._RUNNERS.clear()
    monkeypatch.setattr(estimate_routes, "_other_local_services", lambda port: [])
    monkeypatch.setattr(estimate_routes.staging, "staging_root", lambda: tmp_path / "stage")
    monkeypatch.setattr(estimate_routes, "_within_a_root", lambda p: Path(p))
    monkeypatch.setattr(estimate_routes, "OUTPUT_ROOT", tmp_path / "out")
    monkeypatch.setattr(estimate_routes.config, "API_KEY", "portal-key", raising=False)
    estimate_routes._RUNNERS["LAPTOP-abc"] = estimate_routes.Runner(runner_id="LAPTOP-abc", hostname="LAPTOP")
    drop = tmp_path / "dropoff"
    drop.mkdir()
    monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", str(drop))
    return estimate_routes


def _queue(er, tmp_path, text=b"%PDF-1.4 the drawing"):
    src = tmp_path / "share" / "A Customer" / "12345-01-GA"
    src.mkdir(parents=True, exist_ok=True)
    (src / "12345-01-GA_revB.pdf").write_bytes(text)
    (src / "12345-01-01M_revA.pdf").write_bytes(b"%PDF-1.4 a part")
    return er.start(er.EstimateRequest(
        client="A Customer", drawing_number="12345-01-GA", units=1, job_folder=str(src),
        job_title="TV Wall Speaker Version", source="self_running",
        pack_manifest={"status": "provisional", "references_read": True, "missing": ["12345-01-09M"]}),
        x_sdi_key="portal-key")


def test_queueing_a_job_keeps_its_pack_names_the_run_and_says_so_in_the_log(er, tmp_path):
    out = _queue(er, tmp_path)
    run = er._RUNS[out["run_id"]]
    dest = tmp_path / "dropoff" / "A Customer" / "12345-01-GA - TV Wall Speaker Version"
    assert sorted(p.name for p in dest.iterdir()) == [
        "12345-01-01M_revA.pdf", "12345-01-GA_revB.pdf", "pack_manifest.json"]
    m = json.loads((dest / "pack_manifest.json").read_text())
    assert m["runs"][0]["run_id"] == out["run_id"] and m["missing"] == ["12345-01-09M"]
    ga = next(f for f in m["files"] if f["name"] == "12345-01-GA_revB.pdf")
    assert ga["revision"] == "B" and ga["source_path"].endswith("12345-01-GA_revB.pdf")
    assert "share" in ga["source_path"], "the path it was taken from, not the staged copy"
    assert any(l.startswith("Drop-off  Review copy of this pack") and str(dest) in l for l in run.log)
    note = json.loads((Path(run.job_folder) / "PACK_DROPOFF.json").read_text())
    assert note["saved"] is True and note["folder"] == str(dest)


def test_a_copy_that_fails_is_flagged_in_the_log_and_the_job_is_still_queued(er, tmp_path):
    (tmp_path / "dropoff" / "A Customer").write_text("a file where the client folder should be")
    out = _queue(er, tmp_path)
    run = er._RUNS[out["run_id"]]
    assert run.status == "queued"
    assert any("WARNING: the review copy of this pack was NOT saved" in l for l in run.log)
    assert json.loads((Path(run.job_folder) / "PACK_DROPOFF.json").read_text())["saved"] is False


# ── 13 Nov 2026: A COPY IS NOT CALLED COMPLETE UNLESS IT IS ────────────────────────────────
# Four packs were kept that night. Three lacked files the resolver had listed (IGS models),
# and nothing in the manifest said so: staging left .igs out as "not a drawing file" and the
# drop-off copied what was staged.
def _resolver_listing(staged: Path, *extra: str) -> None:
    files = [{"path": str(Path("//design/share/pack") / p.name)} for p in D._pack_files(staged)]
    files += [{"path": str(Path("//design/share/pack") / n)} for n in extra]
    (staged / D.MANIFEST).write_text(json.dumps(
        {"status": "complete", "members": [{"drawing": "12345-01-GA", "files": files}]}),
        encoding="utf-8")


def test_a_file_the_resolver_listed_that_is_not_in_the_copy_is_named_with_its_reason(tmp_path, monkeypatch):
    _drop(tmp_path, monkeypatch)
    s = _staged(tmp_path)
    _resolver_listing(s, "12345-01-07.IGS", "12345-01-08.igs")
    got = _save(tmp_path, s, left_out=[{"path": "//design/share/pack/12345-01-07.IGS",
                                        "reason": "not a drawing file (.IGS)"}])
    m = json.loads((Path(got["folder"]) / D.MANIFEST).read_text(encoding="utf-8"))
    absent = {a["name"]: a for a in m["not_in_this_copy"]}
    assert set(absent) == {"12345-01-07.IGS", "12345-01-08.igs"}
    assert absent["12345-01-07.IGS"]["reason"] == "not a drawing file (.IGS)"
    assert "no reason was recorded" in absent["12345-01-08.igs"]["reason"]
    assert m["complete"] is False and "2 file(s)" in m["incomplete_because"][0]
    assert "NOT A COMPLETE PACK" in D.said(got)


def test_a_copy_holding_everything_the_resolver_listed_is_complete_and_says_nothing_more(tmp_path, monkeypatch):
    """The contrasting case: the same pack with nothing left out."""
    _drop(tmp_path, monkeypatch)
    s = _staged(tmp_path)
    _resolver_listing(s)
    got = _save(tmp_path, s)
    m = json.loads((Path(got["folder"]) / D.MANIFEST).read_text(encoding="utf-8"))
    assert m["complete"] is True and m["not_in_this_copy"] == [] and m["incomplete_because"] == []
    assert "NOT A COMPLETE PACK" not in D.said(got)


def test_an_unread_assembly_or_a_missing_drawing_is_not_a_complete_pack_either(tmp_path, monkeypatch):
    _drop(tmp_path, monkeypatch)
    s = _staged(tmp_path)
    (s / D.MANIFEST).write_text(json.dumps({"status": "partial", "members": [],
                                            "missing": ["12345-01-15A"],
                                            "unread_assemblies": ["SA01", "SA02"]}), encoding="utf-8")
    got = _save(tmp_path, s)
    m = json.loads((Path(got["folder"]) / D.MANIFEST).read_text(encoding="utf-8"))
    assert m["complete"] is False
    assert any("not found" in b for b in m["incomplete_because"])
    assert any("2 assembly" in b for b in m["incomplete_because"])


def test_each_file_says_whether_the_engine_reads_that_kind_of_file():
    assert D.engine_use("a.pdf") == "read by the engine"
    assert D.engine_use("a.SLDASM") == "read through SolidWorks"
    assert "does not read" in D.engine_use("a.igs") and "does not read" in D.engine_use("a.STEP")
    assert "supporting file" in D.engine_use("notes.txt")


def test_the_drop_offs_idea_of_what_is_read_is_the_engines_own():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import cad_inputs as C
    read = {k for k, v in D._ENGINE.items()}
    assert read == set(C.READ_NATIVELY) | set(C.READ_BY_SOLIDWORKS) | set(C.CONVERTIBLE)
    assert D._KEPT_NOT_READ == set(C.KNOWN_UNREAD)


def test_an_igs_model_is_staged_with_its_pack_like_a_step(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"))
    import staging as S
    src = tmp_path / "src"
    src.mkdir()
    for n in ("70001-01-GA.pdf", "70001-01-01.IGS", "70001-01-02.iges", "70001-01-03.step",
              "notes.xyz"):
        (src / n).write_bytes(b"x")
    found, skipped = S._expand([str(src)])
    names = {p.name for p in found}
    assert {"70001-01-01.IGS", "70001-01-02.iges", "70001-01-03.step"} <= names
    assert [Path(p).name for p, _why in skipped] == ["notes.xyz"], "the contrasting file is still left, and said"


def test_what_staging_left_is_handed_to_the_drop_off():
    code = (Path(__file__).resolve().parents[1] / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
    assert 'left_out=list((staged or {}).get("skipped") or [])' in code


def test_a_selection_of_nothing_but_igs_models_is_still_nothing_to_estimate(tmp_path, monkeypatch):
    """Carried with a pack, never a reason to run one: the refusal that stood before stands."""
    import pytest
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"))
    import staging as S
    monkeypatch.setenv("SDI_STAGING_ROOT", str(tmp_path / "stage"))
    src = tmp_path / "only models"
    src.mkdir()
    (src / "70002-01-01.igs").write_bytes(b"x")
    with pytest.raises(S.StagingError) as got:
        S.stage([str(src)], client="A Customer", drawing="70002-01-GA")
    assert "the engine can read" in str(got.value) and "70002-01-01.igs" in str(got.value)
