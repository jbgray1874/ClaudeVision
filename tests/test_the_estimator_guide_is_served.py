"""The estimator's guide is served by the portal, from the same origin as the page it explains.

A guide that has to be emailed is a guide nobody has when they need it. This one is one click
from the run button, and it covers every deliverable an estimator is handed: the Estimate sheet
they edit, the two tabs that explain it, the job report, and what "drawings missing" looks like.
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
    # The backend has its own `config`; displace the engine's for the import, then restore.
    _clash = ("config", "estimate_routes", "app", "log_filters", "hr_routes")
    saved = {n: sys.modules.pop(n) for n in _clash if n in sys.modules}
    sys.path.insert(0, _BACKEND)
    try:
        from fastapi.testclient import TestClient
        import app as backend
        yield TestClient(backend.app)
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


def test_the_guide_is_served(client):
    r = client.get("/guide")
    assert r.status_code == 200
    assert len(r.text) > 4000                      # a real document, not a stub


def test_it_covers_every_deliverable_an_estimator_is_handed(client):
    body = client.get("/guide").text.lower()
    for section in ("estimate sheet", "ai provenance", "decision report",
                    "job report", "client quote"):
        assert section in body, section


def test_it_explains_the_incomplete_pack_case(client):
    """The case that most needs explaining: a priced job whose pack was missing drawings."""
    body = client.get("/guide").text.lower()
    assert "drawings missing" in body or "missing drawings" in body
    assert "priced from what we have" in body or "incomplete pack" in body


def test_it_tells_the_estimator_to_save_in_excel_before_regenerating(client):
    """The one operational trip-hazard on the override path — the totals are formulas."""
    body = client.get("/guide").text.lower()
    assert "excel" in body and "save" in body


def test_the_estimating_page_links_to_it(client):
    assert "/guide" in client.get("/estimating").text


def test_both_standalone_pages_keep_the_left_hand_navigation(client):
    """THE DEAD END. /estimating and /guide are their own documents, so the portal's sidebar
    vanished the moment an estimator opened either and the only way back was the browser's Back
    button — on the page they use daily, that reads as having left the system. Both now carry the
    navigation, and every entry links into the portal's hash routes."""
    for path in ("/estimating", "/guide"):
        body = client.get(path).text
        assert "sdinav" in body, f"{path} has no sidebar"
        assert "is-here" in body, f"{path} does not mark where you are"
        assert "/#files" in body and "/#tools" in body, f"{path} cannot get back to the portal"


def test_the_guide_is_named_for_the_product(client):
    assert "SDI Estimating Intelligence Guide" in client.get("/guide").text
