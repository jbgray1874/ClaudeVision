"""The quotation leads with the unit and the price follows, smaller (D-570); the unit is pictured
in the client's own setting as an artist's impression made from the drawing itself, once (D-571).

James Gray, 21 Oct 2026: "de-emphasise the price and put it below the image of the unit —
some font sizes smaller but keeping all the same details; take the unit in the GA and turn it
into a rendered image with a suitable backdrop depending on the client."
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config  # noqa: E402
import quote_render as qr  # noqa: E402
import run_timing as rt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
CFG = {"enabled": True, "model": "grok-imagine-image-2.0", "aspect_ratio": "3:2", "resolution": "2k",
       "quality": "medium", "text_model": "grok-2-image"}


def _online(monkeypatch, tmp_path, cfg=None):
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.delenv("SDI_QUOTE_RENDER_ENABLED", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("SDI_READ_STORE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(config, "QUOTE_RENDER", dict(cfg or CFG), raising=False)
    rt.reset()


# ── D-571: the scene is the customer's ─────────────────────────────────────────────────

def test_the_scene_is_the_customers_by_table_template_or_default(monkeypatch):
    monkeypatch.setattr(config, "CUSTOMER_QUOTE_SCENES", {"TTI": "a Milwaukee tool retailer's power-tool wall"},
                        raising=False)
    monkeypatch.setattr(config, "QUOTE_RENDER", {"scene_template": "inside a {customer} store, on the shop floor",
                                                 "default_scene": "on a bright, modern retail shop floor"},
                        raising=False)
    assert qr.scene_for("Tesco") == "inside a Tesco store, on the shop floor"
    assert qr.scene_for("TTI") == "a Milwaukee tool retailer's power-tool wall"
    assert qr.scene_for("Techtronic TTI Ltd") == "a Milwaukee tool retailer's power-tool wall"
    assert qr.scene_for("") == "on a bright, modern retail shop floor"


def test_the_words_come_from_the_record_and_the_prompt_keeps_the_drawing_and_asks_for_space():
    parts = [{"part_number": "90001-01-05M", "normalized_material": "MILD STEEL", "normalized_finish": "POWDER COATED",
              "colour": "CHALK WHITE"},
             {"part_number": "90001-01-01M", "normalized_material": "STAINLESS STEEL", "normalized_finish": "BRUSHED"}]
    words = qr.product_words({"solidworks_native": {"top_assembly": "90001-01-GA",
                                                    "top_assembly_bbox_mm": [1298, 1438, 450]}},
                             parts, product="1200 Rail - Chalk White")
    assert words.startswith("1200 Rail - Chalk White")
    assert "Mild Steel" in words and "Stainless Steel" in words
    assert "powder coated" in words and "Chalk White" in words
    assert "about 1438 x 1298 x 450 mm" in words
    prompt = qr.render_prompt(words, "inside a Tesco store, on the shop floor", {}, from_drawing=True)
    assert "inside a Tesco store" in prompt and "generous clear space around it" in prompt
    assert "Preserve the unit's complete form, proportions, structure, materials and stated finish" in prompt
    assert "Ignore the drawing's title block, parts tables, dimensions" in prompt
    assert "Do not invent features" in prompt and "No people" in prompt and "no text" in prompt
    # The first live picture drew a solid top on an open rail: an open frame stays open.
    assert "do not add a top, panel, surface or infill the drawing does not show" in prompt
    assert "a bar or a rail, it stays open" in prompt
    plain = qr.render_prompt(words, "inside a Tesco store, on the shop floor", {}, from_drawing=False)
    assert "drawing" not in plain and "No text, no captions, no price tags, no people." in plain


def test_no_picture_offline_without_a_key_or_when_switched_off(monkeypatch):
    monkeypatch.setenv("SDI_OFFLINE", "1")
    assert qr.artist_impression({}, [], "Tesco") is None
    monkeypatch.delenv("SDI_OFFLINE", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert qr.artist_impression({}, [], "Tesco") is None
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setattr(config, "QUOTE_RENDER", {"enabled": False}, raising=False)
    assert qr.artist_impression({}, [], "Tesco") is None
    monkeypatch.setattr(config, "QUOTE_RENDER", {"enabled": True}, raising=False)
    monkeypatch.setenv("SDI_QUOTE_RENDER_ENABLED", "0")                # one machine may say no
    assert qr.artist_impression({}, [], "Tesco") is None


def test_the_drawing_is_the_reference_and_the_picture_is_made_once(monkeypatch, tmp_path):
    _online(monkeypatch, tmp_path)
    calls = []

    def fake_edit(reference_png, prompt, shape):
        calls.append((reference_png, prompt, dict(shape)))
        return base64.b64encode(PNG).decode("ascii")
    monkeypatch.setattr(qr, "_edit", fake_edit)
    monkeypatch.setattr(qr, "_generate", lambda *a: (_ for _ in ()).throw(AssertionError("words-only path taken")))
    first = qr.artist_impression({}, [{"normalized_material": "MILD STEEL"}], "Tesco", ga_png=PNG, product="Rail")
    second = qr.artist_impression({}, [{"normalized_material": "MILD STEEL"}], "Tesco", ga_png=PNG, product="Rail")
    assert first and first["png"] == PNG and first["reused"] is False and first["from_drawing"] is True
    assert second and second["reused"] is True and len(calls) == 1
    ref, prompt, shape = calls[0]
    assert ref == PNG                                                 # the sheet IS the reference
    assert "inside a Tesco store" in prompt and "general arrangement drawing" in prompt
    assert shape == {"model": "grok-imagine-image-2.0", "aspect_ratio": "3:2", "resolution": "2k",
                     "quality": "medium"}
    assert rt.reuse_counts()["quote_render"] == {"reused": 1, "computed": 1}
    # A new sheet is a new picture: the GA's bytes are in the key.
    other = qr.artist_impression({}, [{"normalized_material": "MILD STEEL"}], "Tesco", ga_png=PNG + b"\x00",
                                 product="Rail")
    assert other and other["reused"] is False and len(calls) == 2
    rt.reset()


def test_the_edit_request_is_json_with_the_sheet_as_a_data_url(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    sent = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(PNG).decode("ascii")}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, headers=headers, body=json, timeout=timeout)
        return _Resp()
    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    out = qr._edit(PNG, "the prompt", {"model": "grok-imagine-image-2.0", "aspect_ratio": "3:2",
                                       "resolution": "2k", "quality": "medium"})
    assert base64.b64decode(out) == PNG
    assert sent["url"] == "https://api.x.ai/v1/images/edits"
    assert sent["headers"]["Authorization"] == "Bearer xai-test"
    body = sent["body"]
    assert body["model"] == "grok-imagine-image-2.0" and body["prompt"] == "the prompt"
    assert body["image"] == {"url": "data:image/png;base64," + base64.b64encode(PNG).decode("ascii"),
                             "type": "image_url"}
    assert body["aspect_ratio"] == "3:2" and body["response_format"] == "b64_json" and body["n"] == 1
    assert sent["timeout"] == (15, 180)


def test_when_the_edit_is_refused_the_unit_is_drawn_from_words_and_says_so(monkeypatch, tmp_path, capsys):
    _online(monkeypatch, tmp_path)

    def refuse(reference_png, prompt, shape):
        raise RuntimeError("HTTP 404: no such endpoint")
    drawn = []

    def fake_generate(prompt, model):
        drawn.append((prompt, model))
        return base64.b64encode(PNG).decode("ascii")
    monkeypatch.setattr(qr, "_edit", refuse)
    monkeypatch.setattr(qr, "_generate", fake_generate)
    shot = qr.artist_impression({}, [], "Tesco", ga_png=PNG, product="Rail")
    assert shot and shot["png"] == PNG and shot["from_drawing"] is False
    assert drawn[0][1] == "grok-2-image" and "data:image" not in drawn[0][0]
    assert "drawing the unit from its description instead" in capsys.readouterr().out


def test_when_both_fail_the_drawing_stays_in_place(monkeypatch, tmp_path, capsys):
    _online(monkeypatch, tmp_path)

    def boom(*a):
        raise RuntimeError("quota")
    monkeypatch.setattr(qr, "_edit", boom)
    monkeypatch.setattr(qr, "_generate", boom)
    assert qr.artist_impression({}, [], "Tesco", ga_png=PNG, product="Rail") is None
    assert "the page shows the drawing" in capsys.readouterr().out


def test_without_a_sheet_the_unit_is_drawn_from_words(monkeypatch, tmp_path):
    _online(monkeypatch, tmp_path)
    monkeypatch.setattr(qr, "_edit", lambda *a: (_ for _ in ()).throw(AssertionError("no sheet to edit")))
    monkeypatch.setattr(qr, "_generate", lambda prompt, model: base64.b64encode(PNG).decode("ascii"))
    shot = qr.artist_impression({}, [], "Tesco", ga_png=None, product="Rail")
    assert shot and shot["from_drawing"] is False and "inside a Tesco store" in shot["prompt"]


def test_the_scene_table_is_a_scoped_customer_table():
    guard = (ROOT / "tests" / "test_the_engine_holds_no_job_and_proves_itself_on_a_replay.py").read_text(encoding="utf-8")
    assert '("config.py", "CUSTOMER_QUOTE_SCENES")' in guard
    assert isinstance(getattr(config, "CUSTOMER_QUOTE_SCENES", None), dict)
    assert "scene_template" in config.QUOTE_RENDER and "{customer}" in config.QUOTE_RENDER["scene_template"]
    assert config.QUOTE_RENDER["model"] and config.QUOTE_RENDER["text_model"]


# ── D-570: the unit first, the price after and smaller ─────────────────────────────────

def test_the_page_shows_the_unit_then_the_price_then_the_specification():
    src = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    page = src.split('<div class="body">')[1]
    assert page.index("{unit_block}") < page.index('<div class="price-box">'), \
        "the unit's picture comes before the price"
    assert page.index('<div class="price-box">') < page.index('<div class="grid">'), \
        "the price sits between the picture and the specification"
    assert page.index('<div class="grid">') < page.index("What's included")
    css = src.split(".price-box {{")[1].split(".estimator-action")[0]
    assert "#f5f5f1" in css and "var(--sdi-ink)" in css                # a light panel, ink figures
    unit_px = int(re.search(r"\.price-box \.unit \{\{ font-size:(\d+)px", src).group(1))
    ov_px = int(re.search(r"\.price-box \.right \.ov \{\{ font-size:(\d+)px", src).group(1))
    assert unit_px <= 22 and ov_px <= 16, (unit_px, ov_px)            # was 34 and 20
    assert "Unit price" in src and "Order value" in src and '{_unit_caption}' in src   # the same details
    assert "@media (max-width:560px)" in src and ".price-box .unit {{ font-size:20px; }}" in src


def test_the_impression_is_labelled_and_the_drawing_is_the_fallback():
    src = (ROOT / "src" / "client_quote_html.py").read_text(encoding="utf-8")
    assert "Artist&#39;s impression" in src or "Artist's impression" in src
    assert "the drawing governs" in src
    assert "from the general arrangement" in src                      # which basis the picture had
    assert "General arrangement" in src                              # the fallback caption stays
    assert "quote_render.artist_impression(" in src


def test_a_regenerated_quotation_reuses_the_picture_through_the_store(monkeypatch, tmp_path):
    """client_quote_regen rebuilds the page through build_quote_html, which asks for the
    impression the same way — same sheet, same prompt, same key — so it costs nothing twice."""
    _online(monkeypatch, tmp_path)
    monkeypatch.setattr(qr, "_edit", lambda *a: base64.b64encode(PNG).decode("ascii"))
    qr.artist_impression({}, [], "Tesco", ga_png=PNG, product="Rail")
    entries = list((tmp_path / "cache" / "quote_render").glob("*.json"))
    assert len(entries) == 1
    kept = json.loads(entries[0].read_text(encoding="utf-8"))
    assert kept["raw"]["png_b64"] == base64.b64encode(PNG).decode("ascii")
    again = qr.artist_impression({}, [], "Tesco", ga_png=PNG, product="Rail")
    assert again["reused"] is True
    rt.reset()
