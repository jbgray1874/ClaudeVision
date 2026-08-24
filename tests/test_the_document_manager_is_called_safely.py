"""The Document Manager client: the secret stays server-side, and a pack we cannot read says so.

Two things here would do real damage if they were wrong, and neither is about happy paths.

THE SECRET. DM authenticates with ONE shared access secret covering every consumer. Putting it
anywhere a browser can see it hands every visitor the ability to drive somebody else's CAD host.
So the portal calls our backend and our backend holds the key — and the key must never appear in
a log line, an error message, or anything returned to the page.

THE PACK WE CANNOT READ. DM reports `outputDir` as a path on ITS OWN host. Unless that is a share
this machine can also read, the extract genuinely succeeded and the drawings are still
unreachable — and every symptom shows up at our end, in a browser listing nothing, long after an
API call that "worked". A job reported as usable when it is not is the expensive failure.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "sdi-intelligence-backend"


@pytest.fixture()
def dm(monkeypatch):
    """The module with a stub config — the real one wants a .env."""
    stub = types.ModuleType("config")
    stub.DM_API_BASE = "http://dm-host:8000"
    stub.DM_API_KEY = "s3cr3t-not-a-real-key"
    monkeypatch.setitem(sys.modules, "config", stub)
    spec = importlib.util.spec_from_file_location("docmgr", _BACKEND / "docmgr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


# ── the secret ──────────────────────────────────────────────────────────────────────────

def test_the_key_is_sent_as_the_header_dm_expects(dm):
    assert dm._headers()["X-API-Key"] == "s3cr3t-not-a-real-key"


def test_health_is_called_without_the_key(dm, monkeypatch):
    """`GET /health` takes no key by DM's own contract, and sending one anyway would put the
    secret on a call that does not need it."""
    seen = {}

    def _get(url, **kw):
        seen["url"] = url
        seen["headers"] = kw.get("headers")
        return _Resp(payload={"status": "ok", "comAvailable": True})

    monkeypatch.setattr(dm, "_requests", lambda: types.SimpleNamespace(get=_get))
    dm.health()
    assert seen["url"].endswith("/health")
    assert not seen["headers"], "the health check must not carry the access secret"


def test_no_error_message_ever_contains_the_key(dm, monkeypatch):
    """An exception string reaches the page and the run log. The key must not travel with it."""
    def _get(url, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(dm, "_requests", lambda: types.SimpleNamespace(get=_get))
    with pytest.raises(dm.DocMgrError) as exc:
        dm.health()
    assert "s3cr3t" not in str(exc.value)


def test_a_401_is_explained_as_the_secret_not_as_the_network(dm, monkeypatch):
    """'HTTP 401' sends somebody to the firewall. It is the shared secret, every time."""
    monkeypatch.setattr(dm, "_requests",
                        lambda: types.SimpleNamespace(get=lambda *a, **k: _Resp(401)))
    with pytest.raises(dm.DocMgrError) as exc:
        dm.health()
    msg = str(exc.value)
    assert "401" in msg and "secret" in msg.lower()
    assert "s3cr3t" not in msg


def test_missing_configuration_names_the_setting(dm, monkeypatch):
    monkeypatch.setattr(dm.config, "DM_API_KEY", "")
    monkeypatch.delenv("DOCMGR_ACCESS_SECRET", raising=False)
    with pytest.raises(dm.DocMgrError) as exc:
        dm._headers()
    assert "SDI_DM_API_KEY" in str(exc.value)


def test_the_secret_can_come_from_dms_own_env_name(dm, monkeypatch):
    """An estimator who followed DM's guide set DOCMGR_ACCESS_SECRET. Making them learn a
    second name for the same fact is friction with no purpose."""
    monkeypatch.setattr(dm.config, "DM_API_KEY", "")
    monkeypatch.setenv("DOCMGR_ACCESS_SECRET", "from-their-guide")
    assert dm.api_key() == "from-their-guide"


# ── refusing to start work that cannot succeed ──────────────────────────────────────────

def test_an_extract_is_not_sent_when_com_is_down(dm, monkeypatch):
    """DM accepts the job either way and fails it minutes later. The estimator reads that as
    a broken feature rather than as a CAD host that is not driving SOLIDWORKS."""
    posted = []
    monkeypatch.setattr(dm, "health",
                        lambda: {"status": "ok", "comAvailable": False, "comError": "no seat"})
    monkeypatch.setattr(dm, "_requests",
                        lambda: types.SimpleNamespace(post=lambda *a, **k: posted.append(a)))
    with pytest.raises(dm.DocMgrError) as exc:
        dm.start_extract("11650", customer="Boots")
    assert "comAvailable=false" in str(exc.value)
    assert not posted, "nothing may be sent when it is known it would fail"


def test_only_the_three_consumer_parameters_are_sent(dm, monkeypatch):
    """DM's advanced fields have server defaults its guide calls right for most packs. A
    setting we pass without understanding is one we cannot explain when a pack comes back
    wrong."""
    sent = {}

    def _post(url, **kw):
        sent.update(kw.get("json") or {})
        return _Resp(202, {"jobId": "j-1", "status": "queued"})

    monkeypatch.setattr(dm, "health", lambda: {"comAvailable": True})
    monkeypatch.setattr(dm, "_requests", lambda: types.SimpleNamespace(post=_post))
    dm.start_extract("11650", customer="Boots", assembly_folder="11650-00")
    assert sent == {"projectNumber": "11650", "customer": "Boots",
                    "assemblyFolder": "11650-00"}


def test_optional_fields_are_omitted_rather_than_sent_empty(dm, monkeypatch):
    """An empty customer is not a customer named ''. DM narrows its lookup on that field."""
    sent = {}

    def _post(url, **kw):
        sent.update(kw.get("json") or {})
        return _Resp(202, {"jobId": "j-1"})

    monkeypatch.setattr(dm, "health", lambda: {"comAvailable": True})
    monkeypatch.setattr(dm, "_requests", lambda: types.SimpleNamespace(post=_post))
    dm.start_extract("11650")
    assert sent == {"projectNumber": "11650"}


def test_an_accepted_job_with_no_id_is_an_error_not_a_success(dm, monkeypatch):
    """Without a job id there is nothing to follow, so reporting success would leave the page
    polling an empty string for ever."""
    monkeypatch.setattr(dm, "health", lambda: {"comAvailable": True})
    monkeypatch.setattr(dm, "_requests",
                        lambda: types.SimpleNamespace(post=lambda *a, **k: _Resp(202, {})))
    with pytest.raises(dm.DocMgrError) as exc:
        dm.start_extract("11650")
    assert "no job id" in str(exc.value).lower()


# ── the job, and what "finished" means ──────────────────────────────────────────────────

@pytest.mark.parametrize("status,finished,ok", [
    ("queued", False, False), ("running", False, False),
    ("completed", True, True), ("failed", True, False),
])
def test_the_four_states_are_reduced_to_two_questions(dm, monkeypatch, status, finished, ok):
    """The page should test one flag, not keep a list of DM's status strings in step."""
    monkeypatch.setattr(dm, "_requests", lambda: types.SimpleNamespace(
        get=lambda *a, **k: _Resp(200, {"status": status,
                                        "result": {"outputDir": "X:\\p", "fileCount": 9}})))
    out = dm.job("j-1")
    assert out["finished"] is finished and out["ok"] is ok


def test_the_output_folder_is_lifted_out_of_dms_nesting(dm, monkeypatch):
    """result.outputDir is what everything downstream needs; digging for it at each call site
    is how one of them ends up not checking whether it is there."""
    monkeypatch.setattr(dm, "_requests", lambda: types.SimpleNamespace(
        get=lambda *a, **k: _Resp(200, {"status": "completed",
                                        "result": {"outputDir": "\\\\srv\\packs\\11650",
                                                   "fileCount": 12}})))
    out = dm.job("j-1")
    assert out["output_dir"] == "\\\\srv\\packs\\11650" and out["file_count"] == 12


def test_a_completed_job_with_no_result_block_does_not_invent_one(dm, monkeypatch):
    monkeypatch.setattr(dm, "_requests", lambda: types.SimpleNamespace(
        get=lambda *a, **k: _Resp(200, {"status": "completed"})))
    out = dm.job("j-1")
    assert out["output_dir"] is None and out["file_count"] is None
