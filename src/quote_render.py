"""An artist's impression of the unit in the client's own setting, for the quotation's first
page (D-571).

James Gray, 21 Oct 2026: "take the unit in the GA and turn it into a rendered image with a
suitable backdrop depending on the client — if it's Tesco, put it into a Tesco store — with a
small amount of landscaping and some space around it, so that it's extremely aesthetically
pleasing."

THE DRAWING IS THE REFERENCE. The picture is an image EDIT: the general arrangement's first
sheet, rendered, goes to the image model as the reference and the prompt asks for that unit —
its proportions, structure, materials and stated finish kept — placed in the customer's scene.
A picture drawn from words alone (the first cut) gave a plausible display unit; a picture
drawn from the sheet gives THIS one. The sheet already reaches the same xAI account for the
vision read of the bill, so nothing leaves that did not leave before. The picture is labelled
an artist's impression on the page, because it is one: the drawing governs.

THE SCENE IS THE CUSTOMER'S. config.CUSTOMER_QUOTE_SCENES names a setting for a customer whose
stores are not simply "a {customer} store" (a brand sold through others, a maker with no shop
floor); every other customer takes QUOTE_RENDER["scene_template"] with its own name in it, and
a job with no customer takes the default scene. The template is the rule; the table holds the
exceptions.

MADE ONCE. The picture is kept in the read store under the sheet's bytes, the prompt and the
model, so a re-run or a regenerated quotation of the same job shows the same picture and pays
nothing; a new revision of the sheet, a changed description, scene or model is a new picture.

WORKED TOWARDS, NEVER SILENTLY DROPPED. If the edit endpoint refuses, the picture is drawn
from words instead; offline, switched off, without a key, or when both fail, the page falls
back to the general arrangement it always showed — and says why on the console. The quotation
never waits on a picture.
"""
from __future__ import annotations

import base64
import os
import re
from typing import Any, Dict, List, Optional

import config

PROMPT_VERSION = "r2"
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_XAI_BASE = "https://api.x.ai/v1"


def _cfg() -> Dict[str, Any]:
    return dict(getattr(config, "QUOTE_RENDER", {}) or {})


def _switched_off(cfg: Dict[str, Any]) -> bool:
    """config says, unless SDI_QUOTE_RENDER_ENABLED says otherwise for this machine."""
    env = os.environ.get("SDI_QUOTE_RENDER_ENABLED", "").strip().lower()
    if env in _FALSE:
        return True
    if env in _TRUE:
        return False
    return not cfg.get("enabled", True)


def scene_for(customer: Any) -> str:
    """The setting the unit is pictured in: the customer's named scene, else the template with
    the customer's name in it, else the default."""
    cfg = _cfg()
    name = " ".join(str(customer or "").split())
    key = name.upper()
    table = getattr(config, "CUSTOMER_QUOTE_SCENES", {}) or {}
    if key:
        for k, v in table.items():
            if str(k).upper() == key:
                return str(v)
        for k, v in table.items():
            if len(str(k)) > 2 and str(k).upper() in key:
                return str(v)
        return str(cfg.get("scene_template") or "inside a {customer} store, on the shop floor"
                   ).format(customer=name)
    return str(cfg.get("default_scene") or "on a bright, modern retail shop floor")


