"""D-597: every page of every document reaches the read, in whole pages, or the gap is named.

The whole-pack read was handed the job's anchor PDF alone and cut it at 60,000 characters
without a word; the concept read trimmed every page to a proportional share and called every
page included. Now the whole-pack read takes every document, an oversized pack is read in
page-labelled batches of whole pages and reconciled, the concept read sends whole pages and
names any it could not, and a page coverage record says, page by page, what read it — with
unread text holding the release and image-only or coarse pages asking for a ruling.

Packs here are made on the fly; nothing names a job.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402
import invariants  # noqa: E402
import llm_full_extract as lfe  # noqa: E402
import page_coverage as pcov  # noqa: E402


def _pdf(path, pages, size=(595, 842)):
    """A PDF whose pages carry the given lines of text; None makes an image-only page."""
    import pymupdf
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=size[0], height=size[1])
        y = 40
        for line in (lines or []):
            page.insert_text((30, y), line, fontsize=7)
            y += 9
    doc.save(str(path))
    return str(path)


def _lines(prefix, n):
    return [f"{prefix} LINE {i:04d} FINISH ZINC PLATED NOTE {i}" for i in range(n)]


# ── the whole-pack read takes every document, in whole pages ───────────────────────────────

def test_one_document_under_the_budget_is_word_for_word_the_old_context(tmp_path):
    pdf = _pdf(tmp_path / "ga.pdf", [_lines("GA", 5), None, _lines("SPEC", 3)])
    batches = lfe.context_batches(lfe.pack_pages([pdf]))
    assert len(batches) == 1
    assert batches[0]["text"] == lfe.build_document_context(pdf), \
        "same words, so a pack read before D-597 keeps its cached read"


def test_every_document_of_the_job_reaches_the_whole_pack_read(tmp_path):
    ga = _pdf(tmp_path / "ga.pdf", [_lines("GA", 3)])
    spec = _pdf(tmp_path / "spec.pdf", [["SPECIFICATION: POLISH 400 GRIT, NICKEL 15 MICRON"]])
    text = lfe.context_batches(lfe.pack_pages([ga, spec]))[0]["text"]
    assert "ga.pdf — PAGE 1" in text and "spec.pdf — PAGE 1" in text
    assert "NICKEL 15 MICRON" in text, "the specification in the second file is read"


def test_an_oversized_pack_is_batched_in_whole_pages_never_trimmed(tmp_path):
    pages = [_lines(f"P{k}", 60) for k in range(6)]
    pdf = _pdf(tmp_path / "big.pdf", pages)
    pp = lfe.pack_pages([pdf])
    batches = lfe.context_batches(pp, budget=6000)
    assert len(batches) > 1 and all(b["chars"] <= 6000 + 400 for b in batches)
    joined = "\n".join(b["text"] for b in batches)
    for p in pp:
        for line in p["lines"]:
            assert line in joined, "every line of every page is in some batch, whole"
    assert all(b["text"].startswith(f"[PART {b['index']} OF {len(batches)} OF THIS PACK")
               for b in batches)
    assert all(len(set(b["keys"])) == len(b["keys"]) for b in batches)


def test_a_page_longer_than_a_batch_is_split_and_labelled_not_cut(tmp_path):
    pdf = _pdf(tmp_path / "long.pdf", [_lines("LONG", 80)])
    pp = lfe.pack_pages([pdf])
    batches = lfe.context_batches(pp, budget=2500)
    labels = [l for b in batches for l in b["pages"]]
    assert len(labels) > 1 and all("(part " in l for l in labels)
    joined = "\n".join(b["text"] for b in batches)
    assert "".join(pp[0]["lines"]).replace("\n", "") in joined.replace("\n", "") or all(
        line[:20] in joined for line in pp[0]["lines"])


def _answer(rows, notes=(), weld=None):
    return json.dumps({"drawing_info": {"notes": list(notes), "finish_general": "ZINC"},
                       "bom": rows, "routes": [], "assemblies": [],
                       "spec": {"weld": weld}, "warnings": [], "missing_information": [],
                       "extraction_confidence": "high"})


def test_batches_are_read_and_reconciled_with_disagreements_kept(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path / "big.pdf", [_lines(f"P{k}", 60) for k in range(4)])
    monkeypatch.setenv("SDI_LLM_EXTRACT_CACHE_DIR", str(tmp_path / "cache"))
    calls = []

    def fake(content, model, system=""):
        calls.append(content)
        k = len(calls)
        if k == 1:
            return _answer([{"part_number": "A1", "description": "BRACKET", "qty": 2,
                             "material": "MILD STEEL"}], notes=["DEBURR ALL EDGES"], weld="TIG")
        return _answer([{"part_number": "A1", "description": "BRACKET", "qty": 2,
                         "material": "STAINLESS"},
                        {"part_number": "B2", "description": "CAP", "qty": 4}],
                       notes=["POLISH 400 GRIT"], weld="TIG")
    monkeypatch.setattr(lfe, "_call_llm", fake)
    job = lfe.extract_full_pack([pdf], budget=6000)
    assert len(calls) > 1 and job["found"]
    codes = {str(r.get("part_number")) for r in job["bom"]}
    assert codes == {"A1", "B2"}, "a part from any part of the pack is kept, once"
    assert any("disagree on bom[A1].material" in w for w in job["warnings"])
    assert job["_batch_conflicts"] and job["_coverage"]["not_read"] == []
    assert all(p["read"] for p in job["_coverage"]["pages"])


def test_a_part_of_the_pack_that_fails_leaves_its_pages_an_explicit_gap(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path / "big.pdf", [_lines(f"P{k}", 60) for k in range(4)])
    monkeypatch.setenv("SDI_LLM_EXTRACT_CACHE_DIR", str(tmp_path / "cache"))
    calls = []

    def fake(content, model, system=""):
        calls.append(content)
        return "not json" if len(calls) == 2 else _answer([{"part_number": f"X{len(calls)}",
                                                            "description": "PART", "qty": 1}])
    monkeypatch.setattr(lfe, "_call_llm", fake)
    job = lfe.extract_full_pack([pdf], budget=6000)
    cov = job["_coverage"]
    assert cov["not_read"] and any(not b["read"] for b in cov["batches"])
    unread = [p for p in cov["pages"] if not p.get("read")]
    assert unread, "the failed part's pages are marked unread"
    pc = pcov.build({"llm_full_extract_coverage": cov})
    assert {g["kind"] for g in pc["gaps"]} == {"text_not_read"}
    viol = invariants.check_every_page_reached_a_read({"page_coverage": pc})
    assert viol[0]["code"] == "page_text_not_read" and viol[0]["severity"] == invariants.BLOCKING


def test_the_inference_pass_asks_each_part_only_about_parts_still_missing(monkeypatch):
    asked = []

    def fake(ctx, bom, missing, model=""):
        asked.append([m["part_number"] for m in missing])
        if ctx == "first":
            return {"parts": [{"part_number": "A1", "material": "MILD STEEL"}], "routes": [],
                    "found": True, "_raw_response": "r1"}
        return {"parts": [{"part_number": "B2", "material": "ACRYLIC"},
                          {"part_number": "A1", "material": "ALUMINIUM"}],
                "routes": [], "found": True, "_raw_response": "r2"}
    monkeypatch.setattr(lfe, "infer_missing_details", fake)
    res = lfe.infer_missing_details_in_batches(
        ["first", "second"], [], [{"part_number": "A1"}, {"part_number": "B2"}])
    assert asked == [["A1", "B2"], ["B2"]]
    assert {p["part_number"]: p["material"] for p in res["parts"]} == {"A1": "MILD STEEL",
                                                                      "B2": "ACRYLIC"}


def test_drawing_facts_are_gathered_from_every_document(tmp_path, monkeypatch):
    import drawing_facts as df
    a, b = str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")
    facts = {a: {"pages": [{"page": 1}], "by_part": {"P1": {"finish": "ZINC"}},
                 "spec_block": {"weld": "TIG"}},
             b: {"pages": [{"page": 1}], "by_part": {"P1": {"finish": "RAW", "material": "MS"},
                                                     "P2": {"finish": "POWDER"}},
                 "spec_block": {"weld": "MIG", "powder_micron": "80"}}}
    monkeypatch.setattr(df, "extract_drawing_facts", lambda p: facts[str(p)])
    got = df.extract_drawing_facts_for([a, b])
    assert got["by_part"]["P1"] == {"finish": "ZINC", "material": "MS"}
    assert got["by_part"]["P2"] == {"finish": "POWDER"}
    assert got["spec_block"] == {"weld": "TIG", "powder_micron": "80"}
    assert [p["document"] for p in got["pages"]] == ["a.pdf", "b.pdf"]


def test_the_scan_hands_the_whole_pack_read_every_job_document(tmp_path):
    import file_scan
    ga = _pdf(tmp_path / "ga.pdf", [["GA"]])
    spec = _pdf(tmp_path / "spec.pdf", [["SPEC"]])
    brief = _pdf(tmp_path / "ENQUIRY_BRIEF.pdf", [["BRIEF"]])
    (tmp_path / "model.step").write_text("x", encoding="utf-8")
    docs = file_scan.job_documents({"scanned_documents": [spec, ga, brief,
                                                          str(tmp_path / "model.step"), ga]}, ga)
    assert [Path(d).name for d in docs][:2] == ["ga.pdf", "spec.pdf"]
    assert all(Path(d).suffix == ".pdf" for d in docs) and len(docs) == len(set(docs))
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "_job = extract_full_pack(_job_pdfs)" in src
    assert "extract_drawing_facts_for(_job_pdfs)" in src
    assert "infer_missing_details_in_batches(" in src
    assert "extract_full_job(str(pdf_path))" not in src


# ── the concept read sends whole pages and names what it could not ─────────────────────────

def test_the_concept_read_sends_whole_pages_and_names_any_it_could_not(tmp_path, monkeypatch):
    pages = [_lines(f"P{k}", 40) for k in range(5)]
    pdf = _pdf(tmp_path / "pack.pdf", pages)
    full, cov = cs.sheet_text_with_coverage([pdf])
    assert cov["pages_omitted"] == 0 and cov["omitted_pages"] == []
    monkeypatch.setattr(cs, "SHEET_TEXT_MAX_CHARS", len(full) // 2)
    text, cov = cs.sheet_text_with_coverage([pdf])
    assert cov["pages_omitted"] >= 1 and cov["pages_trimmed"] == 0
    assert "trimmed" not in text and "NOT SENT" in text
    for label in cov["omitted_pages"]:
        assert label in text, "the page not sent is named to the model"
    chunks = [c for c in full.split("\n[") if c]
    sent_whole = [c for c in chunks if c.split("\n", 1)[0].strip("[]") not in cov["omitted_pages"]]
    assert all(c in text for c in sent_whole), "a page that went, went whole"


def test_a_png_reports_its_size():
    import pymupdf
    doc = pymupdf.open()
    doc.new_page(width=842, height=595)
    png = doc[0].get_pixmap(dpi=72).tobytes("png")
    assert cs.png_size(png) == (842, 595) and cs.png_size(b"nope") == (0, 0)


# ── the page coverage record ───────────────────────────────────────────────────────────────

def _pages(*specs):
    return [{"document": d, "page": n, "chars": c, "has_text": c > 0, "width_pt": w,
             "height_pt": h} for d, n, c, w, h in specs]


def test_coverage_names_image_only_and_coarse_pages_and_unsent_text():
    pages = _pages(("ga.pdf", 1, 400, 595, 842), ("ga.pdf", 2, 0, 842, 595),
                   ("big.pdf", 1, 0, 2384, 1684), ("spec.pdf", 1, 900, 595, 842))
    summary = {"concept_read": {
        "pages_rendered": [{"document": "ga.pdf", "page": 1, "px": [1414, 2000]},
                           {"document": "ga.pdf", "page": 2, "px": [2000, 1414]},
                           {"document": "big.pdf", "page": 1, "px": [2000, 1414]},
                           {"document": "spec.pdf", "page": 1, "px": [1414, 2000]}],
        "text_coverage": {"omitted_pages": ["spec.pdf, page 1"]}}}
    pc = pcov.build(summary, pages)
    kinds = {(g["document"], g["page"]): g["kind"] for g in pc["gaps"]}
    assert kinds == {("big.pdf", 1): "image_coarse", ("spec.pdf", 1): "text_not_sent"}
    big = next(p for p in pc["pages"] if p["document"] == "big.pdf")
    assert big["paper"] == "A1" and big["concept_image"]["dpi"] < 150
    ga2 = next(p for p in pc["pages"] if p["page"] == 2)
    assert ga2["paper"] == "A4" and ga2["concept_image"]["dpi"] >= 150


def test_an_image_only_page_no_llm_read_took_is_named_and_asks_a_ruling():
    pages = _pages(("ga.pdf", 1, 400, 595, 842), ("ga.pdf", 2, 0, 842, 595))
    cov = {"batches": [{"index": 1, "read": True}],
           "pages": [dict(p, read=True, batches=[1]) for p in pages]}
    pc = pcov.build({"llm_full_extract_coverage": cov}, pages)
    assert [(g["page"], g["kind"]) for g in pc["gaps"]] == [(2, "image_only")]
    viol = invariants.check_every_page_reached_a_read({"page_coverage": pc})
    assert viol[0]["code"] == "page_image_not_read_reliably"
    assert viol[0]["severity"] == invariants.WARNING and viol[0]["detail"]["needs_ruling"]


def test_no_llm_reading_is_said_not_reported_as_every_page_read():
    pc = pcov.build({}, _pages(("ga.pdf", 1, 400, 595, 842)))
    assert pc["llm_read"] is False and pc["gaps"] == []
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert "NO LLM READING RAN" in src


def test_a_coverage_record_that_failed_holds_the_release():
    viol = invariants.check_every_page_reached_a_read(
        {"page_coverage": {"error": "boom", "pages": [], "gaps": []}})
    assert viol[0]["code"] == "page_coverage_not_built"
    assert viol[0]["severity"] == invariants.BLOCKING
    assert invariants.check_every_page_reached_a_read in invariants.CHECKS


def test_paper_sizes_are_named_from_the_page_itself():
    assert pcov.paper(595, 842) == "A4" and pcov.paper(1191, 842) == "A3"
    assert pcov.paper(2384, 1684) == "A1" and pcov.paper(500, 500) == "176 x 176 mm"
    assert pcov.effective_dpi([2000, 1414], 842, 595) == 171
    assert pcov.effective_dpi([2000, 1414], 2384, 1684) == 60
