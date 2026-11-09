"""Targeted model help for the gaps the deterministic read left (SCRUM-194 requirement 3).

Deterministic first; one narrow question per gap on the part's own pages; the answer checked
against the sheet's own readings before it is used; written as llm_assisted below every
deterministic source; every ask recorded; a deterministic-only run asks nothing and names each
gap. An LLM recovery never turns the deterministic reading test into a pass: the source says so.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import gap_fill as gf  # noqa: E402
import source_precedence as sp  # noqa: E402


def _summary(**m2):
    part = {"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP", "pages": [5], "quantity": 1,
            "materials": ["STAINLESS STEEL"], "normalized_thickness_mm": 3.0, "page_roles": ["detail"],
            "title_block_material": {"material": "STAINLESS STEEL", "thickness_mm": 3.0, "page": 5},
            "pitch_values_mm": [282.0]}
    part.update(m2)
    return {"manufacturing_writeup": {"parts": [part, {"part_number": "HAFELE 651.09.302", "quantity": 4,
                                                        "page_roles": ["bought_in"], "pages": [2]}]},
            "pages": [{"page_number": 5, "pdfplumber_text": "11O A (5x)n3.4THRU 1168O A 3mmSTAINLESSSTEEL"}],
            "document_analysis": {"bom_rows": [{"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP",
                                                "quantity": 1}]}}


def test_the_gaps_are_the_facts_costing_cannot_do_without():
    assert gf.gaps_of(_summary()["manufacturing_writeup"]["parts"][0]) == ["size"]
    full = _summary(blank_length_mm=1168.0, blank_width_mm=11.0)["manufacturing_writeup"]["parts"][0]
    assert gf.gaps_of(full) == []
    bare = {"part_number": "X", "pages": [4]}
    assert gf.gaps_of(bare) == ["material", "thickness_or_section", "size", "quantity"]
    tube = {"part_number": "T", "pages": [7], "materials": ["MILD STEEL"], "quantity": 2,
            "section_stock": {"a": 30, "b": 30, "t": 2}}
    assert gf.gaps_of(tube) == ["size"], "a section without a length is a size gap"


def test_a_deterministic_only_run_asks_nothing_and_names_every_gap(monkeypatch):
    monkeypatch.setenv("SDI_DETERMINISTIC_ONLY", "1")
    s = _summary()
    calls = []
    rec = gf.run(s, call=lambda payload: calls.append(payload) or "{}")
    assert calls == [] and rec["asked"] == 0
    assert rec["open"] == ["UPC0358141 M2: size"] and "deterministic-only" in rec["items"][0]["effect"][0]
    assert s["gap_fill"] is rec and "blank_length_mm" not in s["manufacturing_writeup"]["parts"][0]


def test_one_question_on_the_parts_own_pages_validated_then_written_as_llm_assisted(monkeypatch):
    monkeypatch.delenv("SDI_DETERMINISTIC_ONLY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "test-key-never-sent")
    s = _summary()
    seen = []

    def model(payload):
        seen.append(payload)
        assert "PAGE 5" in payload and "PAGE 1" not in payload and "HAFELE" not in payload
        return json.dumps({"length_mm": 1168, "width_mm": 11, "page": 5, "words": "1168 O/A, 11 O/A"})

    rec = gf.run(s, call=model)
    part = s["manufacturing_writeup"]["parts"][0]
    assert rec["asked"] == 1 and rec["filled"] == 1 and rec["open"] == []
    assert (part["blank_length_mm"], part["blank_width_mm"]) == (1168.0, 11.0)
    assert part["blank_length_mm_source"] == "llm_assisted", "an LLM recovery is labelled, never deterministic"
    item = rec["items"][0]
    assert item["gap"] == "size" and item["pages"] == [5] and item["validation"]["ok"] and item["answer"]["page"] == 5
    assert any("llm_assisted" in f for f in part["review_flags"])
    assert sp.rank("llm_assisted") < sp.rank("drawing_deterministic") and sp.rank("llm_assisted") > sp.rank("inference")
    assert sp.rank("llm_assisted") > sp.rank("llm_full_extract")


def test_an_answer_that_contradicts_the_sheet_or_names_another_page_is_not_used(monkeypatch):
    monkeypatch.delenv("SDI_DETERMINISTIC_ONLY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "test-key-never-sent")
    s = _summary()
    rec = gf.run(s, call=lambda p: json.dumps({"length_mm": 100, "width_mm": 11, "page": 5, "words": "100"}))
    assert rec["filled"] == 0 and "feature spread" in rec["items"][0]["validation"]["why"]
    assert "blank_length_mm" not in s["manufacturing_writeup"]["parts"][0]
    s2 = _summary()
    rec2 = gf.run(s2, call=lambda p: json.dumps({"length_mm": 1168, "width_mm": 11, "page": 9, "words": "x"}))
    assert rec2["filled"] == 0 and "page 9" in rec2["items"][0]["validation"]["why"]
    s3 = _summary(normalized_thickness_mm=None)
    rec3 = gf.run(s3, call=lambda p: json.dumps({"thickness_mm": 2.0, "page": 5, "words": "2mm"})
                  if "gauge" in p else json.dumps({"length_mm": 1168, "width_mm": 11, "page": 5, "words": "O/A"}))
    thick = next(i for i in rec3["items"] if i["gap"] == "thickness_or_section")
    assert not thick["validation"]["ok"] and "title block" in thick["validation"]["why"]
    assert rec3["open"] == ["UPC0358141 M2: thickness_or_section"], "the gap stays open and named"


def test_a_model_that_cannot_be_reached_leaves_the_gap_named(monkeypatch):
    monkeypatch.delenv("SDI_DETERMINISTIC_ONLY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "test-key-never-sent")
    s = _summary()

    def down(p):
        raise ConnectionError("no route")

    rec = gf.run(s, call=down)
    assert rec["asked"] == 1 and rec["filled"] == 0 and "could not be reached" in rec["items"][0]["effect"][0]
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    rec2 = gf.run(_summary(), call=lambda p: "{}")
    assert rec2["why_not_asked"] == "no model key on this machine" and rec2["open"] == ["UPC0358141 M2: size"]
