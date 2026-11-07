"""A fitting is charged once; the run holding SolidWorks is named; the wall gives an ETA and the
accuracy to expect (D-738).

12002-02-GA, 7 Nov 2026 13:19 book, review: "Hankbush fitting is charged twice ... Row 153
charges £8.19 for hardware insertion. Row 161 charges £7.79 for base assembly, and its recorded
reason explicitly says it is fitting the same M6 hankbush. Keep one appropriate fitting
allowance."

JG, the same day: "we wait up to 30 minutes with feedback to the control panel of the wait time
and which job is currently using the solid works com api license. we only switch to the
document manager api when the 30 minutes is up and we don't kill the job" and "if we can
provide an ETA of when the run might finish also and accuracy result expectation."
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(ROOT / "src"))

import route_compiler as rc  # noqa: E402
import solidworks_turn as swt  # noqa: E402

J = "12002-02"
HANK_WORDS = ("Inferred method. Sheet 2/8 BOM item 3 is M6 HANKBUSH, qty 1, and the GA prints M6 "
              "HANKBUSH. No part drawing and no press, clinch or weld instruction. Booked once "
              "per base as a fit, not as a second weld.")


# ── ONE FITTING ──────────────────────────────────────────────────────────────────────────

def _base(welded=True):
    steel = lambda pn, d: {"part_number": pn, "quantity": 1, "description": d,  # noqa: E731
                           "normalized_material": "MILD STEEL", "normalized_thickness_mm": 3.0}
    base = {"part_number": f"{J}-101", "quantity": 1, "description": "SA STAND BASE",
            "is_sub_assembly": True, "assembly_children": [f"{J}-M01", f"{J}-M02", "BI-HANKBUSH"]}
    if welded:
        base.update({"weld_stated_by_note": True, "textual_operations": ["welding"],
                     "operation_sources": {"welding": "drawing_deterministic"}})
    return [{"part_number": f"{J}-GA", "quantity": 1, "is_assembly_parent": True,
             "assembly_children": [f"{J}-101"]}, base,
            steel(f"{J}-M01", "BASE PLATE"), steel(f"{J}-M02", "BASE UPRIGHT"),
            {"part_number": "BI-HANKBUSH", "quantity": 1, "is_bought_in": True,
             "description": "M6 HANKBUSH"}]


def _compile(parts, words):
    out = rc.compile_job_route(
        parts, {"routes": [{"operation": "assembly", "part_numbers": [f"{J}-M01"],
                            "scope": "assembly", "inferred": True, "notes": words}]},
        known_assemblies=[f"{J}-GA", f"{J}-101"], declared_product=f"{J}-GA")
    return [d if isinstance(d, dict) else d.__dict__ for d in out["decisions"]]


def _on_101(ds, op):
    return [d for d in ds if d["target_id"] == f"{J}-101" and d["operation"] == op]


def test_the_bench_row_that_only_fits_the_insert_is_not_charged_beside_the_insertion():
    ds = _compile(_base(), HANK_WORDS)
    (ins,) = _on_101(ds, "hardware_insertion")
    assert ins["status"] == rc.REQUIRED and ins["participants"] == ["BI-HANKBUSH"]
    (asm,) = _on_101(ds, "assembly")
    assert asm["status"] == rc.NOT_APPLICABLE
    assert "fitted by the hardware insertion" in asm["reason"]
    assert "HANKBUSH" in asm["reason"], "the read's own words stay on the record"


def test_an_assemble_whose_words_do_not_name_the_insert_still_stands():
    ds = _compile(_base(), "Bolt the base plate to the upright before coating.")
    (asm,) = _on_101(ds, "assembly")
    assert asm["status"] == rc.REQUIRED


def test_on_an_assembly_its_weld_does_not_build_the_assemble_still_stands():
    ds = _compile(_base(welded=False), HANK_WORDS)
    assert all(d["status"] == rc.REQUIRED for d in _on_101(ds, "assembly"))


def test_the_insert_is_named_by_its_distinctive_words_never_by_a_word_every_fixing_shares():
    graph = {"records": {"BI-HANKBUSH": {"description": "M6 HANKBUSH"},
                         "BI-SCREW": {"description": "M6 SCREW INSERT"}}}
    words = rc._insert_words(["BI-HANKBUSH", "BI-SCREW"], graph)
    assert "HANKBUSH" in words and "BI-HANKBUSH" in words
    assert "SCREW" not in words and "INSERT" not in words


# ── THE LICENCE HOLDER, NAMED ────────────────────────────────────────────────────────────

def test_the_wait_is_thirty_minutes_by_default(monkeypatch):
    monkeypatch.delenv(swt.WAIT_ENV, raising=False)
    assert swt.TURN_WAIT_LIMIT == 30.0 and swt.wait_minutes() == 30.0


def test_the_holder_writes_its_name_a_waiter_says_it_and_the_name_goes_with_the_turn(
        tmp_path, monkeypatch):
    token = tmp_path / "solidworks.token"
    monkeypatch.setenv("SDI_SERVICE_RUN_ID", "4b1c2d9e")
    monkeypatch.setenv("SDI_SUBMITTED_SCOPE", json.dumps({"drawing_number": "12677-01-GA"}))
    said = []
    held, turn = swt.take_turn(path=token, wait_s=0, say=said.append)
    assert turn["state"] == swt.HELD
    assert said == ["SolidWorks turn taken: this run reads its models now."]
    holder = swt.read_holder(token)
    assert holder["drawing_number"] == "12677-01-GA" and holder["run_id"] == "4b1c2d9e"
    assert holder["pid"] == os.getpid()

    # A second run on the desktop waits, and says who has SolidWorks.
    ticks = iter([0.0, 0.0, 400.0, 400.0, 2000.0, 2000.0])
    words = []
    _h, t2 = swt.take_turn(path=token, wait_s=1800, update_s=300, say=words.append,
                           sleep=lambda s: None, clock=lambda: next(ticks))
    assert t2["state"] == swt.TIMED_OUT and t2["holder"]["drawing_number"] == "12677-01-GA"
    assert words[0].startswith("Waiting for the desktop's SolidWorks: 12677-01-GA (run 4b1c2d) "
                               "has had it")
    assert "up to 30 minutes" in words[0]
    assert words[1].startswith("Still waiting for the desktop's SolidWorks: 7 min so far, up to "
                               "30. 12677-01-GA (run 4b1c2d) has had it")
    swt.release(held, token)
    assert swt.read_holder(token) is None, "the name goes with the turn"


def test_a_probe_never_writes_a_name(tmp_path):
    token = tmp_path / "solidworks.token"
    assert swt.busy(token) is False
    assert swt.read_holder(token) is None


def test_the_engine_says_when_it_gives_the_turn_back():
    src = (ROOT / "src" / "source_connectors" / "solidworks.py").read_text(encoding="utf-8")
    assert "SolidWorks turn given back: the next run may read its models." in src


# ── THE SERVICE AND THE WALL ─────────────────────────────────────────────────────────────

def _wall():
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_wall
        return estimate_wall
    finally:
        sys.path.remove(str(BACKEND))


NOW = 1_800_000_000.0


def _done(i, minutes, drawing="D", price=None, ago_h=3.0):
    fin = NOW - ago_h * 3600 - i
    return {"run_id": f"d{i}", "drawing_number": drawing if drawing != "D" else f"D-{i}",
            "client": "M&S", "job_type": "", "status": "done", "queued_at": fin - minutes * 60,
            "started_at": fin - minutes * 60, "finished_at": fin, "runner": "lap",
            "engine_price_gbp": price, "log": []}


HIST = [_done(i, m) for i, m in enumerate((18, 20, 22, 19, 21, 26))] + [
    _done(9, 20, drawing=f"{J}-GA", price=408.74, ago_h=1.0)]


def test_the_wall_names_the_holder_and_each_waiter_against_the_limit(monkeypatch):
    w = _wall()
    monkeypatch.delenv("SDI_SW_TURN_WAIT_MINUTES", raising=False)
    holder = {"run_id": "a", "drawing_number": "12677-01-GA", "client": "Harley", "job_type": "",
              "status": "running", "started_at": NOW - 600, "queued_at": NOW - 620,
              "runner": "lap", "sw_turn_at": NOW - 300,
              "log": ["SolidWorks turn taken: this run reads its models now."]}
    waiter = {"run_id": "b", "drawing_number": f"{J}-GA", "client": "M&S", "job_type": "",
              "status": "running", "started_at": NOW - 500, "queued_at": NOW - 510,
              "runner": "lap-s2", "sw_wait_since": NOW - 420,
              "log": ["Waiting for the desktop's SolidWorks: 12677-01-GA (run a) has had it "
                      "for 2 min. This run waits its turn, up to 30 minutes."]}
    runners = [{"runner_id": "lap", "hostname": "LAPTOP", "online": True, "run_id": "a"},
               {"runner_id": "lap-s2", "hostname": "LAPTOP", "online": True, "run_id": "b"},
               {"runner_id": "srv", "hostname": "SDI-APP01", "online": True}]
    snap = w.snapshot(HIST + [holder, waiter], runners, now=NOW, max_runs=3)
    machines = {m["host"]: m for m in snap["solidworks"]}
    lap = machines["LAPTOP"]
    assert lap["holder"]["drawing_number"] == "12677-01-GA" and lap["holder"]["held_s"] == 300
    (wt,) = lap["waiting"]
    assert (wt["drawing_number"], wt["waited_s"], wt["limit_s"], wt["left_s"]) == (
        f"{J}-GA", 420, 1800, 1380)
    assert machines["SDI-APP01"]["state"] == "free"
    live = {r["run_id"]: r for r in snap["live"]}
    assert live["b"]["rag"] == "amber"
    assert "7 of 30 min" in live["b"]["rag_reason"] and "12677-01-GA" in live["b"]["rag_reason"]
    assert live["b"]["evidence"]["label"] == "Waiting for SolidWorks"
    assert live["b"]["last_result"]["engine_price_gbp"] == 408.74


def test_the_eta_is_a_window_plus_this_runs_waits_and_the_queue_starts_when_a_slot_frees():
    w = _wall()
    run = {"run_id": "r", "job_type": "", "status": "running", "started_at": NOW - 600,
           "sw_waited_s": 120.0, "sw_wait_since": NOW - 300}
    win = {"lo_s": 1000.0, "mid_s": 1200.0, "hi_s": 1500.0}
    e = w.eta(run, NOW, win)
    assert (e["eta_lo_at"], e["eta_at"], e["eta_hi_at"]) == (
        NOW - 600 + 1000 + 420, NOW - 600 + 1200 + 420, NOW - 600 + 1500 + 420)
    assert e["overdue_s"] == 0 and e["waited_s"] == 420
    # The window the run was given when it started wins over today's.
    given = w.eta({**run, "predicted": {"lo_s": 10.0, "mid_s": 20.0, "hi_s": 30.0}}, NOW, win)
    assert given["eta_at"] == NOW - 600 + 20 + 420
    q = [{"run_id": "q1", "job_type": ""}, {"run_id": "q2", "job_type": ""},
         {"run_id": "q3", "job_type": "sw_extract"}]
    live = [{"eta_at": NOW + 300}]
    out = w.queue_etas(q, live, NOW, 1, 1200.0, None)
    assert (out[0]["start_at"], out[0]["finish_at"]) == (NOW + 300, NOW + 1500)
    assert out[1]["start_at"] == NOW + 1500
    assert out[2]["start_at"] is None, "no history for extracts, so no guess"
    two = w.queue_etas(q[:2], live, NOW, 2, 1200.0, None)
    assert two[0]["start_at"] == NOW, "a free slot starts it now"


@pytest.mark.parametrize("line, kind, label", [
    ("   [solidworks] model extract APPLIED (flat+4)", "sw", "SolidWorks measured model"),
    ("   [solidworks] read by the Document Manager BACKUP reader — SolidWorks timed out",
     "dm_fallback", "Document Manager fallback · not yet validated"),
    ("  SWITCHING TO THE DOCUMENT MANAGER for this run's models", "dm_fallback",
     "Document Manager fallback · not yet validated"),
    ("  the desktop's SolidWorks stayed in use ...: this run goes on without its models",
     "drawings", "Drawing/DXF evidence"),
    ("   [solidworks] NOT APPLIED — no _sw_native_extract.json for this job", "drawings",
     "Drawing/DXF evidence"),
    ("engine started", "pending", "Model read not reached yet"),
])
def test_the_wall_states_what_read_the_models_never_an_accuracy(line, kind, label):
    """The 7 Nov review: "Reader type is not estimate accuracy". Only the unvalidated
    Document Manager fallback carries a caution."""
    w = _wall()
    got = w.evidence({"job_type": "", "log": ["engine started", line]})
    assert (got["kind"], got["label"]) == (kind, label)
    assert got["caution"] is (kind == "dm_fallback")
    assert not hasattr(w, "accuracy")


def test_history_is_read_net_of_its_own_waits_so_a_delay_is_not_counted_twice():
    w = _wall()
    runs = [{**_done(i, 20), "sw_waited_s": 600.0 if i == 0 else 0.0} for i in range(4)]
    runs[0]["started_at"] -= 600                              # 30 min, 10 of them waiting
    assert w.net_duration(runs[0]) == 1200.0
    win = w.predict_window(runs, NOW, 30)
    assert win["mid_s"] == 1200.0 and win["n"] == 4 and "net of" in win["basis"]
    assert w.predict_window(runs[:2], NOW, 30) is None


def test_the_eta_error_is_measured_against_the_runs_that_finish():
    w = _wall()
    assert w.eta_error([], NOW) == {"n": 0, "median_abs_error_s": None, "inside_pct": None}
    win = {"lo_s": 1000.0, "mid_s": 1200.0, "hi_s": 1400.0}
    runs = [{**_done(1, 20), "predicted": win},               # 1200 s: inside, error 0
            {**_done(2, 25), "predicted": win},               # 1500 s: outside, error 300
            {**_done(3, 21), "predicted": win}]               # 1260 s: inside, error 60
    e = w.eta_error(runs, NOW)
    assert (e["n"], e["median_abs_error_s"], e["inside_pct"]) == (3, 60.0, 67.0)


def test_a_finished_run_shows_what_still_needs_a_person_from_the_engines_tally():
    w = _wall()
    run = {**_done(5, 20), "review": {"total": 14, "missing": 0, "decisions": 3,
                                      "quantity_checks": 5, "provisional": 6, "phrase": "x"}}
    snap = w.snapshot([run], [{"runner_id": "lap", "hostname": "L", "online": True}], now=NOW)
    oi = snap["recent"][0]["open_items"]
    assert (oi["total"], oi["decisions"], oi["quantity_checks"], oi["provisional"]) == (14, 3, 5, 6)


def test_the_engine_says_its_open_items_as_one_line():
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert 'print("REVIEW_TALLY=" + json.dumps({' in src
    for key in ('"missing"', '"decisions"', '"provisional"', '"quantity_checks"'):
        assert key in src


def test_a_second_runner_on_a_desktop_is_its_slot(monkeypatch):
    w = _wall()
    monkeypatch.setenv("SDI_WALL_FLEET", "LAPTOP=Laptop")
    snap = w.snapshot([], [{"runner_id": "LAPTOP-90fa", "hostname": "LAPTOP", "online": True},
                           {"runner_id": "LAPTOP-90fa-s2", "hostname": "LAPTOP", "online": True}],
                      now=NOW)
    assert sorted(f["label"] for f in snap["fleet"]) == ["Laptop", "Laptop · slot 2"]


def test_the_service_keeps_each_runs_solidworks_state_from_its_own_words():
    sys.path.insert(0, str(BACKEND))
    try:
        src = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    finally:
        sys.path.remove(str(BACKEND))
    assert "_note_solidworks_turn(run, text, now)" in src
    assert "sw_turn_at: float = 0.0" in src and "sw_wait_since: float = 0.0" in src
    page = (BACKEND / "sdi-estimating-wall.html").read_text(encoding="utf-8")
    for needle in ("renderSolidWorks", "eta_lo_at", "Models:", "last run", "starts ~",
                   "ETA error", "openItems"):
        assert needle in page
    assert "Accuracy" not in page


@pytest.fixture
def svc(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history",
             "estimate_wall")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    sys.path.insert(0, str(BACKEND))
    try:
        import estimate_routes as er
        yield er
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        sys.path.remove(str(BACKEND))
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_the_service_totals_each_wait_and_keeps_the_tally(svc):
    er = svc
    run = er.Run(run_id="r1", client="M&S", drawing_number=f"{J}-GA", units=1,
                 job_folder="/x", output_path="/y")
    er._note_solidworks_turn(run, "  Waiting for the desktop's SolidWorks: X has had it", 100.0)
    assert run.sw_wait_since == 100.0
    er._note_solidworks_turn(run, "  SolidWorks is free after 300 s: this run reads", 400.0)
    assert (run.sw_waited_s, run.sw_wait_since, run.sw_turn_at) == (300.0, 0.0, 400.0)
    er._note_solidworks_turn(run, "  SolidWorks turn given back: the next run may read", 700.0)
    assert run.sw_turn_at == 0.0 and run.sw_waited_s == 300.0
    er._note_solidworks_turn(run, 'REVIEW_TALLY={"total": 14, "provisional": 6}', 900.0)
    assert run.review == {"total": 14, "provisional": 6}
