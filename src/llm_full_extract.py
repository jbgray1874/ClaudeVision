r"""
llm_full_extract.py — WHOLE-DOCUMENT LLM extraction (the "chat session" in the engine).

Why this exists: the per-page Grok BOM transcriber reads ONE page in isolation and is told to
transcribe only a BOM table. A human/LLM reading the whole PDF in a chat does far better — it
reasons over the ENTIRE pack at once: GA -> sub-assemblies -> parts -> tube cut lists, cross-
references part numbers, reads the weld/finish spec, ties each detail sheet to its parent. This
module gives the engine that same whole-document pass.

It is TRANSCRIPTION, not invention: the prompt forbids computing or guessing — every value must
be printed on the drawing, else null. Output is tagged source="llm_full_extract" and is meant to
be CROSS-CHECKED against the deterministic reads (pdfplumber BOM tables, drawing_facts weights)
and flagged for the estimator — never passed off as measured.

Plumbing: reuses the xAI OpenAI-compatible client (XAI_API_KEY, base_url https://api.x.ai/v1),
the same one the vision reader uses — but as a TEXT chat call over the document context, which is
fast and cheap (no per-page images).

Public API:
    build_document_context(pdf_path)         -> str    (compact all-pages text + BOM tables)
    extract_full_job(pdf_path, model=..., )  -> dict   (structured job; {} on failure)

Standalone:
    python llm_full_extract.py <pdf> [--model grok-4.3] [--context-only]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover
    pdfplumber = None

DEFAULT_MODEL = os.environ.get("XAI_VISION_MODEL", "grok-4.3")
SOURCE_NAME = "llm_full_extract"

_SCHEMA = """{
  "drawing_info": {
    "drawing_number": "", "revision": "", "title": "", "project": "", "client": "",
    "drawn_by": "", "date": "", "scale": "", "material_general": "", "finish_general": "",
    "colour": "", "tolerance_linear": "", "tolerance_angular": "", "notes": []
  },
  "bom": [
    {"item_no": "", "part_number": "", "description": "", "qty": 0,
     "material_family": "metal|acrylic|timber|wire|tube|bought_in|mixed|other",
     "material": "", "thickness_or_section": "", "finish": "", "colour": "",
     "is_fabricated": true, "is_bought_in": false,
     "confidence": "high|medium|low",
     "source": "explicit_bom_table|title_block|notes|inferred_from_views|filename",
     "comments": ""}
  ],
  "routes": [
    {"sequence": 10, "operation": "", "department": "", "part_numbers": [],
     "material_family": "metal|acrylic|timber|wire|tube|mixed",
     "description": "", "inferred": false, "confidence": "high|medium|low", "notes": ""}
  ],
  "assemblies": [{"part_number": "", "children": [{"part_number": "", "qty": 0}]}],
  "spec": {"weld": null, "powder_micron": null, "tolerances": null,
           "material_grades": [], "timber_note": null},
  "warnings": [], "missing_information": [],
  "extraction_confidence": "high|medium|low"
}"""

# SHARED RULES. Both passes return the same shape; what differs is whether they are allowed
# to fill a field the drawing does not state. Keeping the schema identical means the consumer
# has one thing to read, and the `inferred` flag on every route — plus the `source` on every
# BOM row — is what separates a reading from a judgement, per item rather than per pass.
_COMMON_RULES = """
MATERIAL FAMILIES. Classify every component: metal, acrylic, timber, wire, tube, bought_in.
thickness_or_section uses the style that suits the family — "1.2mm" for sheet and acrylic,
"18mm" for board, "\u00d86mm" for wire and round tube, "25x25x1.5 SHS" for box section.

MIXED ASSEMBLIES. Keep components PURE. Only a top-level assembly, or a sub-assembly that
genuinely combines materials, is "mixed" — never force one material onto everything under it.
Generate separate process steps per material stream, then a final assembly step that brings
them together with material_family "mixed". A finish stated for the metal parts belongs to
those part numbers only; do not spread it across acrylic or timber that is not coated.

DEPARTMENTS are the shop's own: Laser (Metal), Laser (Acrylic), Fold, Linebend, Tubebend,
Saw, CNC / Joinery machining, Edge Banding, Gluing / Bonding, Weld (CO2), Spotweld,
Dress Welds, P.Coat, Spray / Wet Paint, Diamond Polish, Robomac, Assemble/pack (Metal),
Assemble/pack (Acrylic), Manual labour (Metal).

