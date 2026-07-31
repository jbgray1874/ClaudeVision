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
import hashlib
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

# THE WORDS WE ASK FOR MUST BE WORDS WE CAN COST.
#
# The route vocabulary was written out longhand inside two prompts, and five of the words in
# it -- tube_cut, tube_bending, hole_machining, tapping, edge_banding -- had no entry in
# wb_populate.OP_NAME_MAP. So the model would return exactly the word it was told to use, and
# the workbook would not know what department it belonged to. tube_cut is the operation M&S
# 2085's two tubes need; it was on the asking side of the contract and missing from the
# paying side.
#
# One list, imported by both prompts and cross-checked against the department map by a
# fixture, so a word can never again be added on one side only.
ROUTE_OPERATIONS = (
    "laser_cutting", "punch", "saw", "tube_cut", "folding", "rolling", "tube_bending",
    "welding", "dress_welds", "hole_machining", "tapping", "deburring", "cnc_routing",
    "edge_banding", "glue", "powder_coating", "wet_spray", "diamond_polish",
    "wire_forming", "handling",
)

# THE SHOP'S CLOSED VOCABULARY, ASKED FOR DIRECTLY.
#
# ROUTE_OPERATIONS above are the engine's words and they all resolve. But a model writing
# about manufacturing produces "Cut to length", "MIG weld", "Laser cut" — sensible English
# that no rate table row matches, so the line costs zero and reads on the sheet exactly like
# work nobody identified. Asking for the CODE removes the translation step: the answer is
# already in the vocabulary that pays.
from department_codes import CODE_TITLES, DEPARTMENT_CODES  # noqa: E402

_DEPT_VOCAB = ", ".join(sorted(DEPARTMENT_CODES))

