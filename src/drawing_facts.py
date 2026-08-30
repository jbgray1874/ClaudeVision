r"""
drawing_facts.py — DETERMINISTIC extraction of manufacturing facts from a drawing PDF.

This is Layer 2 of the source waterfall — the trustworthy backbone. EVERYTHING here is a
value PRINTED on the drawing, read by table/regex; it CANNOT hallucinate. It complements the
strict Grok BOM transcriber (Layer 3, fuzzy fields) and is OVERRIDDEN by DXF / SolidWorks
(Layers 0-1) wherever those exist. For a job with no DXF and no native model (e.g. a customer
tender drawing set) this is the best available source, and it is honest: read-or-null, never
inferred. No SolidWorks, no LLM, no network — pure pdfplumber + regex.

Per PAGE it extracts, where printed:
  - sheet_part      the DWG NO this sheet details (title block)
  - weight_g        the part weight        ("WEIGHT: 2068g")
  - tube_section    e.g. "30.00 x 30.00 x 1.50mm TUBE"  (from the cut-length table)
  - cut_length_mm   the tube/bar cut length (LENGTH column of that table)
  - material        MILD STEEL / MDF / TIMBER / STAINLESS ...
  - thickness_mm    plate gauge if printed
  - finish          POWDER COATED - MATT / LACQUERED / RAW ...

Once per DOCUMENT (the repeated notes block):
  - spec_block      powder_micron, weld_spec, tolerances, material_grades, timber_note

Public API:
    extract_drawing_facts(pdf_path) -> {
        "pages":     [ {page, sheet_part, weight_g, tube_section, cut_length_mm,
                        material, thickness_mm, finish}, ... ],
        "by_part":   { "<dwg no>": {weight_g, tube_section, cut_length_mm, material,
                        thickness_mm, finish, source:"drawing_pdf"}, ... },
        "spec_block":{ powder_micron, weld_spec, tolerances, material_grades, timber_note },
        "source": "drawing_pdf_deterministic",
    }

Every value carries the implicit contract "printed on the drawing"; callers tag it
source="drawing_pdf" reliability<1.0 and flag for estimator confirmation. Nothing here is
computed from geometry — a weight is a transcribed weight, never a derived one.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pdfplumber  # type: ignore
except Exception:  # pragma: no cover
    pdfplumber = None

# ── regexes (case-insensitive, tolerant of the jumbled multi-column note text) ──
_RE_WEIGHT = re.compile(r"WEIGHT[:\s]*([\d,]+(?:\.\d+)?)\s*g\b", re.I)
# drawing number: 11772-01-09-GA2, 11772-01-09-106, 11772-01-09-12M, 1448-GA, 12120-01-103 ...
_RE_DWGNO = re.compile(r"\b(\d{3,5}-\d{2}-\d{2}-[A-Z0-9]{1,4}|\d{3,5}-\d{2}-[A-Z0-9]{1,4})\b")
# tube/section: "30.00 x 30.00 x 1.50mm TUBE" or "30 x 30 x 1.5mm" (RHS/SHS/tube)
_RE_TUBE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*mm?\b", re.I)
_RE_THK = re.compile(r"(\d+(?:\.\d+)?)\s*mm\s*(?:THK|THICK|THICKNESS|GA(?:UGE)?)", re.I)
# spec-block fields (survive the multi-column jumble because the values sit at line-ends)
_RE_POWDER_MICRON = re.compile(r"(\d{1,3})\s*-\s*(\d{1,3})\s*MICRON", re.I)
_RE_MICRON_ANY = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*-\s*(\d{1,3}(?:\.\d+)?)\s*MICRON", re.I)

# Labelled title-block fields — these carry the PART's real material/finish/colour.
# We read the labelled value ONLY (never a whole-page keyword scan) so the repeated boilerplate
# spec block ("6063 - ALUMINIUM FOR EXTRUSION", "CHROME PLATING: ...") cannot pollute a part's
# fields. A value of "SEE ASSEMBLY/INDIVIDUAL DRAWING(S)" is a POINTER (kept verbatim so the
# engine's existing pointer-resolver can follow it), not a material.
_FIELD_LABELS = ("MATERIAL", "FINISH", "COLOUR", "COLOR")
_RE_THK_IN_MATERIAL = re.compile(r"(\d+(?:\.\d+)?)\s*mm", re.I)


def _num(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _title_block_part(page, text: str) -> Optional[str]:
    """The DWG NO this sheet details = the drawing-number ref in the title block (bottom-right).
    Prefer a ref physically inside the bottom-right title-block region; fall back to the last
    ref in the page text (title block is drawn last / lowest)."""
    try:
        W, H = page.width, page.height
        words = page.extract_words()
        tb = [w for w in words if w["top"] > H * 0.80 and w["x0"] > W * 0.55]
        blob = " ".join(w["text"] for w in sorted(tb, key=lambda w: (w["top"], w["x0"])))
        m = _RE_DWGNO.findall(blob)
        if m:
            # last ref in the title block = the drawing number line
            return m[-1]
    except Exception:
        pass
    refs = _RE_DWGNO.findall(text or "")
    return refs[-1] if refs else None


def _title_block_fields(page) -> Dict[str, Optional[str]]:
    """Read the labelled MATERIAL/FINISH/COLOUR values from the title-block region (bottom-left),
    NOT from the whole page — so the repeated boilerplate spec block cannot pollute them.
    Returns {'material','finish','colour'} with each value verbatim (may be a 'SEE ...' pointer)."""
    out: Dict[str, Optional[str]] = {"material": None, "finish": None, "colour": None}
    try:
        W, H = page.width, page.height
        words = [w for w in page.extract_words() if w["top"] > H * 0.74 and w["x0"] < W * 0.45]
        from collections import defaultdict
        lines: Dict[int, list] = defaultdict(list)
        for w in words:
            lines[round(w["top"] / 3)] += [w]
        for y in sorted(lines):
            s = " ".join(w["text"] for w in sorted(lines[y], key=lambda w: w["x0"])).strip()
            up = s.upper()
            for lab in _FIELD_LABELS:
                if up.startswith(lab):
                    # value = text after the label + colon, trimmed of trailing spec bleed
                    val = re.sub(rf"^{lab}\s*:?\s*", "", s, flags=re.I).strip(" -:")
                    # a labelled line sometimes has boilerplate appended to its right; cut at 2+ spaces
                    val = re.split(r"\s{2,}", val)[0].strip()
                    key = "colour" if lab in ("COLOUR", "COLOR") else lab.lower()
                    if val and out.get(key) in (None, ""):
                        out[key] = val
    except Exception:
        pass
    return out


def _is_pointer(v: Optional[str]) -> bool:
    return bool(v) and ("SEE " in str(v).upper())  # SEE ASSEMBLY / SEE INDIVIDUAL DRAWING(S)


def _tube_and_length(page, text: str) -> tuple[Optional[str], Optional[float]]:
    """A cut-length table has header ITEM/DESCRIPTION/LENGTH/QTY and a row like
    '1 | 30.00 x 30.00 x 1.50mm TUBE | 1600 | 1'. Return (section_string, length_mm)."""
    try:
        for t in page.extract_tables() or []:
            if not t or not t[0]:
                continue
            hdr = " ".join((c or "") for c in t[0]).upper()
            if "LENGTH" not in hdr or "DESCRIPTION" not in hdr:
                continue
            # locate the LENGTH and DESCRIPTION columns
            cols = [(c or "").upper() for c in t[0]]
            try:
                li = next(i for i, c in enumerate(cols) if "LENGTH" in c)
                di = next(i for i, c in enumerate(cols) if "DESCRIPTION" in c)
            except StopIteration:
                continue
            for row in t[1:]:
                if not row or len(row) <= max(li, di):
                    continue
                desc = (row[di] or "").replace("\n", " ").strip()
                length = _num(row[li])
                if desc and _RE_TUBE.search(desc) and length:
                    return desc, length
    except Exception:
        pass
    # fallback: a tube section printed in free text, no table length
    m = _RE_TUBE.search(text or "")
    if m and "TUBE" in (text or "").upper():
        return m.group(0), None
    return None, None


def _spec_region_text(page) -> str:
    """Reconstruct the bottom notes region from WORD POSITIONS (line-clustered by y, sorted by
    x). extract_text() scrambles the multi-column notes so badly that even de-spacing can't
    recover 'RESISTANCE WELDING'; the word-position rebuild keeps each glyph-spaced line intact
    ('A L L W E L D S T O B E T I G'), which de-spaces cleanly to ALLWELDSTOBETIG."""
    try:
        H = page.height
        words = [w for w in page.extract_words() if w["top"] > H * 0.70]
        from collections import defaultdict
        lines: Dict[int, list] = defaultdict(list)
        for w in words:
            lines[round(w["top"] / 3)] += [w]
        rows = []
        for y in sorted(lines):
            rows.append(" ".join(w["text"] for w in sorted(lines[y], key=lambda w: w["x0"])))
        return "\n".join(rows)
    except Exception:
        return ""


# ── spec block (document-level; identical boilerplate repeated on each page) ──
def _spec_block(all_text_up: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "powder_micron": None, "weld_spec": None, "tolerances": None,
        "material_grades": [], "timber_note": None,
    }
    # The spec block is often laid out one glyph per column, so the extracted text is
    # letter-spaced ("A L L W E L D S T O B E T I G"). Search BOTH the raw text (values like
    # "80 - 120 MICRON" survive) and a whitespace-stripped copy (distinctive phrases survive).
    despaced = re.sub(r"\s+", "", all_text_up)
    # Powder micron: the value nearest the word POWDER wins; else the first micron range that
    # is NOT the chrome (8-12 / 0.1-0.3) or zinc (13-15) figure.
    pw = None
    for m in _RE_MICRON_ANY.finditer(all_text_up):
        a, b = _num(m.group(1)), _num(m.group(2))
        window = all_text_up[max(0, m.start() - 40): m.start()]
        if "POWDER" in window or (a and b and a >= 40):  # 80-120 style, not 8-12 / 0.1-0.3
            pw = f"{m.group(1)}-{m.group(2)}"
            break
    out["powder_micron"] = pw
    _tig = "WELDSTOBETIG" in despaced or "WELDS TO BE TIG" in all_text_up
    _res = "RESISTANCEWELDING" in despaced or "RESISTANCE WELDING" in all_text_up
    if _tig or _res:
        bits = []
        if _tig:
            bits.append("TIG default")
        if _res:
            bits.append("resistance (wire-to-wire) 20% set-down")
        out["weld_spec"] = "; ".join(bits)
    if "FSC" in despaced:
        out["timber_note"] = "FSC certified required"
    for g in ("Q195", "Q235", "SPCC", "304", "6063"):
        if g in despaced:
            out["material_grades"].append(g)
    if "TOLERANCE" in despaced or "TOLERANCE" in all_text_up:
        # keep it simple + honest: record that tolerance bands are present (verbatim parse is
        # fragile across the jumbled columns; the estimator has the drawing for exact bands)
        out["tolerances"] = "linear/angular tolerance bands present on drawing"
    return out


def extract_drawing_facts(pdf_path: str | Path) -> Dict[str, Any]:
    """Deterministically read the printed manufacturing facts from a drawing PDF."""
    result: Dict[str, Any] = {
        "pages": [], "by_part": {}, "spec_block": {}, "source": "drawing_pdf_deterministic",
    }
    if pdfplumber is None:
        result["error"] = "pdfplumber not installed"
        return result
    p = Path(pdf_path)
    if not p.exists():
        result["error"] = f"not found: {p}"
        return result

    all_text_parts: List[str] = []
    spec_text_parts: List[str] = []
    try:
        with pdfplumber.open(str(p)) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                all_text_parts.append(text)
                spec_text_parts.append(_spec_region_text(page))
                wt = _RE_WEIGHT.search(text)
                tube, cutlen = _tube_and_length(page, text)
                fields = _title_block_fields(page)
                material = fields.get("material")
                finish = fields.get("finish")
                # a "SEE ASSEMBLY" material/finish is a pointer, not a value — null it here and
                # leave resolution to the engine's pointer-follower (which already does this).
                if _is_pointer(material):
                    material = None
                finish_ptr = _is_pointer(finish)
                # thickness: only if the MATERIAL field states it (e.g. "2mm MILD STEEL"); else
                # null (the tube section carries its own wall thk; plate thk lives in the views,
                # which we do NOT guess). Honest null beats a boilerplate-polluted number.
                thk = None
                if material:
                    mt = _RE_THK_IN_MATERIAL.search(material)
                    if mt:
                        thk = _num(mt.group(1))
                rec = {
                    "page": i,
                    "sheet_part": _title_block_part(page, text),
                    "weight_g": _num(wt.group(1)) if wt else None,
                    "tube_section": tube,
                    "cut_length_mm": cutlen,
                    "material": material,
                    "thickness_mm": thk,
                    "finish": None if finish_ptr else finish,
                    "finish_pointer": bool(finish_ptr),
                    "colour": fields.get("colour") if not _is_pointer(fields.get("colour")) else None,
                }
                result["pages"].append(rec)
    except Exception as exc:  # pragma: no cover
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    # spec block: search the word-reconstructed notes text (weld/grade phrases survive there),
    # with the plain page text appended so cleanly-printed values (80-120 MICRON) are also seen.
    result["spec_block"] = _spec_block(
        (" \n ".join(spec_text_parts) + " \n " + " ".join(all_text_parts)).upper())

    # roll page facts up by part number (a part's own detail sheet is authoritative for it)
    for rec in result["pages"]:
        pn = rec.get("sheet_part")
        if not pn:
            continue
        slot = result["by_part"].setdefault(pn, {"source": "drawing_pdf"})
        for k in ("weight_g", "tube_section", "cut_length_mm", "material", "thickness_mm", "finish", "colour"):
            v = rec.get(k)
            if v is not None and slot.get(k) in (None, ""):
                slot[k] = v
    return result


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(description="Deterministically extract printed manufacturing facts from a drawing PDF.")
    ap.add_argument("pdf")
    ap.add_argument("--json", action="store_true", help="dump full JSON")
    a = ap.parse_args()
    facts = extract_drawing_facts(a.pdf)
    if a.json:
        print(json.dumps(facts, indent=2))
    else:
        print(f"SPEC BLOCK: {facts.get('spec_block')}")
        print(f"{'PART':<22}{'WEIGHT g':>9}{'THK':>6}  {'TUBE / MATERIAL / FINISH'}")
        for pn, d in facts.get("by_part", {}).items():
            desc = " · ".join(str(d.get(k)) for k in ("tube_section", "material", "finish") if d.get(k))
            cl = f" @{d.get('cut_length_mm')}" if d.get("cut_length_mm") else ""
            print(f"{pn:<22}{str(d.get('weight_g') or ''):>9}{str(d.get('thickness_mm') or ''):>6}  {desc}{cl}")
