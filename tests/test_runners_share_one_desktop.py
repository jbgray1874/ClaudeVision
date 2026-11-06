"""Several runs on one desktop, sharing its one SolidWorks (SCRUM-183 phase 2, D-731).

JG, 6 Nov 2026: "we need to see the multi run on this laptop ... for any second or third runs,
we shouldn't stop unless the machine has insufficient compute available and we should use
document manager for all other runs. if we can't we run without solid works and document
manager and use what we have otherwise."

SolidWorks is a token, one lock per desktop: the run holding it reads models with SolidWorks,
every other run with the Document Manager when its key is present, otherwise with nothing, and
nobody waits. The service lets runners that declare the token share a desktop, a runner with no
model reader takes a model job when no runner that can read it is idle, and a second or third
run is claimed only while the machine has the room. Synthetic runs and a temporary token file.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import sdi_estimate_runner as runner                                     # noqa: E402

KEY = "test-key-not-real"


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
    monkeypatch.delenv("SDI_RUN_WITHOUT_MODEL_READER", raising=False)
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


# ── the service ──────────────────────────────────────────────────────────────────────

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


def test_a_slot_with_no_model_reader_runs_a_model_job_when_none_is_free(api):
    """Slot 1 holds SolidWorks on a run; slot 2 has no Document Manager key. The model job is
    not left waiting: slot 2 runs it on what it has, and the run says so."""
    er, tmp_path = api
    _claim(er, "laptop", "LAPTOP", SLOT)
    a = _queue(er, tmp_path, "a", "AAA")
    assert _claim(er, "laptop", "LAPTOP", SLOT)["run"]["run_id"] == a       # slot 1 busy
    b = _queue(er, tmp_path, "b", "BBB")
    _with_models(er, b)
    got = _claim(er, "laptop-s2", "LAPTOP", ["xai_extract", "desktop_token", "no_models"])
    assert got["run"]["run_id"] == b
    assert any("no model reader free" in line for line in er._RUNS[b].log)


def test_a_model_job_waits_for_an_idle_runner_that_can_read_it(api):
    er, tmp_path = api
    _claim(er, "laptop", "LAPTOP", SLOT)                                     # idle, able
    a = _queue(er, tmp_path, "a", "AAA")
    _with_models(er, a)
    refused = _claim(er, "laptop-s2", "LAPTOP", ["desktop_token", "no_models"])
    assert refused["run"] is None and "need a model reader" in refused["reason"]
    assert _claim(er, "laptop", "LAPTOP", SLOT)["run"]["run_id"] == a


def test_a_runner_long_unseen_is_not_counted_as_idle(api):
    er, tmp_path = api
    _claim(er, "laptop", "LAPTOP", SLOT)
    a = _queue(er, tmp_path, "a", "AAA")
    _with_models(er, a)
    er._RUNNERS["laptop"].last_seen = time.time() - 600
    assert _claim(er, "laptop-s2", "LAPTOP", ["desktop_token", "no_models"])["run"]


def test_the_strict_rule_can_be_restored(api, monkeypatch):
    er, tmp_path = api
    monkeypatch.setenv("SDI_RUN_WITHOUT_MODEL_READER", "0")
    _claim(er, "server", "SDI-APP01", ["no_models"])
    a = _queue(er, tmp_path, "a", "AAA")
    _with_models(er, a)
    assert _claim(er, "server", "SDI-APP01", ["no_models"])["run"] is None


# ── the runner ───────────────────────────────────────────────────────────────────────

def test_one_desktop_has_one_solidworks_token(tmp_path):
    token = tmp_path / "solidworks.token"
    first, state = runner.take_desktop_token(token)
    assert state == "held"
    second, state2 = runner.take_desktop_token(token)
    assert state2 == "busy" and second is None
    assert runner.desktop_token_busy(token)
    runner.release_desktop_token(first)
    third, state3 = runner.take_desktop_token(token)
    assert state3 == "held"
    runner.release_desktop_token(third)
    assert not runner.desktop_token_busy(token)


def test_an_unusable_token_fails_open_as_a_lone_runner(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    handle, state = runner.take_desktop_token(blocker / "solidworks.token")
    assert handle is None and state == "unavailable"
    env, said = runner.model_reader_for(state, {})
    assert env == {} and said.startswith("SolidWorks as configured")


def test_the_run_without_the_token_reads_models_with_the_document_manager():
    env, said = runner.model_reader_for("busy", {"SDI_SW_DOCMGR_KEY": KEY})
    assert env == {"SDI_SW_RUN_ANALYSER": "0", "SDI_SW_DOCMGR": "1"}
    assert said.startswith("Document Manager")


def test_with_no_key_it_runs_on_what_it_has_and_says_so():
    env, said = runner.model_reader_for("busy", {})
    assert env == {"SDI_SW_RUN_ANALYSER": "0"}
    assert "no model reader" in said and "drawings" in said


def test_the_run_holding_the_token_uses_solidworks_as_configured():
    env, said = runner.model_reader_for("held", {})
    assert env == {} and said.startswith("SolidWorks: this run holds")


def test_a_slot_without_the_token_declares_itself_honestly(monkeypatch):
    monkeypatch.delenv("SDI_SW_RUN_ANALYSER", raising=False)
    monkeypatch.delenv("SDI_SW_DOCMGR", raising=False)
    monkeypatch.delenv("SDI_SW_DOCMGR_KEY", raising=False)
    caps = runner.runner_capabilities(token_busy=True)
    assert "desktop_token" in caps and "no_models" in caps
    assert "sw_extract" not in caps, "a SolidWorks extract needs the SolidWorks token"
    monkeypatch.setenv("SDI_SW_DOCMGR_KEY", KEY)
    assert "no_models" not in runner.runner_capabilities(token_busy=True)
    alone = runner.runner_capabilities()
    assert "desktop_token" in alone and "sw_extract" in alone and "no_models" not in alone


def test_compute_headroom_is_measured_against_the_settings():
    ok, said = runner.compute_headroom(min_free_gb=0.0, max_cpu_pct=100.0)
    assert ok
    short, said2 = runner.compute_headroom(min_free_gb=1e9, max_cpu_pct=100.0)
    if "not measurable" in said2:
        assert short, "what cannot be measured is not held against the run"
    else:
        assert not short and "GB free" in said2
