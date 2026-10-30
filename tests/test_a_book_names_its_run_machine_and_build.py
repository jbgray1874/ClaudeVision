"""The book names its run, machine, build and mode on its first page (D-601).

THE ALTAVIO HPP RUNS OF 30 OCT 2026. Four books in one afternoon, and every one of them
reopened the same questions. Was the fix in? Which machine claimed the job? Was it the
LLM-only button? Were the reads fresh? The run knew every answer and printed them in its
log. The book carried the build only, at the far end of one centred header line that Excel
clipped from view, and the report carried none of them.

So the run stamps its identity when it starts. The job report shows it in a panel on the
first page: Run ID, runner machine, engine build, mode, reference documents, reads, and the
final review status. AI Provenance opens with the same facts and the build it already
carried. The customer quotation shows none of it.
"""
from __future__ import annotations

import os
import platform
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import run_provenance as rp  # noqa: E402
from build_stamp import build_stamp_line  # noqa: E402
from test_one_costed_record_for_every_deliverable import seventy_three_thirty_two  # noqa: E402


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@pytest.fixture()
def by_the_runner(monkeypatch):
    monkeypatch.setenv(rp.RUNNER_ID_ENV, "DESKTOP-4F3TLJN-a1b2c3")
    monkeypatch.setenv(rp.SERVICE_RUN_ID_ENV, "27d315c6")


def _stamped(**extra) -> dict:
    s = seventy_three_thirty_two()
    s.update(extra)
    rp.record(s)
    return s


# ── what the run records ─────────────────────────────────────────────────────────

def test_a_run_started_by_the_runner_names_the_machine_runner_and_portal_run(by_the_runner):
    s = {}
    prov = rp.record(s)
    assert s["run_provenance"] is prov
    assert prov["machine"] == platform.node()
    assert prov["runner_id"] == "DESKTOP-4F3TLJN-a1b2c3"
    assert prov["runner_pid"] == os.getppid(), "the runner is the engine's parent process"
    assert prov["service_run_id"] == "27d315c6"
    text = rp.machine_text(s)
    assert platform.node() in text and "runner DESKTOP-4F3TLJN-a1b2c3" in text


def test_a_run_started_by_hand_says_so(monkeypatch):
    monkeypatch.delenv(rp.RUNNER_ID_ENV, raising=False)
    monkeypatch.delenv(rp.SERVICE_RUN_ID_ENV, raising=False)
    s = {}
    rp.record(s)
    assert s["run_provenance"]["runner_id"] == ""
    assert s["run_provenance"]["runner_pid"] is None
    assert "started by hand, not by a portal runner" in rp.machine_text(s)


def test_the_runners_own_setting_is_not_read_as_a_claim():
    """SDI_RUNNER_ID configures a runner. A shell that has it set must not make a run started
    by hand claim that runner, so the engine reads a name only the runner hands down."""
    assert rp.RUNNER_ID_ENV != "SDI_RUNNER_ID"


def test_the_build_is_the_stamp_the_book_already_carries():
    """One stamp, from one function. The panel never computes a competing one."""
    s = {}
    rp.record(s)
    assert s["run_provenance"]["engine_build"] == build_stamp_line()
    assert rp.build_text(s).startswith(build_stamp_line())


def test_a_build_warning_rides_with_the_build():
    s = {"run_provenance": {"machine": "M", "engine_build": "abc1234 · src 0123456789ab",
                            "build_warning": "BEHIND THE BRANCH — 2 commit(s) behind"}}
    assert rp.build_text(s) == ("abc1234 · src 0123456789ab · ⚠ BEHIND THE BRANCH — 2 "
                                "commit(s) behind")


def test_a_run_without_the_record_never_borrows_the_readers_machine():
    """A report re-rendered tomorrow on another machine must not name that machine."""
    s = {"run_id": "TG-20261030-145936-036ba94"}
    assert rp.machine_text(s) == rp.NOT_RECORDED
    assert rp.build_text(s) == rp.NOT_RECORDED
    assert platform.node() not in rp.machine_text(s)


# ── the rows, in the reviewer's order ────────────────────────────────────────────

def test_the_panel_rows_come_in_the_order_named(by_the_runner):
    s = _stamped(run_id="HPP-20261030-145936-036ba94")
    labels = [k for k, _ in rp.facts(s, review_status="Estimator review — 42 item(s)")]
    assert labels == ["Run ID", "Runner machine", "Engine build", "Mode",
                      "Reference documents", "Reads", "Final review status"]
    assert dict(rp.facts(s))["Run ID"] == "HPP-20261030-145936-036ba94 · portal run 27d315c6"
    assert "Final review status" not in dict(rp.facts(s)), (
        "with no final status to give, the row is left off rather than guessed")


def test_the_mode_says_llm_only_or_normal():
    assert rp.mode_text({"llm_only": True}).startswith("LLM-only")
    assert rp.mode_text({"llm_only": False}).startswith("Normal")


def test_reference_documents_and_the_brief_are_named():
    s = {"reference_pack_paths": [r"C:\jobs\HPP\Samsung TG guide.pdf"],
         "enquiry_brief": {"text": "x" * 120, "file": r"C:\jobs\HPP\ENQUIRY_BRIEF.txt"}}
    t = rp.references_text(s)
    assert "Samsung TG guide.pdf (held out of the product read)" in t
    assert "enquiry brief filed (120 characters, ENQUIRY_BRIEF.txt)" in t
    assert rp.references_text({}) == "none declared · no enquiry brief"


