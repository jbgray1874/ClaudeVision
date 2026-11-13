"""ONE COMPLETED-ESTIMATES LIST, EACH RUN WITH ITS BUNDLE ON THE SHARE CHECKED (JG, 13 Nov 2026).

"We should not need to identify a runner or search two folders. For each completed run, show
the drawing, run ID, completion time and a link to its verified AISheets bundle. Flag missing
deliverables explicitly. Put the same bundle link in the email and saved covering note. Local
working-folder paths can remain secondary diagnostic information. The shared copies still need
verification before saying everything is filed successfully. No moving existing outputs,
repricing, resending emails or restarting active jobs for this change."
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

import bundle_link as B  # noqa: E402

PORTAL = "https://portal.example.test"
STEM = "70001-01-GA_AI_20261113_210500"
WHOLE = (f"{STEM}.xlsx", f"{STEM}_record.json", f"{STEM}_report.html",
         f"{STEM}_covering_email.html", f"{STEM}_covering_email.txt",
         f"{STEM}_walkthrough.txt", f"{STEM}_walkthrough.wav", f"{STEM}_deliverables.json")


def _bundle(root: Path, names=WHOLE, working=r"C:\ClaudeVision-s2\output\estimates",
            wrote=()) -> Path:
    folder = root / "AISheets" / "A Customer" / "70001-01-GA" / "2026-11-13 21.05 (1 off)"
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        if n.endswith("_deliverables.json"):
            (folder / n).write_text(json.dumps({
                "schema": "run_deliverables.v1", "workbook": f"{STEM}.xlsx",
                "runner_id": "LAPTOP-abc-s2", "output_folder": working,
                "files": [{"name": x, "what": ""} for x in tuple(WHOLE[:-1]) + tuple(wrote)]}),
                encoding="utf-8")
        elif n.endswith("_covering_email.html"):
            (folder / n).write_text("<!-- subject: SDI estimate -->\n<div><p>The estimate.</p></div>", encoding="utf-8")
        else:
            (folder / n).write_text("content of " + n, encoding="utf-8")
    return folder


def _reported(folder: Path, names=WHOLE):
    return [{"name": n, "path": str(folder / n)} for n in names]


# ── the check of the share ─────────────────────────────────────────────────────────────────
def test_a_whole_bundle_on_the_share_is_verified(tmp_path):
    folder = _bundle(tmp_path)
    v = B.verify(folder, _reported(folder))
    assert v["state"] == "verified" and v["missing"] == [] and len(v["files"]) == len(WHOLE)
    assert v["says"] == f"verified: {len(WHOLE)} file(s) on the share"


@pytest.mark.parametrize("gone, what", [
    (f"{STEM}.xlsx", "the estimate workbook"),
    (f"{STEM}_record.json", "the run's pinned record"),
    (f"{STEM}_report.html", "the report"),
    (f"{STEM}_covering_email.html", "the covering note"),
    (f"{STEM}_walkthrough.txt", "the walkthrough's words"),
    (f"{STEM}_walkthrough.wav", "the spoken walkthrough"),
])
def test_each_kind_of_deliverable_is_flagged_by_name_when_it_is_not_there(tmp_path, gone, what):
    folder = _bundle(tmp_path)
    (folder / gone).unlink()
    v = B.verify(folder, _reported(folder))
    assert v["state"] == "INCOMPLETE"
    assert any(m["name"] == gone and "runner reported filing it" in m["why"] for m in v["missing"])
    assert any(m["what"] == what and "no file of this kind" in m["why"] for m in v["missing"])
    assert gone in v["says"]


def test_an_empty_file_is_not_a_filed_file(tmp_path):
    folder = _bundle(tmp_path)
    (folder / f"{STEM}_report.html").write_text("", encoding="utf-8")
    v = B.verify(folder, _reported(folder))
    assert v["state"] == "INCOMPLETE"
    assert any(m["name"] == f"{STEM}_report.html" and "empty" in m["why"] for m in v["missing"])


def test_a_file_the_run_wrote_and_the_runner_never_filed_is_flagged(tmp_path):
    """The runner's own report is not the only witness: the run's manifest says what it wrote."""
    folder = _bundle(tmp_path, wrote=(f"{STEM}_quote_internal.html",))
    v = B.verify(folder, _reported(folder))
    assert v["state"] == "INCOMPLETE"
    assert any(m["name"] == f"{STEM}_quote_internal.html" and "was not filed" in m["why"] for m in v["missing"])


def test_a_share_that_cannot_be_reached_is_not_checked_which_is_not_missing(tmp_path):
    v = B.verify(tmp_path / "no such share" / "AISheets" / "A" / "B" / "C" / "D")
    assert v["state"] == "NOT CHECKED" and v["missing"] == []
    assert "could not be reached" in v["says"]


def test_a_reachable_share_without_the_bundle_folder_is_incomplete(tmp_path):
    (tmp_path / "AISheets" / "A Customer" / "70001-01-GA").mkdir(parents=True)
    v = B.verify(tmp_path / "AISheets" / "A Customer" / "70001-01-GA" / "2026-11-13 21.05 (1 off)")
    assert v["state"] == "INCOMPLETE" and "not on the share" in v["says"]


def test_the_working_folder_is_read_from_the_run_and_stays_secondary(tmp_path):
    folder = _bundle(tmp_path)
    v = B.verify(folder, _reported(folder))
    assert v["working_folder"] == r"C:\ClaudeVision-s2\output\estimates"
    assert v["folder"] == str(folder), "the bundle is the share folder, never the working one"


# ── one list ───────────────────────────────────────────────────────────────────────────────
def _run(run_id, runner, folder, at, status="done", **kw):
    return dict({"run_id": run_id, "runner": runner, "drawing_number": "70001-01-GA",
                 "client": "A Customer", "units": 1, "status": status, "finished_at": at,
                 "output_path": str(folder), "deliverables": _reported(Path(folder)),
                 "job_type": "", "bundle_url": f"{PORTAL}/estimating/bundle/tok-{run_id}"}, **kw)


def test_runs_from_both_runners_are_one_list_newest_first(tmp_path):
    a = _bundle(tmp_path / "a", working=r"C:\ClaudeVision\output\estimates")
    b = _bundle(tmp_path / "b")
    rows = B.completed([_run("r1", "LAPTOP-abc", a, 100.0), _run("r2", "LAPTOP-abc-s2", b, 200.0)])
    assert [r["run_id"] for r in rows] == ["r2", "r1"]
    for r in rows:
        assert r["drawing_number"] == "70001-01-GA" and r["finished_at"] and r["bundle_url"]
        assert r["bundle_state"] == "verified" and r["bundle_folder"].endswith("(1 off)")
    assert {r["working_folder"] for r in rows} == {r"C:\ClaudeVision\output\estimates",
                                                  r"C:\ClaudeVision-s2\output\estimates"}


def test_a_run_that_did_not_finish_is_listed_as_that_and_an_extract_is_not_an_estimate(tmp_path):
    a = _bundle(tmp_path / "a")
    rows = B.completed([
        _run("r1", "LAPTOP-abc", a, 100.0),
        _run("r2", "LAPTOP-abc", tmp_path / "none", 200.0, status="error", error="exit code 2", deliverables=[]),
        _run("r3", "LAPTOP-abc", a, 300.0, job_type="sw_extract"),
        _run("r4", "LAPTOP-abc", a, 400.0, status="running")])
    assert [r["run_id"] for r in rows] == ["r2", "r1"]
    assert rows[0]["outcome"] == "did not finish" and rows[0]["bundle_state"] == "NO BUNDLE"
    assert rows[0]["error"] == "exit code 2"


def test_the_list_flags_exactly_what_is_missing(tmp_path):
    a = _bundle(tmp_path / "a")
    (a / f"{STEM}_walkthrough.wav").unlink()
    row = B.completed([_run("r1", "LAPTOP-abc", a, 100.0)])[0]
    assert row["bundle_state"] == "INCOMPLETE"
    assert f"{STEM}_walkthrough.wav" in [m["name"] for m in row["missing"]]


# ── through the service ────────────────────────────────────────────────────────────────────
@pytest.fixture()
def er(monkeypatch, tmp_path):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    import estimate_routes
    estimate_routes._RUNS.clear()
    estimate_routes._RUNNERS.clear()
    estimate_routes._COMPLETED.update(at=0.0, body=None)
    monkeypatch.setattr(estimate_routes, "_other_local_services", lambda port: [])
    monkeypatch.setattr(estimate_routes.config, "API_KEY", "portal-key", raising=False)
    monkeypatch.setattr(estimate_routes, "_keep", lambda run: None)
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SDI_PORTAL_URL", PORTAL)
    return estimate_routes


def _a_finished_run(er, tmp_path, run_id="abc123def456", runner="LAPTOP-abc-s2", names=WHOLE):
    folder = _bundle(tmp_path / run_id, names=names)
    run = er.Run(run_id=run_id, client="A Customer", drawing_number="70001-01-GA", units=1,
                 job_folder=str(tmp_path / "stage"), output_path=str(folder), queued_at=1.0)
    run.status, run.finished_at, run.runner = "done", 1794600000.0, runner
    run.deliverables = _reported(folder, names)
    er._RUNS[run_id] = run
    return run, folder


def test_grid_controls_list_gives_tonights_finished_runs_their_links_without_touching_them(er, tmp_path):
    run, folder = _a_finished_run(er, tmp_path)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    body = er.wall_completed(x_sdi_key="portal-key")
    row = body["rows"][0]
    assert row["run_id"] == run.run_id and row["bundle_state"] == "verified"
    assert row["bundle_url"] == f"{PORTAL}/estimating/bundle/{run.bundle_token}"
    assert body["counts"] == {"completed": 1, "verified": 1, "incomplete": 0, "not_checked": 0,
                              "did_not_finish": 0}
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before, "a filed file was changed"


def test_the_link_opens_that_bundles_files_and_no_others(er, tmp_path):
    run, folder = _a_finished_run(er, tmp_path)
    er.wall_completed(x_sdi_key="portal-key")
    seen = er.bundle_view(run.bundle_token, None, x_sdi_key="portal-key")
    assert seen["run_id"] == run.run_id and seen["verification"]["state"] == "verified"
    assert seen["bundle_folder"] == str(folder)
    rec = B.load(run.bundle_token)
    assert B.file_for(rec, f"{STEM}.xlsx").is_file()
    (folder.parent / "another run.xlsx").write_text("x")
    for name in ("../another run.xlsx", "..", "sub/x.xlsx", "nothing.xlsx", str(folder / f"{STEM}.xlsx")):
        assert B.file_for(rec, name) is None, name
    assert B.load("not-a-token") is None


def test_the_email_and_the_filed_note_both_carry_the_bundle_link_and_what_the_check_found(er, tmp_path, monkeypatch):
    run, folder = _a_finished_run(er, tmp_path)
    run.bundle_token = B.make(run.as_json())
    link = f"{PORTAL}/estimating/bundle/{run.bundle_token}"
    sent = {}
    monkeypatch.setattr(er.estimate_email, "send",
                        lambda to, subject, html, text, paths: sent.update(html=html, text=text) or {"sent": True})
    er._email_finished_run(run.as_json(), run.deliverables, ["someone@example.test"], False, True)
    note = folder / f"{STEM}_covering_email.html"
    B.stamp_note_files([str(note)], run.as_json())
    for which, html, text in (("the e-mail", sent["html"], sent["text"]),
                              ("the filed note", note.read_text(encoding="utf-8"),
                               note.with_suffix(".txt").read_text(encoding="utf-8"))):
        assert link in html and link in text, which
        assert f"run {run.run_id}" in html.lower() and f"Run {run.run_id}" in text, which
        assert "Bundle verified" in html and "Bundle verified" in text, which
        assert "C:\\ClaudeVision" not in html, f"{which}: a working-folder path is shown as the bundle"
        assert html.index("filed bundle") < html.index("The estimate."), f"{which}: not near the top"


def test_an_incomplete_bundle_is_said_in_the_email_not_only_on_grid_control(er, tmp_path, monkeypatch):
    names = tuple(n for n in WHOLE if not n.endswith("_walkthrough.wav"))
    run, folder = _a_finished_run(er, tmp_path, names=names)
    run.bundle_token = B.make(run.as_json())
    sent = {}
    monkeypatch.setattr(er.estimate_email, "send",
                        lambda to, subject, html, text, paths: sent.update(html=html, text=text) or {"sent": True})
    er._email_finished_run(run.as_json(), run.deliverables, ["someone@example.test"], False, True)
    assert "Bundle INCOMPLETE: missing " in sent["text"]
    assert f"{STEM}_walkthrough.wav" in sent["text"] and "the spoken walkthrough" in sent["text"]
    assert "Bundle INCOMPLETE" in sent["html"]


def test_stamping_twice_changes_nothing_and_nothing_here_sends_or_moves(er, tmp_path):
    run, folder = _a_finished_run(er, tmp_path)
    run.bundle_token = B.make(run.as_json())
    note = folder / f"{STEM}_covering_email.html"
    assert B.stamp_note_files([str(note)], run.as_json()) == [str(note)]
    once = note.read_text(encoding="utf-8")
    assert B.stamp_note_files([str(note)], run.as_json()) == []
    assert note.read_text(encoding="utf-8") == once and once.count("/estimating/bundle/") == 1
    src = (BACKEND / "bundle_link.py").read_text(encoding="utf-8")
    for word in ("estimate_email.send", "smtplib", "shutil.move", "shutil.copy", ".unlink(", "rmtree"):
        assert word not in src, word


def test_every_finished_estimate_gets_its_link_when_it_reports_whichever_runner_ran_it():
    src = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    at = src.index("run.bundle_token = bundle_link.make(run.as_json())")
    assert src.index("run.deliverables = _only_this_runs_files(run, list(req.deliverables))") < at
    assert at < src.index("_send_to = [] if run.email_result else list(run.email_to)")
    assert "note = bundle_link.into_note(note, snapshot)" in src
    # the Ask and Listen buttons still lead the e-mail (D-613): the bundle line goes in first
    assert src.index("note = bundle_link.into_note(note, snapshot)") < src.index(
        "note = estimate_walkthrough.email_button(note")


def test_grid_control_shows_the_one_list_with_the_runner_only_in_the_tooltip():
    page = (BACKEND / "sdi-estimating-wall.html").read_text(encoding="utf-8")
    assert "/api/estimate/wall/completed" in page and 'id="hDone"' in page
    at = page.index("function renderHDone(){")
    body = page[at:page.index("function renderHistory(){")]
    head = body[body.index("<table>"):body.index(".map(r =>")]
    for col in ("Finished", "Drawing", "Run", "Bundle on the share", "Missing"):
        assert f"<th>{col}</th>" in head, col
    assert "Runner" not in head and "Working" not in head, "the runner is not a column to search by"
    assert "working folder" in body and "title=" in body


def test_the_bundle_page_is_behind_sign_in_and_says_what_the_check_does_not_do():
    app = (BACKEND / "app.py").read_text(encoding="utf-8")
    page = app[app.index('@app.get("/estimating/bundle/{token}")'):][:300]
    assert "auth.current_user(request) is None" in page and "auth.login_redirect(request)" in page
    html = (BACKEND / "sdi-bundle.html").read_text(encoding="utf-8")
    assert "Content is not compared" in html and "For diagnosis only" in html
