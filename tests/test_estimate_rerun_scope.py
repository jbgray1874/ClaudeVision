"""Synthetic preservation tests: no live services, drawing shares or real prices."""
import copy
import http.server
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

spec = importlib.util.spec_from_file_location("estimate_rerun_scope", Path(__file__).resolve().parents[1] / "tools/estimating/estimate_rerun_scope.py")
scope_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope_tool)


@pytest.fixture
def sample(tmp_path):
    rows = [{"drawing": code, "title": code, "unit_cost": 12.5, "material": 8,
             "manufacturing": 4, "loading": .5, "status": "PROVISIONAL", "basis": "own evidence"}
            for code in ("A.77111", "B.77222", "C.77333")]
    sources = []
    for row in rows:
        book, record = (tmp_path / (row["drawing"] + ext) for ext in (".xlsx", ".json"))
        book.write_bytes(b"synthetic workbook bytes")
        record.write_text("{}")
        sources.append({"drawing": row["drawing"], "workbook": str(book), "record": str(record),
                        "book_sha256": scope_tool.digest(book), "record_sha256": scope_tool.digest(record)})
    book = tmp_path / "first-issue.xlsx"
    book.write_bytes(b"synthetic consolidated workbook")
    baseline, plan, inventory = (tmp_path / name for name in ("baseline.json", "plan.json", "sources.json"))
    scope_tool.write_new(baseline, {"issue": "first", "workbook_sha256": scope_tool.digest(book), "products": rows})
    scope_tool.write_new(plan, {"files_read": 6, "files_expected": 6,
                             "products": [{"drawing": row["drawing"], "selected": True, "files": []} for row in rows]})
    scope_tool.write_new(inventory, {"sources": sources})
    return {"plan_path": plan, "baseline_path": baseline, "sources_path": inventory, "workbook_path": book,
            "only": ["a-77111", "B77222"], "output_dir": tmp_path / "new-issue",
            "journal_path": tmp_path / "submissions.jsonl"}


def test_exact_scope_normalises_references_and_preserves_all_originals(sample):
    path = scope_tool.prepare(**sample)
    result = scope_tool.check(path)
    assert set(result["selected"]) == {"A77111", "B77222"}
    assert result["protected"] == ["C77333"]
    assert len(result["original_files"]) == 10
    assert result["prepared_without_submission"] is True


@pytest.mark.parametrize("only", [[], ["A.77111", "A-77111"], ["Z.99999"]])
def test_bad_selection_is_rejected_before_output(sample, only):
    sample["only"] = only
    with pytest.raises(ValueError):
        scope_tool.prepare(**sample)
    assert not sample["output_dir"].exists()


def test_duplicate_product_cannot_be_hidden_by_normalisation(sample):
    plan = scope_tool.read_json(sample["plan_path"])
    plan["products"].append({"drawing": "A-77111", "selected": False})
    with pytest.raises(ValueError, match="duplicate"):
        scope_tool.select_plan(plan, scope_tool.read_json(sample["baseline_path"]), sample["only"])


def test_incomplete_file_accounting_is_rejected(sample):
    plan = scope_tool.read_json(sample["plan_path"])
    plan["files_read"] = 5
    with pytest.raises(ValueError, match="accounting"):
        scope_tool.select_plan(plan, scope_tool.read_json(sample["baseline_path"]), sample["only"])


def test_plan_changes_are_detected(sample):
    path = scope_tool.prepare(**sample)
    manifest = scope_tool.read_json(path)
    selected_plan = Path(manifest["plan"])
    selected_plan.write_text(selected_plan.read_text() + " ")
    with pytest.raises(ValueError, match="plan changed"):
        scope_tool.check(path)


