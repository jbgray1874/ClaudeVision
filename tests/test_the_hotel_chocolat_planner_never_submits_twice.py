"""The Hotel Chocolat planner never submits a product twice, and drops none (26 Nov 2026).

Three shelving products whose every file was 0 bytes were missing from the 09:43 plan (32
of 35). A submit that timed out was reported REFUSED while the run was on the queue and
running, and -Rerun resubmitted products with no regard for what was already in flight.
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PLANNER = Path(__file__).resolve().parents[1] / "tools" / "estimating" / "hc_plan.py"


def _pack(root: Path) -> None:
    shelving = root / "Drawing" / "FF" / "07. SHELVING"
    for folder, files in {
        "Perimeter wall bay shelf 500 ( standard )": {"nc1-b34466.pdf": b"x", "nc1-d34467.pdf": b"x"},
        "Perimeter wall bay shelving 500 ( narrow )": {"nc1-b34469.pdf": b"", "nc1-d34467.pdf": b""},
    }.items():
        (shelving / folder).mkdir(parents=True)
        for name, data in files.items():
            (shelving / folder / name).write_bytes(data)


class _Service:
    """Two ports, one list of runs. The first submit is created, then answered slowly."""

    def __init__(self, slow: float):
        self.runs, self.posts = [], 0
        service = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"runs": service.runs}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(body)

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                service.posts += 1
                service.runs.append({"run_id": "r%d" % service.posts, "client": req["client"],
                                     "job_title": req["job_title"], "status": "queued",
                                     "queued_at": time.time(), "method": req.get("method")})
                if service.posts == 1:
                    time.sleep(slow)
                try:
                    body = json.dumps({"run_id": "r%d" % service.posts}).encode()
                    self.send_response(200); self.end_headers(); self.wfile.write(body)
                except Exception:                                      # noqa: BLE001
                    pass

        self.servers = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), H) for _ in range(2)]
        for s in self.servers:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        self.urls = ",".join("http://127.0.0.1:%d" % s.server_address[1] for s in self.servers)

    def close(self):
        for s in self.servers:
            s.shutdown()


def _run(*args, env):
    out = subprocess.run([sys.executable, "-I", str(PLANNER), *args], capture_output=True,
                         text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_an_all_empty_product_is_planned_from_a_brief_and_a_slow_submit_is_not_a_refusal(tmp_path):
    _pack(tmp_path / "pack")
    svc = _Service(slow=3)
    env = dict(os.environ, HC_SERVICES=svc.urls, HC_SUBMIT_TIMEOUT="1")
    try:
        text = _run("plan", str(tmp_path / "pack"), str(tmp_path), env=env)
        assert "2 products" in text and "empty (warned)                           2" in text
        plan = json.loads(next(tmp_path.glob("Hotel Chocolat plan *.json")).read_text("utf-8"))
        narrow = next(p for p in plan["products"] if "narrow" in p["title"])
        assert narrow["files"] == [] and "D.34467 (readable in: Perimeter wall bay shelf 500" in narrow["brief"]

        plan_file = str(next(tmp_path.glob("Hotel Chocolat plan *.json")))
        first = _run("queue", plan_file, "once", "since=", env=env)
        assert "the service answered slowly; the run is on the list" in first
        assert "REFUSED" not in first and "2 queued" in first

        again = _run("queue", plan_file, "rerun", "since=", env=env)
        assert again.count("IN FLIGHT") == 2 and "0 queued" in again
        assert svc.posts == 2

        for r in svc.runs:
            r["status"], r["queued_at"] = "done", time.time() - 7200
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 3600))
        assert "2 queued" in _run("queue", plan_file, "once", "since=" + stamp, env=env)
        assert "0 queued" in _run("queue", plan_file, "once", "since=", env=env)
    finally:
        svc.close()
