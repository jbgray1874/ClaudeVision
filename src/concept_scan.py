"""concept_scan.py — sight the parts of a product from a customer's render.

James Gray, 22 September 2026, with two renders of an M&S Plan A collection bin: "we need
to build in the pipeline to populate the pricing s/sheet from the LLM only model."

A render carries no dimensions, no title block, no BOM — so the drawing readers correctly
find nothing, and before this module an --llm-only run of one produced an empty book with
no explanation. This is the reader for that pack: it looks at the images and names what it
can SEE — a carcass, a header, castors, a printed panel — with the material each part
appears to be and an envelope guessed off human-scale cues, every figure stamped as an
assumption with the cue that produced it.

── WHAT THIS IS AND IS NOT ─────────────────────────────────────────────────────────

IT SIGHTS PARTS AND ASSUMES SIZES; IT NEVER TOUCHES MONEY. The parts it produces go down
the SAME pricing waterfall as every other part — SDI Live/UDEF first, supplier evidence
next, evidenced research after that, and one estimator action where nothing answers. No
figure is invented here and none could be: the model is asked for geometry and materials
only, and a price in its answer would have nowhere to land.

EVERY NUMBER WEARS ITS OWN NAME. Fields are written through source_precedence.apply_field
at rank `vision_concept` (20, with the inferences), so the moment a real drawing arrives,
anything read off it displaces these field by field. That is the lifecycle a concept
estimate exists for: budget first, tightened when the pack lands, nothing re-keyed.

A PAGE IS NOT A PRODUCT. All pages go to the model in ONE call, told they are views or
variants of one product — his pack is the same bin rendered twice with two print sets, and
two independent page reads would have returned two carcasses.

INVENTING PARTS IS FORBIDDEN; NOT SEEING THEM IS EXPECTED. The model may only name what is
visible, and is asked to list separately what a real unit must contain that a render cannot
show (fixings, internal structure). That list lands on the record for the estimator — a
concept estimate that silently omits the insides is wrong in the direction nobody checks.

Cache and call shape follow _bom_vision_reader deliberately: one isolated call function,
temperature 0, content-keyed JSON cache, so an unchanged pack replays its answer and never
reaches the model twice.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Bump when the prompt changes — it is part of the cache key.
CONCEPT_PROMPT_VERSION = "c1"

SOURCE = "vision_concept"

_PROMPT = """You are looking at {n} image(s): customer-supplied product renders or photos of ONE
retail display product (SDI Displays estimating). They may be different views or print/graphic
variants of the SAME product — never treat each image as a separate product.

Name ONLY the parts you can actually SEE, so a manufacturer could price a budget build.
For every part: what it appears to be made of, and an ESTIMATED envelope in mm derived from
visible human-scale cues (castors ~75mm, standard aperture heights, brick/floor tile scale,
door heights). Every estimate must name the cue it was scaled from.

Rules:
- NEVER state a price, cost, weight or supplier. Geometry, materials and counts only.
- NEVER invent parts you cannot see. What a real unit must contain but the images cannot
  show (fixings, internal framing, base weights) goes in "not_visible" as words.
- Every dimension is an ASSUMPTION: give integers in mm and always say why in "why_size".
- If the images are variants (different graphics, same build), say so in "variants" and list
  each graphic set once in "print_sets" — do not duplicate the build per variant.
- quantity is what is visible (4 castors seen or implied by symmetry = 4, and say which).

