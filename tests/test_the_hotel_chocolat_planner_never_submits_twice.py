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
import pytest
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
    rc, out = _run_rc("queue", plan_file, "once", "since=", env=env)
    assert rc == 2 and out.startswith("NOT QUEUED: this plan read 4 of the 7 files")


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


def test_a_drawing_whose_pdf_has_no_text_names_its_parts_through_its_dxf(tmp_path):
    """B.34493's PDF is outlines only; its DXF's parts list names the ballast plate D.34496."""
    plinths = tmp_path / "pack" / "Drawing" / "ACC" / "02. PLINTHS"
    (plinths / "03. 1050MM HIGH PLINTH").mkdir(parents=True)
    (plinths / "04. PLINTH BALLAST PLATE").mkdir(parents=True)
    own = plinths / "03. 1050MM HIGH PLINTH"
    (own / "nc1-b34493.pdf").write_bytes(b"x")
    (own / "nc1-b34493.DXF").write_bytes(b"  1\nA.34494\n  1\nD.34496\n  5\nB34499\n")
    (own / "nc1-a34494.pdf").write_bytes(b"x")
    (plinths / "04. PLINTH BALLAST PLATE" / "nc1-d34496.pdf").write_bytes(b"x")
    env = dict(os.environ, HC_SERVICES="http://127.0.0.1:9,http://127.0.0.1:9")
    _run("plan", str(tmp_path / "pack"), str(tmp_path), env=env)
    plan = json.loads(next(tmp_path.glob("Hotel Chocolat plan *.json")).read_text("utf-8"))
    plinth = next(p for p in plan["products"] if "1050" in p["title"])
    assert plinth["drawing"] == "B.34493"
    assert "nc1-d34496.pdf" in [f["name"] for f in plinth["files"]]
    assert not any("top drawing chosen" in w for w in plinth["warnings"])


def test_review_reads_the_actual_workbook_inside_the_run_output_directory(tmp_path):
    import openpyxl
    _pack(tmp_path / 'pack')
    svc = _Service(slow=0)
    env = dict(os.environ, HC_SERVICES=svc.urls)
    try:
        _run('plan', str(tmp_path / 'pack'), str(tmp_path), env=env)
        plan_path = next(tmp_path.glob('Hotel Chocolat plan *.json'))
        plan = json.loads(plan_path.read_text('utf-8'))
        item = plan['products'][0]
        output = tmp_path / 'finished'
        output.mkdir()
        main = output / 'B.34466_20261127_003000.xlsx'
        _finished_book(main, item['drawing'])
        svc.runs.append(dict(run_id='finished',status='done',client='Hotel Chocolat',
            job_title=item['title']+' [hc:'+item['fingerprint']+']', queued_at=time.time(),
            output_path=str(output), engine_price_gbp=110.75, price_validated=True,
            deliverables=[dict(name=main.name,path=str(main))]))
        text = _run('review',str(plan_path),str(tmp_path/'review'),env=env)
        assert '2 products: 1 priced, 1 not yet' in text
        master=openpyxl.load_workbook(next((tmp_path/'review').glob('*master*')))
        priced=[r for r in master['Price schedule'].iter_rows(min_row=5,values_only=True)
                if isinstance(r[3],(int,float))]
        assert len(priced)==1 and priced[0][3]==110.75
        assert priced[0][12]=='finished' and priced[0][13]==str(main)
        assert svc.posts==0
    finally:
        svc.close()


def test_review_preserves_a_validated_run_price_when_the_share_is_unreachable(tmp_path):
    import openpyxl
    item=dict(drawing='A.12345',title='Saved product',pack='1 Panels',fingerprint='123456abcdef',
              files=[],warnings=[],selected=True,brief=None)
    plan=tmp_path/'plan.json'
    plan.write_text(json.dumps(dict(products=[item],accounting={})),encoding='utf-8')
    svc=_Service(slow=0)
    env=dict(os.environ,HC_SERVICES=svc.urls)
    svc.runs.append(dict(run_id='saved',status='done',client='Hotel Chocolat',
        job_title='Saved product [hc:123456abcdef]',queued_at=time.time(),
        output_path=str(tmp_path/'unavailable'),engine_price_gbp=0.0,price_validated=True))
    try:
        text=_run('review',str(plan),str(tmp_path/'review'),env=env)
        assert '1 products: 1 priced, 0 not yet' in text
        wb=openpyxl.load_workbook(next((tmp_path/'review').glob('*master*')))
        assert wb['Price schedule']['D5'].value==0
        assert 'workbook not found' in wb['Price schedule']['H5'].value
        assert svc.posts==0
    finally:
        svc.close()


