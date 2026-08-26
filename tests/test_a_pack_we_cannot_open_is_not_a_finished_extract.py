"""The two Document Manager routes — the layer between the page and the client, which had no
tests at all.

WHAT WAS AND WAS NOT COVERED. `docmgr.py` is well tested: the secret never leaks, a 401 is
explained as the secret rather than the network, COM-down is refused before a job is sent. All of
that is the CLIENT. The two routes that sit between the page and that client —
`POST /dm/extract` and `GET /dm/extract/{job_id}` — were never exercised by anything.

That is the wrong half to leave untested, because the client talks to an API somebody else
defined and got right, while the routes do the part NOBODY ELSE IS DOING FOR US: deciding whether
a pack that DM says it wrote is a pack this machine can actually open. The route's own docstring
calls it "THE PART THAT WILL BITE, AND IT IS NOT AN API PROBLEM".

THE FAILURE IT GUARDS AGAINST. DM returns `outputDir` as a path on ITS OWN host. If that folder
is not a share we can read, the extract genuinely succeeded, the API call genuinely worked, and
the drawings are still out of reach — and every symptom appears at OUR end, minutes later, in a
file browser that lists nothing. An estimator sees "Extract finished" and an empty folder, and
there is nothing in that pairing that points at the real cause.

So `readable_here` is the assertion that matters here, in all four combinations: a folder that is
there, one that is not, one outside SDI_FILE_ROOTS, and a completed job that named no folder at
all. Three of those four are "succeeded but unusable", and each has a different fix.

WHY IT IS WORTH WRITING NOW, with the Document Manager host off the network for days. None of
this needs that host. It is precisely the part that does not: our side of the integration, tested
against a stub, so that when the machine reappears the only unknown left is theirs. Waiting means
the first real exercise of this code is on the day it is needed.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _StubDocMgr:
    """Stands in for docmgr. The client is tested elsewhere; what matters here is what the
    routes do with whatever it hands back."""

    class DocMgrError(Exception):
        pass

    def __init__(self):
        self.started = None
        self.start_result = {"jobId": "J-1", "status": "queued", "requested": {},
                             "sourcePath": r"\\cad\projects\11650"}
        self.start_error = None
        self.job_result = {}
        self.job_error = None

    def start_extract(self, project_number, *, customer="", assembly_folder=""):
        if self.start_error:
            raise self.DocMgrError(self.start_error)
        self.started = (project_number, customer, assembly_folder)
        return self.start_result

    def job(self, job_id):
        if self.job_error:
            raise self.DocMgrError(self.job_error)
        return dict(self.job_result)


@pytest.fixture(scope="module")
def env():
    """A real readable root, so 'the pack is there' is a fact on disk rather than a mock."""
    pytest.importorskip("fastapi", reason="fastapi not installed")
    root = tempfile.mkdtemp()
    os.environ["SDI_FILE_ROOTS"] = root
    os.environ.setdefault("SDI_ESTIMATE_OUTPUT_ROOT", root)

    # Same isolation as the override endpoint's test: the engine's `config` is already imported
    # in this interpreter under the same name, and the backend's `import config` would find it.
    _clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr")
    saved = {n: sys.modules.pop(n) for n in _clash if n in sys.modules}
    backend_dir = os.path.join(_REPO, "sdi-intelligence-backend")
    sys.path.insert(0, backend_dir)
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import estimate_routes as _er
        app = FastAPI()
        app.include_router(_er.router)
        tc = TestClient(app)
        key = getattr(_er.config, "API_KEY", "") or ""
        if key:
            tc.headers.update({"X-SDI-Key": key})
        yield tc, _er, root
    except Exception as exc:                                    # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        try:
            sys.path.remove(backend_dir)
        except ValueError:
            pass
        for n in _clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


@pytest.fixture()
def dm(env, monkeypatch):
    tc, er, root = env
    stub = _StubDocMgr()
    monkeypatch.setattr(er, "docmgr", stub)
    return tc, stub, root


# ── asking for a pack ──────────────────────────────────────────────────────────

def test_the_job_id_comes_back_so_the_page_has_something_to_follow(dm):
    tc, stub, _ = dm
    r = tc.post("/api/estimate/dm/extract", json={"project_number": "11650"})
    assert r.status_code == 200
    assert r.json()["job_id"] == "J-1"


def test_the_three_fields_reach_the_client_unchanged(dm):
    tc, stub, _ = dm
    tc.post("/api/estimate/dm/extract",
            json={"project_number": "11650", "customer": "M&S", "assembly_folder": "11650-02"})
    assert stub.started == ("11650", "M&S", "11650-02")


def test_a_refusal_is_a_sentence_and_not_a_stack_trace(dm):
    """DocMgrError carries text written for an estimator. A 500 would replace it with
    'Internal Server Error' and lose the only thing that says what to do."""
    tc, stub, _ = dm
    stub.start_error = ("The Document Manager host is up but cannot drive SolidWorks right now "
                        "(comAvailable=false).")
    r = tc.post("/api/estimate/dm/extract", json={"project_number": "11650"})
    assert r.status_code == 400
    assert "cannot drive SolidWorks" in r.json()["detail"]


def test_an_unreachable_host_is_reported_rather_than_raised(dm):
    """Today's actual state: the host went home in somebody's bag. It must arrive at the page
    as a readable 400, not as a broken endpoint."""
    tc, stub, _ = dm
    stub.start_error = ("The Document Manager at http://DESKTOP-4F3TLJN:8000 could not be "
                        "reached (ConnectTimeout). Its host must be online.")
    r = tc.post("/api/estimate/dm/extract", json={"project_number": "11650"})
    assert r.status_code == 400
    assert "must be online" in r.json()["detail"]


# ── whether the pack can actually be opened ────────────────────────────────────

def test_a_pack_on_a_share_we_can_read_is_usable(dm):
    tc, stub, root = dm
    pack = os.path.join(root, "11650")
    os.makedirs(pack, exist_ok=True)
    stub.job_result = {"status": "completed", "finished": True, "ok": True,
                       "output_dir": pack, "file_count": 12}
    body = tc.get("/api/estimate/dm/extract/J-1").json()
    assert body["readable_here"] is True
    assert body["note"] == "", "a usable pack must not carry a warning"
    assert body["file_count"] == 12


def test_a_pack_on_their_host_is_not_called_usable(dm):
    """THE ASSERTION THIS FILE EXISTS FOR. The API call worked, the job says completed, and the
    folder is on a machine we cannot see. Reporting that as finished sends an estimator to an
    empty browser with no idea why."""
    tc, stub, root = dm
    inside_but_absent = os.path.join(root, "never-created")
    stub.job_result = {"status": "completed", "finished": True, "ok": True,
                       "output_dir": inside_but_absent, "file_count": 12}
    body = tc.get("/api/estimate/dm/extract/J-1").json()
    assert body["ok"] is True, "the extract really did succeed and must not be recast as a failure"
    assert body["readable_here"] is False
    assert "not reachable from this machine" in body["note"]
    assert "Document Manager's own host" in body["note"]


def test_a_pack_outside_the_permitted_roots_names_the_setting_to_change(dm):
    """A different fault with a different fix — the folder exists and this service is not
    allowed to read it. Saying 'not reachable' would send somebody to the network instead."""
    tc, stub, _ = dm
    elsewhere = tempfile.mkdtemp()                       # real, readable, outside SDI_FILE_ROOTS
    stub.job_result = {"status": "completed", "finished": True, "ok": True,
                       "output_dir": elsewhere, "file_count": 3}
    body = tc.get("/api/estimate/dm/extract/J-1").json()
    assert body["readable_here"] is False
    assert "SDI_FILE_ROOTS" in body["note"]


def test_a_completed_job_that_named_no_folder_says_there_is_nothing_to_import(dm):
    tc, stub, _ = dm
    stub.job_result = {"status": "completed", "finished": True, "ok": True,
                       "output_dir": None, "file_count": None}
    body = tc.get("/api/estimate/dm/extract/J-1").json()
    assert body["readable_here"] is False
    assert "nothing to import" in body["note"]


def test_a_drive_letter_from_their_machine_is_translated_before_it_is_judged(dm):
    """A mapped letter means nothing to a service. Judging containment against 'K:\\packs' fails
    for a folder that is right there — staging failed exactly this way once."""
    tc, stub, root = dm
    cfg = sys.modules["estimate_routes"].config
    old = getattr(cfg, "DRIVE_MAP", None)
    cfg.DRIVE_MAP = {"K": root}
    try:
        stub.job_result = {"status": "completed", "finished": True, "ok": True,
                           "output_dir": "K:\\", "file_count": 4}
        body = tc.get("/api/estimate/dm/extract/J-1").json()
        assert body["output_dir"] == root, "the letter reached the containment check untranslated"
        assert body["readable_here"] is True
    finally:
        if old is None:
            delattr(cfg, "DRIVE_MAP")
        else:
            cfg.DRIVE_MAP = old


# ── the states, and not inventing one ──────────────────────────────────────────

def test_a_running_job_is_not_finished_and_not_usable(dm):
    tc, stub, _ = dm
    stub.job_result = {"status": "running", "finished": False, "ok": False,
                       "progress": "reading references", "output_dir": None}
    body = tc.get("/api/estimate/dm/extract/J-1").json()
    assert body["finished"] is False and body["readable_here"] is False
    assert body["progress"] == "reading references"


def test_a_failed_job_carries_its_reason_and_no_note_of_ours(dm):
    """DM's own error is the useful thing. Adding one of our own about folders would bury it."""
    tc, stub, _ = dm
    stub.job_result = {"status": "failed", "finished": True, "ok": False,
                       "error": "SolidWorks refused to open 11650-02.SLDASM", "output_dir": None}
    body = tc.get("/api/estimate/dm/extract/J-1").json()
    assert body["ok"] is False
    assert body["error"] == "SolidWorks refused to open 11650-02.SLDASM"
    assert body["note"] == ""


def test_losing_track_of_a_job_is_a_sentence_too(dm):
    tc, stub, _ = dm
    stub.job_error = "The Document Manager has no record of that job (404)."
    r = tc.get("/api/estimate/dm/extract/J-1")
    assert r.status_code == 400
    assert "no record of that job" in r.json()["detail"]


# ── the gate ───────────────────────────────────────────────────────────────────

def test_neither_route_can_be_driven_without_the_key(dm):
    """These two reach out to somebody else's CAD host and start minutes of work on it. An
    unauthenticated caller must not be able to queue that."""
    tc, stub, _ = dm
    key = getattr(sys.modules["estimate_routes"].config, "API_KEY", "") or ""
    if not key:
        pytest.skip("no API key configured in this environment, so there is no gate to test")
    bare = {"X-SDI-Key": "not-the-key"}
    assert tc.post("/api/estimate/dm/extract", json={"project_number": "1"},
                   headers=bare).status_code in (401, 403)
    assert tc.get("/api/estimate/dm/extract/J-1", headers=bare).status_code in (401, 403)
