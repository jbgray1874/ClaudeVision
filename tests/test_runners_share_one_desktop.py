"""Two runs on one desktop share its one SolidWorks reader, each waiting its turn (SCRUM-183
phase 2, D-731).

JG, 6 Nov 2026: "We agreed that two estimating workers would share one SolidWorks reader,
waiting briefly for their turn ... the same job could receive different model evidence
depending on what else is running. Document Manager has not yet passed the outstanding
acceptance checks."

JG, later the same day (D-732): "we should not fail.. we should report in the portal that [we]
are switching to document manager and provide a 5 minute update every delay due to waiting for
solid works com api."

So the engine takes the desktop's SolidWorks in turn around its model read and a second run
waits, saying so at the start and every five minutes; a normal wait never changes the reader;
a wait that reaches its limit switches that run to the Document Manager, said, or goes on
without its models when there is no key; the service lets two runners that declare the turn
share a desktop and keeps the strict model-reader rule; and a second or third run is claimed
only while the machine has the room. Synthetic runs, a stand-in analyser and a temporary token
file.
"""
from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import sdi_estimate_runner as runner                                     # noqa: E402
import solidworks_turn as turn_mod                                       # noqa: E402
from source_connectors import solidworks as sw                           # noqa: E402


@pytest.fixture()
def token(tmp_path, monkeypatch):
    path = tmp_path / "SDI" / "solidworks.token"
    monkeypatch.setenv(turn_mod.TOKEN_ENV, str(path))
    return path


# ── the turn ─────────────────────────────────────────────────────────────────────────

def test_one_desktop_has_one_solidworks_turn(token):
    first, state = turn_mod.try_take()
    assert state == "held"
    second, state2 = turn_mod.try_take()
    assert state2 == "busy" and second is None
    assert turn_mod.busy()
    turn_mod.release(first)
    third, state3 = turn_mod.try_take()
    assert state3 == "held"
    turn_mod.release(third)
    assert not turn_mod.busy()


def test_a_second_run_waits_for_its_turn_and_then_takes_it(token):
    held, _ = turn_mod.try_take()
    threading.Timer(0.4, turn_mod.release, args=(held,)).start()
    said = []
    handle, turn = turn_mod.take_turn(wait_s=10, poll_s=0.05, say=said.append)
    try:
        assert turn["state"] == "held" and turn["waited_s"] > 0
        assert any("Waiting for the desktop's SolidWorks" in s for s in said)
        assert any("reads its models the same way it would alone" in s for s in said)
    finally:
        turn_mod.release(handle)


def test_a_lone_run_never_waits(token):
    said = []
    handle, turn = turn_mod.take_turn(wait_s=10, say=said.append)
    turn_mod.release(handle)
    # It says it took the turn (D-738: the wall names the run holding SolidWorks), and never
    # that it waited.
    assert turn["state"] == "held"
    assert said == ["SolidWorks turn taken: this run reads its models now."]


def test_a_turn_that_never_comes_times_out_in_its_own_words(token):
    held, _ = turn_mod.try_take()
    try:
        handle, turn = turn_mod.take_turn(wait_s=0.2, poll_s=0.05, say=lambda m: None)
        assert handle is None and turn["state"] == "timed_out"
        why = turn_mod.timed_out_reason(turn)
        assert "another run on this machine" in why and "SolidWorks did not read" in why
    finally:
        turn_mod.release(held)


def test_a_waiting_run_says_so_every_five_minutes(token):
    """JG: "provide a 5 minute update every delay due to waiting for solid works com api"."""
    held, _ = turn_mod.try_take()
    now = [0.0]
    said = []
    try:
        turn_mod.take_turn(wait_s=12 * 60, update_s=5 * 60, poll_s=60, say=said.append,
                           sleep=lambda s: now.__setitem__(0, now[0] + s),
                           clock=lambda: now[0])
    finally:
        turn_mod.release(held)
    assert sum("Waiting for the desktop's SolidWorks" in m for m in said) == 1
    updates = [m for m in said if m.startswith("Still waiting")]
    assert len(updates) == 2 and "5 min so far" in updates[0] and "10 min so far" in updates[1]


