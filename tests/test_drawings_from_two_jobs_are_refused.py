"""Drawings from two different job folders are refused, not silently queued against their parent.

10575-02 was queued with one stray 11650 model still in the file list. os.path.commonpath always
returns something, so the job folder was promoted to "...\\Live Enquiry" — the folder that
CONTAINS the jobs. The engine looked there, found no drawings directly beneath it, exited cleanly
and filed nothing. The page reported COMPLETE and produced no estimate, which is the worst way for
a run to fail: it looks like it worked.

A pack that files its drawings into sub-folders of ONE job must keep working. The two situations
are told apart by SDI's naming: a job folder is named for its job number and begins with a digit
(10575-02-V2UprightDisplay, 11650-04-SidePanel); PDFs\\ and DXFs\\ do not.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_REPO, "sdi-intelligence-backend")


@pytest.fixture(scope="module")
def client():
    pytest.importorskip("fastapi", reason="fastapi not installed")
    out = tempfile.mkdtemp()
    os.environ["SDI_FILE_ROOTS"] = out
    os.environ["SDI_ESTIMATE_OUTPUT_ROOT"] = out
    # The access gate is off for this fixture: what is under test is which folder a set of
    # drawings resolves to, not authentication. Left set, a key from another test's environment
    # answers 401 before the routing logic is ever reached.
    #
    # RESTORED AFTERWARDS, because clearing it is not this test's business beyond its own run.
    # Left cleared, the override endpoint's "this write path is behind the key" test finds no
    # key to assert against and SKIPS — an auth test on a write path quietly not running, caused
    # by a fixture two files earlier in the alphabet.
    _saved_key = os.environ.get("SDI_API_KEY")
    os.environ["SDI_API_KEY"] = ""
    _clash = ("config", "estimate_routes", "app", "log_filters", "hr_routes")
    saved = {n: sys.modules.pop(n) for n in _clash if n in sys.modules}
    sys.path.insert(0, _BACKEND)
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import estimate_routes as _er
        app = FastAPI()
        app.include_router(_er.router)
        yield TestClient(app), out
    except Exception as exc:                                    # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        try:
            sys.path.remove(_BACKEND)
        except ValueError:
            pass
        for n in _clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)
        if _saved_key is None:
            os.environ.pop("SDI_API_KEY", None)
        else:
            os.environ["SDI_API_KEY"] = _saved_key


def _post(c, files, root, units=1):
    return c.post("/api/estimate", json={
        "files": files, "units": units, "drawing_number": "10575-02", "client": "Dyson"})


def test_files_from_two_job_folders_are_refused_by_name(client):
    """THE 10575-02 FAILURE. The message must name the folders, so the stray file is findable."""
    c, root = client
    r = _post(c, [os.path.join(root, "10575-02-V2Upright", "a.pdf"),
                  os.path.join(root, "11650-04-SidePanel", "11650-04-01A.SLDPRT")], root)
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "10575-02-V2Upright" in detail and "11650-04-SidePanel" in detail
    assert "different job folders" in detail


def test_files_in_one_job_folder_are_accepted(client):
    """The ordinary case must be untouched — refusing it would break every normal run."""
    c, root = client
    job = os.path.join(root, "10575-02-V2Upright")
    os.makedirs(job, exist_ok=True)
    r = _post(c, [os.path.join(job, "a.pdf"), os.path.join(job, "b.dxf")], root)
    assert r.status_code != 400 or "different job folders" not in r.json().get("detail", "")


def test_sub_folders_of_one_job_are_accepted(client):
    """A pack that files drawings into PDFs\\ and DXFs\\ shares one job as its parent — those
    folders are not named for a job number, so they are not two jobs."""
    c, root = client
    job = os.path.join(root, "10575-02")
    os.makedirs(os.path.join(job, "PDFs"), exist_ok=True)
    os.makedirs(os.path.join(job, "DXFs"), exist_ok=True)
    r = _post(c, [os.path.join(job, "PDFs", "a.pdf"), os.path.join(job, "DXFs", "b.dxf")], root)
    assert r.status_code != 400 or "different job folders" not in r.json().get("detail", "")
