"""EVERY AUTOMATIC E-MAIL AND EVERY FILED COVERING NOTE SHOWS THE DRAWING PACK THE RUN WAS
GIVEN (JG, 13 Nov 2026).

"Near the top, show an accessible link to the exact pack supplied to that run, its version /
run ID, the file list and revisions, actual read outcomes, and unresolved gaps. A recovered
review pack must be labelled separately, not presented as what the earlier estimate used.
Please test both email outputs, not just the manifest. Also, matching a drawing number alone
must not establish equivalent model coverage where revisions or configurations differ."

These tests queue a job through the service's one queueing place, have the engine's own code
write the covering note, and then read the two things a person receives: the body the mail
service is handed, and the note filed on disk (HTML and its plain-text sibling).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "src"))

import pack_dropoff  # noqa: E402
import pack_link  # noqa: E402
import pack_used  # noqa: E402

PORTAL = "https://portal.example.test"


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
    (tmp_path / "dropoff").mkdir()
    monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", str(tmp_path / "dropoff"))
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SDI_PORTAL_URL", PORTAL)
    return estimate_routes


FILES = ("70001-01-GA_revB.pdf", "70001-01-01M_revA.dxf", "70001-01-02M_revC.SLDPRT",
         "70001-01-02M_revC.igs", "70001-01-03M_revA.igs", "70001-01-03M_revB.SLDPRT")


def _queue(er, tmp_path, source="self_running", **manifest):
    src = tmp_path / "share" / "A Customer" / "70001-01-GA"
    src.mkdir(parents=True, exist_ok=True)
    for n in FILES:
        (src / n).write_bytes(b"%PDF-1.4 " + n.encode())
    out = er.start(er.EstimateRequest(
        client="A Customer", drawing_number="70001-01-GA", units=1, job_folder=str(src),
        job_title="A Display", source=source,
        pack_manifest=dict({"status": "provisional", "references_read": True,
                            "missing": ["70001-01-15A"], "unread_assemblies": ["SA01", "SA02"]},
                           **manifest)), x_sdi_key="portal-key")
    return er._RUNS[out["run_id"]]


def _engine_writes_its_note(run, tmp_path, failed=()):
    """What src/main.py does at the end of a run: the covering note with the pack section,
    filed as HTML and plain text."""
    record = {"run_id": run.run_id, "job_folder": run.job_folder,
              "cad_inputs": {"folder": run.job_folder,
                             "read": ["70001-01-GA_revB.pdf", "70001-01-01M_revA.dxf"],
                             "solidworks": ["70001-01-02M_revC.SLDPRT", "70001-01-03M_revB.SLDPRT"],
                             "unread": ["70001-01-02M_revC.igs", "70001-01-03M_revA.igs"]},
              "solidworks_native": {"extract_reader": "solidworks",
                                    "extract_errors": [{"path": n, "errors": ["could not be opened"]} for n in failed]}}
    note = pack_used.into_note_safely(
        {"subject": "SDI estimate 70001-01-GA", "html": "<div><p>The estimate.</p></div>",
         "text": "The estimate.\n"}, record)
    pack_used.record_read_evidence_safely(record)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    path = out / "70001-01-GA_covering_email.html"
    path.write_text(f"<!-- subject: {note['subject']} -->\n{note['html']}", encoding="utf-8")
    path.with_suffix(".txt").write_text(note["text"], encoding="utf-8")
    return [{"name": path.name, "path": str(path), "what": "covering note"}]


def _the_email(er, run, deliverables, monkeypatch):
    sent = {}

    def send(recipients, subject, html, text, paths):
        sent.update(to=recipients, subject=subject, html=html, text=text)
        return {"sent": True}
    monkeypatch.setattr(er.estimate_email, "send", send)
    er._email_finished_run(run.as_json(), deliverables, ["someone@example.test"], False, True)
    return sent


def _the_filed_note(er, run, deliverables):
    pack_link.stamp_note_files([d["path"] for d in deliverables], run.as_json())
    p = Path(deliverables[0]["path"])
    return p.read_text(encoding="utf-8"), p.with_suffix(".txt").read_text(encoding="utf-8")


def _both_outputs(er, tmp_path, monkeypatch, **kw):
    run = _queue(er, tmp_path, **{k: v for k, v in kw.items() if k != "failed"})
    deliverables = _engine_writes_its_note(run, tmp_path, failed=kw.get("failed", ()))
    mail = _the_email(er, run, deliverables, monkeypatch)
    html, text = _the_filed_note(er, run, deliverables)
    return run, [("the e-mail", mail["html"], mail["text"]), ("the filed note", html, text)]


def test_both_carry_a_link_that_is_not_a_laptop_path_to_the_pack_kept_for_this_run(er, tmp_path, monkeypatch):
    run, outputs = _both_outputs(er, tmp_path, monkeypatch)
    assert run.pack_token
    link = f"{PORTAL}/estimating/pack/{run.pack_token}"
    for which, html, text in outputs:
        assert link in html, which
        assert link in text, which
        assert html.index("Drawing pack used for this estimate") < html.index("The estimate."), \
            f"{which}: the section is not near the top"
    rec = pack_link.load(run.pack_token)
    assert rec["run_id"] == run.run_id and rec["version"] == 1
    assert Path(rec["folder"]).parent.parent == tmp_path / "dropoff"


def test_both_name_the_run_and_the_pack_version(er, tmp_path, monkeypatch):
    run, outputs = _both_outputs(er, tmp_path, monkeypatch)
    for which, html, text in outputs:
        assert f"Run {run.run_id} · pack version 1" in html, which
        assert f"Run {run.run_id} · pack version 1" in text, which


def test_both_list_each_file_with_its_drawing_number_revision_and_format(er, tmp_path, monkeypatch):
    _run, outputs = _both_outputs(er, tmp_path, monkeypatch)
    for which, html, text in outputs:
        for n in FILES:
            assert n in html and n in text, (which, n)
        assert "70001-01-GA  |  rev B  |  PDF" in text, which
        assert "70001-01-02M  |  rev C  |  SLDPRT" in text, which
        for head in ("Drawing", "Rev", "Format", "On this run"):
            assert f">{head}</th>" in html, (which, head)


def test_both_say_what_was_read_what_is_supporting_and_what_was_not_read(er, tmp_path, monkeypatch):
    _run, outputs = _both_outputs(er, tmp_path, monkeypatch, failed=["70001-01-03M_revB.SLDPRT"])
    for which, _html, text in outputs:
        lines = {l.split("  |  ")[0].strip(): l for l in text.splitlines() if "  |  " in l}
        assert lines["70001-01-GA_revB.pdf"].endswith("read"), which
        assert "NOT READ - could not be opened" in lines["70001-01-03M_revB.SLDPRT"], which
        assert "not read; covered" in lines["70001-01-02M_revC.igs"], which
        assert "NOT READ; COVERAGE UNRESOLVED" in lines["70001-01-03M_revA.igs"], which


def test_both_show_missing_references_unread_assemblies_and_the_warning(er, tmp_path, monkeypatch):
    _run, outputs = _both_outputs(er, tmp_path, monkeypatch)
    for which, html, text in outputs:
        for words in ("PACK COMPLETENESS NOT PROVED", "70001-01-15A", "SA01", "SA02"):
            assert words in html and words in text, (which, words)


def test_a_pack_with_nothing_open_carries_no_warning(er, tmp_path, monkeypatch):
    """The contrasting case: same job, nothing missing, every model read as the same issue."""
    run = _queue(er, tmp_path, missing=[], unread_assemblies=[])
    record_files = [n for n in FILES if "03M" not in n]
    record = {"run_id": run.run_id, "job_folder": run.job_folder,
              "cad_inputs": {"folder": run.job_folder, "read": record_files[:2],
                             "solidworks": [record_files[2]], "unread": [record_files[3]]},
              "solidworks_native": {"extract_reader": "solidworks", "extract_errors": []}}
    s = pack_used.section(record)
    assert "PACK COMPLETENESS NOT PROVED" not in s["html"] and "!!" not in s["text"]


# ── the same number is not the same model ─────────────────────────────────────────────────
def test_a_model_of_the_same_number_at_another_revision_does_not_cover_it(er, tmp_path, monkeypatch):
    _run, outputs = _both_outputs(er, tmp_path, monkeypatch)
    line = next(l for l in outputs[0][2].splitlines() if l.strip().startswith("70001-01-03M_revA.igs"))
    assert "NOT READ; COVERAGE UNRESOLVED" in line and "revisions differ" in line
    assert "rev A" in line and "rev B" in line


def test_unconfirmed_configurations_leave_coverage_unresolved_even_at_the_same_revision():
    record = {"run_id": "r1", "cad_inputs": {"solidworks": ["70001-01-02M_revC.SLDPRT"],
                                             "unread": ["70001-01-02M_revC.igs"]},
              "solidworks_native": {}}
    plain = pack_used.read_evidence(record, ["70001-01-02M_revC.igs"], {"members": []})
    assert plain["files"][0]["state"] == "not read; covered"
    unsure = pack_used.read_evidence(record, ["70001-01-02M_revC.igs"],
                                     {"members": [], "configurations_unconfirmed": True})
    assert unsure["files"][0]["state"] == "NOT READ; COVERAGE UNRESOLVED"
    assert "configurations are unconfirmed" in unsure["files"][0]["why"]


def test_a_number_alone_with_no_revision_on_either_file_establishes_nothing():
    record = {"run_id": "r1", "cad_inputs": {"solidworks": ["70001-01-02M 1.2mm.SLDPRT"],
                                             "unread": ["70001-01-02M export.igs"]},
              "solidworks_native": {}}
    f = pack_used.read_evidence(record, ["70001-01-02M export.igs"], {"members": []})["files"][0]
    assert f["state"] == "NOT READ; COVERAGE UNRESOLVED" and "cannot be compared" in f["why"]


def _ev(solidworks, unread, manifest=None, failed=()):
    record = {"run_id": "r1", "cad_inputs": {"solidworks": list(solidworks), "unread": [unread]},
              "solidworks_native": {"extract_errors": [{"path": n, "errors": ["could not be opened"]}
                                                       for n in failed]}}
    return pack_used.read_evidence(record, [unread], manifest or {"members": []})["files"][0]


def test_the_same_file_name_does_not_override_a_second_issue_of_the_component_in_the_pack():
    """JG: a matching filename alone must not override conflicting evidence."""
    alone = _ev(["70001-01-02M.SLDPRT"], "70001-01-02M.igs")
    assert alone["state"] == "not read; covered" and "same file name" in alone["why"]
    assert "no revision is stated on either file" in alone["why"]
    beside = _ev(["70001-01-02M_revC.SLDPRT", "70001-01-02M_revD.SLDPRT"], "70001-01-02M_revC.igs")
    assert beside["state"] == "NOT READ; COVERAGE UNRESOLVED"
    assert "more than one issue of this component" in beside["why"] and "rev D" in beside["why"]


def test_the_same_file_name_does_not_override_the_revision_the_packs_manifest_gives():
    manifest = {"members": [{"drawing": "70001-01-02M", "revision": "D"}]}
    f = _ev(["70001-01-02M_revC.SLDPRT"], "70001-01-02M_revC.igs", manifest)
    assert f["state"] == "NOT READ; COVERAGE UNRESOLVED"
    assert "manifest gives this drawing as rev D" in f["why"]
    agreed = _ev(["70001-01-02M_revC.SLDPRT"], "70001-01-02M_revC.igs",
                 {"members": [{"drawing": "70001-01-02M", "revision": "C"}]})
    assert agreed["state"] == "not read; covered" and "same revision" in agreed["why"]


def test_the_same_file_name_does_not_override_unconfirmed_configurations():
    f = _ev(["70001-01-02M.SLDPRT"], "70001-01-02M.igs",
            {"members": [], "configurations_unconfirmed": True})
    assert f["state"] == "NOT READ; COVERAGE UNRESOLVED" and "configurations are unconfirmed" in f["why"]


def test_a_second_issue_that_failed_to_read_is_still_a_second_issue():
    f = _ev(["70001-01-02M_revC.SLDPRT", "70001-01-02M_revD.SLDPRT"], "70001-01-02M_revC.igs",
            failed=["70001-01-02M_revD.SLDPRT"])
    assert f["state"] == "NOT READ; COVERAGE UNRESOLVED" and "more than one issue" in f["why"]


def test_another_components_model_never_covers_this_one():
    f = _ev(["70001-01-03M_revC.SLDPRT"], "70001-01-02M_revC.igs")
    assert f["state"] == "NOT READ; COVERAGE UNRESOLVED" and "no native model of this component" in f["why"]


# ── a recovered pack is labelled as one ────────────────────────────────────────────────────
def test_the_link_stays_on_the_pack_the_run_was_given_and_a_recovery_is_shown_apart(er, tmp_path, monkeypatch):
    run = _queue(er, tmp_path)
    rec = pack_link.load(run.pack_token)
    original = Path(rec["folder"])
    # a file found for the pack and left out of the copy, then recovered into a new version
    lost = tmp_path / "share" / "A Customer" / "70001-01-GA" / "70001-01-04M_revA.igs"
    lost.write_bytes(b"model")
    import pack_resolver
    st = lost.stat()
    m = json.loads((original / pack_dropoff.MANIFEST).read_text(encoding="utf-8"))
    m["resolver"] = dict(m.get("resolver") or {}, members=[{"drawing": "70001-01-GA", "files": [
        {"path": str(lost), "fingerprint": pack_resolver.fingerprint(lost, st.st_size, st.st_mtime)}]}])
    (original / pack_dropoff.MANIFEST).write_text(json.dumps(m), encoding="utf-8")
    done = pack_dropoff.recover(original)
    assert pack_link.load(run.pack_token)["folder"] == str(original), "the run's link moved to a later pack"
    seen = pack_link.view(pack_link.load(run.pack_token))
    assert seen["this_is_a_recovered_pack"] is False
    assert "70001-01-04M_revA.igs" not in {f["name"] for f in seen["files"]}
    later = seen["recovered_versions_made_later"]
    assert [x["folder"] for x in later] == [Path(done["created"]).name]
    assert later[0]["added"] == ["70001-01-04M_revA.igs"]
    recovered = pack_link.view({"folder": done["created"], "run_id": run.run_id})
    assert recovered["this_is_a_recovered_pack"] is True
    assert next(f for f in recovered["files"] if f["name"] == "70001-01-04M_revA.igs")["recovered"] is True
    page = (BACKEND / "sdi-pack.html").read_text(encoding="utf-8")
    assert "RECOVERED REVIEW PACK" in page and "NOT given to the earlier runs" in page
    assert "are not what it was given" in page


# ── every way a job is queued, and a run with no engine note ───────────────────────────────
@pytest.mark.parametrize("source", ["", "self_running", "tti"])
def test_a_manual_a_self_running_and_a_tti_job_all_get_the_link(er, tmp_path, monkeypatch, source):
    run, outputs = _both_outputs(er, tmp_path, monkeypatch, source=source)
    for which, html, _text in outputs:
        assert f"{PORTAL}/estimating/pack/{run.pack_token}" in html, (source, which)


def test_the_note_is_written_by_engine_code_both_runners_share():
    main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "from pack_used import into_note_safely as _pack_note" in main
    assert "_note = _pack_note(_note, summary)" in main
    runner = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    assert "--engine-root" in runner, "slot 2 runs the same engine from its own checkout"


def test_an_email_for_a_run_whose_engine_filed_no_note_still_shows_its_pack(er, tmp_path, monkeypatch):
    run = _queue(er, tmp_path)
    mail = _the_email(er, run, [], monkeypatch)
    for body in (mail["html"], mail["text"]):
        assert f"{PORTAL}/estimating/pack/{run.pack_token}" in body
        assert f"Run {run.run_id} · pack version 1" in body
        assert "PACK COMPLETENESS NOT PROVED" in body
        assert "70001-01-GA_revB.pdf" in body
    assert "no record here of which files it read" in mail["text"]


def test_where_no_pack_was_kept_both_say_so_instead_of_linking(er, tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", "off")
    run, outputs = _both_outputs(er, tmp_path, monkeypatch)
    assert run.pack_token == ""
    for which, html, text in outputs:
        assert "/estimating/pack/" not in html, which
        assert "No link to the saved pack" in html and "No link to the saved pack" in text, which


# ── the page hands out the pack's files and nothing else ───────────────────────────────────
def test_the_link_serves_the_packs_own_files_and_refuses_anything_else(er, tmp_path):
    run = _queue(er, tmp_path)
    rec = pack_link.load(run.pack_token)
    assert pack_link.file_for(rec, "70001-01-GA_revB.pdf").is_file()
    for name in ("../../state/packs/x.json", "pack_manifest.json", "C:/Windows/win.ini", "nothing.pdf"):
        assert pack_link.file_for(rec, name) is None, name
    with pytest.raises(er.HTTPException) as got:
        er.pack_file(run.pack_token, "pack_manifest.json", None, x_sdi_key="portal-key")
    assert got.value.status_code == 404
    assert pack_link.load("not-a-token") is None and pack_link.load("A" * 24) is None


def test_the_page_is_behind_sign_in_like_the_walkthrough():
    app = (BACKEND / "app.py").read_text(encoding="utf-8")
    page = app[app.index('@app.get("/estimating/pack/{token}")'):]
    assert "auth.current_user(request) is None" in page[:300] and "auth.login_redirect(request)" in page[:300]


# ── nothing already sent is sent again or rewritten ────────────────────────────────────────
def test_filling_in_the_link_twice_changes_nothing_the_second_time(er, tmp_path, monkeypatch):
    run = _queue(er, tmp_path)
    deliverables = _engine_writes_its_note(run, tmp_path)
    first = _the_filed_note(er, run, deliverables)
    assert pack_link.stamp_note_files([d["path"] for d in deliverables], run.as_json()) == []
    assert _the_filed_note(er, run, deliverables) == first
    assert first[0].count("/estimating/pack/") == 1 and first[1].count("/estimating/pack/") == 1


def test_nothing_here_sends_and_a_run_already_mailed_is_not_mailed_again():
    link = (BACKEND / "pack_link.py").read_text(encoding="utf-8")
    assert "estimate_email.send" not in link and "smtplib" not in link
    routes = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    assert "_send_to = [] if run.email_result else list(run.email_to)" in routes
