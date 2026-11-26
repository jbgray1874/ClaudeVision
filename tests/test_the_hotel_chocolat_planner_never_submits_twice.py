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

    def __init__(self, slow: float, on_first_post=None):
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
                    if on_first_post:
                        on_first_post(service.runs)
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


def test_a_plan_that_read_fewer_files_than_the_share_holds_cannot_be_queued(tmp_path):
    """Three shelving folders sit 260-261 characters deep on the share. PowerShell counted 590
    files; the planner read 566 and planned 32 products of 35 without a word."""
    _pack(tmp_path / "pack")
    env = dict(os.environ, HC_SERVICES="http://127.0.0.1:9,http://127.0.0.1:9")
    text = _run("plan", str(tmp_path / "pack"), str(tmp_path), "expect=7", env=env)
    assert "THE SHARE HOLDS 7 FILES AND THIS PLAN READ 4" in text
    plan_file = str(next(tmp_path.glob("Hotel Chocolat plan *.json")))
    out = _run("queue", plan_file, "once", "since=", env=env)
    assert out.startswith("NOT QUEUED: this plan read 4 of the 7 files")


def test_a_path_past_260_characters_is_read_by_its_long_form_and_shown_by_its_own():
    import types
    src = PLANNER.read_text("utf-8")
    ns = {"os": types.SimpleNamespace(name="nt", path=types.SimpleNamespace(
        abspath=lambda x: "C:\\work\\" + x))}
    exec(src[src.index("def long_path"):src.index("TOO_LONG = 260")], ns)
    unc = "\\\\sdi-dc01\\shareddata$\\Shared\\HotelChocolat-1204\\nc1-b33381.pdf"
    assert ns["long_path"](unc) == "\\\\?\\UNC\\sdi-dc01\\shareddata$\\Shared\\HotelChocolat-1204\\nc1-b33381.pdf"
    assert ns["short_path"](ns["long_path"](unc)) == unc
    assert ns["long_path"](ns["long_path"](unc)) == ns["long_path"](unc)
    assert ns["short_path"](ns["long_path"]("a.pdf")) == "C:\\work\\a.pdf"


def test_a_product_submitted_by_someone_else_meanwhile_is_not_submitted_again(tmp_path):
    """The run list is read again right before each submit: a second queue window, or a
    person on the Wall, may have submitted the product since this queue started."""
    _pack(tmp_path / "pack")
    holder = {}

    def someone_else_submits_the_second(runs):
        second = holder["plan"]["products"][1]
        runs.append({"run_id": "elsewhere", "client": "Hotel Chocolat", "status": "queued",
                     "job_title": "%s [hc:%s]" % (second["title"], second["fingerprint"]),
                     "queued_at": time.time()})

    svc = _Service(slow=0, on_first_post=someone_else_submits_the_second)
    env = dict(os.environ, HC_SERVICES=svc.urls)
    try:
        _run("plan", str(tmp_path / "pack"), str(tmp_path), env=env)
        plan_file = next(tmp_path.glob("Hotel Chocolat plan *.json"))
        holder["plan"] = json.loads(plan_file.read_text("utf-8"))
        out = _run("queue", str(plan_file), "once", "since=", env=env)
        assert "elsewhere (queued); not submitted again" in out and svc.posts == 1
    finally:
        svc.close()


def _finished_book(path: Path, drawing: str) -> None:
    """A made-up finished estimate, laid out as the engine lays its workbook out."""
    import openpyxl
    wb = openpyxl.Workbook()
    est = wb.active
    est.title = "Estimate"
    est["C5"], est["D5"] = "Drawing No.", drawing
    est["H6"] = "DRAFT — 2 item(s) to confirm"
    est["C200"], est["H200"] = "Total Material Cost", 90.5
    est["C223"], est["H223"] = "Total Labour Cost (Including  Downtime)", 20.25
    est["C225"], est["H225"] = "Total Unit Cost Price", 110.75
    est["C284"] = "OUTSTANDING ESTIMATOR INPUTS (1) — questions from the drawings"
    est["C285"] = "1.  MARGIN  —  MARGIN NOT SET"
    ai = wb.create_sheet("AI Explanation")
    ai.append(["FOR THE ESTIMATOR TO CONFIRM"])
    ai.append(["#", "Kind", "Decision", "Part", "Current assumption", "Action", "£ at stake"])
    ai.append([1, "Market figure", "BI-X rests on a market price", "BI-X", "web", "replace it", "£40.00"])
    ai.append([2, "Indicative rate", "PACKAGING indicative", "PACKAGING", "house", "verify", "£10.00"])
    ai.append([None])
    ai.append(["- What does a unit cost, and of what? £110.75 — material £90.50 + labour £20.25"])
    wb.save(str(path))


def test_the_review_writes_one_schedule_and_a_pack_per_family_from_the_finished_books(tmp_path):
    import openpyxl
    _pack(tmp_path / "pack")
    signs = tmp_path / "pack" / "Drawing" / "Signage & Graphics"
    signs.mkdir(parents=True)
    (signs / "01. SHOP FRONT SIGN.pdf").write_bytes(b"x")
    env = dict(os.environ, HC_SERVICES="http://127.0.0.1:9,http://127.0.0.1:9")
    _run("plan", str(tmp_path / "pack"), str(tmp_path), env=env)
    plan_file = next(tmp_path.glob("Hotel Chocolat plan *.json"))
    plan = json.loads(plan_file.read_text("utf-8"))
    standard = next(p for p in plan["products"] if "standard" in p["title"])
    books = tmp_path / "books"
    books.mkdir()
    _finished_book(books / "one.xlsx", standard["drawing"])
    out = _run("review", str(plan_file), str(tmp_path / "review"), "books=" + str(books), env=env)
    assert "2 products: 1 priced, 1 not yet" in out and "Nothing was submitted or re-priced." in out

    master = openpyxl.load_workbook(next((tmp_path / "review").glob("*master price schedule*")))
    rows = [r for r in master["Price schedule"].iter_rows(min_row=5, values_only=True) if r[3] is not None]
    assert [(r[1], r[3], r[4], r[5], r[8], r[9]) for r in rows] == \
        [(standard["drawing"], 110.75, 90.5, 20.25, 2, 50.0)]
    assert [r[1] for r in master["Signage"].iter_rows(min_row=4, values_only=True)] == ["01. SHOP FRONT SIGN.pdf"]
    assert "Not yet priced" in master.sheetnames

    pack = openpyxl.load_workbook(next((tmp_path / "review").glob("*review pack 2 Perimeter shelving*")))
    tab = pack[next(n for n in pack.sheetnames if n.startswith(standard["drawing"]))]
    text = " ".join(str(v) for r in tab.iter_rows(values_only=True) for v in r if v is not None)
    assert "BI-X rests on a market price" in text and "MARGIN NOT SET" in text and "£110.75" in text


def test_the_planner_survives_being_saved_as_ascii():
    """The wrapper is fetched with Set-Content -Encoding ASCII: a pound sign in the planner
    becomes '?', and the review could no longer find the '£ at stake' column."""
    wrapper = PLANNER.with_name("hc_estimates.ps1").read_text("utf-8")
    assert PLANNER.read_text("utf-8").isascii() and wrapper.isascii()
    planner = PLANNER.read_text("utf-8").rstrip("\n")
    assert wrapper[wrapper.index("@'\n") + 3:wrapper.index("\n'@ | Set-Content")] == planner