_SCHEMA = """{
  "drawing_info": {
    "drawing_number": "", "revision": "", "title": "", "project": "", "client": "",
    "drawn_by": "", "date": "", "scale": "", "material_general": "", "finish_general": "",
    "colour": "", "tolerance_linear": "", "tolerance_angular": "", "notes": []
  },
  "bom": [
    {"item_no": "", "part_number": "", "description": "", "qty": 0,
     "material_family": "metal|acrylic|timber|wire|tube|bought_in|mixed|other",
     "material": "", "thickness_or_section": "",
     "cut_length_mm": null, "weight_g": null,
     "finish": "", "colour": "",
     "is_fabricated": true, "is_bought_in": false,
     "confidence": "high|medium|low",
     "source": "explicit_bom_table|title_block|notes|inferred_from_views|filename",
     "comments": ""}
  ],
  "routes": [
    {"sequence": 10, "operation": "", "department": "", "part_numbers": [],
     "scope": "part|assembly", "qty_per_unit": 1,
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
The family decides whether we MAKE the part or BUY it, so it is not decoration: metal, acrylic,
timber, wire and tube are all things we cut and form here. Reserve bought_in for a component
purchased complete, and set is_bought_in to match it.

cut_length_mm is the length a tube, wire or extruded section is sawn to. Without it a section
cannot be costed at all \u2014 the section size alone does not say how much of it we buy.

MIXED ASSEMBLIES. Keep components PURE. Only a top-level assembly, or a sub-assembly that
genuinely combines materials, is "mixed" — never force one material onto everything under it.
Generate separate process steps per material stream, then a final assembly step that brings
them together with material_family "mixed". A finish stated for the metal parts belongs to
those part numbers only; do not spread it across acrylic or timber that is not coated.

OPERATIONS AND DEPARTMENTS ARE A CLOSED LIST. This is the single most important rule here.

`department` MUST be one of these exact codes, and nothing else:
""" + _DEPT_VOCAB + """

They are the shop's own department codes and they are the only strings the costing sheet can
price. Anything else — "Cut to length", "MIG weld", "Laser cut", a code you invent, a blank —
produces no rate and no cost, and the operation disappears from the estimate without a trace.
A wrong code can be corrected by an estimator; an unrecognised one is silently free.

  tube cutting, sawing or notching a tube ....... TUBE   (or SAW for bar and section)
  CO2 / MIG / TIG welding ....................... WELD
  spot welding .................................. SPOT
  laser cutting sheet metal ..................... LASM   (acrylic: LASA)
  press brake / forming a flat part .............. FOLD
  bending tube .................................. TBEN   (line bending: LINE)
  drilling, tapping, countersinking ............. DRIL
  deburring, fettling, bench finishing .......... BENC
  dressing or linishing a weld .................. DRES
  powder coating ................................ P/C    (wet paint: SPRY)
  CNC routing / joinery machining ............... CNCJ
  edge banding .................................. EDGE
  gluing or bonding ............................. GLUE
  assembly, fitting, handling, packing .......... PACM

`operation` should be the matching engine word from:
""" + ", ".join(ROUTE_OPERATIONS) + """.
Put the specific wording in `description` instead ("cut outer tube to length") — that field is
free text and is read by a person, so nothing is lost by keeping `operation` and `department`
strictly to the lists.

ONE OPERATION, ONE ROUTE LINE. An operation that joins parts together — a weld, an assembly,
a finish applied to the built unit — is ONE route line naming every part it acts on, not one
line per part. Repeating it per part books the same work several times over.

SCOPE says how often that line happens, and it is not the same as how many parts it names.
  scope "part"      — done once PER PART. Cutting three brackets is three cuttings.
  scope "assembly"  — done once per finished PRODUCT, however many parts it involves. Welding
                      three components into one bracket is ONE welding, not three; dressing
                      that weld is one dressing; coating the built unit is one coating.
qty_per_unit is how many times the operation happens per finished product — normally 1 for
assembly scope, and for part scope the number of those parts in the product.

Getting this wrong is expensive in one direction only: a joining operation marked "part" and
naming three components is charged three times.

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



# ── THE SAME PACK MUST PRODUCE THE SAME ROUTE ────────────────────────────────────────
#
# M&S 2085 was run twice with identical inputs and identical code. The first run returned a
# route including welding and dress_welds; the second did not. Labour fell from GBP 11.14 to
# GBP 5.19 and the unit cost from GBP 12.13 to GBP 5.73 -- a 53% drop that represents no
# manufacturing saving whatsoever, only the model reconsidering an inference it had already
# made. temperature=0 does not make a model deterministic, and an estimate that moves by half
# between identical runs cannot be an estimate.
#
# This is the route-side twin of the price problem this engine already refuses to tolerate:
# a figure that will not repeat cannot be quoted. Prices got a reproducibility gate; routes
# got nothing, because until the route reached the sheet nobody could see it move.
#
# So the extract is cached on the CONTENT it was derived from. The key covers the document
# text, the model, and the prompt -- so a redrawn pack, a model change, or a prompt edit all
# miss and re-ask, while a re-run of the same job on the same code returns the same answer,
# by construction rather than by hope.
#
# SDI_LLM_EXTRACT_REFRESH=1 forces a fresh call. SDI_LLM_EXTRACT_CACHE_DIR relocates it.
_CACHE_VERSION = "v1"


def _cache_dir() -> Optional[Path]:
    raw = os.environ.get("SDI_LLM_EXTRACT_CACHE_DIR")
    if not raw:
        # Beside the repo, not at a hardcoded Windows path. A literal
        # r"C:\ClaudeVision\cache\llm_extract" default creates a directory named
        # exactly that in the working tree on any other platform — which is how a
        # stray "C:\ClaudeVision" folder appeared in this checkout while the cache
        # was being written. The Windows install still resolves to the same place.
        raw = str(Path(__file__).resolve().parents[1] / "cache" / "llm_extract")
    try:
        d = Path(raw)
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return None


def _cache_key(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


def _cache_read(key: str) -> Optional[Dict[str, Any]]:
    if os.environ.get("SDI_LLM_EXTRACT_REFRESH", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    d = _cache_dir()
    if not d:
        return None
    f = d / f"{_CACHE_VERSION}_{key}.json"
    try:
        if f.exists():
            with open(f, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
            if isinstance(obj, dict):
                obj["_from_cache"] = True
                return obj
    except Exception:
        return None
    return None


def _cache_write(key: str, obj: Dict[str, Any]) -> None:
    d = _cache_dir()
    if not d or not isinstance(obj, dict):
        return
    # ATOMIC, AND NOT SILENT. A half-written entry is worse than none: the next run reads
    # it, json.load raises, _cache_read swallows it and re-asks — which is survivable — but
    # a TRUNCATED yet still-valid JSON would be reused as if it were the whole answer. Write
    # beside and rename, which is atomic on both platforms this runs on.
    #
    # And say so on failure. A cache that cannot write is a job silently back to being
    # non-reproducible, which is the exact property the cache exists to provide.
    _final = d / f"{_CACHE_VERSION}_{key}.json"
    # The temp name carries the pid: two runs writing the SAME key would otherwise share one
    # temp file, and the second's rename could publish the first's half-written bytes.
    _tmp = d / f"{_CACHE_VERSION}_{key}.{os.getpid()}.tmp"
    try:
        with open(_tmp, "w", encoding="utf-8") as fh:
            json.dump({k: v for k, v in obj.items() if k != "_from_cache"},
                      fh, indent=1, ensure_ascii=False)
        os.replace(_tmp, _final)
    except Exception as exc:
        try:
            _tmp.unlink()
        except Exception:
            pass
        print(f"   [llm-extract] could NOT cache this read ({exc}) — the next run will "
              f"re-ask the model, so this job is not reproducible until it can write to "
              f"{d}", flush=True)


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


# THE SYSTEM MESSAGE IS PART OF THE PROMPT, AND THE TWO PASSES NEED OPPOSITE ONES.
#
# This function used to hardcode the transcription prompt AND "Never invent" into every call,
# then append whatever the caller passed as if it were the drawing pack. So the inference pass
# — whose whole purpose is to conclude what the drawing does not print — was sent
# "TRANSCRIBE, NEVER INVENT... return an empty routes list rather than a plausible one" FIRST,
# and its own instructions second. It obeyed the first one. That is why the second pass came
# back all nulls with no routes, and why the same model in a chat window did better than this
# engine did: the chat window was not being told to refuse before it was asked to answer.
#
# The caller now owns its whole message. Nothing is prepended.
SYSTEM_TRANSCRIBE = "You transcribe engineering drawings to JSON. Never invent."
SYSTEM_INFER = (
    "You are a manufacturing estimator reading an engineering drawing pack and answering in "
    "JSON. You are being asked what the drawing IMPLIES, not what it prints — say what an "
    "experienced estimator would conclude, label every conclusion as inferred, and return null "
    "where you genuinely cannot tell rather than a guess dressed up as a reading."
)


def _call_llm(user_content: str, model: str,
              system: str = SYSTEM_TRANSCRIBE) -> Optional[str]:
    """One TEXT chat call (xAI OpenAI-compatible). `user_content` is the COMPLETE user message —
    prompt and payload both — because a caller whose prompt gets something else stapled in
    front of it is not in control of what it asked."""
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY not set (C:\\ClaudeVision\\.env or $env:XAI_API_KEY).")
    from openai import OpenAI  # xAI is OpenAI-compatible
    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
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
    # Same pack, same model, same prompt -> same answer. See the cache block above: 2085
    # returned a route with welding on one run and without it on the next, and the unit cost
    # halved. An estimate that moves by half between identical runs is not an estimate.
    _key = _cache_key("full", ctx, model, _PROMPT, SYSTEM_TRANSCRIBE)
    _hit = _cache_read(_key)
    if _hit is not None:
        print(f"   [llm-full-extract] reusing the cached read for this pack "
              f"(unchanged drawings, model and prompt) — the route does not get "
              f"reconsidered between runs", flush=True)
        return _hit
    try:
        raw = _call_llm(_PROMPT + "\n\n--- DRAWING PACK ---\n" + ctx, model,
                        system=SYSTEM_TRANSCRIBE)
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
    normalize_job(obj)
    # THE RAW RESPONSE, KEPT. Without it "the model did not say it" and "we did not read
    # it" are indistinguishable from every saved artefact, because _llm_extract.json holds
    # the PARSED job. 2085's vanishing weld was settled by reading a commit diff and
    # noticing the parse path had not changed between two runs — which works once and is
    # not a method. Truncated, because this is for answering a question, not an archive.
    obj["_raw_response"] = (raw or "")[:20000]
    obj["_prompt_fingerprint"] = _cache_key(_PROMPT, SYSTEM_TRANSCRIBE)
    _cache_write(_key, obj)
    return obj


# ── the bridge between what the model returns and what the engine reads ──────────────
#
# THE SCHEMA SAYS `bom`. THREE CONSUMERS READ `parts`. NOTHING JOINED THEM.
#
# apply_full_job_to_pre_estimate keys on job["parts"], overlay_drawing_facts iterates
# job["parts"], and parts_missing_detail is handed job["parts"]. When the multi-material
# schema replaced the old one, the component list was renamed to `bom` and all three went
# quietly to zero: no material, no thickness, no section reached any part, and because the
# missing-detail list came back empty the inference pass was never even asked to run.
#
# M&S 2085 is the whole of that failure in one sheet. Two tubes with no material, no section
# and no operation; the outer tube priced at GBP 86.04 by a market estimate because nothing
# said we make it; GBP 2.00 of labour on a welded three-part bracket, all of it booked to the
# one part that happened to have a DXF. Every downstream fix looked like a costing bug.
#
# So this projects `bom` onto the field names the engine reads, once, at the source. Both
# shapes work: a job that already carries `parts` is left alone.
_FABRICATED_FAMILIES = frozenset({"metal", "acrylic", "timber", "wire", "tube"})
_RE_SECTION_3D = re.compile(r"\d+(?:\.\d+)?\s*[xX]\s*\d+(?:\.\d+)?\s*[xX]\s*\d+(?:\.\d+)?")
_RE_SINGLE_DIM = re.compile(r"([\d.]+)\s*mm", re.I)


def _split_size(raw: Any, family: str):
    """thickness_or_section -> (thickness_mm, tube_section). The prompt asks for one field in
    whichever style suits the family; the engine has two, and they drive different costing
    paths — a thickness feeds sheet nesting, a section feeds the tube/bar catalogue."""
    s = str(raw or "").strip()
    if not s:
        return None, None
    if _RE_SECTION_3D.search(s):
        return None, s                      # 25x25x1.5 SHS — a section, verbatim
    if family in ("tube", "wire"):
        return None, s                      # Ø6mm — a section we cannot decompose, kept as read
    m = _RE_SINGLE_DIM.search(s)
    if m:
        try:
            return float(m.group(1)), None  # 1.2mm / 18mm — a sheet or board thickness
        except ValueError:
            pass
    return None, None


def project_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One BOM row -> one part record in the shape the engine reads. None if unusable."""
    if not isinstance(row, dict):
        return None
    pn = str(row.get("part_number") or "").strip()
    if not pn:
        return None
    fam = str(row.get("material_family") or "").strip().lower()
    thk, sec = _split_size(row.get("thickness_or_section"), fam)
    # THE FAMILY IS THE MAKE/BUY ANSWER, and it is the reason this matters beyond plumbing.
    # A tube is stock we saw and weld, not a component we purchase — but with nothing
    # carrying the family through, a tube with no material read as an unidentified bought-in,
    # had its fabrication operations stripped by bought_in_policy, and was priced by the
    # market instead of costed from a route.
    bought = bool(row.get("is_bought_in")) or fam == "bought_in"
    if fam in _FABRICATED_FAMILIES:
        bought = False
    return {
        "part_number": pn,
        "description": row.get("description"),
        "material": row.get("material") or None,
        "material_family": fam or None,
        "thickness_mm": thk if thk is not None else row.get("thickness_mm"),
        "tube_section": sec or row.get("tube_section"),
        "cut_length_mm": row.get("cut_length_mm"),
        "weight_g": row.get("weight_g"),
        "finish": row.get("finish") or None,
        "colour": row.get("colour") or None,
        "is_bought_in": bought,
        "confidence": row.get("confidence"),
        "source": row.get("source"),
    }