Never invent a part number or a quantity. Put anything you could not find in
missing_information, and anything that looked wrong in warnings.
"""

_PROMPT = """You are an expert manufacturing engineer specialising in multi-material
fabrication (sheet metal, acrylic, timber, wire, tube and display/POS work), reading a
COMPLETE drawing pack from SDI Displays. Below is the text and the tables from every page.

ABSOLUTE RULE FOR THIS PASS — TRANSCRIBE, NEVER INVENT. Every value you output must be
PRINTED somewhere in the pack. Never compute, estimate or guess. If something is not printed,
leave it empty or null. This is what makes the result trustworthy; a second pass will fill the
gaps and will be labelled differently.

Accordingly: every route you return must have inferred=false and be justified by something the
drawing SAYS — a finish note, a weld callout, "TAP M4", "DEBURR ALL EDGES", "POWDER COATED".
Do NOT propose a process because a part looks like it would need one. Return an empty routes
list rather than a plausible one.

Return ONLY valid JSON (no markdown) in this shape:
""" + _SCHEMA + _COMMON_RULES + """
Every bom row needs its `source`: explicit_bom_table where you read it from a parts table,
title_block / notes where the drawing states it elsewhere, filename where that is all there is.
qty must be the PRINTED quantity. A part is is_bought_in only where the drawing says so.
"""


def build_document_context(pdf_path: str | Path, max_chars: int = 60000) -> str:
    """Compact whole-document context: per-page free text + any BOM/parts tables. This is what the
    LLM reasons over — the same content a person sees flipping through the pack."""
    if pdfplumber is None:
        return ""
    p = Path(pdf_path)
    if not p.exists():
        return ""
    out: List[str] = []
    with pdfplumber.open(str(p)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            out.append(f"\n===== PAGE {i} =====")
            txt = (page.extract_text() or "").strip()
            if txt:
                out.append(txt)
            for t in (page.extract_tables() or []):
                if not t or not t[0]:
                    continue
                flat = " ".join((c or "") for row in t for c in row).upper()
                if any(k in flat for k in ("ITEM", "DESCRIPTION", "QTY", "DWG NO", "LENGTH")):
                    out.append("[TABLE]")
                    for row in t:
                        cells = [(c or "").replace("\n", " ").strip() for c in row]
                        if any(cells):
                            out.append(" | ".join(cells))
    ctx = "\n".join(out)
    return ctx[:max_chars]


def _strip_fences(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    return s


def _parse(raw: str) -> Optional[Dict[str, Any]]:
    txt = _strip_fences(raw)
    if not txt.startswith("{"):
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            txt = m.group(0)
    try:
        obj = json.loads(txt)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _call_llm(context: str, model: str) -> Optional[str]:
    """One TEXT chat call over the whole-document context (xAI OpenAI-compatible)."""
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY not set (C:\\ClaudeVision\\.env or $env:XAI_API_KEY).")
    from openai import OpenAI  # xAI is OpenAI-compatible
    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You transcribe engineering drawings to JSON. Never invent."},
            {"role": "user", "content": _PROMPT + "\n\n--- DRAWING PACK ---\n" + context},
        ],
        temperature=0,
    )
    return resp.choices[0].message.content


def extract_full_job(pdf_path: str | Path, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Whole-document LLM extraction. Returns the structured job dict, or {} on any failure
    (caller then falls back to the per-page / deterministic paths — never crashes a run)."""
    result: Dict[str, Any] = {"source": SOURCE_NAME, "found": False}
    ctx = build_document_context(pdf_path)
    if not ctx:
        result["error"] = "no document context (pdfplumber missing or empty PDF)"
        return result
    try:
        raw = _call_llm(ctx, model)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    obj = _parse(raw or "")
    if not obj:
        result["error"] = "LLM response was not parseable JSON"
        result["raw"] = (raw or "")[:2000]
        return result
    obj["source"] = SOURCE_NAME
    obj["found"] = True
    return obj