Return ONLY valid JSON, no markdown, exactly this shape:
{{
  "product": {{"name": "<what this is>", "assumed_overall_mm": {{"height": 0, "width": 0, "depth": 0}},
              "scale_cue": "<what the overall size was scaled from>", "variants": 1}},
  "parts": [
    {{"name": "<part>", "kind": "fabricated|bought_in|graphic",
      "sighted_material": "<what it looks like, verbatim impression>",
      "material_guess": "<closest stock material name, e.g. MFMDF, MDF, ACRYLIC, MILD STEEL, PRINTED_PAPER>",
      "assumed_blank_mm": {{"length": 0, "width": 0, "thickness": 0}},
      "quantity": 1, "quantity_basis": "<seen / implied by symmetry / per print set>",
      "seen": "<which image, where>", "why_size": "<the cue this was scaled from>"}}
  ],
  "print_sets": ["<one line per graphic variant>"],
  "not_visible": ["<what a real unit needs that these images cannot show>"]
}}"""


class ConceptUnavailable(RuntimeError):
    """The vision model could not be asked — no key, offline, or the client is absent.

    ITS OWN TYPE for the same reason the splitter's NoOCR is: a missing capability is a
    fact about the machine, not about the pack, and an empty estimate must say "nothing was
    read", never "there was nothing to read".
    """


# ── the call, isolated exactly as _bom_vision_reader isolates its own ───────────────

def _call_vision_llm(png_pages: List[bytes], model: str) -> str:
    if os.getenv("SDI_OFFLINE", "").strip().lower() in {"1", "true", "yes"}:
        raise ConceptUnavailable(
            "SDI_OFFLINE=1 — the concept read needs the vision model and this run may not "
            "call one.")
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise ConceptUnavailable(
            "XAI_API_KEY not found. Set it in .env (XAI_API_KEY=xai-...) — the concept read "
            "is a vision-model read and cannot run without it.")
    from openai import OpenAI                                       # noqa: WPS433

    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": _PROMPT.format(n=len(png_pages))}]
    for png in png_pages:
        b64 = base64.b64encode(png).decode("ascii")
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}})
    resp = client.chat.completions.create(
        model=model, temperature=0,
        messages=[{"role": "user", "content": content}])
    return resp.choices[0].message.content or ""


def parse_concept_response(raw: str) -> Optional[Dict[str, Any]]:
    """The model's text, as the schema or None — tolerant of a stray markdown fence."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("parts"), list):
        return None
    return data


# ── cache: one call per (pack images + model + prompt), ever ────────────────────────

def _cache_dir() -> Path:
    import config                                                   # noqa: WPS433
    return Path(config.BASE_DIR) / "cache" / "vision_concept"


def _cache_key(png_pages: List[bytes], model: str) -> str:
    h = hashlib.sha256()
    for png in png_pages:
        h.update(png)
        h.update(b"\x00")
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(CONCEPT_PROMPT_VERSION.encode("utf-8"))
    return h.hexdigest()


def read_concept(pdf_paths: List[str], *, model: Optional[str] = None,
                 refresh: bool = False) -> Dict[str, Any]:
    """One concept read of a whole pack. Returns {'parsed', 'raw_response', 'cache_hit'}.

    Pages are rendered exactly as the BOM vision reader renders them, and ALL of them go in
    one call — see A PAGE IS NOT A PRODUCT above.
    """
    import _bom_vision_reader as pathB                              # noqa: WPS433

    if model is None:
        model = os.environ.get("XAI_VISION_MODEL", "grok-4.3")
    pngs: List[bytes] = []
    for pdf in pdf_paths:
        for index in range(pathB.count_pages(str(pdf))):
            pngs.append(pathB.render_page_to_png(str(pdf), index))
    if not pngs:
        raise ConceptUnavailable("no pages could be rendered from this pack")

    key = _cache_key(pngs, model)
    path = _cache_dir() / (key + ".json")
    if not refresh and path.is_file():
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            raw = entry.get("raw_response", "")
            parsed = parse_concept_response(raw)
            if parsed is not None:
                return {"parsed": parsed, "raw_response": raw, "cache_hit": True}
        except (OSError, ValueError):
            pass                                     # corrupt entry → re-fetch

    raw = _call_vision_llm(pngs, model)
    parsed = parse_concept_response(raw)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"raw_response": raw, "model": model,
                                    "prompt_version": CONCEPT_PROMPT_VERSION,
                                    "pages": len(pngs)}, indent=1), encoding="utf-8")
    except OSError:
        pass                                         # a cache that cannot write is not an error
    return {"parsed": parsed, "raw_response": raw, "cache_hit": False}


