"""More than one run at once, where it is safe (D-703, SCRUM-183 phase 1).

claim() refused every runner while ANY run was running, so a second runner on another machine
sat idle beside a queue of work, although the service's own docstring said "capacity comes from
more runners". The rule it protects is narrower: one desktop drives one SolidWorks and one
estimate. Now a claim is refused when this runner, or another runner on the same desktop,
already has a run, or when the number running has reached SDI_MAX_CONCURRENT_RUNS (default 1,
the old behaviour). A pack that needs a model reader is not handed to a runner that says it has
none ("no_models"), so it is not priced from PDF and DXF alone on one machine and from models on
another.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"


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
    monkeypatch.delenv("SDI_MAX_CONCURRENT_RUNS", raising=False)
    return er, tmp_path


def _queue(er, tmp_path, job, drawing):
    return er.start(er.EstimateRequest(client="Boots", drawing_number=drawing, units=1,
                                       job_folder=str(tmp_path / job),
                                       output_root=str(tmp_path / "share")))["run_id"]


def _claim(er, runner_id, host, caps=()):
    return er.claim(er.ClaimRequest(runner_id=runner_id, hostname=host,
                                    capabilities=list(caps)))


def _two_queued(er, tmp_path):
    _claim(er, "laptop", "LAPTOP")
    a = _queue(er, tmp_path, "a", "AAA")
    b = _queue(er, tmp_path, "b", "BBB")
    return a, b


def test_by_default_one_run_at_a_time_as_before(api):
    er, tmp_path = api
    a, b = _two_queued(er, tmp_path)
    assert _claim(er, "laptop", "LAPTOP")["run"]["run_id"] == a
    got = _claim(er, "server", "SDI-APP01")
    assert got["run"] is None and got["reason"] == "another run is in progress"


def test_with_two_allowed_a_runner_on_another_machine_takes_the_next(api, monkeypatch):
    er, tmp_path = api
    monkeypatch.setenv("SDI_MAX_CONCURRENT_RUNS", "2")
    a, b = _two_queued(er, tmp_path)
    assert _claim(er, "laptop", "LAPTOP")["run"]["run_id"] == a
    assert _claim(er, "server", "SDI-APP01")["run"]["run_id"] == b
    assert er._RUNS[a].runner == "laptop" and er._RUNS[b].runner == "server"


def test_one_desktop_still_runs_one_estimate(api, monkeypatch):
    er, tmp_path = api
    monkeypatch.setenv("SDI_MAX_CONCURRENT_RUNS", "3")
    a, b = _two_queued(er, tmp_path)
    assert _claim(er, "laptop", "LAPTOP")["run"]["run_id"] == a
    again = _claim(er, "laptop", "LAPTOP")
    assert again["run"] is None and "already has a run" in again["reason"]
    twin = _claim(er, "laptop-2", "LAPTOP")
    assert twin["run"] is None and "one desktop" in twin["reason"]
    assert er._RUNS[b].status == "queued", "job B waits, it is not lost"


def test_the_cap_holds(api, monkeypatch):
    er, tmp_path = api
    monkeypatch.setenv("SDI_MAX_CONCURRENT_RUNS", "2")
    _claim(er, "laptop", "LAPTOP")
    runs = [_queue(er, tmp_path, j, d) for j, d in (("a", "AAA"), ("b", "BBB"), ("c", "CCC"))]
    assert _claim(er, "laptop", "LAPTOP")["run"]["run_id"] == runs[0]
    assert _claim(er, "server", "SDI-APP01")["run"]["run_id"] == runs[1]
    third = _claim(er, "box3", "THIRD")
    assert third["run"] is None and third["reason"] == "another run is in progress"


def test_a_pack_needing_a_model_reader_goes_to_a_runner_that_has_one(api, monkeypatch):
    er, tmp_path = api
    monkeypatch.setenv("SDI_MAX_CONCURRENT_RUNS", "2")
    (tmp_path / "a" / "12693-02-GA.SLDASM").write_bytes(b"model")
    _claim(er, "laptop", "LAPTOP")
    a = _queue(er, tmp_path, "a", "AAA")
    staged = er._RUNS[a].job_folder
    if not er._needs_model_reader(staged):
        # A staged pack may carry its models by address, in staging's MODEL_SOURCES_FILENAME,
        # instead of as files: the rule must see that pointer the same as the models.
        Path(staged, "_sdi_model_sources.json").write_text('{"models_folders": []}')
    assert er._needs_model_reader(staged)
    refused = _claim(er, "server", "SDI-APP01", caps=["sw_extract", "no_models"])
    assert refused["run"] is None and "need a model reader" in refused["reason"]
    assert _claim(er, "laptop", "LAPTOP", caps=["sw_extract"])["run"]["run_id"] == a


def test_a_fresh_extract_lets_a_runner_without_models_take_it(api, monkeypatch, tmp_path):
    er, _ = api
    folder = tmp_path / "pack"
    folder.mkdir()
    (folder / "x.SLDPRT").write_bytes(b"model")
    assert er._needs_model_reader(folder)
    extract = folder / "_sw_native_extract.json"
    extract.write_text("[]")
    os.utime(extract, (os.path.getmtime(folder / "x.SLDPRT") + 10,) * 2)
    assert not er._needs_model_reader(folder), "the extract already holds what the models say"


def test_a_pack_with_no_models_goes_to_any_runner(api, monkeypatch):
    er, tmp_path = api
    monkeypatch.setenv("SDI_MAX_CONCURRENT_RUNS", "2")
    _claim(er, "laptop", "LAPTOP")
    a = _queue(er, tmp_path, "a", "AAA")
    assert _claim(er, "server", "SDI-APP01", caps=["no_models"])["run"]["run_id"] == a


def test_the_runner_says_no_models_only_when_it_has_no_reader(monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner as runner
    monkeypatch.delenv("SDI_SW_RUN_ANALYSER", raising=False)
    monkeypatch.delenv("SDI_SW_DOCMGR", raising=False)
    assert "no_models" not in runner.runner_capabilities()
    monkeypatch.setenv("SDI_SW_RUN_ANALYSER", "0")
    assert "no_models" in runner.runner_capabilities()
    monkeypatch.setenv("SDI_SW_DOCMGR_KEY", "test-key-not-real")
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    assert "no_models" not in runner.runner_capabilities()
    monkeypatch.setenv("SDI_SW_DOCMGR", "on")
    assert "no_models" not in runner.runner_capabilities(), "on means on, as the engine reads it"


def test_the_backup_switch_without_its_key_is_no_reader(monkeypatch):
    """SCRUM-184: the Document Manager reads nothing without its licence key, so a runner with
    the switch on and no key must not take a job that needs models."""
    sys.path.insert(0, str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner as runner
    monkeypatch.setenv("SDI_SW_RUN_ANALYSER", "0")
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    monkeypatch.delenv("SDI_SW_DOCMGR_KEY", raising=False)
    assert "no_models" in runner.runner_capabilities()