def main() -> None:
    ap = argparse.ArgumentParser(description="Whole-document LLM extraction of a drawing pack.")
    ap.add_argument("pdf")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--context-only", action="store_true", help="print the document context, no LLM call")
    a = ap.parse_args()
    if a.context_only:
        print(build_document_context(a.pdf))
        return
    job = extract_full_job(a.pdf, model=a.model)
    print(json.dumps(job, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()


# ── second pass: infer what the drawing implies but does not print ───────────────────
#
# The prompt above forbids inference, and it is right to: transcription is what stops a model
# filling a title block from imagination. But a GA-only pack prints almost nothing per part.
# M&S 2085 states MATERIAL: MILD STEEL once, at assembly level, and dimensions its tubes on
# the views — so a strict transcriber correctly returns null for every part field, and the
# estimate books no material for two of the three parts and no operation at all for either
# tube. £2.00 of labour on a welded three-part bracket.
#
# What is missing is not better transcription. It is the judgement an estimator applies after
# reading the same page: a tube in a welded assembly is cut to length and welded in; a plate
# with a wall is folded; an assembly finished RAL9006 means every part is coated.
#
# So this is a SEPARATE pass with the opposite rule, and everything it returns is stamped
# `inference` — rank 20, the lowest in the waterfall — so it can never overwrite a printed or
# measured value. It fills holes that would otherwise be silent zeros, and says that it did.

INFERENCE_SOURCE = "inference"

_INFER_PROMPT = """You are an expert manufacturing engineer at SDI Displays, working in
sheet metal, acrylic, timber, wire and tube.

Everything PRINTED on this pack has already been transcribed. What follows are the parts that
still have no material, no size or no route — because the drawing does not state them. A GA-only
pack prints almost nothing per part, and a part with nothing against it cannot be costed or
routed at all: it reaches the estimate as a zero.

Your job now is the opposite of transcription. Say what an experienced estimator would CONCLUDE
from the same page, so the job can be costed. This is explicitly inference, it is labelled as
such, and it is ranked below every printed or measured value — it can only fill a hole, never
overwrite a fact.

Return ONLY valid JSON in this shape:
""" + _SCHEMA + _COMMON_RULES + """
FOR THIS PASS
- Every route you return must have inferred=true. Set confidence honestly: "high" for a tube in
  a welded assembly needing cutting and welding, "low" where you are reading the room.
- Include a bom row ONLY for a part listed below as missing detail, and set its `source` to
  inferred_from_views. Do not restate parts that were already read.
- Justify each route in `notes`, citing what on the drawing led you there.
- A finish applied to an assembly applies to the parts that make it up — but only the ones it
  would actually be applied to.
- If you genuinely cannot tell, leave it null and say so in missing_information. A null is
  honest; a guess dressed as a reading is not, and this engine has been burned by exactly that.
"""


def infer_missing_details(context: str, bom: List[Dict[str, Any]],
                          missing: List[Dict[str, Any]],
                          model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Second pass over parts the transcription left empty. {} on any failure — a job that
    cannot reach the model estimates exactly as it does today."""
    if not missing:
        return {}
    try:
        payload = (
            f"{_INFER_PROMPT}\n\n===== PACK TEXT =====\n{context[:40000]}\n\n"
            f"===== BOM =====\n{json.dumps(bom, ensure_ascii=False)}\n\n"
            f"===== PARTS STILL MISSING DETAIL =====\n"
            f"{json.dumps(missing, ensure_ascii=False)}\n"
        )
        raw = _call_llm(payload, model)
        parsed = _parse(raw) if raw else None
    except Exception:
        return {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("parts"), list):
        return {}
    out = []
    for row in parsed["parts"]:
        if not isinstance(row, dict) or not row.get("part_number"):
            continue
        row["source"] = INFERENCE_SOURCE
        out.append(row)
    return {"source": INFERENCE_SOURCE, "parts": out, "found": bool(out)}


def parts_missing_detail(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Which transcribed parts have nothing to cost from.

    A part with no material AND no size is not merely thin — nothing downstream can price it
    or route it, so it reaches the sheet as a bought-in guess or as nothing at all. Those are
    the only ones worth asking a second question about; a part the drawing described is left
    exactly as the drawing described it.
    """
    out = []
    for p in parts or []:
        if not isinstance(p, dict) or not p.get("part_number"):
            continue
        if p.get("is_bought_in"):
            continue
        has_material = bool(p.get("material"))
        has_size = any(p.get(k) for k in
                       ("thickness_mm", "tube_section", "cut_length_mm", "overall_size_mm"))
        if not has_material or not has_size:
            out.append({"part_number": p.get("part_number"),
                        "description": p.get("description"),
                        "has_material": has_material, "has_size": has_size})
    return out