def test_stock_number_only_bom_selects_the_shelving_assembly_not_its_panel(tmp_path):
    import pymupdf
    folder=tmp_path/'pack'/'Drawing'/'Shelving 800 standard'
    folder.mkdir(parents=True)
    sources={
        'nc1-b34471.pdf':'PART NO. 20126611\nDRG No. B.34471\n800 SHELF PANEL',
        'nc1-b34473.pdf':'PART NO. 10100900\nDRG No. B.34473\nITEM NO.\n20126611 SHELF PANEL 1\n20125999 BRACKET 2',
        'nc1-c33383.pdf':'PART NO. 20125999\nDRG No. C.33383\nSHELF BRACKET'}
    for name,text in sources.items():
        doc=pymupdf.open()
        page=doc.new_page()
        page.insert_text((50,50),text)
        doc.save(folder/name)
        doc.close()
    env=dict(os.environ,HC_SERVICES='http://127.0.0.1:9,http://127.0.0.1:9')
    _run('plan',str(tmp_path/'pack'),str(tmp_path),env=env)
    plan=json.loads(next(tmp_path.glob('Hotel Chocolat plan *.json')).read_text())
    assert len(plan['products'])==1
    assert plan['products'][0]['drawing']=='B.34473'
    assert len(plan['products'][0]['files'])==3


@pytest.mark.parametrize('validated',[False,True])
def test_review_never_borrows_another_products_workbook_or_an_unvalidated_price(tmp_path,validated):
    import openpyxl
    item=dict(drawing='A.12345',title='Saved product',pack='1 Panels',fingerprint='123456abcdef',
              files=[],warnings=[],selected=True,brief=None)
    plan=tmp_path/'plan.json'
    plan.write_text(json.dumps(dict(products=[item],accounting={})),encoding='utf-8')
    other=tmp_path/'other.xlsx';_finished_book(other,'B.98765')
    svc=_Service(slow=0)
    svc.runs.append(dict(run_id='saved',status='done',client='Hotel Chocolat',
        job_title='Saved product [hc:123456abcdef]',queued_at=time.time(),
        output_path=str(other),engine_price_gbp=555,price_validated=validated,
        quality={'label':'Missing costs'}))
    try:
        _run('review',str(plan),str(tmp_path/'review'),env=dict(os.environ,HC_SERVICES=svc.urls))
        wb=openpyxl.load_workbook(next((tmp_path/'review').glob('*master*')))
        row=wb['Price schedule']
        assert row['D5'].value==(555 if validated else None)
        assert 'does not match' in row['H5'].value and 'Missing costs' in row['H5'].value
        assert not row['N5'].value and svc.posts==0
    finally:
        svc.close()


# -- FAIL CLOSED (27 Nov 2026): a queue that cannot see the whole history submits nothing --

def _run_rc(*args, env):
    out = subprocess.run([sys.executable, "-I", str(PLANNER), *args], capture_output=True,
                         text=True, env=env, timeout=120)
    return out.returncode, out.stdout + out.stderr


def _planned(tmp_path, env):
    _pack(tmp_path / "pack")
    _run("plan", str(tmp_path / "pack"), str(tmp_path), env=env)
    plan_file = next(tmp_path.glob("Hotel Chocolat plan *.json"))
    return plan_file, json.loads(plan_file.read_text("utf-8"))


def test_one_service_not_answering_means_nothing_is_submitted(tmp_path):
    svc = _Service(slow=0)
    env = dict(os.environ, HC_SERVICES=svc.urls)
    try:
        plan_file, _ = _planned(tmp_path, env)
        svc.servers[1].shutdown(); svc.servers[1].server_close()
        rc, out = _run_rc("queue", str(plan_file), "once", "since=", env=env)
        assert rc != 0 and "NOT QUEUED: the run history is incomplete" in out and svc.posts == 0
    finally:
        svc.servers[0].shutdown()