def product_words(summary: Any, parts: Any, product: Any = None) -> str:
    """The unit as the record describes it — name, what it is made of, its finish and colour,
    its overall size — the sentence the prompt names it by."""
    s = summary if isinstance(summary, dict) else {}
    name = " ".join(str(product or s.get("declared_product_title") or s.get("product")
                        or s.get("source_file") or "the display unit").split())
    name = re.sub(r"\b[0-9A-Z]{3,}(?:-[0-9A-Z]+){1,4}\b", "", name).strip(" -–—·") or "the display unit"
    mats: List[str] = []
    finishes: List[str] = []
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        m = str(p.get("normalized_material") or "").replace("_", " ").strip().title()
        if m and m not in mats:
            mats.append(m)
        f = str(p.get("normalized_finish") or "").strip()
        if f and f.upper() not in ("WELDED", "RAW", "NONE") and f.title() not in finishes:
            finishes.append(f.title())
    colour = ""
    for p in parts or []:
        if isinstance(p, dict) and p.get("colour"):
            colour = str(p["colour"]).strip().title()
            break
    bits = [name]
    if mats:
        bits.append("made in " + ", ".join(mats[:3]))
    if finishes:
        bits.append(", ".join(finishes[:2]).lower() + (f" in {colour}" if colour else ""))
    try:
        from commercial_lines import product_envelope
        env = product_envelope(s, parts)
        if env:
            bits.append(f"about {env['length']:.0f} x {env['width']:.0f} x {env['height']:.0f} mm")
    except Exception:                                                # noqa: BLE001
        pass
    return ", ".join(bits)


def render_prompt(words: str, scene: str, cfg: Optional[Dict[str, Any]] = None,
                  from_drawing: bool = True) -> str:
    """The sentence the picture is made from. Everything that shapes the picture is in it, so
    the picture is kept under it. With a drawing as reference the prompt asks the model to
    keep what the sheet shows and to ignore what a sheet carries that a photograph does not —
    tables, dimensions, the scale figure; without one it describes the unit in words only."""
    cfg = cfg or _cfg()
    dressing = cfg.get("dressing") or ("restrained planting in separate planters at the edges of "
                                       "the scene and a clean, uncluttered floor")
    style = cfg.get("style") or ("Soft natural daylight, subtle shadows, a calm backdrop, "
                                 "shallow depth of field.")
    if from_drawing:
        return (f"Create a photorealistic image of {words}, the complete unit shown on the supplied "
                f"general arrangement drawing, placed {scene}. Preserve the unit's complete form, "
                f"proportions, structure, materials and stated finish exactly as drawn; use the "
                f"assembled view as the subject, not an exploded view. Show one complete unit, "
                f"standing on the floor with all feet visible, in a landscape three-quarter view at "
                f"eye level, with generous clear space around it; {dressing}. {style} "
                f"Ignore the drawing's title block, parts tables, dimensions, notes and any human "
                f"scale figure. Do not invent features, shelves, wheels or merchandise the drawing "
                f"does not show; do not add a top, panel, surface or infill the drawing does not "
                f"show — where the drawing shows an open frame, a bar or a rail, it stays open, "
                f"the same slender section as drawn. No people, no drawing annotations, no text, "
                f"no prices, no captions, no watermarks.")
    return (f"Photorealistic product visualisation of {words}, placed {scene}. The unit is the "
            f"subject, centred, seen from a slight three-quarter angle at eye level, with generous "
            f"clear space around it; {dressing}. {style} "
            f"No text, no captions, no price tags, no people.")