def test_reads_say_fresh_or_cached_with_the_store_counts():
    s = {"fresh_read": False, "estimate_summary": {"reads_reused": {
        "vision_concept": {"reused": 0, "computed": 1},
        "vision_bom": {"reused": 31, "computed": 0}}}}
    t = rp.reads_text(s)
    assert t.startswith("Cached reads allowed")
    assert "vision_bom 31 reused / 0 made; vision_concept 0 reused / 1 made" in t
    assert rp.reads_text({"fresh_read": True,
                          "estimate_summary": {"reads_reused": {"x": {}}}}).startswith("Fresh")


def test_the_saved_file_carries_the_run_id_inside_the_record():
    """The quote prints the top-level run_id as its reference, so main.py saves the run ID
    inside run_provenance; the panel reads it from there."""
    s = {"run_provenance": {"machine": "M", "run_id": "HPP-20261030-145936-036ba94"}}
    assert rp.run_text(s) == "HPP-20261030-145936-036ba94"


# ── the job report's first page ───────────────────────────────────────────────────

def test_the_report_opens_with_the_panel_and_the_summarys_own_status(by_the_runner):
    import job_report_html as jr
    s = _stamped(llm_only=True, fresh_read=False,
                 run_provenance=None)  # replaced by record() below
    rp.record(s)
    s["run_provenance"]["run_id"] = "HPP-20261030-145936-036ba94"
    html = jr.build_report_html(s)
    assert "Run provenance" in html
    assert html.index("Run provenance") < html.index("<h2>Summary</h2>"), (
        "the panel is on the first page, above the Summary")
    panel = _text(html.split('class="card run-provenance"')[1].split("</table>")[0])
    for want in ("Run ID", "HPP-20261030-145936-036ba94 · portal run 27d315c6",
                 "Runner machine", platform.node(), "runner DESKTOP-4F3TLJN-a1b2c3",
                 "Engine build", build_stamp_line().split(" · ")[0],
                 "Mode", "LLM-only", "Reference documents", "Reads",
                 "Final review status"):
        assert want in panel, f"{want!r} missing from the panel: {panel}"
    status = jr._release_words(jr._record_for(s), s)[1]
    assert status in panel, "the panel and the Summary must state one release status"
    assert _text(html).count(status) >= 2


# ── internal only ─────────────────────────────────────────────────────────────────

def test_the_customer_quotation_carries_none_of_it(by_the_runner):
    from client_quote_html import build_quote_html
    s = _stamped()
    html = build_quote_html(s)
    for kept_out in ("Run provenance", "DESKTOP-4F3TLJN", "Runner machine",
                     s["run_provenance"]["engine_build"]):
        assert kept_out not in html, f"{kept_out!r} reached the customer quotation"


# ── the workbook: the same build, now where it can be seen ───────────────────────

def test_ai_provenance_opens_with_the_run_and_the_build(by_the_runner):
    from openpyxl import Workbook
    from estimation_report import add_provenance_sheet
    s = _stamped(run_id="HPP-20261030-145936-036ba94")
    wb = Workbook()
    add_provenance_sheet(wb, s, {"job_number": "7332"})
    a2 = str(wb["AI Provenance"]["A2"].value)
    first = a2.split("\n")[0]
    assert first.startswith("Run: HPP-20261030-145936-036ba94 · portal run 27d315c6")
    assert f"Machine: {platform.node()} · runner DESKTOP-4F3TLJN-a1b2c3" in first
    assert "Mode: Normal" in first
    assert f"Build: {build_stamp_line()}" in first, "the build is on the first line now"
    assert a2.count("Build: ") == 1, "one build stamp, not a competing second one"
    assert "Drawing: " in a2.split("\n")[1]
    assert wb["AI Provenance"]["A2"].alignment.wrap_text


def test_the_runner_hands_the_engine_its_id_and_the_portal_run(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools" / "runner"))
    import sdi_estimate_runner as runner
    (tmp_path / "output" / "estimates").mkdir(parents=True)
    (tmp_path / "output" / "json").mkdir(parents=True)
    tpl = tmp_path / "Blank Estimate Sheet  WB 2026.xlsx"
    tpl.write_bytes(b"present is all the runner checks")
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(tpl))
    seen = {}

    class _Done:
        returncode = 0
        stdout = iter(())

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    def _popen(*a, **k):
        seen.update(k.get("env") or {})
        return _Done()

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)

    class _Req:
        def post(self, *a, **k):
            class _R:
                @staticmethod
                def raise_for_status():
                    return None
            return _R()

    job = {"run_id": "27d315c6", "client": "Pixel", "units": 1, "drawing_number": "HPP",
           "job_folder": str(tmp_path), "output_path": str(tmp_path / "share")}
    runner._execute(_Req(), "http://x/api/estimate", {}, job, tmp_path, Path("python"),
                    "DESKTOP-4F3TLJN-a1b2c3")
    assert seen.get(rp.RUNNER_ID_ENV) == "DESKTOP-4F3TLJN-a1b2c3"
    assert seen.get(rp.SERVICE_RUN_ID_ENV) == "27d315c6"
    assert seen.get("PATH") == os.environ.get("PATH"), "the rest of the environment is kept"