def test_the_update_interval_and_the_timeout_reader_are_settings(monkeypatch):
    monkeypatch.delenv(turn_mod.UPDATE_ENV, raising=False)
    monkeypatch.delenv(turn_mod.TIMEOUT_ENV, raising=False)
    assert turn_mod.update_minutes() == 5.0 and turn_mod.timeout_reader() == "docmgr"
    monkeypatch.setenv(turn_mod.TIMEOUT_ENV, "none")
    assert turn_mod.timeout_reader() == "none"


def test_an_unusable_token_fails_open_as_a_lone_run(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv(turn_mod.TOKEN_ENV, str(blocker / "solidworks.token"))
    handle, turn = turn_mod.take_turn(wait_s=0, say=lambda m: None)
    assert handle is None and turn["state"] == "unavailable"


def test_the_token_is_one_per_machine_not_per_checkout(monkeypatch):
    monkeypatch.delenv(turn_mod.TOKEN_ENV, raising=False)
    path = turn_mod.token_path()
    assert "ClaudeVision" not in str(path) and path.name == "solidworks.token"


# ── the engine's model read takes the turn ───────────────────────────────────────────

class _Done:
    returncode, stdout, stderr = 0, "", ""


def test_the_analyser_runs_only_while_the_run_holds_the_turn(token, monkeypatch):
    seen = {}

    def _analyser(*a, **k):
        seen["busy_meanwhile"] = turn_mod.busy()
        return _Done()
    monkeypatch.setattr(sw.subprocess, "run", _analyser)
    turn = {}
    assert sw._run_analyser("/tmp/models", turn=turn) is None
    assert seen["busy_meanwhile"], "another run must find SolidWorks taken during the read"
    assert turn["state"] == "held"
    assert not turn_mod.busy(), "the turn is given back when the read ends"


def test_the_turn_is_given_back_when_the_analyser_fails(token, monkeypatch):
    def _boom(*a, **k):
        raise OSError("com error")
    monkeypatch.setattr(sw.subprocess, "run", _boom)
    assert "could not be run" in sw._run_analyser("/tmp/models")
    assert not turn_mod.busy()


def test_a_timed_out_turn_never_starts_the_analyser(token, monkeypatch):
    monkeypatch.setenv(turn_mod.WAIT_ENV, "0")
    monkeypatch.setattr(sw.subprocess, "run",
                        lambda *a, **k: pytest.fail("the analyser ran without the turn"))
    held, _ = turn_mod.try_take()
    try:
        turn = {}
        err = sw._run_analyser("/tmp/models", turn=turn)
    finally:
        turn_mod.release(held)
    assert turn["state"] == "timed_out" and "another run on this machine" in err


def _timed_out_job(tmp_path, monkeypatch, **env):
    """One job whose SolidWorks turn never comes: another run holds the token throughout."""
    models = tmp_path / "job"
    models.mkdir()
    (models / "x.SLDPRT").write_bytes(b"model")
    monkeypatch.setenv(turn_mod.WAIT_ENV, "0")
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    monkeypatch.setattr(sw, "solidworks_com_available", lambda: (True, ""))
    asked = []

    def _backup(jp, analyse_from, reason, **k):
        asked.append(reason)
        return jp, {"docmgr_backup_reason": reason}
    monkeypatch.setattr(sw, "_docmgr_backup", _backup)
    held, _ = turn_mod.try_take()
    try:
        job = sw.native_extract_for_job(folder=models, run=True, docmgr=False)
    finally:
        turn_mod.release(held)
    return job, asked


def test_a_timed_out_turn_switches_to_the_document_manager_and_says_so(token, monkeypatch,
                                                                        tmp_path, capsys):
    """The run does not fail: the portal is told it is switching, and the Document Manager
    reads the models, even with the general backup switch off."""
    job, asked = _timed_out_job(tmp_path, monkeypatch,
                                SDI_SW_DOCMGR_KEY="test-key-not-real", SDI_SW_TURN_TIMEOUT=None)
    assert len(asked) == 1 and "switched to the Document Manager" in asked[0]
    assert job.meta["solidworks_turn"]["switched_to"] == "docmgr"
    assert "SWITCHING TO THE DOCUMENT MANAGER" in capsys.readouterr().out


def test_with_no_key_the_run_goes_on_without_its_models_and_says_so(token, monkeypatch,
                                                                    tmp_path, capsys):
    job, asked = _timed_out_job(tmp_path, monkeypatch, SDI_SW_DOCMGR_KEY=None,
                                SDI_SW_TURN_TIMEOUT=None)
    assert not asked
    assert job.meta["solidworks_turn"]["switched_to"] == "none"
    assert "another run on this machine" in job.meta["analyser_error"]
    out = capsys.readouterr().out
    assert "no Document Manager key" in out and "goes on without its models" in out


def test_the_timeout_can_leave_the_models_unread(token, monkeypatch, tmp_path):
    job, asked = _timed_out_job(tmp_path, monkeypatch, SDI_SW_DOCMGR_KEY="test-key-not-real",
                                SDI_SW_TURN_TIMEOUT="none")
    assert not asked and job.meta["solidworks_turn"]["switched_to"] == "none"


def test_a_normal_wait_never_changes_the_reader(token, monkeypatch, tmp_path):
    """A run that gets its turn reads with SolidWorks; the backup is not asked."""
    models = tmp_path / "job"
    models.mkdir()
    (models / "x.SLDPRT").write_bytes(b"model")
    monkeypatch.setenv("SDI_SW_DOCMGR_KEY", "test-key-not-real")
    monkeypatch.setattr(sw, "solidworks_com_available", lambda: (True, ""))
    monkeypatch.setattr(sw.subprocess, "run", lambda *a, **k: _Done())
    monkeypatch.setattr(sw, "_docmgr_backup", lambda *a, **k: pytest.fail(
        "the backup was asked although SolidWorks read the models"))
    job = sw.native_extract_for_job(folder=models, run=True, docmgr=False)
    assert job.meta["solidworks_turn"]["state"] == "held"


# ── the service ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def api(tmp_path, monkeypatch):
    stub = types.ModuleType("config")
    stub.API_KEY = ""
    stub.FILE_ROOTS = [str(tmp_path)]
    stub.STAGING_ROOT = str(tmp_path / "staged")
    monkeypatch.setitem(sys.modules, "config", stub)
    for name in list(sys.modules):
        if name in ("staging", "estimate_routes"):
            del sys.modules[name]
    monkeypatch.syspath_prepend(str(BACKEND))
    er = pytest.importorskip("estimate_routes",
                             reason="fastapi/pydantic not installed in this environment")
    er._RUNS.clear(); er._RUNNERS.clear()
    for job in ("a", "b", "c"):
        (tmp_path / job).mkdir(exist_ok=True)
        (tmp_path / job / "ga.pdf").write_bytes(b"%PDF-1.4 a drawing")
    monkeypatch.setenv("SDI_MAX_CONCURRENT_RUNS", "3")
    return er, tmp_path


def _queue(er, tmp_path, job, drawing):
    return er.start(er.EstimateRequest(client="Boots", drawing_number=drawing, units=1,
                                       job_folder=str(tmp_path / job),
                                       output_root=str(tmp_path / "share")))["run_id"]


def _claim(er, runner_id, host, caps=()):
    return er.claim(er.ClaimRequest(runner_id=runner_id, hostname=host,
                                    capabilities=list(caps)))


def _with_models(er, run_id):
    staged = Path(er._RUNS[run_id].job_folder)
    (staged / "x.SLDASM").write_bytes(b"model")
    assert er._needs_model_reader(staged)


SLOT = ["sw_extract", "xai_extract", "desktop_token"]


def test_two_slots_on_one_desktop_each_take_a_run(api):
    er, tmp_path = api
    _claim(er, "laptop", "LAPTOP", SLOT)
    a, b = _queue(er, tmp_path, "a", "AAA"), _queue(er, tmp_path, "b", "BBB")
    assert _claim(er, "laptop", "LAPTOP", SLOT)["run"]["run_id"] == a
    assert _claim(er, "laptop-s2", "LAPTOP", SLOT)["run"]["run_id"] == b


def test_a_runner_that_does_not_share_the_desktop_keeps_the_old_rule(api):
    er, tmp_path = api
    _claim(er, "laptop", "LAPTOP", ["sw_extract"])
    _queue(er, tmp_path, "a", "AAA"); _queue(er, tmp_path, "b", "BBB")
    assert _claim(er, "laptop", "LAPTOP", ["sw_extract"])["run"]
    refused = _claim(er, "laptop-s2", "LAPTOP", SLOT)
    assert refused["run"] is None and "one desktop drives one" in refused["reason"]


def test_the_cap_still_holds(api, monkeypatch):
    er, tmp_path = api
    monkeypatch.setenv("SDI_MAX_CONCURRENT_RUNS", "2")
    _claim(er, "laptop", "LAPTOP", SLOT)
    for job, dwg in (("a", "AAA"), ("b", "BBB"), ("c", "CCC")):
        _queue(er, tmp_path, job, dwg)
    assert _claim(er, "laptop", "LAPTOP", SLOT)["run"]
    assert _claim(er, "laptop-s2", "LAPTOP", SLOT)["run"]
    assert _claim(er, "laptop-s3", "LAPTOP", SLOT)["run"] is None


def test_a_model_job_is_never_given_to_a_runner_without_a_model_reader(api):
    """Even with every runner that can read models busy, a model job waits for one: it is not
    priced from the drawings because of what else is running."""
    er, tmp_path = api
    _claim(er, "laptop", "LAPTOP", SLOT)
    a = _queue(er, tmp_path, "a", "AAA")
    assert _claim(er, "laptop", "LAPTOP", SLOT)["run"]["run_id"] == a       # slot 1 busy
    b = _queue(er, tmp_path, "b", "BBB")
    _with_models(er, b)
    refused = _claim(er, "laptop-s2", "LAPTOP", ["xai_extract", "desktop_token", "no_models"])
    assert refused["run"] is None and "need a model reader" in refused["reason"]
    assert _claim(er, "laptop-s2", "LAPTOP", SLOT)["run"]["run_id"] == b


def test_the_service_has_no_switch_to_run_without_a_model_reader():
    src = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    assert "SDI_RUN_WITHOUT_MODEL_READER" not in src


# ── the runner ───────────────────────────────────────────────────────────────────────

def test_every_slot_declares_the_same_reader_whatever_else_is_running(monkeypatch):
    monkeypatch.delenv("SDI_SW_RUN_ANALYSER", raising=False)
    monkeypatch.delenv("SDI_SW_DOCMGR", raising=False)
    monkeypatch.delenv("SDI_SW_DOCMGR_KEY", raising=False)
    caps = runner.runner_capabilities()
    assert "desktop_token" in caps and "sw_extract" in caps and "no_models" not in caps


def test_the_runner_does_not_change_how_a_run_reads_models():
    src = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    for gone in ("model_reader_for", "take_desktop_token", "SDI_MODEL_READER", "token_busy"):
        assert gone not in src, f"{gone}: the runner must not pick a model reader per run"


def test_slot_one_is_never_held_back():
    ok, said = runner.slot_may_claim(1)
    assert ok and "slot 1" in said


def test_a_second_slot_claims_only_with_the_room(monkeypatch):
    monkeypatch.setattr(runner, "compute_headroom", lambda: (False, "1.0 GB free (needs 3)"))
    ok, said = runner.slot_may_claim(2)
    assert not ok and "GB free" in said


def test_compute_headroom_is_measured_against_the_settings():
    ok, said = runner.compute_headroom(min_free_gb=0.0, max_cpu_pct=100.0)
    assert ok
    short, said2 = runner.compute_headroom(min_free_gb=1e9, max_cpu_pct=100.0)
    if "not measurable" in said2:
        assert short, "what cannot be measured is not held against the run"
    else:
        assert not short and "GB free" in said2