# ── sighted answer → engine parts ───────────────────────────────────────────────────

def _slug(text: Any, fallback: str) -> str:
    out = re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-").upper()
    return out[:24] or fallback


def parts_from_concept(answer: Dict[str, Any], stem: str) -> List[Dict[str, Any]]:
    """The sighted parts as engine part records, every field attributed at concept rank.

    Written through apply_field so the stamps are the arbitration machinery's own, not a
    hand-rolled imitation of them — and so length, width and thickness share one recorded
    source, which is what lets flat_blank_mm treat the pair as ONE reading (D-152).
    """
    from document_builder import _empty_part_record                 # noqa: WPS433
    from source_precedence import apply_field                       # noqa: WPS433

    parts: List[Dict[str, Any]] = []
    for n, sighted in enumerate(answer.get("parts") or [], start=1):
        if not isinstance(sighted, dict):
            continue
        name = str(sighted.get("name") or f"part {n}").strip()
        record = _empty_part_record(
            f"{_slug(stem, 'CONCEPT')}-C{n:02d} {_slug(name, str(n))}",
            item_number=n, description=name, quantity=None)
        record["concept"] = True
        record["page_roles"] = ["render"]
        record["concept_seen"] = str(sighted.get("seen") or "")

        qty = sighted.get("quantity")
        basis = str(sighted.get("quantity_basis") or "sighted on the render")
        try:
            qty = max(1, int(qty))
        except (TypeError, ValueError):
            qty = 1
            basis = "assumed — the render does not show a count"
        apply_field(record, "quantity", qty, SOURCE, note=basis)

        kind = str(sighted.get("kind") or "").strip().lower()
        sighted_mat = str(sighted.get("sighted_material") or "").strip()
        guess = str(sighted.get("material_guess") or "").strip().upper()
        if kind == "bought_in" and not guess:
            # A sourcing fact, not a zero — the bought-in price chain starts here (D-153).
            guess = "BOUGHT_IN"
        if guess:
            apply_field(record, "normalized_material", guess, SOURCE,
                        note=f"sighted as '{sighted_mat}' on the render" if sighted_mat
                        else "sighted on the render")
        if sighted_mat:
            record["materials"].append(sighted_mat)

        blank = sighted.get("assumed_blank_mm") or {}
        why = str(sighted.get("why_size") or "scaled from the render")
        wrote_size = False
        for field, key in (("blank_length_mm", "length"), ("blank_width_mm", "width")):
            try:
                value = float(blank.get(key))
            except (TypeError, ValueError):
                continue
            if value > 0:
                apply_field(record, field, value, SOURCE, note=why)
                wrote_size = True
        try:
            thickness = float(blank.get("thickness"))
        except (TypeError, ValueError):
            thickness = 0.0
        if thickness > 0:
            apply_field(record, "normalized_thickness_mm", thickness, SOURCE, note=why)

        # THE ACTION RIDES ON THE PART. One line, in the estimator's imperative, because a
        # concept figure that nobody is told to confirm becomes a firm one by seniority.
        if wrote_size or thickness > 0:
            record["review_flags"].append(
                f"CONCEPT: size assumed from the render ({why}) — confirm "
                f"{blank.get('length', '?')} x {blank.get('width', '?')} x "
                f"{blank.get('thickness', '?')}mm before release")
        else:
            record["review_flags"].append(
                "CONCEPT: no size could be sighted — enter this part's dimensions")
        parts.append(record)
    return parts


def concept_note(answer: Dict[str, Any]) -> Dict[str, Any]:
    """What the run and the report say about this read — product, variants, the unseen."""
    product = answer.get("product") or {}
    return {
        "product": product.get("name"),
        "assumed_overall_mm": product.get("assumed_overall_mm"),
        "scale_cue": product.get("scale_cue"),
        "variants": product.get("variants"),
        "print_sets": answer.get("print_sets") or [],
        "not_visible": answer.get("not_visible") or [],
    }
