"""The Technical Design workflow maps are on the portal menu, below SDI Drawing Search.

Two standalone pages from Technical Design (full and compact) that map creative input to
released production files, with the SDI Design Vault and the automation opportunities marked.
They live in sdi-intelligence-backend/workflows/ so push-to-server carries them to SDI-APP01
with the rest of the backend, and are served by a fixed list so no URL can reach another file.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BACKEND = _REPO / "sdi-intelligence-backend"
_PORTAL = (_BACKEND / "sdi-intelligence-portal.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client():
    pytest.importorskip("fastapi", reason="fastapi not installed")
    out = tempfile.mkdtemp()
    os.environ["SDI_FILE_ROOTS"] = out
    os.environ["SDI_ESTIMATE_OUTPUT_ROOT"] = out
    _clash = ("config", "estimate_routes", "app", "log_filters", "hr_routes")
    saved = {n: sys.modules.pop(n) for n in _clash if n in sys.modules}
    sys.path.insert(0, str(_BACKEND))
    try:
        from fastapi.testclient import TestClient
        import app as backend
        yield TestClient(backend.app)
    except Exception as exc:                                    # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        try:
            sys.path.remove(str(_BACKEND))
        except ValueError:
            pass
        for n in _clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


@pytest.mark.parametrize("name,marker", [
    ("technical-design", "From Creative Intent to Released Production Files"),
    ("technical-design-compact", "Compact Technical Design Workflow"),
])
def test_each_workflow_page_is_served(client, name, marker):
    r = client.get(f"/workflow/{name}")
    assert r.status_code == 200
    assert marker in r.text
    assert "no-store" in r.headers.get("cache-control", "")


def test_a_name_off_the_list_is_not_a_file_path(client):
    for bad in ("../app.py", "app.py", "nothing-here"):
        assert client.get(f"/workflow/{bad}").status_code == 404


def test_both_are_on_the_menu_directly_below_drawing_search():
    nav = _PORTAL[_PORTAL.index('<nav class="nav">'):_PORTAL.index("</nav>")]
    links = re.findall(r'<a [^>]*>(?:<svg.*?</svg>)?([^<]+)</a>', nav, re.S)
    at = links.index("SDI Drawing Search Intelligence")
    assert links[at + 1:at + 3] == ["Technical Design Workflow",
                                    "Technical Design Workflow · Compact"], links
    assert 'href="/workflow/technical-design"' in nav
    assert 'href="/workflow/technical-design-compact"' in nav


def test_the_pages_travel_to_the_server_with_the_backend():
    push = (_REPO / "tools" / "start" / "push-to-server.ps1").read_text(encoding="utf-8")
    assert '"sdi-intelligence-backend/"' in push
    for f in ("technical-design-workflow.html", "technical-design-workflow-compact.html"):
        assert (_BACKEND / "workflows" / f).is_file(), f
