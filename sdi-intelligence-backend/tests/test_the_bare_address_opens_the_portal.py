"""The bare public address opens the app portal (11 Nov 2026).

JG opened https://sdiintelligence-sdidisplays.msappproxy.net with nothing after it and got {"detail":"Not Found"}:
the root is the office intranet page, never public, so the public guard refused it. It now sends people to /app/,
the page they are meant to land on, and everything else that is not public is still refused as before.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
PUBLIC = "sdiintelligence.example.net"


@pytest.fixture()
def outside(monkeypatch):
    # The app checks its settings as it loads; without these it refuses, and that refusal would be a skip
    # (SCRUM-137: the estimator guide went untested that way). Test-only values, never the server's.
    out = tempfile.mkdtemp()
    monkeypatch.setenv("SDI_FILE_ROOTS", out)
    monkeypatch.setenv("SDI_ALLOWED_ORIGINS", "http://localhost")
    monkeypatch.setenv("SDI_ESTIMATE_OUTPUT_ROOT", out)
    # A fresh import with these settings: an earlier test may have loaded config without them. What was
    # loaded before is put back afterwards, as tests/test_the_estimator_guide_is_served.py does.
    clash = ("config", "estimate_routes", "app", "log_filters", "hr_routes")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    try:
        import app as backend
        monkeypatch.setattr(backend, "_PUBLIC_HOSTS", {PUBLIC})
        c = TestClient(backend.app, follow_redirects=False)
        yield lambda method, path: c.request(method, path, headers={"host": PUBLIC})
    except Exception as exc:                                       # noqa: BLE001
        pytest.fail(f"the backend did not load: {exc}")
    finally:
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_the_bare_address_goes_to_the_app_portal(outside):
    for method in ("GET", "HEAD"):
        r = outside(method, "/")
        assert r.status_code == 302, (method, r.status_code)
        assert r.headers["location"] == "/app/"


def test_the_intranet_stays_closed_from_outside(outside):
    for path in ("/api/hr/sync", "/api/db", "/sdi-intelligence-portal.html", "/guide"):
        assert outside("GET", path).status_code == 404, path
    assert outside("POST", "/").status_code == 404                 # only a page visit is redirected
