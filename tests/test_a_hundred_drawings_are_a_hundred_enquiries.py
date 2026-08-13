r"""
test_a_hundred_drawings_are_a_hundred_enquiries.py

TWO SHAPES OF JOB, AND CONFUSING THEM PRODUCES A CONFIDENT ANSWER TO THE WRONG QUESTION.

11650 is four drawings that are ONE cabinet. They share a BOM, they share a route, and
pooling them is the entire point -- that is main.py --job, and getting it wrong there
produces four partial estimates where one belonged.

An M&S enquiry is the opposite: a hundred PDFs that are a hundred unrelated products, each
wanting its own price. Pooling those would produce a single meaningless total. That is
main.py --pdf, one drawing at a time.

Both shapes already existed in the engine. Neither could be submitted:

  * start() raised 409 whenever anything was RUNNING, so the first drawing was claimed
    within five seconds and the other ninety-nine were all refused. The one-at-a-time rule
    is real, but it is a rule about EXECUTION and claim() is where it lives. Queueing is not
    executing, and a queue that refuses work while it is working is not a queue.

  * the runner had no way to be told which question was asked. Both arrive as paths under
    the same share, so it cannot be inferred, and inferring it wrongly is the worst kind of
    wrong available here: not a failure, a plausible estimate of something else.

Filed as  <root>/<client>/<drawing>/<dated run>  -- the existing convention, with the
drawing taken from the PDF's own filename. The filename is deliberate: it is knowable
BEFORE the run, so a drawing that fails still has a named folder, and the estimator can
match it against the file the customer sent them.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
RUNNER_DIR = ROOT / "tools" / "runner"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    stub = types.ModuleType("config")
    stub.API_KEY = ""
    stub.FILE_ROOTS = [str(tmp_path)]
    monkeypatch.setitem(sys.modules, "config", stub)
    monkeypatch.syspath_prepend(str(BACKEND))
    sys.modules.pop("estimate_routes", None)
    er = pytest.importorskip("estimate_routes",
                             reason="fastapi/pydantic not installed in this environment")
    er._RUNS.clear(); er._RUNNERS.clear()
    # NO REAL SCAN THREAD, AND NOT BECAUSE IT IS SLOW. The default method is "both", so
    # every batch below would otherwise spawn a daemon thread that outlives its test, keeps
    # mutating Run objects after the registry has been cleared, and reaches for x.ai. The
    # symptom was a suite that passed on one run and failed on the next -- which is worse
    # than failing, because the failures get re-run rather than read. The scan has its own
    # tests, with a stub, further down.
    er.REAL_SCAN_BATCH = er._scan_batch          # kept so a test can run the real one
    monkeypatch.setattr(er, "_scan_batch", lambda runs: None)
    enquiry = tmp_path / "M and S enquiry"
    enquiry.mkdir(exist_ok=True)
    return er, tmp_path, enquiry


def _pdfs(folder, n):
    out = []
    for i in range(n):
        p = folder / f"MS-{1000 + i} SHELF UNIT.pdf"
        p.write_text("%PDF-1.4")
        out.append(str(p))
    return out


def _check_in(er, runner_id="rnr-1", host="DESKTOP"):
    return er.claim(er.ClaimRequest(runner_id=runner_id, hostname=host))


def _batch(er, tmp_path, enquiry, n=5, client="M & S", units=100):
    return er.batch(er.BatchRequest(client=client, units=units, files=_pdfs(enquiry, n),
                                    output_root=str(tmp_path / "share")))


# ── the enquiry is accepted whole ───────────────────────────────────────────────────
def test_every_drawing_is_queued_not_just_the_first(api):
    """The defect in one line: with start()'s 409 in place, one of these would have been
    accepted and the rest refused."""
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=100)
    assert len(out["queued"]) == 100
    assert all(er._RUNS[r].status == "queued" for r in out["queued"])


def test_they_run_one_at_a_time_and_in_the_order_they_were_given(api):
    """An estimator working down a customer's list wants the answers in that list's order,
    and one Excel automation at a time on one desktop."""
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=4)
    first = _check_in(er)["run"]
    assert first["run_id"] == out["queued"][0], "the queue did not start at the top"
    assert _check_in(er, "rnr-2")["run"] is None, (
        "a second drawing was handed out while one was running — two COM automations")
    er.complete(first["run_id"], er.CompleteRequest(runner_id="rnr-1", status="done"))
    assert _check_in(er)["run"]["run_id"] == out["queued"][1]


def test_the_order_is_recorded_and_not_inherited_from_a_dictionary(api):
    """claim() hands out the oldest queued run, so "oldest" has to mean something. Stamping
    every drawing in an enquiry with one timestamp leaves the order resting on dict
    insertion order and a stable sort — true in CPython today, and not a property anyone
    writing the next change would think to preserve. The list's order is the customer's
    order, so it is written down."""
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=5)
    stamps = [er._RUNS[r].queued_at for r in out["queued"]]
    assert stamps == sorted(stamps) and len(set(stamps)) == len(stamps), (
        "every drawing carries the same queued_at, so their order is only whatever the "
        "registry happens to iterate in")


def test_each_drawing_files_into_its_own_folder_under_the_client(api):
    """<root>/<client>/<drawing>/<dated run>. One client folder, one folder per drawing,
    and a dated folder inside so a re-run never overwrites an earlier answer."""
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=3)
    paths = [Path(er._RUNS[r].output_path) for r in out["queued"]]
    assert len({p.parent.parent for p in paths}) == 1, "the drawings landed under different clients"
    assert paths[0].parent.parent.name == "M & S"
    assert len({p.parent.name for p in paths}) == 3, "two drawings share a folder"
    assert paths[0].parent.name == "MS-1000 SHELF UNIT", (
        "the folder is not named from the drawing the customer sent")
    assert "(100 off)" in paths[0].name, "the quantity is not in the run folder name"
    assert out["client_folder"].endswith("M & S")


def test_the_runner_is_told_this_is_one_drawing_and_not_a_pack(api):
    """It cannot be inferred — both arrive as paths under the same share — and inferring it
    wrongly gives a confident estimate of a different question."""
    er, tmp_path, enquiry = api
    _check_in(er)
    _batch(er, tmp_path, enquiry, n=2)
    handed = _check_in(er)["run"]
    assert handed["pdf_path"].endswith("MS-1000 SHELF UNIT.pdf")


def test_the_command_asks_the_engine_the_single_drawing_question(api, monkeypatch):
    """THE TWO ENDS TOGETHER. The service says "this is one drawing" and the runner has to
    turn that into --pdf; asserting either alone leaves the pair free to disagree, and the
    symptom of them disagreeing is a plausible number, not an error."""
    er, tmp_path, enquiry = api
    monkeypatch.syspath_prepend(str(RUNNER_DIR))
    import sdi_estimate_runner as runner
    _check_in(er)
    _batch(er, tmp_path, enquiry, n=1)
    handed = _check_in(er)["run"]

    cmd = runner.engine_command(tmp_path, Path("python.exe"), Path(handed["job_folder"]),
                                handed["units"], handed["client"],
                                pdf=Path(handed["pdf_path"]))
    assert "--pdf" in cmd and "--job" not in cmd
    assert cmd[cmd.index("--pdf") + 1] == handed["pdf_path"]
    assert "--deliverables" in cmd
    assert cmd[cmd.index("--customer") + 1] == "M & S"


def test_a_pooled_pack_still_asks_the_folder_question(api, monkeypatch):
    """The other half of the same pair. 11650 must keep pooling."""
    er, tmp_path, enquiry = api
    monkeypatch.syspath_prepend(str(RUNNER_DIR))
    import sdi_estimate_runner as runner
    cmd = runner.engine_command(tmp_path, Path("python.exe"), enquiry, 45, "Boots")
    assert "--job" in cmd and "--pdf" not in cmd


# ── what it refuses, and what it says ───────────────────────────────────────────────
def test_a_drawing_outside_the_share_is_refused_by_name(api):
    er, tmp_path, enquiry = api
    _check_in(er)
    out = er.batch(er.BatchRequest(client="M & S", units=100,
                                   files=_pdfs(enquiry, 2) + [r"C:\Windows\notepad.pdf"],
                                   output_root=str(tmp_path / "share")))
    assert len(out["queued"]) == 2
    assert len(out["refused"]) == 1 and "notepad" in out["refused"][0]["file"]


def test_an_enquiry_that_queued_nothing_is_not_reported_as_submitted(api):
    """200 with an empty list reads on the page as accepted, and the estimator waits for a
    hundred answers nobody is producing."""
    er, tmp_path, _ = api
    _check_in(er)
    with pytest.raises(er.HTTPException) as exc:
        er.batch(er.BatchRequest(client="M & S", units=100,
                                 files=[r"C:\Windows\notepad.pdf"],
                                 output_root=str(tmp_path / "share")))
    assert exc.value.status_code == 400


def test_no_runner_means_no_enquiry_is_accepted(api):
    """A hundred jobs queued against nothing that will ever run them is worse than one."""
    er, tmp_path, enquiry = api
    with pytest.raises(er.HTTPException) as exc:
        _batch(er, tmp_path, enquiry, n=3)
    assert exc.value.status_code == 503
    assert not er._RUNS


@pytest.mark.parametrize("client,units", [("", 100), ("   ", 100), ("M & S", 0),
                                          ("M & S", -1)])
def test_an_enquiry_without_a_client_or_a_quantity_is_refused(api, client, units):
    er, tmp_path, enquiry = api
    _check_in(er)
    with pytest.raises(er.HTTPException):
        er.batch(er.BatchRequest(client=client, units=units, files=_pdfs(enquiry, 1),
                                 output_root=str(tmp_path / "share")))


# ── watching a hundred of them ──────────────────────────────────────────────────────
def test_the_whole_enquiry_is_readable_in_one_request(api):
    """A hundred separate status polls every two seconds is a hundred requests a tick, and
    the per-run log that makes one run readable is noise when you want a list of answers."""
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=4)
    first = _check_in(er)["run"]
    er.complete(first["run_id"], er.CompleteRequest(
        runner_id="rnr-1", status="done",
        deliverables=[{"name": "MS-1000.xlsx", "path": "x"}]))

    view = er.batch_status(out["batch_id"])
    assert view["total"] == 4 and view["finished"] == 1 and view["failed"] == 0
    assert [r["drawing_number"] for r in view["runs"]] == \
        [er._RUNS[r].drawing_number for r in out["queued"]], "the order is not the list order"
    assert view["runs"][0]["deliverables"][0]["name"] == "MS-1000.xlsx"
    assert view["client"] == "M & S"


def test_a_failed_drawing_is_counted_and_does_not_stop_the_rest(api):
    """Ninety-nine good answers must not be lost because one drawing would not read."""
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=3)
    first = _check_in(er)["run"]
    er.complete(first["run_id"], er.CompleteRequest(runner_id="rnr-1", status="error",
                                                    error="could not read the drawing"))
    view = er.batch_status(out["batch_id"])
    assert view["failed"] == 1 and view["finished"] == 1
    assert _check_in(er)["run"]["run_id"] == out["queued"][1], "the queue stopped at a failure"


def test_an_unknown_enquiry_is_not_an_empty_one(api):
    """A batch id the service does not hold must not come back as a successful enquiry of
    zero drawings — that reads as "all done" to anything counting finished against total."""
    er, _, _ = api
    with pytest.raises(er.HTTPException) as exc:
        er.batch_status("does-not-exist")
    assert exc.value.status_code == 404


# ── stopping one ────────────────────────────────────────────────────────────────────
def test_the_rest_of_an_enquiry_can_be_stopped_in_one_go(api):
    """A hundred queued drawings is the case where changing your mind costs ninety-nine
    clicks. Finished drawings keep their estimates."""
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=5)
    first = _check_in(er)["run"]
    er.complete(first["run_id"], er.CompleteRequest(runner_id="rnr-1", status="done"))

    released = er.batch_abandon(out["batch_id"])["released"]
    assert released == 4
    assert er._RUNS[out["queued"][0]].status == "done", "a finished estimate was thrown away"
    assert all(er._RUNS[r].status == "error" for r in out["queued"][1:])
    assert _check_in(er)["run"] is None, "a released enquiry was still handed out"


def test_stopping_an_enquiry_stops_the_drawing_being_worked_on(api):
    """THIS TEST USED TO ASSERT THE OPPOSITE, and was right to at the time: the runner is
    another process on another machine, nothing could reach it, and the message said so --
    "if the runner was still working, its result will be refused when it reports". Claiming
    to have cancelled it would have had somebody walk away from a live SOLIDWORKS session.

    The single-run stop then learned to end the engine, by riding the heartbeat the runner
    already sends. A batch is the same act ninety-nine times over and had no reason to mean
    less -- otherwise stopping a hundred-drawing enquiry left the one in progress driving
    SOLIDWORKS and Excel for the fifteen minutes it had left, on work already given up on.

    Queued and running still read differently, because they are different: one had not
    started and the other has an engine to end.
    """
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=3)
    running = _check_in(er)["run"]["run_id"]
    er.batch_abandon(out["batch_id"])

    live = er._RUNS[running]
    assert live.cancel_requested is True, "the runner is never told to stop"
    assert "ends the engine" in live.error
    assert "had not started" in er._RUNS[out["queued"][1]].error


def test_a_stopped_enquiry_refuses_the_runner_the_moment_it_speaks(api):
    """The message that actually arrives. Once the run is not "running", the progress
    endpoint refuses the post -- and that 409 is what the runner acts on, because the request
    carrying the cancel flag is the one being rejected."""
    import pytest as _pytest
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=2)
    claim = _check_in(er)["run"]
    er.batch_abandon(out["batch_id"])
    with _pytest.raises(Exception) as exc:
        er.progress(claim["run_id"],
                    er.ProgressRequest(runner_id="rnr-1", lines=[]))
    assert getattr(exc.value, "status_code", None) == 409


def test_a_finished_drawing_keeps_its_estimate_when_the_rest_is_stopped(api):
    """The whole point of stopping the REST. An estimator who spots the wrong folder after
    twenty drawings should keep the twenty."""
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=3)
    first = _check_in(er)["run"]["run_id"]
    er._RUNS[first].status = "done"
    er.batch_abandon(out["batch_id"])
    assert er._RUNS[first].status == "done"
    assert er._RUNS[first].cancel_requested is False


def test_one_enquiry_does_not_release_another(api):
    er, tmp_path, enquiry = api
    _check_in(er)
    a = _batch(er, tmp_path, enquiry, n=2, client="M & S")
    other = enquiry.parent / "other"
    other.mkdir(exist_ok=True)
    b = er.batch(er.BatchRequest(client="Boots", units=45, files=_pdfs(other, 2),
                                 output_root=str(tmp_path / "share")))
    er.batch_abandon(a["batch_id"])
    assert all(er._RUNS[r].status == "queued" for r in b["queued"])


# ── the page ────────────────────────────────────────────────────────────────────────
PAGE = BACKEND / "sdi-estimating-intelligence.html"


def _page():
    return PAGE.read_text(encoding="utf-8")


def test_the_page_has_its_own_section_and_calls_the_batch_endpoints():
    """A SEPARATE SECTION BECAUSE IT IS A DIFFERENT QUESTION. Folding it into the Job panel
    would make the difference between "price this pack" and "price each of these" a
    checkbox — and getting that checkbox wrong does not fail, it returns a confident
    estimate of a question nobody asked."""
    page = _page()
    assert "Multi-drawing enquiry" in page
    assert '"/api/estimate/batch"' in page, "the page never submits an enquiry"
    assert "/api/estimate/batch/" in page, "the page never asks how the enquiry is going"
    assert "/abandon" in page


def test_the_page_uses_one_file_picker_for_both_lists():
    """The enquiry selects files exactly as the Job panel does — same shares, same
    containment rule, same server-resolved paths. A second copy of the browser would be a
    second place for the path rules to drift, and the paths are the one thing that must
    mean the same to the engine as they do on screen."""
    page = _page()
    assert page.count("async function openBrowser") == 1
    assert "pickList()" in page and "pickSet(" in page, (
        "the picker writes straight into `drawings` again, so the enquiry either shares the "
        "Job panel's list or needs a second browser")


def test_the_enquiry_button_is_gated_on_the_same_things_the_job_button_is():
    """A hundred jobs queued against a client nobody typed files a hundred estimates under
    a folder called nothing, and un-filing them is manual."""
    page = _page()
    block = page[page.index("function renderBatch()"):page.index("function bSet(")]
    for needed in ("client", "number of units", "at least one drawing", "a connected runner"):
        assert needed in block, f"the enquiry can be started with no {needed}"


def test_refused_drawings_are_named_on_the_page():
    """A hundred submitted and ninety-seven queued is a fact the estimator has to be told
    at the moment it happens. Three missing answers are invisible in a list of ninety-seven."""
    assert "could NOT be queued" in _page()


def test_the_page_script_parses():
    """THIRTY-THREE KILOBYTES OF INLINE SCRIPT, and a single syntax error anywhere in it
    blanks the entire page — no console for the estimator, no error on the server, just a
    dead screen. Cheap to check and impossible to notice otherwise."""
    import shutil
    import subprocess
    import re
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    script = re.search(r"<script>(.*)</script>", _page(), re.S)
    assert script, "the page has no script block at all"
    proc = subprocess.run([node, "--check", "-"], input=script.group(1),
                          capture_output=True, text=True)
    assert proc.returncode == 0, f"the page's script does not parse:\n{proc.stderr[:600]}"


# ── two methods, side by side ───────────────────────────────────────────────────────
# 11650-00 took about forty minutes on the runner and estimates run one at a time, so a
# hundred drawings through the engine alone is sixty hours. The LLM read answers in seconds
# and is independent of the engine — it shares none of its rate tables, nesting rules or
# catalogue lookups — so where the two disagree the disagreement carries information. That
# is the reason to run both rather than to pick the faster one.

def _stub_model(monkeypatch, price=41.5, found=True):
    """Stand in for GROK, and for nothing else.

    THE FIRST VERSION OF THIS REPLACED _scan_batch, which meant the stub re-implemented the
    production logic it was meant to be testing -- who gets marked finished, when a refusal
    becomes None rather than zero -- and three mutants walked straight through it. What is
    under test is the service's wiring; the only thing that has to be faked is the model.
    """
    import types
    stub = types.ModuleType("llm_scan_price")
    stub.scan_price = lambda pdf, units, **k: (
        {"found": True, "price_gbp": price, "basis": "2mm panel, laser and fold",
         "confidence": 0.4, "source": "llm_scan_estimate_grok"} if found else
        {"found": False, "why": "no material or size given"})
    monkeypatch.setitem(sys.modules, "llm_scan_price", stub)


def _scan_now(er, out):
    """Run the REAL _scan_batch over this enquiry, in the foreground.

    Production spawns a daemon thread so the HTTP request can return; a test that let that
    thread run would be racing it. Calling the same function directly keeps every line of
    it under test and keeps the result deterministic.
    """
    er.REAL_SCAN_BATCH([er._RUNS[r] for r in out["queued"]])


def test_both_methods_land_on_the_same_row(api, monkeypatch):
    """The comparison is the deliverable. Two numbers in two places nobody joins up is two
    reports, not a cross-check."""
    er, tmp_path, enquiry = api
    _stub_model(monkeypatch)
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=3)
    _scan_now(er, out)
    view = er.batch_status(out["batch_id"])
    assert view["runs"][0]["llm_price_gbp"] == 41.5
    assert "laser and fold" in view["runs"][0]["llm_basis"]
    assert view["runs"][0]["status"] == "queued", (
        "the LLM answer must not be mistaken for the engine having finished")


def test_an_llm_only_enquiry_never_waits_for_a_runner(api, monkeypatch):
    """It needs no SOLIDWORKS seat and no Excel. Queued as ordinary work it would sit in
    front of real jobs for ever, waiting for a machine that has nothing to do with it."""
    er, tmp_path, enquiry = api
    _stub_model(monkeypatch)
    out = er.batch(er.BatchRequest(client="M & S", units=100, method="llm",
                                   files=_pdfs(enquiry, 3),
                                   output_root=str(tmp_path / "share")))
    assert len(out["queued"]) == 3
    # THE FIRST CLAIM, not the second. Asking twice and checking the second is None passes
    # even when the first was wrongly handed a scan-only drawing, because one run being in
    # progress is itself enough to make the second answer None.
    assert _check_in(er)["run"] is None, "a scan-only drawing was handed to a runner"


def test_an_llm_only_enquiry_is_accepted_with_no_runner_connected(api, monkeypatch):
    """Refusing it because a laptop is closed would withhold the one method that can answer
    a hundred drawings today."""
    er, tmp_path, enquiry = api
    _stub_model(monkeypatch)
    out = er.batch(er.BatchRequest(client="M & S", units=100, method="llm",
                                   files=_pdfs(enquiry, 2),
                                   output_root=str(tmp_path / "share")))
    assert len(out["queued"]) == 2


def test_a_full_enquiry_is_still_refused_with_no_runner(api, monkeypatch):
    """The other half. Queueing engine work nobody will ever run is the failure the 503
    exists for, and adding a second method must not open a hole in it."""
    er, tmp_path, enquiry = api
    _stub_model(monkeypatch)
    for method in ("both", "engine"):
        with pytest.raises(er.HTTPException) as exc:
            er.batch(er.BatchRequest(client="M & S", units=100, method=method,
                                     files=_pdfs(enquiry, 2),
                                     output_root=str(tmp_path / "share")))
        assert exc.value.status_code == 503, method


def test_a_scan_only_enquiry_can_actually_finish(api, monkeypatch):
    """Left queued after its scan, an LLM-only drawing counts against the enquiry total for
    ever and the page never says it is done. A progress bar that cannot reach the end is
    worse than no progress bar."""
    er, tmp_path, enquiry = api
    _stub_model(monkeypatch)
    out = er.batch(er.BatchRequest(client="M & S", units=100, method="llm",
                                   files=_pdfs(enquiry, 4),
                                   output_root=str(tmp_path / "share")))
    _scan_now(er, out)
    view = er.batch_status(out["batch_id"])
    assert view["finished"] == view["total"] == 4


def test_a_drawing_the_model_would_not_price_says_so_and_is_not_zero(api, monkeypatch):
    """Zero reads as a part that costs nothing to make. "I could not price this" has to
    stay that all the way to the row."""
    er, tmp_path, enquiry = api
    _stub_model(monkeypatch, found=False)
    out = er.batch(er.BatchRequest(client="M & S", units=100, method="llm",
                                   files=_pdfs(enquiry, 2),
                                   output_root=str(tmp_path / "share")))
    _scan_now(er, out)
    row = er.batch_status(out["batch_id"])["runs"][0]
    assert row["llm_price_gbp"] is None
    assert "no material or size" in row["llm_basis"]


def test_an_unknown_method_is_refused_rather_than_guessed(api):
    er, tmp_path, enquiry = api
    _check_in(er)
    with pytest.raises(er.HTTPException) as exc:
        er.batch(er.BatchRequest(client="M & S", units=100, method="magic",
                                 files=_pdfs(enquiry, 1),
                                 output_root=str(tmp_path / "share")))
    assert exc.value.status_code == 400


def test_the_engine_method_asks_no_model_at_all(api, monkeypatch):
    """A method called "engine" that quietly also bills an LLM account is not the method it
    says it is."""
    er, tmp_path, enquiry = api
    called = []
    monkeypatch.setattr(er, "_scan_batch", lambda runs: called.append(len(runs)))
    _check_in(er)
    er.batch(er.BatchRequest(client="M & S", units=100, method="engine",
                             files=_pdfs(enquiry, 3),
                             output_root=str(tmp_path / "share")))
    assert called == [], "the scan ran for a method that did not ask for it"


def test_the_engine_price_reaches_the_row_so_there_is_something_to_compare(api, monkeypatch):
    """A column of AI figures with nothing to check them against is the opposite of the
    point of running two methods."""
    er, tmp_path, enquiry = api
    _stub_model(monkeypatch)
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=2)
    _scan_now(er, out)
    run_id = _check_in(er)["run"]["run_id"]
    er.complete(run_id, er.CompleteRequest(runner_id="rnr-1", status="done",
                                           unit_cost_gbp=137.17))
    row = er.batch_status(out["batch_id"])["runs"][0]
    assert row["engine_price_gbp"] == 137.17 and row["llm_price_gbp"] == 41.5


def test_the_runner_finds_the_unit_cost_in_the_summary_it_filed(tmp_path, monkeypatch):
    """THE REAL READER over the real shape. The service never opens an estimate — the
    runner is the machine that has the file — so if this misses, the page silently shows no
    engine price and the comparison quietly becomes a single column."""
    import json as _json
    monkeypatch.syspath_prepend(str(RUNNER_DIR))
    import sdi_estimate_runner as runner
    summary = tmp_path / "11650-00.json"
    summary.write_text(_json.dumps({
        "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": 137.1742}}))
    assert runner._unit_cost_from_deliverables(
        [{"name": "11650-00.json", "path": str(summary)}]) == 137.17


def test_an_older_summary_shape_is_still_read():
    """The summary has grown over time. A runner that knows only the newest key reports
    nothing on an older record — and reporting nothing looks exactly like an estimate that
    produced no price."""
    import sys as _sys
    _sys.path.insert(0, str(RUNNER_DIR))
    import sdi_estimate_runner as runner
    assert runner.unit_cost_from(
        {"headline_cost_price": {"total_unit_cost_gbp": 99.5}}) == 99.5


def test_a_summary_with_no_price_reports_none_not_zero(tmp_path, monkeypatch):
    """Zero would show on the page as an estimate of nothing, beside an AI figure of forty
    pounds, and the variance column would read -100%."""
    import json as _json
    monkeypatch.syspath_prepend(str(RUNNER_DIR))
    import sdi_estimate_runner as runner
    bad = tmp_path / "x.json"
    bad.write_text(_json.dumps({"headline_cost_price": {"total_unit_cost_gbp": 0}}))
    assert runner._unit_cost_from_deliverables([{"name": "x.json", "path": str(bad)}]) is None
    assert runner.unit_cost_from({}) is None
    assert runner.unit_cost_from("not a summary") is None


def test_an_unreadable_summary_does_not_take_the_completion_down_with_it(tmp_path,
                                                                        monkeypatch):
    """The estimate is filed by this point. Failing to report it because one JSON will not
    parse would lose a finished run over a cosmetic column."""
    monkeypatch.syspath_prepend(str(RUNNER_DIR))
    import sdi_estimate_runner as runner
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert runner._unit_cost_from_deliverables(
        [{"name": "broken.json", "path": str(broken)},
         {"name": "gone.json", "path": str(tmp_path / "nope.json")}]) is None


def test_the_page_shows_both_and_labels_which_is_which():
    """A column of bare pound signs, half from Grok and half from the engine, is one
    copy-and-paste away from a quote going out on a number nobody costed."""
    page = (BACKEND / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
    assert "AI £" in page and "engine £" in page
    assert "apart)" in page, "the variance between the two methods is not shown"
    assert "NOT a quote" in page, "nothing on the page says what the LLM figure is not"


def test_the_completion_actually_carries_the_engine_price(tmp_path, monkeypatch):
    """THE CALLER. _unit_cost_from_deliverables can be perfect and _finish can still post
    None, and every test above would pass — the reader is exercised directly, the service
    is handed a figure directly, and the one line that joins them is asserted nowhere. That
    exact gap let this mutant through on the first pass."""
    import json as _json
    monkeypatch.syspath_prepend(str(RUNNER_DIR))
    import sdi_estimate_runner as runner

    summary = tmp_path / "11650-00.json"
    summary.write_text(_json.dumps(
        {"workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": 137.17}}))

    posted = {}

    class _Req:
        @staticmethod
        def post(url, json=None, headers=None, timeout=None):
            posted.update(json or {})

            class _R:
                @staticmethod
                def raise_for_status():
                    return None
            return _R()

    runner._finish(_Req(), "http://x/api/estimate", {}, "r1", "rnr-1", "done", "", [],
                   deliverables=[{"name": "11650-00.json", "path": str(summary)}])
    assert posted.get("unit_cost_gbp") == 137.17, (
        "the runner read the price and then did not send it")