def test_a_run_list_at_its_limit_is_not_complete_history(tmp_path):
    svc = _Service(slow=0)
    env = dict(os.environ, HC_SERVICES=svc.urls, HC_RUN_LIMIT="3")
    try:
        plan_file, _ = _planned(tmp_path, env)
        svc.runs.extend({"run_id": "x%d" % i, "client": "Other", "job_title": "t", "status": "done",
                         "queued_at": time.time()} for i in range(3))
        rc, out = _run_rc("queue", str(plan_file), "once", "since=", env=env)
        assert rc != 0 and "its limit" in out and svc.posts == 0
    finally:
        svc.close()


def test_a_live_run_of_the_same_drawing_blocks_a_submit_whatever_its_title(tmp_path):
    svc = _Service(slow=0)
    env = dict(os.environ, HC_SERVICES=svc.urls)
    try:
        plan_file, plan = _planned(tmp_path, env)
        for p in plan["products"]:
            svc.runs.append({"run_id": "wall-" + p["drawing"], "client": "Someone", "job_title": "by hand",
                             "drawing_number": p["drawing"].replace(".", "-").lower(), "status": "claimed",
                             "queued_at": time.time()})
        rc, out = _run_rc("queue", str(plan_file), "once", "since=", env=env)
        assert rc == 0 and out.count("IN FLIGHT") == 2 and svc.posts == 0
    finally:
        svc.close()


def test_a_finished_run_counts_as_done_only_on_the_verified_release(tmp_path):
    svc = _Service(slow=0)
    env = dict(os.environ, HC_SERVICES=svc.urls)
    try:
        plan_file, plan = _planned(tmp_path, env)
        verified = time.time() - 600
        release = tmp_path / "release.json"
        release.write_text(json.dumps({"build": "abc1234", "loaded_verified_at": verified}), "utf-8")
        a, b = plan["products"]
        title = lambda p: "%s [hc:%s]" % (p["title"], p["fingerprint"])
        svc.runs += [
            # after the verified release, but its own log shows the OLD engine: not done
            {"run_id": "old-engine", "client": "Hotel Chocolat", "job_title": title(a), "status": "done",
             "queued_at": verified + 60, "log": ["   [build] engine source: 8e03a71 · src 51dd (782 modules)"]},
            # its own log shows the released engine: done
            {"run_id": "new-engine", "client": "Hotel Chocolat", "job_title": title(b), "status": "done",
             "queued_at": verified + 60, "log": ["   [build] engine source: abc1234 · src 77aa (790 modules)"]},
        ]
        rc, out = _run_rc("queue", str(plan_file), "once", "release=" + str(release), env=env)
        assert rc == 0, out
        assert "old-engine" in out and "8e03a71" in out and "new-engine" in out
        assert "1 queued, 1 already run or in flight" in out and svc.posts == 1
    finally:
        svc.close()


def test_an_uncertain_submit_is_reconciled_before_anything_is_sent_again(tmp_path):
    def vanish(runs):
        runs.clear()                                   # the service never kept it
    svc = _Service(slow=3, on_first_post=vanish)
    env = dict(os.environ, HC_SERVICES=svc.urls, HC_SUBMIT_TIMEOUT="1", HC_CONFIRM_TRIES="1",
               HC_CONFIRM_SLEEP="0")
    try:
        plan_file, _ = _planned(tmp_path, env)
        rc, out = _run_rc("queue", str(plan_file), "once", "since=", env=env)
        assert rc != 0 and "UNSURE" in out and "1 unsure" in out
        posts = svc.posts
        rc, out = _run_rc("queue", str(plan_file), "once", "since=", env=env)
        assert rc != 0 and "earlier uncertain submit" in out and "HELD" in out
        assert svc.posts == posts
        journal = (tmp_path / "Hotel Chocolat submissions.jsonl").read_text("utf-8")
        assert '"result": "unsure"' in journal and '"result": "queued"' in journal
        rc, out = _run_rc("queue", str(plan_file), "once", "since=", env=dict(env, HC_UNSURE_WAIT_MIN="0"))
        assert "never appeared on either complete run list" in out
    finally:
        svc.close()


def test_a_plan_that_read_too_few_files_exits_with_a_failure():
    src = PLANNER.read_text("utf-8")
    block = src[src.index("NOT QUEUED: this plan read"):]
    assert "sys.exit(2)" in block[:400]
