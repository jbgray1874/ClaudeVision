"""A pack's printed words are read with its pictures (D-462).

K-Wellness FSDU, 11 Oct 2026: a customer's sixteen-page technical brief — a presentation,
neither a drawing sheet nor a bare render — states the product in its words: a 500 × 500
footprint, folded sheet steel powder coated in a neutral colour, five front shelves, ten
mirrored side shelves, and the quantity the price is wanted at. The render read sent the
pictures alone, so every stated fact was left to be guessed off the images.

Now every concept read extracts the pack's own text layer; where the pages are not drawing
sheets (which have their own, stricter channel, D-415) and the text is non-empty, the words
go to the model under their own section. A wordless render asks exactly the question it
always has, so every cache key it holds still stands.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import concept_scan as cs  # noqa: E402

WORDS = ("BR099X Boots Generic FSDU. The new metal FSDU will be manufactured from sheet "
         "steel and powdercoated in a neutral colour. 500mm x 500mm. Front shelves x5. "
         "Side shelves (Mirrored) x10. Please base all prices on a Qty of 200.")


def test_the_document_section_cannot_change_without_its_version():
    got = hashlib.sha256(cs._DOC_TEXT_SECTION.encode()).hexdigest()[:12]
    assert got == cs._DOC_TEXT_FINGERPRINT, (
        f"the document-words section changed. Bump DOC_TEXT_PROMPT_VERSION (now "
        f"{cs.DOC_TEXT_PROMPT_VERSION!r}) and set _DOC_TEXT_FINGERPRINT = {got!r}")


def test_a_read_with_words_is_told_they_are_the_customers_statement():
    text = cs.concept_prompt_text([b"png"], doc_words=WORDS)
    assert "WORDS PRINTED ON THE PAGES" in text
    assert "is a FACT that outranks what" in text
    assert "powdercoated in a neutral colour" in text and "Qty of 200" in text
    # Process prose is named as context, never a part.
    assert "never a part" in text
    # It is a render read still: no sheet preamble, and the render prompt is the body.
    assert "THESE ARE DRAWING SHEETS" not in text


def test_the_brief_still_reads_after_and_over_the_documents_words():
    text = cs.concept_prompt_text([b"png"], "500 x 500 x 1500mm, 200 off", doc_words=WORDS)
    assert text.index("WORDS PRINTED ON THE PAGES") < text.index("ENQUIRY BRIEF")
    assert "the brief outranks these words" in text


def test_a_sheet_read_keeps_its_own_channel_and_never_doubles_the_words():
    text = cs.concept_prompt_text([b"png"], sheet=True, sheet_words=WORDS, doc_words=WORDS)
    assert text.count("powdercoated in a neutral colour") == 1
    assert "WORDS PRINTED ON THE PAGES" not in text
    assert "TEXT PRINTED ON THE SHEET(S)" in text


def test_a_wordless_render_keeps_its_prompt_and_its_cache_key():
    assert cs.concept_prompt_text([b"png"]) == cs.concept_prompt_text([b"png"], doc_words="")
    assert cs._cache_key([b"png"], "m") == cs._cache_key([b"png"], "m", doc_words="")
    with_words = cs._cache_key([b"png"], "m", doc_words=WORDS)
    assert with_words != cs._cache_key([b"png"], "m")
    assert with_words != cs._cache_key([b"png"], "m", doc_words=WORDS + " and a lid")
    # A sheet read's key never hashes the document channel.
    assert (cs._cache_key([b"png"], "m", sheet=True, sheet_words=WORDS, doc_words=WORDS)
            == cs._cache_key([b"png"], "m", sheet=True, sheet_words=WORDS))


def test_read_concept_sends_the_packs_words_and_says_how_many(tmp_path, monkeypatch):
    pdf = tmp_path / "tech_brief.pdf"
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=960, height=540)
    page.insert_text((40, 60), "The new metal FSDU will be manufactured from sheet steel")
    page.insert_text((40, 90), "and powdercoated in a neutral colour. 500mm x 500mm.")
    doc.save(str(pdf))
    doc.close()

    import _bom_vision_reader as pathB
    monkeypatch.setattr(pathB, "count_pages", lambda p: 1)
    monkeypatch.setattr(pathB, "render_page_to_png", lambda p, i: b"png-bytes")
    monkeypatch.setattr(cs, "_cache_dir", lambda: tmp_path / "cache")
    sent = {}

    def fake_call(pngs, model, brief="", **kw):
        sent.update(kw, prompt=cs.concept_prompt_text(pngs, brief, **kw))
        return '{"parts": []}'

    monkeypatch.setattr(cs, "_call_vision_llm", fake_call)
    read = cs.read_concept([str(pdf)])
    assert "sheet steel" in sent.get("doc_words", "")
    assert "WORDS PRINTED ON THE PAGES" in sent["prompt"]
    assert read.get("document_text_chars", 0) > 0


def test_a_pack_with_no_text_layer_sends_no_document_section(tmp_path, monkeypatch):
    pdf = tmp_path / "render.pdf"
    import pymupdf
    doc = pymupdf.open()
    doc.new_page(width=960, height=540)                      # a page with no words on it
    doc.save(str(pdf))
    doc.close()

    import _bom_vision_reader as pathB
    monkeypatch.setattr(pathB, "count_pages", lambda p: 1)
    monkeypatch.setattr(pathB, "render_page_to_png", lambda p, i: b"png-bytes")
    monkeypatch.setattr(cs, "_cache_dir", lambda: tmp_path / "cache")
    sent = {}

    def fake_call(pngs, model, brief="", **kw):
        sent.update(kw, prompt=cs.concept_prompt_text(pngs, brief, **kw))
        return '{"parts": []}'

    monkeypatch.setattr(cs, "_call_vision_llm", fake_call)
    read = cs.read_concept([str(pdf)])
    assert "doc_words" not in sent
    assert "WORDS PRINTED ON THE PAGES" not in sent["prompt"]
    assert "document_text_chars" not in read
