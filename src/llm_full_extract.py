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

_PROMPT = """You are an experienced sheet-metal estimator reading a COMPLETE engineering drawing
pack (all pages of one product) from SDI Displays. Below is the text and the BOM/parts tables
extracted from every page, in order.

Your job: return the COMPLETE structured job — the assembly hierarchy and every part's detail —
by reasoning over the WHOLE pack at once (the GA lists sub-assemblies; each sub-assembly has its
own page listing its parts; each tube part has a cut-length table).

ABSOLUTE RULE — TRANSCRIBE, NEVER INVENT: every value you output must be PRINTED somewhere in the
pack. Never compute, estimate, or guess. If something is not printed, use null. Read part numbers,
quantities, lengths and weights EXACTLY as printed.

Return ONLY valid JSON (no markdown) in this shape:
{
  "top_assembly": "<GA drawing number>",
  "bom": [                          // the GA's own top-level line items, verbatim
    {"part_number": "...", "description": "...", "qty": <int>, "is_assembly": <true/false>}
  ],
  "assemblies": [                   // each sub-assembly and the parts it contains
    {"part_number": "...", "children": [{"part_number": "...", "qty": <int>}]}
  ],
  "parts": [                        // every fabricated/bought part, printed detail only
    {"part_number": "...", "description": "...", "material": null,
     "thickness_mm": null, "tube_section": null, "cut_length_mm": null,
     "overall_size_mm": null, "weight_g": null, "finish": null,
     "hole_count": null, "fold_or_bend": null, "is_bought_in": <true/false>,
     "operations_printed": []}
  ],
  "spec": {"weld": null, "powder_micron": null, "tolerances": null,
           "material_grades": [], "timber_note": null}
}
Rules: qty must be the PRINTED quantity. A row is is_assembly=true only if it has its own parts
page in this pack. tube_section like "30 x 30 x 1.5mm". weight_g only a printed weight. Do not
merge distinct part numbers. Do not drop any BOM row.

operations_printed: the manufacturing operations the DRAWING ITSELF STATES for that part —
in notes, callouts, the title block or the finish field. These packs say a great deal out
loud: "POWDER COATED", "ALL WELDS TO BE TIG", "TAP M4", "DEBURR ALL EDGES", "LINE BEND",
"CSK", "FOLD". Read them; they are printed, so transcribing them is your job, and an
operation the drawing names is worth far more than one anybody works out later.

Use ONLY these names: laser_cutting, punch, saw, tube_cut, folding, rolling, tube_bending,
welding, dress_welds, hole_machining, tapping, deburring, cnc_routing, edge_banding, glue,
powder_coating, wet_spray, diamond_polish, wire_forming, handling.

A finish stated for the whole assembly is printed for that assembly — put it on the assembly
row, not on parts it does not name. Do NOT add an operation because the part looks like it
would need one: that is the other pass's job, and it is labelled differently for a reason.
Empty list when the drawing states nothing.
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

_INFER_PROMPT = """You are an experienced sheet-metal estimator at SDI Displays. You have
already transcribed everything PRINTED on this drawing pack. Some parts still have no material,
no size and no manufacturing route, because the drawing does not state them per part.

Your job now is the opposite of transcription: say what an estimator would CONCLUDE, so the
part can be costed at all. This is explicitly inference and will be labelled as such.

Below: the pack text, the BOM, and the parts that are still missing detail.

For EVERY part listed as missing detail, return:
  - material            the family, e.g. "MILD STEEL". If the pack states a material anywhere
                        and nothing contradicts it for this part, that is the answer.
  - stock_form          one of: sheet, tube, section, wire, bar, board, acrylic, bought_in
  - thickness_mm        wall or sheet thickness if the views imply one, else null
  - tube_section        e.g. "12.7 dia x 1.2 wall" or "25 x 25 x 1.5" if a tube, else null
  - cut_length_mm       only if the views give a length for it, else null
  - operations          the route, from this vocabulary ONLY:
                        laser_cutting, punch, saw, tube_cut, folding, rolling, tube_bending,
                        welding, dress_welds, hole_machining, tapping, deburring,
                        cnc_routing, edge_banding, glue, powder_coating, wet_spray,
                        diamond_polish, wire_forming, handling
  - reason              one sentence, citing what on the drawing led you there

RULES
- An operation must be justified by the part's nature or the drawing, not by habit. A tube in a
  welded assembly is cut and welded. A plate with a stated WALL is folded. Do not add grinding,
  polishing or machining unless something indicates it.
- Finish applied to the assembly applies to the parts that make it up.
- If you genuinely cannot tell, use null. A null is honest; a guess dressed as a reading is not.
- Return ONLY valid JSON: {"parts": [{"part_number": "...", "material": ..., "stock_form": ...,
  "thickness_mm": ..., "tube_section": ..., "cut_length_mm": ..., "operations": [...],
  "reason": "..."}]}
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
