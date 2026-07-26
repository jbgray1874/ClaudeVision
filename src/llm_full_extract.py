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
    python llm_full_extract.py <pdf> [--model grok-4.5] [--context-only]
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

DEFAULT_MODEL = os.environ.get("XAI_VISION_MODEL", "grok-4.5")
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
     "hole_count": null, "fold_or_bend": null, "is_bought_in": <true/false>}
  ],
  "spec": {"weld": null, "powder_micron": null, "tolerances": null,
           "material_grades": [], "timber_note": null}
}
Rules: qty must be the PRINTED quantity. A row is is_assembly=true only if it has its own parts
page in this pack. tube_section like "30 x 30 x 1.5mm". weight_g only a printed weight. Do not
merge distinct part numbers. Do not drop any BOM row.
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
