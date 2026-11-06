"""A partner run says where it is and where its time went — and no other run changes (D-529).

Muhammad's endpoint needed to show a stage while a run works and, once it has finished, the
measured time down to each model call: the vision read, every market-research question, the
cache hits. James: "I don't want the functionality of the portal changing. This is only for
Muhammad." So everything here is off unless the run carries the marker only the partner
endpoint files — and these tests hold the off state as hard as the on state.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import run_timing as rt  # noqa: E402


def test_with_no_marker_nothing_is_said_or_counted(capsys):
    rt.reset()
    rt.mark("start estimate_document")
    rt.stage("pricing")
    rt.count("market research", 2.0)
    rt.mark("done estimate_document")
    out = capsys.readouterr().out
    assert "[api-stage]" not in out, "a portal run printed a partner stage"
    assert rt.report_json()["model_calls"] == {}
    assert "estimate_document" in rt.report() and "[api" not in rt.report()


def test_a_partner_run_says_each_stage_once_with_its_elapsed_time(capsys):
    rt.reset()
    rt.enable_detail()
    rt.mark("start extract_pdf_summary")
    rt.mark("done extract_pdf_summary")
    rt.mark("start estimate_document")
    rt.mark("start job_level_pricing_and_rewrite")          # same stage: said once
    rt.mark("start populate_workbook")
    out = capsys.readouterr().out
    said = [l.split("] ", 1)[1].rsplit(" +", 1)[0] for l in out.splitlines()
            if l.startswith("[api-stage]")]
    assert said == ["reading", "pricing", "workbook"]
    rt.reset()


def test_a_partner_run_counts_its_model_calls_and_cache_hits():
    rt.reset()
    rt.enable_detail()
    rt.count("market research", 3.5)
    rt.count("market research", 2.5, failed=True)
    rt.count("market research", cache_hit=True)
    rt.count("vision read", 41.0)
    data = rt.report_json()
    mr = data["model_calls"]["market research"]
    assert (mr["calls"], mr["seconds"], mr["failed"], mr["cache_hits"]) == (2, 6.0, 1, 1)
    assert data["model_calls"]["vision read"]["calls"] == 1
    json.dumps(data)                                         # it travels as one log line
    rt.reset()


def test_the_research_wrapper_counts_a_cached_answer(monkeypatch):
    import generated_price_cache as gpc
    import web_ai_price_lookup as w
    rt.reset()
    rt.enable_detail()
    monkeypatch.setattr(gpc, "cached_estimate",
                        lambda *a, **k: {"found": True, "price_from_cache": True})
    w._llm_market_estimate({"description": "castor"})
    assert rt.report_json()["model_calls"]["market research"]["cache_hits"] == 1
    rt.reset()


def test_only_the_partner_marker_turns_it_on():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "main.py"),
               encoding="utf-8").read()
    at = src.index("enable_detail()")
    assert 'PARTNER_API_RUN.json").is_file()' in src[at - 400:at]
    assert "if _rt.detail_on():" in src, "the timing data is printed for every run"