def normalize_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Project the schema's `bom` onto the `parts` shape the engine reads. In place."""
    if not isinstance(job, dict):
        return job
    if isinstance(job.get("parts"), list) and job["parts"]:
        return job                           # already in the shape the consumers want
    # WHAT THE DRAWING SHOWS IS NOT WHAT WE SUPPLY -- AND THIS IS THE SECOND DOOR.
    #
    # The prose recogniser was guarded first, and 12120 still shipped BI-SCREENCABLE with no
    # recogniser message at all: the row arrived through the whole-document extract's own
    # `bom` list instead. Same mistake, different path, so the same predicate applies here
    # rather than a second rule that knows about cables.
    #
    # The drawing's general notes are passed in as context, so a row whose description is
    # disclaimed on the page is caught even when the row itself repeats none of the wording.
    try:
        from bought_in_recogniser import bom_row_is_reference_only as _ref_only
    except Exception:                                   # pragma: no cover - import guard
        _ref_only = None
    _notes = " ".join(str(n) for n in ((job.get("drawing_info") or {}).get("notes") or []))

    parts: List[Dict[str, Any]] = []
    seen = set()
    _excluded: List[str] = []
    for row in (job.get("bom") or []):
        p = project_row(row)
        if not p or p["part_number"].upper() in seen:
            continue
        if _ref_only is not None and _ref_only(row.get("description"),
                                               row.get("comments"), _notes):
            _excluded.append(f"{p['part_number']} ({p.get('description') or ''})".strip())
            continue
        seen.add(p["part_number"].upper())
        parts.append(p)
    job["parts"] = parts
    if _excluded:
        job.setdefault("warnings", []).append(
            "BOM rows NOT taken as supplied parts — the drawing shows them and disclaims "
            "supplying them (reference only / by others / customer supplied): "
            + "; ".join(_excluded))
        print(f"   [llm-extract] {len(_excluded)} BOM row(s) excluded as reference-only: "
              f"{'; '.join(_excluded)}", flush=True)
    return job


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
        _ikey = _cache_key("infer", payload, model, SYSTEM_INFER)
        _ihit = _cache_read(_ikey)
        if _ihit is not None:
            return _ihit
        raw = _call_llm(payload, model, system=SYSTEM_INFER)
        parsed = _parse(raw) if raw else None
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}

    # The schema calls the component list `bom`; the prompt above also talks about "parts".
    # Accept either rather than returning nothing because the model picked the other word —
    # a shape mismatch that silently drops the whole pass is the most expensive kind of bug
    # here, because it looks exactly like a model that had nothing to say.
    rows = parsed.get("parts")
    if not isinstance(rows, list) or not rows:
        rows = parsed.get("bom") if isinstance(parsed.get("bom"), list) else []
    out = []
    for row in rows:
        # Projected through the same bridge as the transcription pass: the inference pass
        # answers in the SAME schema, so it comes back with thickness_or_section too, and a
        # merge that reads thickness_mm would silently find nothing on every row.
        p = project_row(row)
        if not p:
            continue
        p["source"] = INFERENCE_SOURCE
        out.append(p)

    # ROUTES ARE THE POINT OF THIS PASS, AND THEY WERE BEING THROWN AWAY.
    # _INFER_PROMPT says "Every route you return must have inferred=true", and
    # apply_routes_to_parts already ranks an inferred route below a stated one. Neither could
    # ever fire, because this function returned parts only. £2.00 of labour on a welded
    # three-part bracket was the visible end of that.
    routes = []
    for r in (parsed.get("routes") or []):
        if not isinstance(r, dict) or not str(r.get("operation") or "").strip():
            continue
        r["inferred"] = True   # whatever it claimed: this pass is inference by construction
        routes.append(r)

    _res = {"source": INFERENCE_SOURCE, "parts": out, "routes": routes,
            "warnings": parsed.get("warnings") or [],
            "missing_information": parsed.get("missing_information") or [],
            # The inferred route is the unstable half — 2085's weld was a conclusion, not a
            # reading, and it is the one that came and went. Keep what the model actually
            # said so the next disagreement is settled by evidence, not by archaeology.
            "_raw_response": (raw or "")[:20000],
            "found": bool(out or routes)}
    # The INFERRED route is the unstable half — welding on 2085 was a conclusion, not a
    # reading, and it is the one that vanished. Cached on the same terms as the rest.
    _cache_write(_ikey, _res)
    return _res


