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


def test_stopping_an_enquiry_says_whether_the_engine_was_actually_working(api):
    """The runner is another process on another machine. Claiming to have cancelled it
    would have somebody walk away from a live SOLIDWORKS session."""
    er, tmp_path, enquiry = api
    _check_in(er)
    out = _batch(er, tmp_path, enquiry, n=3)
    running = _check_in(er)["run"]["run_id"]
    er.batch_abandon(out["batch_id"])
    assert "still working" in er._RUNS[running].error
    assert "had not started" in er._RUNS[out["queued"][1]].error


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