@pytest.mark.parametrize("selected", [True, False])
def test_original_books_are_protected_even_for_selected_products(sample, selected):
    path = scope_tool.prepare(**sample)
    manifest = scope_tool.read_json(path)
    code = "A77111" if selected else "C77333"
    protected = next(x for x in manifest["original_files"] if x.get("drawing") == code and x["kind"] == "workbook")
    Path(protected["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Original files changed"):
        scope_tool.check(path)


def test_merge_changes_only_selected_rows_and_keeps_input_objects_intact(sample):
    path = scope_tool.prepare(**sample)
    previous = scope_tool.read_json(sample["baseline_path"])
    replacements = copy.deepcopy(previous["products"][:2])
    for row in replacements:
        row["unit_cost"] = 15
        row["manufacturing"] = 6.5
        row["basis"] = "Reviewed revised evidence and allowance"
    expected = copy.deepcopy(replacements)
    merged = scope_tool.merge_reviewed(path, replacements, "second")
    assert merged["products"][2] == previous["products"][2]
    assert merged["protected_products_unchanged"] == 1
    assert len(merged["changes"]) == 2
    assert replacements == expected
    assert "workbook_sha256" not in merged
    assert scope_tool.read_json(sample["baseline_path"]) == previous


def test_merge_refuses_unselected_or_missing_replacements(sample):
    path = scope_tool.prepare(**sample)
    products = scope_tool.read_json(sample["baseline_path"])["products"]
    for rows in (products, products[:1]):
        with pytest.raises(ValueError, match="exactly"):
            scope_tool.merge_reviewed(path, rows, "second")


@pytest.mark.parametrize("price", [None, float("nan"), -1, True])
def test_invalid_result_price_is_never_a_successful_merge(sample, price):
    path = scope_tool.prepare(**sample)
    rows = scope_tool.read_json(sample["baseline_path"])["products"][:2]
    rows[0]["unit_cost"] = price
    with pytest.raises(ValueError, match="unit cost"):
        scope_tool.merge_reviewed(path, rows, "second")


def test_existing_outputs_are_never_overwritten(sample):
    scope_tool.prepare(**sample)
    with pytest.raises(FileExistsError):
        scope_tool.prepare(**sample)
    with pytest.raises(FileExistsError):
        scope_tool.write_new(sample["baseline_path"], {})


def test_reviewed_results_must_reconcile_before_merge(sample):
    path = scope_tool.prepare(**sample)
    rows = scope_tool.read_json(sample["baseline_path"])["products"][:2]
    rows[0]["unit_cost"] = 100
    with pytest.raises(ValueError, match="reconcile"):
        scope_tool.merge_reviewed(path, rows, "second")


class Service:
    """Isolated local test servers, never production endpoints."""
    def __init__(self):
        self.runs, self.posts = [], []
        self.build = "abcdef12"
        self.after_post = None
        service = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/api/health":
                    data = {"commit": service.build}
                elif self.path == "/api/estimate/runners":
                    data = {"runners": [{"runner_id": name, "build": service.build,
                                         "online": True, "conflict": False, "process_count": 1}
                                        for name in ("one", "two")]}
                else:
                    data = {"runs": service.runs}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                service.posts.append(data["drawing_number"])
                run = {"run_id": "new-" + str(len(service.posts)), "status": "queued",
                       "drawing_number": data["drawing_number"], "client": data["client"],
                       "job_title": data["job_title"], "queued_at": time.time()}
                service.runs.append(run)
                if service.after_post:
                    service.after_post()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"run_id": run["run_id"]}).encode())

        self.servers = [http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
        for server in self.servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
        self.urls = ",".join(f"http://127.0.0.1:{server.server_port}" for server in self.servers)

    def close(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()


def scoped_queue(sample, service, *, corrupt=False, missing_service=False, unsure=False):
    original = scope_tool.read_json(sample["plan_path"])
    for position, product in enumerate(original["products"]):
        product.update(title=product["drawing"], fingerprint=f"{position:012x}")
    sample["plan_path"].write_text(json.dumps(original))
    path = scope_tool.prepare(**sample)
    scope = scope_tool.read_json(path)
    if corrupt:
        item = next(x for x in scope["original_files"] if x.get("drawing") == "C77333")
        Path(item["path"]).write_bytes(b"changed original")
    if unsure:
        Path(sample["journal_path"]).write_text(json.dumps({"asked": time.time(),
            "fingerprint": "000000000000", "result": "unsure", "run_id": None}) + "\n")
    release = sample["output_dir"] / "release.json"
    scope_tool.write_new(release, {"build": "abcdef12", "loaded_verified_at": time.time() - 60,
                                   "runners": [{"runner": "one"}, {"runner": "two"}]})
    env = dict(os.environ, HC_SERVICES=service.urls, HC_RUN_LIMIT="5000")
    if missing_service:
        env["HC_SERVICES"] = service.urls.split(",")[0] + ",http://127.0.0.1:9"
    command = [sys.executable, "-I", str(Path(__file__).resolve().parents[1] / "tools/estimating/hc_plan.py"),
               "queue", scope["plan"], "once", "release=" + str(release),
               "scope_helper=" + str(Path(scope_tool.__file__))]
    def run():
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=40)
    return run


def test_scoped_queue_submits_only_selected_and_never_duplicates(sample):
    service = Service()
    try:
        run = scoped_queue(sample, service)
        first, again = run(), run()
        assert first.returncode == again.returncode == 0, first.stdout + first.stderr + again.stderr
        assert service.posts == ["A.77111", "B.77222"]
        assert again.stdout.count("IN FLIGHT") == 2
    finally:
        service.close()


@pytest.mark.parametrize("condition", ["corrupt", "missing_service", "old_build"])
def test_scoped_queue_fails_closed_before_any_post(sample, condition):
    service = Service()
    try:
        if condition == "old_build":
            service.build = "12345678"
        run = scoped_queue(sample, service, corrupt=condition == "corrupt", missing_service=condition == "missing_service")
        result = run()
        assert result.returncode != 0
        assert service.posts == []
    finally:
        service.close()


def test_scoped_queue_rechecks_preservation_before_the_next_submit(sample):
    service = Service()
    try:
        run = scoped_queue(sample, service)
        source = scope_tool.read_json(sample["sources_path"])["sources"][2]["workbook"]
        service.after_post = lambda: Path(source).write_bytes(b"unexpected modification")
        result = run()
        assert result.returncode != 0
        assert service.posts == ["A.77111"]
    finally:
        service.close()


def test_frozen_plan_retains_the_old_uncertain_submission_journal(sample):
    service = Service()
    try:
        run = scoped_queue(sample, service, unsure=True)
        result = run()
        assert result.returncode != 0
        assert "earlier uncertain submit" in result.stdout
        assert service.posts == ["B.77222"]
    finally:
        service.close()


def test_old_active_attempt_blocks_a_normalised_drawing_even_without_matching_fingerprint(sample):
    service = Service()
    try:
        service.runs = [{"run_id": "historic-live", "drawing_number": "a-77111", "status": "running",
                         "queued_at": 1, "client": "another client", "job_title": "old title"}]
        run = scoped_queue(sample, service)
        result = run()
        assert result.returncode == 0, result.stderr
        assert service.posts == ["B.77222"]
        assert "historic-live (running)" in result.stdout
    finally:
        service.close()