def artist_impression(summary: Any, parts: Any, customer: Any, ga_png: Optional[bytes] = None,
                      product: Any = None) -> Optional[Dict[str, Any]]:
    """{'png': bytes, 'prompt': str, 'scene': str, 'words': str, 'reused': bool,
    'from_drawing': bool} — or None where no picture is to be had (offline, switched off, no
    key, or the provider failed both ways), and the page shows the drawing as before."""
    cfg = _cfg()
    if _switched_off(cfg) or os.environ.get("SDI_OFFLINE", "").strip().lower() in _TRUE:
        return None
    if not os.environ.get("XAI_API_KEY"):
        print("   [quote] artist's impression not made (XAI_API_KEY is not set) — the page shows "
              "the drawing", flush=True)
        return None
    try:
        import read_store
        scene = scene_for(customer)
        words = product_words(summary, parts, product)
        source = str(product or customer or "quote")
        model = str(cfg.get("model") or "grok-imagine-image-2.0")

        if ga_png:
            prompt = render_prompt(words, scene, cfg, from_drawing=True)
            shape = {"model": model, "aspect_ratio": cfg.get("aspect_ratio", "3:2"),
                     "resolution": cfg.get("resolution", "2k"), "quality": cfg.get("quality", "medium")}

            def _edit_it() -> Dict[str, Any]:
                return {"png_b64": _edit(ga_png, prompt, shape), "prompt": prompt}

            try:
                got = read_store.reuse("quote_render", content=[ga_png, prompt.encode("utf-8")],
                                       fingerprint=read_store.fingerprint_code(render_prompt) + ":" + PROMPT_VERSION,
                                       context=shape, compute=_edit_it, source=source)
                b64 = (got.get("raw") or {}).get("png_b64")
                if b64:
                    return {"png": base64.b64decode(b64), "prompt": prompt, "scene": scene,
                            "words": words, "reused": bool(got.get("hit")), "from_drawing": True}
            except Exception as exc:                                 # noqa: BLE001
                print(f"   [quote] the drawing could not be taken as the reference "
                      f"({type(exc).__name__}: {exc}) — drawing the unit from its description instead",
                      flush=True)

        text_model = str(cfg.get("text_model") or "grok-2-image")
        prompt = render_prompt(words, scene, cfg, from_drawing=False)

        def _draw_it() -> Dict[str, Any]:
            return {"png_b64": _generate(prompt, text_model), "prompt": prompt}

        got = read_store.reuse("quote_render", content=prompt.encode("utf-8"),
                               fingerprint=read_store.fingerprint_code(render_prompt) + ":" + PROMPT_VERSION,
                               context={"model": text_model}, compute=_draw_it, source=source)
        b64 = (got.get("raw") or {}).get("png_b64")
        if not b64:
            return None
        return {"png": base64.b64decode(b64), "prompt": prompt, "scene": scene, "words": words,
                "reused": bool(got.get("hit")), "from_drawing": False}
    except Exception as exc:                                         # noqa: BLE001
        print(f"   [quote] artist's impression not made ({type(exc).__name__}: {exc}) — the page "
              f"shows the drawing", flush=True)
        return None


def _edit(reference_png: bytes, prompt: str, shape: Dict[str, Any]) -> str:
    """One picture from the image model with the drawing as its reference, as base64 PNG.
    xAI's image edit takes JSON, the reference as a data URL, not multipart — so this is a
    plain POST rather than the OpenAI client's images.edit. Isolated so a test can stand in."""
    import requests
    body = {"model": shape["model"], "prompt": prompt,
            "image": {"url": "data:image/png;base64," + base64.b64encode(reference_png).decode("ascii"),
                      "type": "image_url"},
            "aspect_ratio": shape.get("aspect_ratio") or "3:2",
            "resolution": shape.get("resolution") or "2k",
            "quality": shape.get("quality") or "medium",
            "response_format": "b64_json", "n": 1}
    resp = requests.post(f"{_XAI_BASE}/images/edits",
                         headers={"Authorization": f"Bearer {os.environ.get('XAI_API_KEY', '')}"},
                         json=body, timeout=(15, 180))
    if resp.status_code >= 400:
        # The body may describe our request; it never carries the key. Keep it short.
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()["data"][0]
    if data.get("b64_json"):
        return str(data["b64_json"])
    if data.get("url"):
        got = requests.get(str(data["url"]), timeout=(15, 120))
        got.raise_for_status()
        return base64.b64encode(got.content).decode("ascii")
    raise RuntimeError("the image model returned no picture")


def _generate(prompt: str, model: str) -> str:
    """One picture from the image model from words alone, as base64 PNG. Isolated so a test
    can stand in."""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("XAI_API_KEY"), base_url=_XAI_BASE)
    resp = client.images.generate(model=model, prompt=prompt, n=1, response_format="b64_json")
    return str(resp.data[0].b64_json)
