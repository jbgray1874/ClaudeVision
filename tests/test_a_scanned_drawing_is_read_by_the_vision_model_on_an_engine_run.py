"""A scanned drawing on an engine run is read by the one reader that can read it (D-598g).

0320730 through the portal, 24 Oct 2026: an M&S pack whose only drawing is a page with no text
layer, beside seven pages of forms. Every engine reader reads text, vectors, tables or flats;
none could read the picture, so the book went out empty, while the same pack as LLM SCAN ONLY
priced. With no part read, no design-intent sheet, no render pack and a page that is only an
image, the engine run now takes the concept read as its fallback. The measured-CAD guard still
refuses a pack with real geometry.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import file_scan  # noqa: E402

SRC = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")


def _decision(**env) -> bool:
    """Execute the scan's own decision line, not a copy of it."""
    tree = ast.parse(SRC)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_scanned_drawing_fallback"
                        for t in n.targets))
    scope = dict(_no_parts=True, _llm_only_run=False, _is_render_pack=False,
                 _design_intent_pages=[], _design_intent_fallback=False,
                 _scanned_pages=["pack.pdf page 2"])
    scope.update(env)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<scan decision>", "exec"), scope)
    return scope["_scanned_drawing_fallback"]


def test_the_pages_with_no_text_layer_are_named():
    s = {"pages": [{"source_pdf_path": "C:\\jobs\\pack.pdf", "page_number": 1,
                    "pdfplumber_text": "MS4 HEALTH AND SAFETY RISK ASSESSMENT FORM"},
                   {"source_pdf_path": "C:\\jobs\\pack.pdf", "page_number": 2,
                    "pdfplumber_text": ""}]}
    assert file_scan.image_only_pages(s) == ["pack.pdf page 2"]
    assert file_scan.image_only_pages({}) == []


def test_an_engine_run_that_read_nothing_off_a_scanned_drawing_falls_back():
    assert _decision() is True


def test_it_does_not_fall_back_where_another_door_answers_or_a_part_was_read():
    assert _decision(_no_parts=False) is False, "a part was read: the readers answered"
    assert _decision(_llm_only_run=True) is False, "an LLM-only run reads it already"
    assert _decision(_is_render_pack=True) is False, "a render pack keeps its own stop"
    assert _decision(_design_intent_pages=[1]) is False, "design-intent has its own fallback"
    assert _decision(_design_intent_fallback=True) is False
    assert _decision(_scanned_pages=[]) is False, "a pack of text the readers could read"


def test_the_fallback_is_a_sight_run_behind_the_measured_cad_guard():
    sight = SRC.index("_sight_run = _llm_only_run or _design_intent_fallback or _scanned_drawing_fallback")
    assert SRC.index("_scanned_drawing_fallback = bool(") < sight
    guard = SRC.index("_concept_refused = _cs_probe.why_not_sightable(summary, _pack_files)")
    assert sight < guard, "the guard runs for every sight run, the fallback included"
    assert "PRICED FROM THE VISION READ: no engine reader found a part" in SRC


# ── END TO END: the engine's own PDF scan, a replayed read, no model call ───────────────────

def _pack(tmp_path):
    import pymupdf
    pdf = tmp_path / "HOOKBAR-PACK.pdf"
    doc = pymupdf.open()
    form = doc.new_page(width=595, height=842)
    form.insert_text((72, 72), "HEALTH AND SAFETY RISK ASSESSMENT FORM", fontsize=12)
    form.insert_text((72, 96), "EQUIPMENT ITEM NAME: 1200MM HOOK IN BAR", fontsize=10)
    scan = doc.new_page(width=842, height=595)          # the drawing: a picture, no text layer
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1200, 800), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    pix.set_rect(pymupdf.IRect(100, 380, 1100, 420), (0, 0, 0))
    scan.insert_image(scan.rect, pixmap=pix)
    doc.save(pdf)
    return pdf


def _scan(tmp_path, monkeypatch, replay):
    import json
    import config
    # Every output folder the run writes, into this test's own folder.
    for name in [n for n in dir(config) if n.endswith("_DIR")]:
        value = getattr(config, name)
        if isinstance(value, Path) and str(value).startswith(str(config.OUTPUT_DIR)):
            d = tmp_path / "out" / name.lower()
            d.mkdir(parents=True, exist_ok=True)
            monkeypatch.setattr(config, name, d)
    monkeypatch.setenv("SDI_OFFLINE", "1")
    monkeypatch.setenv("SDI_LLM_FULL_EXTRACT", "0")
    monkeypatch.delenv("SDI_LLM_ONLY", raising=False)
    if replay:
        answer = {"product": {"name": "HOOK BAR"}, "unit_operations": ["welding", "assembly"],
                  "parts": [{"name": "MAIN TUBE", "kind": "fabricated", "quantity": 1,
                             "material_guess": "MILD STEEL",
                             "assumed_blank_mm": {"length": 1192, "width": 30, "thickness": 1.5},
                             "operations": ["saw", "deburring"]},
                            {"name": "HOOK BRACKET", "kind": "fabricated", "quantity": 2,
                             "material_guess": "MILD STEEL",
                             "assumed_blank_mm": {"length": 90, "width": 49, "thickness": 3},
                             "operations": ["laser_cutting", "deburring"]}]}
        saved = tmp_path / "saved_read.json"
        saved.write_text(json.dumps({"raw_response": json.dumps(answer)}), encoding="utf-8")
        monkeypatch.setenv("SDI_CONCEPT_REPLAY", str(saved))
    else:
        monkeypatch.delenv("SDI_CONCEPT_REPLAY", raising=False)
    summary, _ = file_scan.scan_pdf_file(_pack(tmp_path), auto_discover_dxf=False)
    return summary


def test_the_engine_run_of_a_scanned_drawing_is_priced_from_the_vision_read(tmp_path, monkeypatch):
    s = _scan(tmp_path, monkeypatch, replay=True)
    assert s["scanned_drawing_fallback"]["pages"] == ["HOOKBAR-PACK.pdf page 2"]
    made = [p for p in s["manufacturing_writeup"]["parts"]
            if str(p.get("part_number") or "").startswith("HOOKBAR-PACK-CPT")]
    assert len(made) == 3, "the unit, the tube and the bracket reach costing"
    assert not s.get("run_stop")
    assert any(f.startswith("PRICED FROM THE VISION READ: no engine reader found a part")
               for f in s.get("review_flags") or [])


def test_a_vision_read_that_cannot_answer_still_stops_and_says_why(tmp_path, monkeypatch):
    s = _scan(tmp_path, monkeypatch, replay=False)
    assert s["run_stop"]["kind"] == "no_parts_read"
    assert "the drawing read was tried and did not answer" in s["run_stop"]["reason"]
    assert s["run_stop"]["pages_not_read"] == ["HOOKBAR-PACK.pdf page 2"]
