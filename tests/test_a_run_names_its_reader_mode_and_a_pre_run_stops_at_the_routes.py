"""One reader mode per run, chosen on the page, and a BOMs & routes pre-run (JG, 9 Nov 2026).

Modes: full estimate, targeted (the drawing reader first, the model asked only about the gaps),
drawing reader only, SolidWorks only, Document Manager only, LLM read only. Each is sent by the
page, carried on the Run, handed to the runner, put on the engine's command line, and checked
back against the engine's echoed command. The pre-run reads and routes, then stops before the
workbook and files only the BOMs and Routes and the record.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "runner"))

import sdi_estimate_runner as runner  # noqa: E402

ROUTES = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")
MAIN = (ROOT / "src" / "main.py").read_text(encoding="utf-8")


def _cmd(**kw):
    return runner.engine_command(ROOT, Path("python"), ROOT / "job", 1, "ACME", **kw)


def test_each_reader_mode_reaches_the_engine_command_line():
    assert "--targeted" in _cmd(reader_mode="targeted")
    assert "--solidworks-only" in _cmd(reader_mode="solidworks")
    assert "--docmgr-only" in _cmd(reader_mode="docmgr")
    full = _cmd()
    assert not {"--targeted", "--solidworks-only", "--docmgr-only", "--bom-routes-only"} & set(full)
    pre = _cmd(reader_mode="targeted", bom_routes_out=Path("C:/out"))
    i = pre.index("--bom-routes-only")
    assert pre[i + 1] == "--bom-routes-out" and pre[i + 2] == str(Path("C:/out")) and "--targeted" in pre


def test_the_service_carries_the_mode_and_checks_the_engine_was_told():
    for m in ('"targeted": "--targeted"', '"solidworks": "--solidworks-only"', '"docmgr": "--docmgr-only"'):
        assert m in ROUTES
    assert 'reader_mode=method if method in READER_MODE_FLAG else "",' in ROUTES
    assert '"reader_mode": str(getattr(run, "reader_mode", "") or ""),' in ROUTES
    assert '("--bom-routes-only", getattr(run, "bom_routes_only", False))' in ROUTES
    assert 'job_type="bom_routes" if req.bom_routes_only else "",' in ROUTES
    assert "Document-Manager-only run cannot read the models" in ROUTES
    assert "bom_routes" in runner.RUNNER_CAPABILITIES


def test_the_page_offers_every_mode_and_the_pre_run():
    for v in ('value="targeted"', 'value="deterministic"', 'value="solidworks"', 'value="docmgr"', 'value="llm"'):
        assert v in PAGE[PAGE.index('id="runMode"'):][:1400], v
    assert 'id="bPreRun"' in PAGE and "bom_routes_only: _preRun," in PAGE


def test_the_engine_stops_at_the_routes_on_a_pre_run_and_names_its_files():
    at = MAIN.index("THE PRE-RUN STOPS HERE")
    block = MAIN[at:at + 2000]
    assert block.index("write_both") < block.index("PACK_EXTRACT_OUTPUTS=") < block.index("continue")
    assert MAIN.index("THE PRE-RUN STOPS HERE") < MAIN.index('_time_stage("populate_workbook", True)')
    assert 'raise SystemExit(f"{\' and \'.join(_modes)} ask different questions; pass one reader mode.")' in MAIN


def test_a_pre_run_files_like_an_extract_from_its_own_output_line():
    log = ["   -> PRE-RUN: 9 BOM row(s)", 'PACK_EXTRACT_OUTPUTS=["/nope/a.xlsx"]']
    assert runner.pack_extract_outputs(log) == [], "only files that exist are filed"
    src = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
    assert 'pre_run = str(job.get("job_type") or "") == "bom_routes"' in src
    assert "extract_job = str(job.get(\"job_type\") or \"\") in PACK_EXTRACT_KIND or pre_run" in src
