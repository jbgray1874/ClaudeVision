"""The TTI connector, started for real: it imports, builds, and lists its tools.

The read-only tests read tti_connector.py as code. That let a server that
could not start pass them: each tool was registered through mcp's Apps
extension, which needs a ui:// card these tools do not have, and the service
stopped on its first line. So this builds the app as the Windows service
would, in a separate Python with only fictional settings, and asks it what
ChatGPT would ask first.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.mcpserver")

BACKEND = Path(__file__).resolve().parent.parent

PROBE = r"""
import asyncio, json, sys
sys.path.insert(0, sys.argv[1])
import tti_connector as c
from starlette.testclient import TestClient

tools = asyncio.run(c.build_server().list_tools())
out = {"tools": {t.name: bool(t.annotations and t.annotations.read_only_hint) for t in tools}}
with TestClient(c.build_app()) as client:
    out["resource"] = client.get("/.well-known/oauth-protected-resource/mcp").json()
    out["server"] = client.get("/.well-known/oauth-authorization-server").json()
    out["no_token"] = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def started(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("tti")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SDI_")}
    env.update({
        "SDI_TENANT_ID": "00000000-0000-0000-0000-000000000001",
        "SDI_CLIENT_ID": "00000000-0000-0000-0000-000000000002",
        "SDI_CLIENT_SECRET": "fictional",
        "SDI_SESSION_SECRET": "fictional-session-secret",
        "SDI_TTI_CONNECTOR_ENABLED": "yes",
        "SDI_TTI_CONNECTOR_URL": "https://tti.example.test/mcp",
        "SDI_TTI_CONNECTOR_CLIENTS": "00000000-0000-0000-0000-000000000003",
        "SDI_TTI_CONNECTOR_OAUTH_CLIENT": "00000000-0000-0000-0000-000000000003",
        "SDI_TTI_CONNECTOR_OAUTH_SECRET": "fictional",
        "SDI_TTI_CONNECTOR_CLIENTS_FILE": str(tmp / "clients.json"),
        "SDI_TTI_OIDS": "00000000-0000-0000-0000-000000000004",
    })
    run = subprocess.run([sys.executable, "-c", PROBE, str(BACKEND)], cwd=tmp, env=env,
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr[-3000:]
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_all_seven_tools_are_listed_and_each_says_it_only_reads(started):
    assert started["tools"] == {name: True for name in (
        "tti_find", "tti_leaving_on", "tti_chase", "tti_overdue",
        "tti_morning", "tti_data_quality", "tti_find_files")}


def test_chatgpt_is_sent_to_the_connectors_own_sign_in(started):
    assert started["resource"]["resource"].rstrip("/") == "https://tti.example.test/mcp"
    assert "tracker.access" in started["resource"].get("scopes_supported", [])
    for path in ("/authorize", "/token", "/register"):
        assert any(str(v).endswith(path) for v in started["server"].values()), path


def test_no_token_no_answer(started):
    assert started["no_token"] == 401