# Which datum a field on an inferred row fills. Kept explicit so a new schema key cannot
# quietly start overwriting a transcribed value just by existing.
_INFERABLE_FIELDS = ("material", "material_family", "thickness_mm", "tube_section",
                     "cut_length_mm", "overall_size_mm", "finish", "colour", "weight_g")


def merge_inference(job: Dict[str, Any], inference: Dict[str, Any]) -> Dict[str, int]:
    """Fold the second pass into the job IN PLACE, gap-fill only, per datum.

    A transcribed value is a reading and always wins; inference can only occupy a hole the
    transcription left. Every field this fills is recorded in the row's `field_sources` so the
    distinction survives into the estimate and onto the sheet, rather than being a fact about
    which pass happened to run.

    Returns counts. Doing the merge here — not at the call site — is deliberate: this is the
    part with the rules in it, and the call site is the part that cannot be tested.
    """
    counts = {"fields": 0, "parts_added": 0, "routes": 0}
    if not isinstance(job, dict) or not isinstance(inference, dict):
        return counts

    parts = job.get("parts")
    if not isinstance(parts, list):
        parts = []
        job["parts"] = parts
    by_pn = {}
    for p in parts:
        if isinstance(p, dict) and p.get("part_number"):
            by_pn[str(p["part_number"]).strip().upper()] = p

    for row in (inference.get("parts") or []):
        if not isinstance(row, dict) or not row.get("part_number"):
            continue
        pn = str(row["part_number"]).strip().upper()
        target = by_pn.get(pn)
        if target is None:
            # A part the transcription never listed at all. Added whole, and every field on it
            # is inference — it is better costed and flagged than absent and silent.
            new_row = dict(row)
            new_row["source"] = INFERENCE_SOURCE
            new_row["field_sources"] = {k: INFERENCE_SOURCE for k in _INFERABLE_FIELDS
                                        if row.get(k) not in (None, "", [])}
            parts.append(new_row)
            by_pn[pn] = new_row
            counts["parts_added"] += 1
            continue
        srcs = target.setdefault("field_sources", {})
        for key in _INFERABLE_FIELDS:
            val = row.get(key)
            if val in (None, "", []):
                continue
            if target.get(key) not in (None, "", []):
                continue          # transcribed — a reading beats a conclusion, always
            target[key] = val
            srcs[key] = INFERENCE_SOURCE
            counts["fields"] += 1

    routes = job.get("routes")
    if not isinstance(routes, list):
        routes = []
        job["routes"] = routes
    # An operation the transcription already read for the same part is not repeated: it is
    # already there at the higher rank, and adding it again would only make it look inferred.
    seen = {(str(r.get("operation") or "").strip().lower(), str(p).strip().upper())
            for r in routes if isinstance(r, dict)
            for p in (r.get("part_numbers") or [])}
    for r in (inference.get("routes") or []):
        if not isinstance(r, dict):
            continue
        op = str(r.get("operation") or "").strip().lower()
        pns = [str(p).strip().upper() for p in (r.get("part_numbers") or []) if p]
        keep = [p for p in pns if (op, p) not in seen]
        if pns and not keep:
            continue
        r["part_numbers"] = keep or pns
        r["inferred"] = True
        routes.append(r)
        for p in keep:
            seen.add((op, p))
        counts["routes"] += 1
    return counts


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
