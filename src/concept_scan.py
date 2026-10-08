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
from typing import Any, Dict, List, Mapping, Optional

# ── BUMP THIS WHENEVER THE PROMPT CHANGES ───────────────────────────────────────────
#
# It is part of the cache key, so a prompt change WITHOUT a bump is the worst of both: the
# new instructions are never sent, every pack replays the answer the old prompt produced,
# and the run looks entirely normal. The whole "a noun list, not a BOM" rewrite would have
# reached nothing on the machine it was written for.
#
# `_PROMPT_FINGERPRINT` below makes forgetting impossible: it pins the prompt's own hash, and
# a test compares the two. Edit the prompt, the hash moves, the test fails, and the message
# tells you to bump the version and record the new hash.
#   c1  first cut — "name the parts you can see"
#   c2  the make list: an enclosure is its panels, and every made line names its work
#   c3  banded edges must be NAMED before edging is charged — see EDGE_BASIS_FIELD
#   c4  print is always its own graphic line, never folded into a board's material (D-365)
CONCEPT_PROMPT_VERSION = "c4"

SOURCE = "vision_concept"

# ── THE ENQUIRY BRIEF ─────────────────────────────────────────────────────────────────
#
# Dave Wright, 30 Sep 2026, on the M&S bin: "350off … Plywood construction with print, or
# mild steel powder coated with print … 600 x 600 x 1200mm bump bin with lid with 1800mm back
# panel." The render alone had been read as a 1,750 mm carcass of 18 mm MFMDF — a different
# product. Nothing in the pack could say otherwise, and nothing may be typed into the code.
#
# So the brief is an INPUT, like the client and the drawing number: typed on the portal for
# an LLM-only run, filed into the job folder beside the pack (on record with it), and put to
# the vision model as stated facts that outrank what it infers from the picture. Every figure
# it supplies is stamped `enquiry_brief` — above anything sighted, below anything read off a
# drawing or measured — so a real pack still displaces it field by field (D-360).
BRIEF_SOURCE = "enquiry_brief"
BRIEF_FILENAME = "ENQUIRY_BRIEF.txt"
BRIEF_MAX_CHARS = 4000

_BRIEF_SECTION = """

ENQUIRY BRIEF — written by SDI estimating for THIS job. These are STATED FACTS and they
override anything you would infer from the images: overall sizes, materials, finish,
construction, quantities, and parts the images cannot show.
- Size every part from the stated dimensions wherever they fix it; use visual cues only for
  what the brief leaves open.
- If the brief offers alternative constructions ("A … or B …"), cost ONLY the FIRST one and
  list the others in "options_not_costed".
- Add to every part "from_brief": a list of which of "size", "material", "quantity" the brief
  states or directly fixes for that part (empty list if none), and say "from the brief" in
  why_size / quantity_basis for those.
- A figure the brief gives as a price is ignored: you still never state a price.
Add "options_not_costed": ["<each alternative the brief offered that you did not cost>"] to
the top level of the JSON.

BRIEF:
<<<
{brief}
>>>"""


def read_brief(job_folder: Any) -> str:
    """The brief filed with this job's pack, or "" — trimmed and capped, never raised."""
    if not job_folder:
        return ""
    try:
        path = Path(str(job_folder)) / BRIEF_FILENAME
        if not path.is_file():
            return ""
        # utf-8-sig: a brief saved from Notepad or PowerShell's Set-Content -Encoding UTF8
        # starts with a byte-order mark, which is not whitespace and would ride into the prompt.
        return path.read_text(encoding="utf-8-sig", errors="replace").strip()[:BRIEF_MAX_CHARS]
    except OSError:
        return ""


def find_brief(folders: List[Any]) -> tuple:
    """(brief, file) from the first folder that holds one, or ("", "").

    THE PACK'S FOLDER, WHEREVER THE RUN WAS POINTED (D-361). A render is scanned as a PDF
    written into the output tree, so the scan's own job folder is not the folder the portal
    staged — the 13:07 plywood run read the render alone with the brief sitting beside it.
    Every folder the run knows its inputs came from is asked."""
    seen = set()
    for folder in folders:
        if not folder:
            continue
        key = str(folder)
        if key in seen:
            continue
        seen.add(key)
        text = read_brief(folder)
        if text:
            return text, str(Path(key) / BRIEF_FILENAME)
    return "", ""


def _from_brief(sighted: Mapping[str, Any], field: str) -> bool:
    """Did the model say the brief fixes this field of this part?"""
    fb = sighted.get("from_brief")
    if fb is True:
        return True
    if isinstance(fb, (list, tuple)):
        return field in {str(x).strip().lower() for x in fb}
    return False

# The field the model names visibly-finished edges in. Named once: the prompt asks for it
# and the assembler gates edge_banding on it, and those two drifting apart is how a rule
# becomes decorative.
EDGE_BASIS_FIELD = "banded_edges"

# ── THE OPERATIONS THE ENGINE CAN ACTUALLY MINT ─────────────────────────────────────
#
# The model may only name work from this list, because every name here resolves to a real
# department on the rate card (department_codes._alias). A word outside it — "print", "wrap",
# "fit" — resolves to nothing, mints nothing, and silently costs nothing, which is exactly
# how the first run produced three route rows and charged for none of them.
#
# Board and joinery vocabulary first: this is what a display bin is made on.
SIGHTABLE_OPERATIONS = {
    "saw":              "cut board or tube to size (panel saw)",
    "cnc_routing":      "router pass — profiles, apertures, cut-outs",
    "edge_banding":     "edge tape or lipping on a visible board edge",
    "laminating":       "laminate, veneer, vinyl wrap or applied graphic laid onto a panel",
    "glue":             "bonded or glued joint",
    "wet_spray":        "sprayed paint or lacquer finish",
    "bench_work":       "bench assembly of a joinery carcass",
    "hole_machining":   "drilled or bored holes — hinge bores, fixing holes",
    "assembly":         "putting the unit together — fitting lid, castors, fittings",
    "laser_cutting":    "laser cut sheet metal",
    "folding":          "press-brake fold in sheet metal",
    "welding":          "welded joint",
    "powder_coating":   "powder coated finish",
    "deburring":        "deburr or fettle an edge",
}

_PROMPT = """You are looking at {n} image(s): customer-supplied renders or photos of ONE retail
display product (SDI Displays estimating). They may be different views or print/graphic variants
of the SAME product — never treat each image as a separate product.

Produce a MAKE LIST: every line is something that is CUT or BOUGHT, with how many per unit.
This is a bill of materials a manufacturer would price, not a list of the things you can see.

THE DIFFERENCE MATTERS AND IT IS THE WHOLE TASK:
- An enclosure is NOT one part. A cabinet is its PANELS — front, two sides, back, base, top —
  each its own line with its own blank size. Never return a carcass as a single blank.
- A printed face is TWO lines where it is a print applied to a board: the board, and the
  applied graphic.
- PRINT IS ALWAYS ITS OWN LINE, even when it goes straight onto the board: one "graphic"
  line per printed face (or per print set), with the printed size. Never fold the print into
  a board's material ("printed plywood") — the board and its print are costed separately.
- Fittings you can see the effect of are lines too: a lid that lifts has a hinge; a unit on
  wheels has castors; panels that meet are screwed or glued.
- Give the quantity PER UNIT (4 castors = one line, quantity 4 — never 4 lines, never "a set").

For every line give the work it needs, from THIS LIST ONLY — any other word is discarded:
{ops}

Sizes: estimate in mm from visible human-scale cues (castors ~75mm, hand-height apertures,
floor tiles, door heights). Every size must name the cue it came from. Integers only.

EDGE BANDING IS CHARGED ONLY WHERE YOU CAN NAME THE EDGES. If you list edge_banding on a
part, say in "banded_edges" WHICH edges are visibly finished — "front and top edges show a
banded lip", "all four edges of the door". If you cannot see which edges are finished,
leave "banded_edges" empty and the operation is recorded as an assumption for the estimator
rather than charged. Do not band every panel because the product looks tidy.

Rules:
- NEVER state a price, cost or supplier. Geometry, materials, counts and operations only.
- A bought-in line (castor, hinge, fitting) needs no blank size — leave the sizes 0.
- NEVER invent a part whose existence you cannot infer from the image. What a real unit must
  contain but the images cannot show goes in "not_visible" as words, for the estimator.
- If the images are variants (different graphics, same build), say so in "variants" and list
  each graphic set once in "print_sets" — ONE build, not one per variant.

Return ONLY valid JSON, no markdown, exactly this shape:
{{
  "product": {{"name": "<what this is>", "assumed_overall_mm": {{"height": 0, "width": 0, "depth": 0}},
              "scale_cue": "<what the overall size was scaled from>", "variants": 1}},
  "parts": [
    {{"name": "<part, e.g. SIDE PANEL>", "kind": "fabricated|bought_in|graphic",
      "sighted_material": "<what it looks like, verbatim impression>",
      "material_guess": "<closest stock material, e.g. MFMDF, MDF, ACRYLIC, MILD STEEL, PRINTED_PAPER>",
      "assumed_blank_mm": {{"length": 0, "width": 0, "thickness": 0}},
      "quantity": 1, "quantity_basis": "<seen / implied by symmetry / per print set>",
      "operations": ["saw", "cnc_routing"],
      "banded_edges": "<which edges are visibly finished, or empty if you cannot tell>",
      "seen": "<which image, where>", "why_size": "<the cue this was scaled from>"}}
  ],
  "unit_operations": ["assembly"],
  "print_sets": ["<one line per graphic variant>"],
  "not_visible": ["<what a real unit needs that these images cannot show>"]
}}"""

# The prompt's own hash, so a change without a version bump cannot pass silently. If a test
# tells you this is wrong: bump CONCEPT_PROMPT_VERSION above, then put the new hash here.
_PROMPT_FINGERPRINT = "93eff7e3c858"


class ConceptUnavailable(RuntimeError):
    """The vision model could not be asked — no key, offline, or the client is absent.

    ITS OWN TYPE for the same reason the splitter's NoOCR is: a missing capability is a
    fact about the machine, not about the pack, and an empty estimate must say "nothing was
    read", never "there was nothing to read".
    """


# ── the call, isolated exactly as _bom_vision_reader isolates its own ───────────────

BRIEF_PAGE_STEM = "ENQUIRY_BRIEF"

# NO IMAGES, ONLY WORDS (D-401). The make-list prompt is written for renders; a brief typed
# on a site or the portal with nothing attached has no picture to sight from, and the model
# must be told so rather than left to invent cues it was promised.
_TEXT_ONLY_PREAMBLE = """There are NO images with this request. Everything you know about the
product is in the ENQUIRY BRIEF below, which SDI estimating wrote as stated facts. Build the
make list from the brief alone: size every part from the dimensions it states, and where it
leaves a size open, give a plausible figure for a retail display of this kind and say "assumed —
not in the brief" in why_size. Do not describe visual cues: there are none.

"""


# ── A DRAWING SHEET IS READ AS A DRAWING (D-415) ──────────────────────────────────────────
#
# 12675-01, 8 Oct 2026: the design-intent GA of a bag stand went to this read as the fallback
# the model take-off could not answer, under a prompt written for a photograph — "estimate in
# mm from visible human-scale cues". The sheet says 600 × 400, 1250 body, 2mm STEEL
# CONSTRUCTION, ADJUSTABLE FEET, 20 x CUSTOMER BAGS at 1.5 kg; the read took 1580 (the top
# of the bags) for four posts, the twenty bags for twenty bars, 530 (the bag's width) for
# their length, and came to about 15 kg of steel on a sheet whose own weight, less its bags,
# is 37 kg. Nothing in the prompt told it the numbers on the page were facts, or that what a
# product holds is not what it is made of.
#
# So a sheet read gets three things a render read does not: the text printed on the sheet,
# verbatim, from the file's own text layer; a preamble that says dimensions and notes are
# facts, the goods held are not parts and a fitting is a line only where it is drawn; and
# "sheet_facts" in the answer, which `sheet_check` holds the bill against. The render
# prompt is unchanged and its cache key is unchanged: only a sheet read hashes this.
#   s1  first cut (D-415)
#   s2  the model's envelope as the body; the goods' numbers never spent on the steel; the body
#       made from its panels; a legend is not a note (D-416)
#   s3  the goods' unit weight and the labelled parts reported, so the check can verify them
#       from what the sheet prints (D-417)
#   s4  a face with a window is still a panel; an internal divider spans the inside of the body
#       (D-418: the 14:42 read dropped the front and back and sized the divider off a bag)
SHEET_PROMPT_VERSION = "s4"
SHEET_TEXT_MAX_CHARS = 6000

_SHEET_PREAMBLE = """THESE ARE DRAWING SHEETS, NOT PHOTOGRAPHS. Each image is a general-arrangement or
design-intent drawing with a title block, dimensions and notes; the text printed on the sheets
is given at the end of this request. READ THE SHEET BEFORE YOU LOOK AT THE PICTURE. Where these
rules and the ones after them differ, THESE RULES WIN.

1. A DIMENSION ON THE SHEET IS A FACT. Size every part from the dimensions drawn and the notes,
   never by eye and never from human-scale cues. A part the sheet does not dimension takes its
   size from the dimensions that bound it (a panel between two dimensioned edges is that size);
   say which in why_size. Only where nothing bounds it, estimate and write "not dimensioned".
2. A MATERIAL, GAUGE OR FINISH NOTE IS A FACT. A note such as "2mm STEEL CONSTRUCTION" fixes the
   material and thickness of every made part it covers; a finish note fixes the coat. A note
   that only points elsewhere ("SEE PART DRAWINGS") states nothing, and a general legend or
   specification block (finish, material or weld specifications, tolerances) says how a thing
   is done if it is done, not that this product has it.
3. WHAT THE PRODUCT HOLDS IS NOT A PART. Goods drawn in or on it (stock, bags, products, the
   customer's items), with their counts, sizes and weights, are the LOAD, not the make list:
   never a line, and their count is never a count of parts. A dimension to the top of the goods
   is not the height of the product, and lines seen through an opening may be the goods behind it.
   NEVER SPEND THE GOODS' NUMBERS ON THE STEEL: no part takes the goods' count as its quantity
   (unless the sheet draws one part per item — then write "one per <item>" in quantity_basis), and
   no part takes a goods dimension, or a dimension to the top of the goods, as its size.
4. A FITTING IS A LINE ONLY WHERE THE SHEET DRAWS OR LABELS IT (a label naming feet, castors or a
   hinge). Do not add fittings or fixings the sheet does not show; put what a real unit may need
   in "not_visible".
5. NO MADE PART IS LONGER OR WIDER THAN THE PRODUCT BODY, unless it is folded and its blank is
   the unfolded shape.
6. MAKE THE BODY FROM ITS PANELS. Where the sheet shows a box, carcass or frame of one material and
   gauge, list the panels or members that make it (faces, base, top, internal dividers), each
   sized from the body's dimensions, with the windows and cut-outs it shows as part of the panel,
   never as separate bars. A face with a window or opening cut in it is still a panel — list it,
   with the opening cut from it; only a side the plan view shows open has no panel. An internal
   divider or shelf spans the inside of the body between the walls it meets. Give each its route from the list below: cut it, fold it where corners
   are formed, weld it where the sheet says welded, finish it as the note says.
7. Add to every part "drawn": the view and label where the sheet draws or names it, or "" if the
   sheet does not show it.
8. Add to the top level "sheet_facts", exactly what the sheet states (0, "" or [] where it is
   silent):
   {{"body_mm": {{"height": 0, "width": 0, "depth": 0}}, "body_basis": "<the dimensions read; never to
   the top of the goods>", "material": "", "thickness_mm": 0, "finish": "",
   "stated_weight_kg": 0, "weight_includes_goods": "yes|no|not stated",
   "goods": "<what the product holds, with count and unit weight where stated>",
   "goods_count": 0, "goods_unit_weight_kg": 0, "goods_weight_kg": 0,
   "goods_dimensions_mm": [<every dimension the sheet gives of the goods themselves>],
   "dimensions_to_goods_mm": [<every product dimension measured to or over the goods>],
   "labelled_parts": [<every label on the sheet that names a part of the product, exactly as
   printed; never the goods>]}}
   Every labelled part must be a line of the make list.

"""

# THE DESIGN'S OWN BODY, WHERE THE MODEL GAVE ONE (D-416). The take-off refuses a block with no
# stock basis as a part; its envelope is still the holder's measured size.
_ENVELOPE_SECTION = """

THE DESIGN'S MODEL: {of} is one undetailed body {dims} mm, measured off the SolidWorks model. That
is the PRODUCT BODY — size the panels from it; no made part is larger than it, and the product is
this size, not a dimension to the top of any goods."""

_SHEET_TEXT_SECTION = """

TEXT PRINTED ON THE SHEET(S), extracted verbatim from the drawing file. The dimensions, notes and
title block are in it; its order is not the drawing's layout.
<<<
{text}
>>>"""

# THE BILL PUT BACK ONCE, WITH WHAT BROKE (D-415). Read after `sheet_check`, never before.
_RECHECK_SECTION = """

YOUR FIRST MAKE LIST FOR THESE SHEETS DID NOT AGREE WITH WHAT THE SHEET STATES:
{failures}
Read the sheet again and return the whole make list, corrected, in the same JSON shape. Do not
pad or trim lines to hit a figure: every line must be drawn on the sheet and sized from it."""

# The sheet prompt's own hash (preamble + text, recheck and envelope sections), pinned beside
# SHEET_PROMPT_VERSION as _PROMPT_FINGERPRINT is pinned beside the render prompt's version.
_SHEET_PROMPT_FINGERPRINT = "72a1d6c427c9"


def is_brief_page(path: Any) -> bool:
    """Is this document the staged brief's own page, and not a drawing or a render?"""
    return BRIEF_PAGE_STEM in Path(str(path or "")).stem.upper()


def sheet_text(pdf_paths: List[Any]) -> str:
    """The text printed on these sheets, from each file's own text layer, capped — or "".

    Verbatim and unparsed: the model is told it is the sheet's words, and `sheet_check` looks
    a figure up in it. A scan with no text layer gives "" and the read proceeds on the image."""
    chunks: List[str] = []
    for pdf in (pdf_paths or []):
        if is_brief_page(pdf):
            continue
        try:
            import pdfplumber                                           # noqa: WPS433
            with pdfplumber.open(str(pdf)) as doc:
                for page in doc.pages:
                    chunks.append(page.extract_text() or "")
        except Exception:                                               # noqa: BLE001
            try:
                import pymupdf                                          # noqa: WPS433
                with pymupdf.open(str(pdf)) as doc:
                    chunks.extend(page.get_text() or "" for page in doc)
            except Exception:                                           # noqa: BLE001
                continue
    text = "\n".join(c.strip() for c in chunks if c and c.strip())
    return text[:SHEET_TEXT_MAX_CHARS]


def _envelope_words(envelope: Any) -> str:
    dims = [d for d in (_num(v) for v in (envelope or [])) if d]
    return " × ".join(f"{d:g}" for d in dims) if len(dims) >= 2 else ""


def concept_prompt_text(png_pages: List[bytes], brief: str = "", *, sheet: bool = False,
                        sheet_words: str = "", recheck: str = "", envelope: Any = None,
                        envelope_of: str = "") -> str:
    """The words put to the model: the make-list prompt, the text-only preamble where there
    is no image, the sheet preamble and the sheet's own text where the pages are drawing
    sheets, the brief section where there is a brief, and what broke where it is re-asked."""
    _ops = "\n".join(f"  {name} — {what}" for name, what in SIGHTABLE_OPERATIONS.items())
    _text = _PROMPT.format(n=len(png_pages), ops=_ops)
    if not png_pages:
        _text = _TEXT_ONLY_PREAMBLE + _text
    if sheet:
        _text = _SHEET_PREAMBLE.format() + _text
    if brief:
        _text += _BRIEF_SECTION.format(brief=brief)
    if sheet and sheet_words:
        _text += _SHEET_TEXT_SECTION.format(text=sheet_words)
    if sheet and _envelope_words(envelope):
        _text += _ENVELOPE_SECTION.format(of=envelope_of or "the design", dims=_envelope_words(envelope))
    if recheck:
        _text += _RECHECK_SECTION.format(failures=recheck)
    return _text


def _call_vision_llm(png_pages: List[bytes], model: str, brief: str = "",
                     **sheet_kw: Any) -> str:
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
    _text = concept_prompt_text(png_pages, brief, **sheet_kw)
    content: List[Dict[str, Any]] = [{"type": "text", "text": _text}]
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


def _cache_key(png_pages: List[bytes], model: str, brief: str = "", *, sheet: bool = False,
               sheet_words: str = "", recheck: str = "", envelope: Any = None,
               envelope_of: str = "") -> str:
    h = hashlib.sha256()
    for png in png_pages:
        h.update(png)
        h.update(b"\x00")
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(CONCEPT_PROMPT_VERSION.encode("utf-8"))
    if brief:
        # A CHANGED BRIEF IS A NEW QUESTION. Only a run with a brief hashes it, so every
        # brief-less read keeps the key it already has in the cache.
        h.update(b"\x00brief\x00")
        h.update(brief.encode("utf-8"))
    if sheet:
        # A SHEET READ IS A DIFFERENT QUESTION (D-415), and only a sheet read hashes it: every
        # render keeps the key, and the answer, it already has.
        h.update(b"\x00sheet\x00")
        h.update(SHEET_PROMPT_VERSION.encode("utf-8"))
        h.update(b"\x00")
        h.update(sheet_words.encode("utf-8"))
        if _envelope_words(envelope):
            h.update(b"\x00envelope\x00")
            h.update(f"{envelope_of}|{_envelope_words(envelope)}".encode("utf-8"))
    if recheck:
        h.update(b"\x00recheck\x00")
        h.update(recheck.encode("utf-8"))
    return h.hexdigest()


def read_concept(pdf_paths: List[str], *, model: Optional[str] = None,
                 refresh: bool = False, brief: str = "", sheet: bool = False,
                 recheck: str = "", envelope: Any = None,
                 envelope_of: str = "") -> Dict[str, Any]:
    """One concept read of a whole pack. Returns {'parsed', 'raw_response', 'cache_hit'}, and
    'sheet_text' for a sheet read.

    Pages are rendered exactly as the BOM vision reader renders them, and ALL of them go in
    one call — see A PAGE IS NOT A PRODUCT above. `sheet` says the pages are drawing sheets
    (design-intent GAs): their own text goes in with them under the sheet preamble (D-415).
    `recheck` is what `sheet_check` found wrong with a first answer, put back once.
    """
    import _bom_vision_reader as pathB                              # noqa: WPS433

    if model is None:
        model = os.environ.get("XAI_VISION_MODEL", "grok-4.3")
    brief = str(brief or "").strip()[:BRIEF_MAX_CHARS]
    pngs: List[bytes] = []
    for pdf in pdf_paths:
        # A BRIEF ALONE IS A PACK (D-401). A run queued from a typed brief with no drawings
        # is staged as the brief's own page (ENQUIRY_BRIEF.png beside ENQUIRY_BRIEF.txt) so
        # every stage downstream — listing, wrapping, the render gate, the runner — carries
        # it unchanged. The model is not shown a picture of its own text: that page is
        # skipped here and the brief goes as words, under a preamble that says there are
        # no images.
        if is_brief_page(pdf):
            continue
        for index in range(pathB.count_pages(str(pdf))):
            pngs.append(pathB.render_page_to_png(str(pdf), index))
    if not pngs and not brief:
        raise ConceptUnavailable("no pages could be rendered from this pack")
    recheck = str(recheck or "").strip()
    _words = sheet_text(pdf_paths) if sheet else ""
    _sheet_kw: Dict[str, Any] = (
        dict({"sheet": True, "sheet_words": _words, "recheck": recheck},
             **({"envelope": list(envelope), "envelope_of": envelope_of}
                if _envelope_words(envelope) else {})) if sheet
        else ({"recheck": recheck} if recheck else {}))
    key = _cache_key(pngs, model, brief, **_sheet_kw)
    path = _cache_dir() / (key + ".json")
    _extra = {"sheet_text": _words} if sheet else {}
    if not refresh and path.is_file():
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            raw = entry.get("raw_response", "")
            parsed = parse_concept_response(raw)
            if parsed is not None:
                return dict({"parsed": parsed, "raw_response": raw, "cache_hit": True}, **_extra)
        except (OSError, ValueError):
            pass                                     # corrupt entry → re-fetch

    # A render read calls exactly as it always has; only a sheet read or a re-ask says more.
    raw = (_call_vision_llm(pngs, model, brief, **_sheet_kw) if _sheet_kw
           else _call_vision_llm(pngs, model, brief))
    parsed = parse_concept_response(raw)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"raw_response": raw, "model": model,
                                    "prompt_version": CONCEPT_PROMPT_VERSION,
                                    "sheet_prompt_version": (SHEET_PROMPT_VERSION if sheet else ""),
                                    "pages": len(pngs)}, indent=1), encoding="utf-8")
    except OSError:
        pass                                         # a cache that cannot write is not an error
    return dict({"parsed": parsed, "raw_response": raw, "cache_hit": False}, **_extra)


# ── sighted answer → engine parts ───────────────────────────────────────────────────

# ── WHEN THE CONCEPT READ MAY NOT RUN ───────────────────────────────────────────────
#
# James Gray, 22 Sep 2026, setting the split between the two paths: "If you point the render
# assembler at a real pack, you will flatten a weldment into one 5 mm panel again. That is
# the defect we just saw." And: "Assembler / nest / routes — NO. Do not run concept-kind
# mapping over a measured DXF."
#
# The first gate was `--llm-only AND (a render pack OR no parts came out)`. The second half
# is the hole: a REAL drawing pack whose BOM read happened to come back empty — a scan the
# reader could not see, a pack with an unreadable table — would be handed to the concept
# read and sighted over. Flats, models and title blocks would sit in the folder, measured
# and ignored, while a vision model guessed at panels from a picture of the same thing.
#
# So measured CAD in the pack is an absolute refusal, whatever else is true. The concept
# read exists for a pack that has nothing to measure; a drawing pack that produced no parts
# is a READER FAILURE, and the honest output for that is the failure, not a sighted guess.
_MEASURABLE_CAD = {".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step", ".stp"}


def why_not_sightable(summary: Mapping[str, Any],
                      files: Optional[List[Any]] = None) -> Optional[str]:
    """The reason this pack must not be concept-read, or None if it may be.

    Returns a sentence, because a refusal nobody can read is a refusal nobody can act on.
    """
    if str(summary.get("source_format") or "").lower() == "dxf":
        return "this pack was read as DXF geometry — it is measured, not sighted"

    # A DXF THAT MEASURED NOTHING IS NOT MEASURED CAD (D-413). 12675-01's pack holds two DXFs
    # the content reader had already refused as drawings of parts — dimensions and a title
    # block, no flat pattern — and this gate refused the concept read for them: "measured CAD
    # is never sighted over", about files that measured nothing. The record of the refusal is
    # the merge's own, read here rather than re-derived.
    _never_measured = set()
    try:
        from costed_facts import dxf_record_code_and_evidence, dxf_record_names  # noqa: PLC0415
        dxf = summary.get("dxf_augmentation") if isinstance(summary.get("dxf_augmentation"), Mapping) else {}
        for key in ("unmatched_dxf", "skipped"):
            for it in (dxf.get(key) or []):
                code, _ev = dxf_record_code_and_evidence(it)
                if code == "drawing_export_not_a_flat":
                    _never_measured.update(n.lower() for n in dxf_record_names(it))
    except Exception:                                                  # noqa: BLE001
        _never_measured = set()

    # THE MODEL DOOR ALREADY ANSWERED (D-414). On a design-intent pack the job's SolidWorks
    # models are offered to the take-off first; where it ran and recorded why it gave nothing
    # to cost (no extract, or no body with a stock basis), the model files are not measured
    # CAD this read would be guessing over — they were asked and said nothing. Without that
    # record they still refuse, as before.
    _door = summary.get("model_takeoff_door") if isinstance(summary.get("model_takeoff_door"), Mapping) else {}
    _models_answered = bool(_door.get("ran") and str(_door.get("why_not") or "").strip())
    _MODEL_SUFFIXES = {".sldprt", ".sldasm", ".slddrw"}

    for raw in (files or []):
        # The paths are written on the box; split on either separator, as every other reader
        # of a staged path does — Path(...).name on another platform is the whole string.
        _base = re.split(r"[\\/]", str(raw or ""))[-1]
        suffix = ("." + _base.rsplit(".", 1)[-1].lower()) if "." in _base else ""
        if suffix in _MEASURABLE_CAD:
            if suffix == ".dxf" and _base.lower() in _never_measured:
                continue
            if suffix in _MODEL_SUFFIXES and _models_answered:
                continue
            return (f"the pack contains {_base} — measured CAD is never sighted over")

    writeup = summary.get("manufacturing_writeup")
    parts = (writeup or {}).get("parts") if isinstance(writeup, dict) else None
    for part in (parts or []):
        if not isinstance(part, dict):
            continue
        if part.get("flat_pattern_detected") or part.get("source_dxf_path"):
            return (f"{part.get('part_number') or 'a part'} carries a measured flat — "
                    f"measured CAD is never sighted over")
        source = str(part.get("geometry_source") or "").lower()
        if source.startswith(("dxf", "solidworks")):
            return (f"{part.get('part_number') or 'a part'} carries {source} geometry — "
                    f"measured CAD is never sighted over")
    return None


# ── THE ONLY KINDS THE MAPPER KNOWS ─────────────────────────────────────────────────
#
# James Gray, 22 Sep 2026, on the first safe-to-rerun review: "Any unexpected LLM `kind`
# falls through as fabricated and can still receive a blank, material, dimensions and route.
# The prompt constrains the model, but the mapper does not validate its output."
#
# That is exactly the two-names fault again, one level up: the prompt writes the word, the
# mapper reads it, and `kind or "fabricated"` made every word the prompt did not write —
# "assembly", "subassembly", "hardware", "electrical", a translation, a typo, a future prompt
# edit — into a made panel. A made panel gets a blank, and a blank is an instruction to nest.
# So a word this mapper does not know is not a default: it is a refusal with a name on it,
# and the line stays on the sheet carrying its count and one estimator action.
CONCEPT_KINDS = ("fabricated", "bought_in", "graphic")
UNKNOWN_KIND = "unknown"


def _concept_kind(raw: Any) -> str:
    """The model's kind word as one of CONCEPT_KINDS, or UNKNOWN_KIND.

    Punctuation and case are normalised — "Bought-In" is the prompt's own word spelled
    differently, not a different classification. Nothing else is mapped: a synonym the
    mapper guesses at ("purchased", "component") is a guess wearing a schema's clothes.
    """
    word = re.sub(r"[^a-z0-9]+", "_", str(raw or "").strip().lower()).strip("_")
    return word if word in CONCEPT_KINDS else UNKNOWN_KIND


def _positive(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _slug(text: Any, fallback: str) -> str:
    out = re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-").upper()
    return out[:24] or fallback


_PRINT_WORDS = re.compile(r"\bPRINT(?:ED|S|ING)?\b|\bGRAPHICS?\b", re.IGNORECASE)


def _with_print_lines(answer: Dict[str, Any]) -> Dict[str, Any]:
    """The answer with a print line for every panel described as printed, when none came back.

    PRINT FOLDED INTO A BOARD IS PRINT NOBODY PAYS FOR (D-365). The M&S plywood read, 14:12:
    five panels came back as "green printed plywood" and not one graphic line, so the book
    priced the board and charged nothing for the print Dave's brief asked for. The prompt now
    says print is always its own line; this is the net under it. Only when the answer has NO
    graphic line at all — so a model that did list the print is never double-counted — each
    fabricated panel whose material names print gets one print line of its own face size,
    marked as assumed, priced as a purchase and put to the estimator to confirm."""
    parts = [p for p in (answer.get("parts") or []) if isinstance(p, dict)]
    if not parts or any(_concept_kind(p.get("kind")) == "graphic" for p in parts):
        return answer
    added: List[Dict[str, Any]] = []
    for p in parts:
        if _concept_kind(p.get("kind")) != "fabricated":
            continue
        said = " ".join(str(p.get(k) or "") for k in ("sighted_material", "material_guess"))
        if not _PRINT_WORDS.search(said):
            continue
        blank = p.get("assumed_blank_mm") or {}
        panel = str(p.get("name") or "panel").strip()
        added.append({
            "name": f"PRINT — {panel}",
            "kind": "graphic",
            "sighted_material": "printed graphic",
            "material_guess": "BOUGHT_IN",
            "assumed_blank_mm": {"length": blank.get("length") or 0,
                                 "width": blank.get("width") or 0, "thickness": 0},
            "quantity": p.get("quantity") or 1,
            "quantity_basis": f"one print per printed {panel} (assumed)",
            "operations": [],
            "from_brief": [],
            "seen": str(p.get("seen") or ""),
            "why_size": f"the face of {panel}",
            "_minted_print_for": panel,
            # What the model SAW, for the flag. The guess is a material code ("PLYWOOD") and
            # joined to the sighting it read "green printed plywood PLYWOOD".
            "_panel_said": (str(p.get("sighted_material") or "").strip()
                            or str(p.get("material_guess") or "").strip()),
        })
    if not added:
        return answer
    out = dict(answer)
    out["parts"] = list(answer.get("parts") or []) + added
    return out


def _with_implied_fittings(answer: Dict[str, Any]) -> Dict[str, Any]:
    """The answer with the fittings its sighted parts cannot work without, when none came back.

    A LID NOTHING HOLDS ON (D-368). The M&S plywood read of 30 Sep, 17:30, returned a LID
    PANEL and no hinge, so the unit was costed without one. The prompt already says a lid
    that lifts has a hinge; this is the net under it, driven by config.CONCEPT_IMPLIED_FITTINGS
    so the rule and its count are the estimators' to change. A fitting is added only when no
    bought-in line already names it, so a model that listed the hinge is never charged twice."""
    try:
        import config                                               # noqa: WPS433
        rules = tuple(getattr(config, "CONCEPT_IMPLIED_FITTINGS", ()) or ())
    except Exception:                                               # noqa: BLE001
        rules = ()
    parts = [p for p in (answer.get("parts") or []) if isinstance(p, dict)]
    if not parts or not rules:
        return answer
    bought = " ".join(f"{p.get('name') or ''} {p.get('sighted_material') or ''}"
                      for p in parts if _concept_kind(p.get("kind")) != "fabricated")
    added: List[Dict[str, Any]] = []
    for rule in rules:
        try:
            part_re = re.compile(rule["part_words"], re.IGNORECASE)
            fitting_re = re.compile(rule["fitting_words"], re.IGNORECASE)
            per_part = float(rule.get("per_part") or 1)
        except Exception:                                           # noqa: BLE001
            continue
        if fitting_re.search(bought):
            continue
        movers = [p for p in parts if _concept_kind(p.get("kind")) == "fabricated"
                  and part_re.search(str(p.get("name") or ""))]
        if not movers:
            continue
        qty = sum(per_part * float(p.get("quantity") or 1) for p in movers)
        names = ", ".join(str(p.get("name") or "part").strip() for p in movers)
        added.append({
            "name": str(rule.get("fitting") or "FITTING"),
            "kind": "bought_in",
            "sighted_material": str(rule.get("description") or rule.get("fitting") or ""),
            "material_guess": "",
            "assumed_blank_mm": {"length": 0, "width": 0, "thickness": 0},
            "quantity": int(qty) if float(qty).is_integer() else qty,
            "quantity_basis": f"{per_part:g} per {names} (assumed)",
            "operations": [],
            "from_brief": [],
            "seen": "not listed by the read; implied by " + names,
            "why_size": "bought-in, no blank",
            "_minted_fitting_for": names,
            "_fitting_per_part": per_part,
        })
    if not added:
        return answer
    out = dict(answer)
    out["parts"] = list(answer.get("parts") or []) + added
    return out


# ── THE SIGHTED BILL, HELD AGAINST WHAT THE SHEET STATES (D-415) ──────────────────────────
#
# Nothing after the 12675-01 answer checked it. A 1580 mm post on a 1250 mm body and about
# 15 kg of steel on a sheet whose stand weighs 37 kg were both costed, because the only thing
# the read was compared with was itself. The sheet states its body, its gauge and its weight;
# a bill made from it can be weighed and measured against those, deterministically, before a
# penny rests on it. The model's own "sheet_facts" give the figures, and a figure is used only
# where it is printed on the sheet's text layer — a number the model says the sheet states
# and the sheet does not print is not a fact to check against.

def _figures_in(words: str) -> set:
    """Every number printed in the sheet's text, as floats."""
    out = set()
    for tok in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", str(words or "")):
        try:
            out.add(round(float(tok), 3))
        except ValueError:
            continue
    return out


def _num(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if f > 0 else 0.0


def _density(material: Any) -> float:
    """kg/m³ for a sighted material from config's density table, or 0 where it names none."""
    try:
        import config                                               # noqa: WPS433
        table = dict(getattr(config, "MATERIAL_DENSITY_KG_PER_M3", {}) or {})
    except Exception:                                               # noqa: BLE001
        table = {}
    said = str(material or "").upper()
    for form in (said, said.replace("_", " ")):
        for name in sorted(table, key=len, reverse=True):
            if name and name.upper() in form:
                return float(table[name])
    return 0.0


def _vocab(name: str, default: Any) -> Any:
    try:
        import config                                               # noqa: WPS433
        return getattr(config, name, default)
    except Exception:                                               # noqa: BLE001
        return default


def _singular(word: str) -> str:
    """A word in the one form the label check compares in (config's irregulars, then -S)."""
    w = str(word or "").upper()
    forms = dict(_vocab("CONCEPT_COMPONENT_WORD_FORMS", {}) or {})
    if w in forms:
        return str(forms[w]).upper()
    if len(w) > 3 and w.endswith("S") and not w.endswith("SS"):
        return w[:-1]
    return w


def _words_of(text: Any) -> set:
    return {_singular(w) for w in re.findall(r"[A-Za-z]+", str(text or ""))}


def _finish_operations() -> List[tuple]:
    return [tuple(x) for x in (_vocab("CONCEPT_FINISH_OPERATIONS", ()) or ())]


def sheet_labels(words: str, facts: Optional[Mapping[str, Any]] = None) -> List[Dict[str, str]]:
    """The components the sheet labels, each with the head word a bill line must carry (D-417).

    Two sources, both printed on the sheet: a short callout (a few words on a line of their
    own) naming a component from config.CONCEPT_COMPONENT_WORDS, found without the model; and
    a label the read lists in sheet_facts["labelled_parts"], kept only where the sheet prints
    it. A label naming the goods the product holds is never a component."""
    components = {_singular(w) for w in (_vocab("CONCEPT_COMPONENT_WORDS", ()) or ())}
    max_words = int(_vocab("CONCEPT_LABEL_MAX_WORDS", 4) or 4)
    facts = facts or {}
    goods_words = _words_of(facts.get("goods"))
    out: List[Dict[str, str]] = []
    seen = set()

    def _add(label: str, head: str) -> None:
        if head and head not in goods_words and head not in seen:
            seen.add(head)
            out.append({"label": label, "head": head})

    for line in str(words or "").splitlines():
        line = " ".join(line.split())
        tokens = re.findall(r"[A-Za-z]+", line)
        if not tokens or len(line.split()) > max_words or re.search(r"\d+\s*[xX×]\s", line):
            continue
        heads = [_singular(t) for t in tokens if _singular(t) in components]
        if heads:
            _add(line, heads[-1])
    flat = " ".join(str(words or "").split()).lower()
    for raw in (facts.get("labelled_parts") or []):
        label = " ".join(str(raw or "").split())
        if not label or (flat and label.lower() not in flat):
            continue
        tokens = [_singular(t) for t in re.findall(r"[A-Za-z]+", label)]
        heads = [t for t in tokens if t in components] or tokens[-1:]
        if heads:
            _add(label, heads[-1])
    return out


def sheet_check(answer: Mapping[str, Any], words: str = "",
                envelope: Any = None) -> Dict[str, Any]:
    """The sighted bill against the sheet's stated body, goods and weight.

    Returns {'checked', 'agrees', 'failures', 'body_mm', 'body_used_mm', 'body_source',
    'stated_weight_kg', 'goods_weight_kg', 'net_weight_kg', 'sighted_weight_kg', 'ratio',
    'breaches', 'goods_spent', 'unweighed', 'not_on_sheet'}. 'checked' is False where the sheet
    gave nothing to check against; then nothing failed and nothing agreed, and the book says so
    rather than calling an unchecked bill sound.

    THE BODY IS THE MODEL'S WHERE THE MODEL GAVE ONE (D-416): one undetailed block's envelope is
    measured; the read's own body figures are used only where there is none, and only where
    the sheet prints them. THE GOODS' NUMBERS ARE NOT THE STEEL'S: a made part that takes the
    goods' count as its quantity, or a goods dimension or a dimension to the top of the goods
    as its size, is the 12:05 misreading and fails, whatever else it agrees with."""
    try:
        import config                                               # noqa: WPS433
        lo, hi = tuple(getattr(config, "CONCEPT_SHEET_WEIGHT_BAND", (0.6, 2.0)))
        tol = float(getattr(config, "CONCEPT_SHEET_ENVELOPE_TOLERANCE_MM", 5.0))
    except Exception:                                               # noqa: BLE001
        lo, hi, tol = 0.6, 2.0, 5.0
    facts = answer.get("sheet_facts") if isinstance(answer.get("sheet_facts"), Mapping) else {}
    printed = _figures_in(words)
    not_on_sheet: List[str] = []

    def _stated(label: str, value: Any) -> float:
        v = _num(value)
        if v and printed and round(v, 3) not in printed:
            not_on_sheet.append(f"{label} {v:g}")
            return 0.0
        return v

    body = {k: _stated(f"body {k}", (facts.get("body_mm") or {}).get(k)
                       if isinstance(facts.get("body_mm"), Mapping) else 0)
            for k in ("height", "width", "depth")}
    dims = sorted((v for v in body.values() if v), reverse=True)
    body_source = "the sheet"
    _env = sorted((d for d in (_num(v) for v in (envelope or [])) if d), reverse=True)
    if len(_env) >= 2:
        dims, body_source = _env, "the SolidWorks model's envelope"
    parts = [p for p in (answer.get("parts") or []) if isinstance(p, Mapping)]
    made = [p for p in parts if _concept_kind(p.get("kind")) == "fabricated"]

    failures: List[str] = []
    breaches: List[Dict[str, Any]] = []
    body_checked = len(dims) >= 2 and bool(made)
    if body_checked:
        _body_words = " × ".join(f"{d:g}" for d in dims)
        for p in made:
            blank = p.get("assumed_blank_mm") if isinstance(p.get("assumed_blank_mm"), Mapping) else {}
            size = sorted((_num(blank.get("length")), _num(blank.get("width"))), reverse=True)
            if not size[0]:
                continue
            ops = {str(o or "").strip().lower().replace(" ", "_") for o in (p.get("operations") or [])}
            if "folding" in ops:
                continue                     # a folded part's blank is its unfolded shape
            if size[0] > dims[0] + tol or (size[1] and size[1] > dims[1] + tol):
                name = str(p.get("name") or "a part").strip()
                breaches.append({"part": name, "size_mm": [size[0], size[1]], "body_mm": dims})
                failures.append(
                    f"{name} is sized {size[0]:g} × {size[1]:g} mm, larger than the product body "
                    f"({_body_words} mm, from {body_source}), and it is not folded")

    # THE GOODS' NUMBERS SPENT ON THE STEEL (D-416). Only figures the sheet prints, and never a
    # figure that is also the body's own: a panel the body's size is the body's panel.
    _body_set = {round(d, 1) for d in dims}
    goods_count = _stated("goods count", facts.get("goods_count"))
    goods_dims = [g for g in (_stated("goods dimension", v)
                              for v in (facts.get("goods_dimensions_mm") or [])
                              if not isinstance(v, (dict, list))) if g and round(g, 1) not in _body_set]
    to_goods = [g for g in (_stated("dimension to the goods", v)
                            for v in (facts.get("dimensions_to_goods_mm") or [])
                            if not isinstance(v, (dict, list))) if g and round(g, 1) not in _body_set]
    goods_spent: List[Dict[str, Any]] = []
    _goods_words = str(facts.get("goods") or "the goods").strip()
    goods_checked = bool(made) and bool(goods_count > 1 or goods_dims or to_goods)
    for p in made:
        name = str(p.get("name") or "a part").strip()
        blank = p.get("assumed_blank_mm") if isinstance(p.get("assumed_blank_mm"), Mapping) else {}
        size = [x for x in (_num(blank.get("length")), _num(blank.get("width"))) if x]
        qty = _num(p.get("quantity"))
        if (goods_count > 1 and qty == goods_count
                and "one per" not in str(p.get("quantity_basis") or "").lower()):
            goods_spent.append({"part": name, "took": "count", "value": qty})
            failures.append(f"{name} x{qty:g} takes the goods' count as its quantity "
                            f"({_goods_words}) — goods are not parts")
        for label, pool in (("a dimension of the goods", goods_dims),
                            ("a dimension to the top of the goods", to_goods)):
            hit = next((g for g in pool for x in size if abs(x - g) <= 1.0), None)
            if hit is not None:
                goods_spent.append({"part": name, "took": label, "value": hit})
                failures.append(f"{name} is sized off {label} ({hit:g} mm) — "
                                f"the goods' size is not the steel's")

    # ── THE WEIGHT, UNDER EVERY READING THE SHEET ALLOWS (D-417) ─────────────────────────
    # The goods' weight is count × unit weight where the sheet prints both; a total the read
    # worked out for itself counts only where the sheet prints it too. Where the sheet does not
    # say whether its weight includes the goods, the bill is weighed against both readings:
    # too light under both, or too heavy under both, fails; fitting only one is UNVERIFIED —
    # the case a single reading let pass as "agrees".
    stated = _stated("stated weight", facts.get("stated_weight_kg"))
    unit_w = _stated("goods unit weight", facts.get("goods_unit_weight_kg"))
    goods = (goods_count * unit_w if (goods_count and unit_w)
             else _stated("goods weight", facts.get("goods_weight_kg")))
    includes = str(facts.get("weight_includes_goods") or "").strip().lower()
    _yes = bool(re.match(r"(yes|true|includes?)\b", includes))
    _no = bool(re.match(r"(no|false|excludes?)\b", includes))
    _less_goods = stated - goods if (stated and 0 < goods < stated) else 0.0
    if _yes:
        readings = [_less_goods] if _less_goods else []
    elif _no:
        readings = [stated] if stated else []
    else:
        readings = ([stated] if stated else []) + ([_less_goods] if _less_goods else [])
    # The light side can be tested only where every reading the sheet allows is known.
    light_testable = bool(readings) and (_no or bool(_less_goods))

    sighted, unweighed = 0.0, []
    for p in made:
        blank = p.get("assumed_blank_mm") if isinstance(p.get("assumed_blank_mm"), Mapping) else {}
        l, w, t = (_num(blank.get(k)) for k in ("length", "width", "thickness"))
        rho = _density(p.get("material_guess")) or _density(facts.get("material"))
        if not (l and w and t and rho):
            unweighed.append(str(p.get("name") or "a part").strip())
            continue
        qty = _num(p.get("quantity")) or 1.0
        sighted += l * w * t * 1e-9 * rho * qty
    weight_checked = bool(stated) and sighted > 0
    unverified: List[str] = []
    net = readings[0] if len(readings) == 1 else 0.0
    ratio = (sighted / min(readings)) if (weight_checked and readings) else None
    if weight_checked:
        _goods = str(facts.get("goods") or "").strip()

        def _of(reading: float) -> str:
            return (f"{stated:g} kg stated, less {goods:g} kg of {_goods or 'goods'}"
                    if reading != stated else f"{stated:g} kg stated")

        too_light = light_testable and not unweighed and all(sighted < lo * r for r in readings)
        too_heavy = all(sighted > hi * r for r in (readings or [stated]))
        if too_light:
            r = max(readings)
            failures.append(
                f"the made parts weigh about {sighted:.1f} kg as sized, against "
                f"{r:.1f} kg of product on the sheet ({_of(r)}) — {sighted / r:.0%} of it, so "
                f"parts are missing or undersized")
        elif too_heavy:
            r = min(readings or [stated])
            failures.append(
                f"the made parts weigh about {sighted:.1f} kg as sized, against "
                f"{r:.1f} kg of product on the sheet ({_of(r)}) — {sighted / r:.0%} of it, so "
                f"parts are oversized or counted twice")
        elif len(readings) == 2 and not unweighed:
            fits = [r for r in readings if lo * r <= sighted <= hi * r]
            if len(fits) == 1:
                unverified.append(
                    f"the bill weighs about {sighted:.1f} kg and fits the sheet's "
                    f"{stated:g} kg only if that weight {'excludes' if fits[0] == stated else 'includes'} "
                    f"the goods, and the sheet does not say which")
        if not light_testable:
            unverified.append(
                "the sheet does not settle how much of its stated weight is the goods, so a bill "
                "too light could not be caught")
    elif not stated:
        unverified.append("the sheet states no weight to weigh the bill against")
    if unweighed:
        unverified.append(f"{len(unweighed)} made part(s) could not be weighed "
                          f"({', '.join(unweighed[:4])}) — no size, gauge or material")

    # ── WHAT THE SHEET LABELS IS ON THE BILL (D-417) ──────────────────────────────────────
    # A short callout naming a component (config.CONCEPT_COMPONENT_WORDS) is a part the
    # product has; so is a label the read lists that the sheet prints. Each must be a line.
    required = sheet_labels(words, facts)
    _held = {}
    for p in parts:
        _held_words = _words_of(f"{p.get('name') or ''} {p.get('drawn') or ''}")
        for w in _held_words:
            _held.setdefault(w, str(p.get("name") or "").strip())
    labels_missing = [lab for lab in required if lab["head"] not in _held]
    for lab in labels_missing:
        failures.append(f"the sheet labels '{lab['label']}' and the bill has no part for it")

    # ── THE STATED GAUGE AND FINISH ARE ON THE BILL (D-417) ───────────────────────────────
    _mat = str(facts.get("material") or "").strip()
    _mat_printed = bool(_mat) and any(w.lower() in str(words or "").lower()
                                      for w in re.findall(r"[A-Za-z]{4,}", _mat)) if words else bool(_mat)
    gauge = _stated("thickness", facts.get("thickness_mm"))
    _family = _density(_mat) if _mat_printed else 0.0
    gauge_checked = bool(gauge and _family and made)
    if gauge_checked:
        for p in made:
            blank = p.get("assumed_blank_mm") if isinstance(p.get("assumed_blank_mm"), Mapping) else {}
            t = _num(blank.get("thickness"))
            if t and _density(p.get("material_guess") or _mat) == _family and abs(t - gauge) > 0.05:
                failures.append(f"{str(p.get('name') or 'a part').strip()} is {t:g} mm, and the "
                                f"sheet states {gauge:g} mm {_mat.lower()}")
    _finish = str(facts.get("finish") or "").strip()
    _finish_printed = bool(_finish) and (not words or any(
        w.lower() in str(words).lower() for w in re.findall(r"[A-Za-z]{4,}", _finish)))
    finish_checked = False
    if _finish_printed and made:
        _ops_held = {str(o or "").strip().lower().replace(" ", "_")
                     for p in parts for o in (p.get("operations") or [])}
        _ops_held |= {str(o or "").strip().lower().replace(" ", "_")
                      for o in (answer.get("unit_operations") or [])}
        for pattern, op in _finish_operations():
            if re.search(pattern, _finish, re.IGNORECASE):
                finish_checked = True
                if op not in _ops_held:
                    failures.append(f"the sheet states '{_finish}' and nothing in the bill "
                                    f"carries {op.replace('_', ' ')}")

    # ── THE GOODS NAMED, THEIR SIZES NOT GIVEN (D-418) ────────────────────────────────────
    # The 14:42 read sized the divider 186 mm — the bag's 186.5 — and reported no goods
    # dimensions, so the goods check had nothing to hold it to. A read that names goods and
    # gives none of their sizes leaves that check blind, and the bill cannot be called checked.
    if made and (goods_count > 1 or str(facts.get("goods") or "").strip()) \
            and not (facts.get("goods_dimensions_mm") or facts.get("dimensions_to_goods_mm")):
        unverified.append("the read names the goods but gives none of their dimensions, so a part "
                          "sized off the goods could not be caught")

    # ── EVERY SIZE IS THE BODY'S OR THE SHEET'S (D-418) ───────────────────────────────────
    # A made part's length and width are a body dimension (or one less a few gauges, for a part
    # inside the walls), or a figure the sheet prints. A size that is neither is the read's own
    # arithmetic — "600 overall less two sides and bag stack spacing" gave the divider 186 —
    # and is unverified, named, for the estimator.
    if body_checked:
        _g = gauge or 0.0
        _bodyish = set()
        for d in dims:
            for k in range(0, 5):
                for t in ({_g} if _g else {0.0}):
                    _bodyish.add(round(d - k * t, 1))
        _odd: List[str] = []
        for p in made:
            blank = p.get("assumed_blank_mm") if isinstance(p.get("assumed_blank_mm"), Mapping) else {}
            for x in (_num(blank.get("length")), _num(blank.get("width"))):
                if not x:
                    continue
                if any(abs(x - b) <= 1.0 for b in _bodyish):
                    continue
                if printed and round(x, 3) in printed:
                    continue
                if not printed and not words:
                    continue
                _odd.append(f"{str(p.get('name') or 'a part').strip()} {x:g} mm")
        if _odd:
            unverified.append("sized from neither the body nor a figure printed on the sheet: "
                              + ", ".join(_odd[:6]))

    # ── THE BODY IS VERIFIED ONLY WHERE SOMETHING INDEPENDENT GAVE IT (D-417) ─────────────
    if body_checked and body_source != "the SolidWorks model's envelope":
        _raw_to_goods = {round(_num(v), 1) for v in (facts.get("dimensions_to_goods_mm") or [])
                         if not isinstance(v, (dict, list)) and _num(v)}
        _both = [d for d in dims if round(d, 1) in _raw_to_goods]
        for d in _both:
            failures.append(f"the read gives {d:g} mm as the product body and as a dimension to "
                            f"the top of the goods")
        unverified.append("the body size is the read's own figures — printed on the sheet, but "
                          "nothing independent says they are the body and not a dimension over "
                          "the goods")
    elif not body_checked and made:
        unverified.append("no body size to hold the parts to")

    checked = body_checked or weight_checked or goods_checked or bool(required) \
        or gauge_checked or finish_checked
    verdict = ("disagrees" if failures else "unchecked" if not checked
               else "unverified" if unverified else "agrees")
    return {"checked": checked, "agrees": verdict == "agrees", "verdict": verdict,
            "failures": failures, "unverified": unverified if not failures else unverified,
            "body_mm": body, "body_used_mm": dims if body_checked else [],
            "body_source": body_source if body_checked else "",
            "goods_spent": goods_spent,
            "goods_checked_clean": goods_checked and not goods_spent,
            "labels_required": [lab["label"] for lab in required],
            "labels_missing": [lab["label"] for lab in labels_missing],
            "gauge_checked": gauge_checked, "finish_checked": finish_checked,
            "stated_weight_kg": stated or None,
            "goods_weight_kg": goods or None, "net_weight_kg": net or None,
            "weight_readings_kg": [round(r, 2) for r in readings],
            "sighted_weight_kg": round(sighted, 2) if sighted else None,
            "ratio": round(ratio, 3) if ratio is not None else None,
            "breaches": breaches, "unweighed": unweighed, "not_on_sheet": not_on_sheet}


def sheet_check_sentence(check: Mapping[str, Any]) -> str:
    """One line for the run, the flags and the report: did the bill agree with the sheet?"""
    if not isinstance(check, Mapping) or not check:
        return ""
    again = (" (after a second read put back with what broke)"
             if check.get("second_read_taken") else
             " (a second read, put back with what broke, did no better)"
             if check.get("rechecked") else "")
    if not check.get("checked"):
        return ("CONCEPT BILL NOT CHECKED AGAINST THE SHEET: the sheet states no body size or "
                "weight the bill could be held against — every size is the read's own.")
    if check.get("failures"):
        return ("CONCEPT BILL DOES NOT AGREE WITH THE SHEET" + again + ": "
                + "; ".join(check["failures"])
                + ". Costed as sighted — an unchecked concept figure to walk against the GA, "
                  "not a checked budget and not a price.")
    if check.get("verdict") == "unverified" or check.get("unverified"):
        # NOTHING CONTRADICTS IT IS NOT THE SAME AS IT AGREES (D-417).
        return ("CONCEPT BILL UNVERIFIED AGAINST THE SHEET" + again + ": nothing in it "
                "contradicts the sheet, but " + "; ".join(check.get("unverified") or [])
                + ". An unchecked concept figure — walk the bill against the GA before "
                  "anyone relies on it.")
    said = []
    if check.get("sighted_weight_kg") and check.get("net_weight_kg"):
        said.append(f"the made parts weigh about {check['sighted_weight_kg']:g} kg as sized "
                    f"against {check['net_weight_kg']:g} kg of product on the sheet")
    if check.get("body_used_mm"):
        said.append(f"every flat part fits the body "
                    f"({' × '.join(f'{d:g}' for d in check['body_used_mm'])} mm, from "
                    f"{check.get('body_source') or 'the sheet'})")
    elif [v for v in (check.get("body_mm") or {}).values() if v]:
        said.append("every flat part fits the body the sheet dimensions")
    if check.get("goods_checked_clean"):
        said.append("no part takes the goods' count or size")
    if check.get("labels_required"):
        said.append("every component the sheet labels is on the bill ("
                    + ", ".join(check["labels_required"]) + ")")
    if check.get("gauge_checked"):
        said.append("every part of the stated material is at the stated gauge")
    if check.get("finish_checked"):
        said.append("the stated finish is on the route")
    return ("CONCEPT BILL CHECKED AGAINST THE SHEET" + again + ": " + "; ".join(said)
            + ". Still a concept budget: nothing was measured.")


def recheck_text(check: Mapping[str, Any]) -> str:
    """What broke, as the list the second read is given."""
    return "\n".join(f"- {f}" for f in (check.get("failures") or []))


def _check_rank(check: Mapping[str, Any]) -> tuple:
    """Lower is better: fewer failures, agreeing, fewer things unverified, then a weight nearer
    the sheet's."""
    ratio = check.get("ratio")
    return (len(check.get("failures") or []), 0 if check.get("agrees") else 1,
            len(check.get("unverified") or []), abs(1.0 - float(ratio)) if ratio else 9.0)


def set_aside_undrawn(answer: Dict[str, Any]) -> tuple:
    """(answer, set aside): a bought-in line the sheet does not draw is not costed (D-415).

    Only where the read answered the sheet's schema — a part with no "drawn" key at all says
    nothing either way, and nothing is dropped on silence. What is set aside goes to the
    estimator as a question, with its count; it is never priced as if drawn."""
    parts = [p for p in (answer.get("parts") or []) if isinstance(p, dict)]
    if not any("drawn" in p for p in parts):
        return answer, []
    kept, aside = [], []
    for p in parts:
        if (_concept_kind(p.get("kind")) == "bought_in" and "drawn" in p
                and not str(p.get("drawn") or "").strip()):
            aside.append({"name": str(p.get("name") or "a fitting").strip(),
                          "quantity": p.get("quantity"),
                          "sighted_material": str(p.get("sighted_material") or "")})
            continue
        kept.append(p)
    if not aside:
        return answer, []
    out = dict(answer)
    out["parts"] = kept
    return out, aside


def read_sheet_concept(pdf_paths: List[str], *, refresh: bool = False,
                       brief: str = "", model: Optional[str] = None, envelope: Any = None,
                       envelope_of: str = "") -> Dict[str, Any]:
    """A concept read of drawing sheets: read, held against the sheet, put back once with what
    broke, and the undrawn fittings set aside. Returns {'read', 'answer', 'check', 'set_aside'}.

    THE BETTER OF TWO, NEVER A THIRD. The second read is taken only where it agrees with the
    sheet more closely than the first; a bill that still does not agree is costed as sighted
    and the book says so — a concept budget to walk against the sheet, not a price."""
    _env = {"envelope": list(envelope or []), "envelope_of": envelope_of}
    read = read_concept(pdf_paths, model=model, refresh=refresh, brief=brief, sheet=True, **_env)
    answer = read.get("parsed") or {}
    words = str(read.get("sheet_text") or "")
    check = sheet_check(answer, words, envelope=envelope)
    if check.get("failures"):
        first = list(check["failures"])
        again = read_concept(pdf_paths, model=model, refresh=refresh, brief=brief, sheet=True,
                             recheck=recheck_text(check), **_env)
        answer2 = again.get("parsed") or {}
        taken = False
        if answer2.get("parts"):
            check2 = sheet_check(answer2, words, envelope=envelope)
            if _check_rank(check2) < _check_rank(check):
                read, answer, check, taken = again, answer2, check2, True
        check["rechecked"] = True
        check["second_read_taken"] = taken
        check["first_read_failures"] = first
    answer, aside = set_aside_undrawn(answer)
    check["sheet_text_chars"] = len(words)
    return {"read": read, "answer": answer, "check": check, "set_aside": aside}


def apply_sheet_notes_to_unit(unit: Optional[Dict[str, Any]],
                              facts_by_sheet: Mapping[str, Mapping[str, Any]]) -> bool:
    """The design sheet's own weld note, stated on the unit it describes (D-418).

    The 14:42 book asked "Welding on 12675-01-CPT00 is inferred, not drawn" beside a sheet that
    prints WELDED AND FINISHED FLUSH. The note reader (weld_symbols.apply_sheet_weld_notes,
    D-397) keys a sheet's notes on the part its title block names — 12675-01-GA — and the unit
    the concept read minted is 12675-01-CPT00, so the note never reached it. The sheet read IS
    the unit's own sheet: its notes (legend already removed) are given to the unit under the
    unit's number, and the same reader decides. Returns True when a weld was stated."""
    if not isinstance(unit, dict) or not facts_by_sheet:
        return False
    try:
        from weld_symbols import _clean_pn, apply_sheet_weld_notes   # noqa: WPS433
    except Exception:                                               # noqa: BLE001
        return False
    merged = {"notes": " ".join(str((f or {}).get("notes") or "") for f in facts_by_sheet.values()),
              "text": "\n".join(str((f or {}).get("text") or "") for f in facts_by_sheet.values())}
    return bool(apply_sheet_weld_notes([unit], {_clean_pn(unit.get("part_number")): merged}))


def raise_sheet_questions(parts: List[Dict[str, Any]], check: Mapping[str, Any],
                          set_aside: List[Mapping[str, Any]]) -> int:
    """What the sheet check could not settle, as manufacturing questions on the unit (D-415).

    On the unit assembly where there is one, else the first part: the channel costed_facts
    already counts, so the book is provisional while they are open and no money moves on
    their account."""
    if not parts:
        return 0
    from source_precedence import raise_manufacturing_question     # noqa: WPS433
    host = next((p for p in parts if p.get("concept_kind") == "assembly"), parts[0])
    n = 0
    if check.get("failures"):
        n += raise_manufacturing_question(
            host,
            "The sighted bill does not agree with the sheet: " + "; ".join(check["failures"]),
            "costed as sighted — a concept budget, not an estimate",
            "Walk the bill against the GA sheet and correct the sizes and counts in the answers "
            "file, or have the design detailed with a parts list",
            "concept_sheet_check")
    elif check.get("unverified"):
        # UNVERIFIED IS ASKED TOO (D-417): nothing contradicts the sheet, but nothing confirmed
        # it either, and an estimator must decide that, not the banner.
        n += raise_manufacturing_question(
            host,
            "The sighted bill could not be verified against the sheet: "
            + "; ".join(check["unverified"]),
            "costed as read — an unchecked concept figure, not a checked budget",
            "Walk the bill against the GA sheet and confirm or correct the sizes, counts and "
            "gauge in the answers file",
            "concept_sheet_check")
    for item in (set_aside or []):
        qty = item.get("quantity")
        n += raise_manufacturing_question(
            host,
            f"{item.get('name')}{f' x{qty}' if qty else ''} was listed by the read but the sheet "
            f"does not draw or label it",
            "not costed",
            "Confirm whether the unit has it; if it does, add it as a bought-in line",
            "concept_sheet_check")
    return n


def parts_from_concept(answer: Dict[str, Any], stem: str, *,
                       sheet: bool = False) -> List[Dict[str, Any]]:
    """The sighted parts as engine part records, every field attributed at concept rank.

    Written through apply_field so the stamps are the arbitration machinery's own, not a
    hand-rolled imitation of them — and so length, width and thickness share one recorded
    source, which is what lets flat_blank_mm treat the pair as ONE reading (D-152).

    `sheet`: the pages are drawing sheets (D-415). A fitting the sheet does not draw is not
    minted by the implied-fittings net; it is asked on the part that implies it.
    """
    from document_builder import _empty_part_record                 # noqa: WPS433
    from source_precedence import apply_field                       # noqa: WPS433

    parts: List[Dict[str, Any]] = []
    answer = _with_print_lines(answer)
    _implied: List[Dict[str, Any]] = []
    if sheet:
        _before = len(answer.get("parts") or [])
        _netted = _with_implied_fittings(answer)
        _implied = [p for p in (_netted.get("parts") or [])[_before:] if isinstance(p, dict)]
    else:
        answer = _with_implied_fittings(answer)
    for n, sighted in enumerate(answer.get("parts") or [], start=1):
        if not isinstance(sighted, dict):
            continue
        name = str(sighted.get("name") or f"part {n}").strip()
        kind = _concept_kind(sighted.get("kind"))
        unclassified = kind == UNKNOWN_KIND
        # ── EVERY GUESS, LISTED WHERE SOMEBODY CAN CONFIRM IT ───────────────────────
        #
        # James Gray, 22 Sep 2026: "The concept path still turns a render's guessed MDF,
        # 5 mm thickness, dimensions and operations into normal pricing inputs... It is
        # acceptable only as a clearly editable concept budget, with each assumption
        # available to confirm — not as a technical estimate reconstructed from a PNG."
        #
        # The provenance was already right — every field is stamped `vision_concept` and
        # says which cue it was scaled from — but provenance is a thing you find by opening
        # a record and asking. An estimator needs the opposite: ONE list of what was
        # assumed, with the answer sheet already written. So each figure this mapper puts
        # into pricing is also recorded here, in the file keys the confirmations door reads,
        # and `write_assumptions_file` turns the list into a file a person edits.
        assumed: List[Dict[str, Any]] = []

        def _assume(file_key: str, value: Any, cue: str, field: str = "") -> None:
            # `file_key` is the answers-file key that confirms this, and is empty for the
            # things that file does not take — a route, an edging basis. `field` is what
            # the assumption is CALLED on the report, which is not always the same word.
            assumed.append({"file_key": file_key, "value": value, "cue": cue,
                            "field": field or file_key or "operations"})

        # ── A PART NUMBER IS A CODE, AND A CODE HAS NO SPACE IN IT ─────────────────
        #
        # James Gray, 22 Sep 2026: "The four board panels are charged correctly on the
        # workbook's nested-sheet rows (£31.91 total), but the report and Provenance tab
        # show each as £0 and call the £31.91 an unexplained residual. That is a generic
        # line-to-workbook mapping failure, not an estimating gap."
        #
        # It was this line. The number was minted as `<CODE> <NAME-SLUG>` — two words — and
        # `costed_facts._material_row_key` joins a nested block row on THE FIRST WORD of its
        # description, because that is where wb_populate writes the part number. So the
        # Other Sheet Material row keyed on `…-C01` while the part looked itself up as
        # `…-C01 HEADER-PANEL`: two keys for one part, the money under one and the line
        # reading the other as £0, with the difference falling out as an unexplained
        # residual on every surface that adds the lines back up.
        #
        # The name was never needed in the code — it is the DESCRIPTION, which sits in the
        # next column and was already carrying it. Every concept job would have hit this.
        record = _empty_part_record(
            f"{_slug(stem, 'CONCEPT')}-CPT{n:02d}",
            item_number=n, description=name, quantity=None)
        record["concept"] = True
        # WHICH KIND OF LINE THIS IS, on the record rather than inferred from its material.
        # A fabricated panel must carry work or it is a part nobody can price; a bought-in
        # castor and an applied graphic correctly carry none, and the difference has to be
        # readable without guessing from a material string.
        record["concept_kind"] = kind
        record["page_roles"] = ["render"]
        record["concept_seen"] = str(sighted.get("seen") or "")
        if unclassified:
            # Everything the model said about this line, kept as words for the estimator and
            # kept OUT of every field that prices. The line is not dropped — a thing the
            # model could see is a thing the unit contains — it is unpriced until classified.
            record["concept_unclassified"] = {
                "kind_returned": str(sighted.get("kind") or ""),
                "sighted_material": str(sighted.get("sighted_material") or ""),
                "material_guess": str(sighted.get("material_guess") or ""),
                "assumed_blank_mm": sighted.get("assumed_blank_mm") or {},
                "operations": [str(o) for o in (sighted.get("operations") or [])],
            }
            record["review_flags"].append(
                "CONCEPT: this line came back as "
                f"'{str(sighted.get('kind') or '(none)')}', which is not a kind this "
                "estimate knows — classify it as fabricated, bought-in or graphic; until "
                "then it carries no material, no size and no route")

        qty = sighted.get("quantity")
        basis = str(sighted.get("quantity_basis") or "sighted on the render")
        try:
            qty = max(1, int(qty))
        except (TypeError, ValueError):
            qty = 1
            basis = "assumed — the render does not show a count"
        _qsrc = BRIEF_SOURCE if _from_brief(sighted, "quantity") else SOURCE
        apply_field(record, "quantity", qty, _qsrc, note=basis)
        _assume("quantity", qty, basis)

        sighted_mat = str(sighted.get("sighted_material") or "").strip()
        guess = str(sighted.get("material_guess") or "").strip().upper()
        if kind == "bought_in" and not guess:
            # A sourcing fact, not a zero — the bought-in price chain starts here (D-153).
            guess = "BOUGHT_IN"
        if unclassified:
            # A material on a line nobody has classified prices a guess at a guess.
            guess, sighted_mat = "", ""
        if guess:
            _why_mat = (f"sighted as '{sighted_mat}' on the render" if sighted_mat
                        else "sighted on the render")
            _msrc = BRIEF_SOURCE if _from_brief(sighted, "material") else SOURCE
            if _msrc == BRIEF_SOURCE:
                _why_mat = "stated in the enquiry brief"
            apply_field(record, "normalized_material", guess, _msrc, note=_why_mat)
            _assume("material", guess, _why_mat)
        if sighted_mat:
            record["materials"].append(sighted_mat)

        # ── A BOUGHT-IN LINE IS NEVER NESTED, WHATEVER SIZE THE MODEL GIVES IT ──────
        #
        # James Gray, 22 Sep 2026: "Never nest a caster." The first run did exactly that —
        # CASTORS came back with a 75×75 envelope, the assembler wrote it as a blank, and
        # the nest block worked out 338 castors per 2500×1250 sheet. A castor is not cut
        # from anything: it is bought, each, and it prices off a catalogue or an evidenced
        # research figure. The same is true of a hinge, a fixing and an applied graphic.
        #
        # THIS IS THE MAPPER REFUSING AN ILLEGAL KIND, not the prompt asking nicely. The
        # model may return a size for a castor — it can see one — and the size may even be
        # right. What it must never do is become a blank, because a blank is an instruction
        # to nest, and nesting a bought item is how a sheet of wheels gets priced.
        blank = sighted.get("assumed_blank_mm") or {}
        if unclassified:
            # Same refusal, one step earlier: a size on an unclassified line would nest too.
            blank = {}
        elif kind in ("bought_in", "graphic"):
            _given = [k for k in ("length", "width", "thickness")
                      if _positive(blank.get(k))]
            if _given:
                record["review_flags"].append(
                    f"CONCEPT: {kind.replace('_', '-')} line — the sighted size "
                    f"({', '.join(_given)}) is recorded as a note, not as a blank; it is "
                    f"bought by the each and is never nested")
                record["concept_sighted_size_mm"] = {
                    k: blank.get(k) for k in ("length", "width", "thickness")}
            blank = {}
            # ── ENOUGH OF A SPECIFICATION TO GO AND BUY ONE ─────────────────────────
            #
            # "We need to be able to price castors and hinges." The researched rung asks
            # the market for a real current listing, and it was being handed the single
            # word CASTOR — which names a drawer, not a purchase: no diameter, no fixing,
            # no load. Nothing usable came back and the line sat at £0.
            #
            # A render answers more than one word. It shows a wheel about 75mm, black,
            # plated bracket — which is a briefable item, as long as every word of it says
            # it was SIGHTED and approximate. The description on the sheet stays what it
            # was; this is a second field, read only by the rung that goes looking.
            _spec = [name]
            if sighted_mat:
                _spec.append(str(sighted_mat))
            _dims = [f"{k} ~{blank_given}mm" for k, blank_given in
                     ((k, (record.get("concept_sighted_size_mm") or {}).get(k))
                      for k in ("length", "width", "thickness")) if _positive(blank_given)]
            if _dims:
                _spec.append("approximately " + " x ".join(
                    str(d).split(" ~")[1] for d in _dims))
            record["research_description"] = (
                ", ".join(_spec)
                + " — sighted on a customer render, so the size is approximate; price a "
                  "standard trade item of this description")
        why = str(sighted.get("why_size") or "scaled from the render")
        _sized_by_brief = _from_brief(sighted, "size")
        _ssrc = BRIEF_SOURCE if _sized_by_brief else SOURCE
        wrote_size = False
        for field, key in (("blank_length_mm", "length"), ("blank_width_mm", "width")):
            try:
                value = float(blank.get(key))
            except (TypeError, ValueError):
                continue
            if value > 0:
                apply_field(record, field, value, _ssrc, note=why)
                _assume(field, value, why)
                wrote_size = True
        try:
            thickness = float(blank.get("thickness"))
        except (TypeError, ValueError):
            thickness = 0.0
        if thickness > 0:
            apply_field(record, "normalized_thickness_mm", thickness, _ssrc, note=why)
            _assume("thickness_mm", thickness, why)

        # ── THE WORK, OR THE LINE COSTS NOTHING ─────────────────────────────────────
        #
        # James Gray, 22 Sep 2026, on the first render run: "Three assembly rows, all ruled
        # out. No cut, print, wrap, CNC, assemble, pack. A route that charges nothing is not
        # a route." He was right: the sighted parts carried no operations at all, so the
        # compiler had nothing to mint but a generic assembly on a leaf part — which it
        # correctly ruled out — and the whole labour column came to £0.00.
        #
        # `inferred_operations` is the honest field for this: these ARE inferred, from a
        # picture. The compiler reads it exactly as it reads an inference off a drawing, and
        # the route report says `inference` against every one.
        #
        # FILTERED TO THE VOCABULARY. A word the rate card cannot resolve resolves to no
        # department, mints nothing and charges nothing — silently. So an unknown operation
        # is dropped and SAID, rather than carried as a row that looks like work and is not.
        #
        # ── EDGING IS CHARGED ONLY WHERE THE EDGES ARE NAMED ────────────────────────
        #
        # James Gray, 22 Sep 2026: "On edging, I would not merely add it to the confirm
        # list while still charging £65.04. Make it an explicit editable concept assumption
        # with a stated visible-edge basis; otherwise it should not mint a deterministic
        # edge-banding route."
        #
        # The first full concept book banded all eight panels — two department set-ups and
        # £65.04, over half the labour on the job — off one word from a vision model. A
        # render cannot show which edges are finished unless the finish is actually visible,
        # and the engine's own rule for a drawing (D-104) is that edging is measured where
        # the drawing MARKS it, never round the perimeter because a part has one.
        #
        # So the same standard: an edge that can be named is work, and an edge that cannot
        # is an assumption. Unnamed, it does not reach `inferred_operations` at all — it
        # goes on the assumptions list with the action that turns it into a charge, which
        # is `estimator_decisions.banded_metres`, the field the engine already reads.
        _edges = str(sighted.get(EDGE_BASIS_FIELD) or "").strip()
        seen_ops, unknown, unbanded = [], [], False
        for raw in ([] if unclassified else (sighted.get("operations") or [])):
            name = str(raw or "").strip().lower().replace(" ", "_")
            if name == "edge_banding" and not _edges:
                unbanded = True
                continue
            if name in SIGHTABLE_OPERATIONS:
                if name not in seen_ops:
                    seen_ops.append(name)
            elif name:
                unknown.append(str(raw))
        if _edges and "edge_banding" in seen_ops:
            record["concept_banded_edges"] = _edges
            _assume("", f"edge_banding: {_edges}", "the edges visible on the render",
                    field="banded edges")
        if unbanded:
            record["review_flags"].append(
                "CONCEPT: edging was sighted on this part but no edges could be named, so "
                "it is NOT charged — a render cannot show which edges are finished. State "
                "the metres in `estimator_decisions.banded_metres` and the line prices "
                "itself")
            _assume("", "edge_banding — sighted, NOT charged",
                    "edging was sighted but no visible edge could be named",
                    field="banded edges")
        if seen_ops:
            record["inferred_operations"] = seen_ops
            # No file key: the answers file states what a drawing says, and it takes no
            # operations. A route sighted from a picture is turned off through
            # `estimator_decisions.operations_off`, which is a DECISION, not a reading.
            _assume("", list(seen_ops), "the work sighted on the render",
                    field="operations")
        elif kind == "fabricated":
            # A made part with no work on it is not a part anybody can price. Say so on the
            # record rather than letting it reach the sheet as a free component.
            record["review_flags"].append(
                "CONCEPT: no manufacturing operation could be sighted for this part — "
                "it will carry material and no labour until one is entered")
        if unknown:
            record["review_flags"].append(
                "CONCEPT: operation(s) not on the rate card were sighted and dropped: "
                + ", ".join(sorted(set(unknown))))

        # THE ACTION RIDES ON THE PART. One line, in the estimator's imperative, because a
        # concept figure that nobody is told to confirm becomes a firm one by seniority.
        if (wrote_size or thickness > 0) and _sized_by_brief:
            record["review_flags"].append(
                f"CONCEPT: size from the enquiry brief ({why}) — the model worked this part "
                f"out from the brief's stated dimensions; confirm "
                f"{blank.get('length', '?')} x {blank.get('width', '?')} x "
                f"{blank.get('thickness', '?')}mm before release")
        elif wrote_size or thickness > 0:
            record["review_flags"].append(
                f"CONCEPT: size {'read off the design-intent sheet by the vision model' if sheet else 'assumed from the render'} "
                f"({why}) — confirm "
                f"{blank.get('length', '?')} x {blank.get('width', '?')} x "
                f"{blank.get('thickness', '?')}mm before release")
        if sheet:
            record["concept_drawn"] = str(sighted.get("drawn") or "")
        elif not unclassified:
            # An unclassified line already carries its one action; "enter the dimensions"
            # on top of it asks for a size before anybody has said what the thing is.
            record["review_flags"].append(
                "CONCEPT: no size could be sighted — enter this part's dimensions")
        if sighted.get("_minted_print_for"):
            record["concept_print_assumed"] = True
            record["review_flags"].append(
                f"CONCEPT: print ASSUMED on {sighted['_minted_print_for']} — the panel came "
                f"back as '{sighted.get('_panel_said') or 'printed'}' with no print line of "
                f"its own, so one print of the panel's face is costed as a purchase. Confirm "
                f"the print method (direct to board or applied), the faces printed and the "
                f"price before release")
        if sighted.get("_minted_fitting_for"):
            record["concept_fitting_assumed"] = True
            record["review_flags"].append(
                f"CONCEPT: {sighted.get('name')} ASSUMED — the read listed "
                f"{sighted['_minted_fitting_for']} and no {str(sighted.get('name')).lower()}, "
                f"so {sighted.get('quantity')} are costed as a purchase "
                f"({sighted.get('_fitting_per_part'):g} each). Confirm the fitting, the count "
                f"and the price before release")
        record["concept_assumptions"] = assumed
        parts.append(record)
    if _implied:
        # A SHEET THAT DRAWS A LID AND NO HINGE IS ASKED, NOT ANSWERED (D-415). On a render the
        # net mints the fitting a moving part cannot work without (D-368); a drawing sheet
        # states what it holds, so the same rule becomes a question on the part, with no money.
        from source_precedence import raise_manufacturing_question  # noqa: WPS433
        for fit in _implied:
            movers = {s.strip().upper() for s in str(fit.get("_minted_fitting_for") or "").split(",")}
            for rec in parts:
                if str(rec.get("description") or "").strip().upper() in movers:
                    raise_manufacturing_question(
                        rec,
                        f"The sheet draws {rec.get('description')} and no "
                        f"{str(fit.get('name') or 'fitting').lower()}",
                        "not costed",
                        f"Confirm the {str(fit.get('name') or 'fitting').lower()} and its count "
                        f"({fit.get('_fitting_per_part'):g} per part is the house assumption) and "
                        f"add it as a bought-in line",
                        "concept_sheet_check")
    return parts


# ── THE CONCEPT BUDGET'S OWN PAPERWORK ──────────────────────────────────────────────
#
# James Gray, 22 Sep 2026: "The concept path still turns a render's guessed MDF, 5 mm
# thickness, dimensions and operations into normal pricing inputs... It is acceptable only
# as a clearly editable concept budget, with each assumption available to confirm — not as
# a technical estimate reconstructed from a PNG."
#
# Two things make that true, and neither is a warning block:
#
#   THE LIST      every figure the render path put into pricing, gathered off the records
#                 in one place, so "what did this assume?" is answered by reading rather
#                 than by opening twelve records and inspecting their stamps;
#   THE DOOR      the answers file `estimator_confirmed` already reads, WRITTEN OUT
#                 PRE-FILLED, so confirming an assumption is editing a line rather than
#                 hand-authoring JSON for a part number nobody wants to retype.
#
# THE TEMPLATE CANNOT APPLY ITSELF, AND THAT IS THE WHOLE DESIGN. Every entry carries
# `"basis": "inferred"` with its reasoning left EMPTY, and `estimator_confirmed` refuses an
# inferred figure that states no reasoning — "a claim without its working is a guess wearing
# a person's authority". So an untouched template changes nothing and says, part by part,
# that it is waiting. A person who types their reasoning has confirmed that assumption on
# purpose, and it then enters at their rank, above the render. The one thing this must never
# do is promote a picture-guess into a person's reading by writing a file, and it cannot:
# omitting `basis` would default it to "read" — PRINTED ON THE SHEET — which is exactly the
# laundering this refuses.

ASSUMPTION_BASIS = "inferred"


def assumption_register(parts: Optional[List[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """Every figure the concept read put into pricing, one row each, with its cue."""
    rows: List[Dict[str, Any]] = []
    for part in (parts or []):
        if not isinstance(part, Mapping) or not part.get("concept"):
            continue
        # A CONFIRMED FIGURE IS NOT AN ASSUMPTION ANY MORE. An estimator who answered one in
        # the answers file should not be asked about it again on every run afterwards — that
        # is how a list of actions becomes a list nobody reads.
        _settled = set((part.get("estimator_confirmed") or {}).get("fields") or {})
        for item in (part.get("concept_assumptions") or []):
            if not isinstance(item, Mapping):
                continue
            if item.get("file_key") and item["file_key"] in _settled:
                continue
            rows.append({"part_number": str(part.get("part_number") or ""),
                         "description": str(part.get("description") or ""),
                         "kind": str(part.get("concept_kind") or ""),
                         "field": str(item.get("field") or item.get("file_key")
                                      or "operations"),
                         "value": item.get("value"),
                         "cue": str(item.get("cue") or ""),
                         "confirmable_in_the_answers_file": bool(item.get("file_key"))})
    return rows


def assumptions_payload(parts: Optional[List[Mapping[str, Any]]],
                        *, job: str = "") -> Dict[str, Any]:
    """The answers file, pre-filled with what was assumed and nothing else.

    `confirmed_by` and the per-part reasoning are the estimator's to write. Until they do,
    every entry is refused by `estimator_confirmed` and the concept figures stand as the
    render's own — which is what they are.
    """
    out: Dict[str, Any] = {}
    for part in (parts or []):
        if not isinstance(part, Mapping) or not part.get("concept"):
            continue
        entry: Dict[str, Any] = {}
        cues: List[str] = []
        for item in (part.get("concept_assumptions") or []):
            key = str((item or {}).get("file_key") or "")
            if not key:
                continue
            entry[key] = item.get("value")
            if item.get("cue"):
                cues.append(f"{key}: {item['cue']}")
        if not entry:
            continue
        entry["basis"] = ASSUMPTION_BASIS
        # EMPTY ON PURPOSE — see above. What the render saw is recorded beside it under a
        # leading underscore, which this file's own convention reads as a comment, so the
        # estimator can see what they are agreeing with or overturning.
        entry["read_from"] = ""
        entry["_sighted_because"] = "; ".join(cues)
        out[str(part.get("part_number") or "")] = entry
    return {
        "drawing_number": job,
        "job": job,
        "confirmed_by": "",
        "confirmed_on": "",
        "note": ("Every figure below was SIGHTED from a render, not read off a drawing. "
                 "Edit the value where it is wrong, then state your reasoning in "
                 "'read_from' — an entry with no reasoning is refused and the render's own "
                 "assumption stands. Prices are never entered here."),
        "parts": out,
    }


def write_assumptions_file(parts: Optional[List[Mapping[str, Any]]], *,
                           folder: Any, job: str) -> Optional[Path]:
    """Write the pre-filled answers file beside the job, or None if it must not be written.

    NEVER OVERWRITES. A file already there is a person's, and a machine that rewrote an
    estimator's confirmations with its own guesses would undo the exact work this exists to
    collect — silently, on the run after they did it.
    """
    if not parts or folder is None:
        return None
    payload = assumptions_payload(parts, job=job)
    if not payload["parts"]:
        return None
    try:
        import estimator_confirmed as _ec                              # noqa: WPS433
        if _ec.find_corrections_file(folder, None, job):
            return None                        # a person's file is already there
    except Exception:                                                  # noqa: BLE001
        return None                            # cannot prove it is safe → do not write
    safe = re.sub(r"[^\w\-. ]", "", str(job or "concept")).strip() or "concept"
    path = Path(folder) / f"{safe}_estimator_dimensions.json"
    if path.exists():
        return None
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        return None                            # a share we cannot write to is not an error
    return path


def unit_operations(answer: Dict[str, Any]) -> List[str]:
    """The work that belongs to the UNIT, not to any one panel.

    "Route: cut board → print/wrap → assemble carcass → fit lid & wheels → pack." The first
    three happen to panels and ride on the parts; the last two happen to the product and
    have nowhere else to live. Filtered to the vocabulary for the same reason the per-part
    list is, and defaulted to `assembly` — a unit made of several sighted parts is assembled,
    whatever else the model did or did not say about it.
    """
    out: List[str] = []
    for raw in (answer.get("unit_operations") or []):
        name = str(raw or "").strip().lower().replace(" ", "_")
        if name in SIGHTABLE_OPERATIONS and name not in out:
            out.append(name)
    if not out and len(answer.get("parts") or []) > 1:
        out = ["assembly"]
    return out


def unit_assembly_part(parts: List[Dict[str, Any]], answer: Dict[str, Any],
                       stem: str) -> Optional[Dict[str, Any]]:
    """The product itself, as an assembly parent — or None where there is nothing to assemble.

    ── NOBODY ASSEMBLED THE BIN ────────────────────────────────────────────────────────
    #
    James Gray, 22 Sep 2026, on the first full concept book: twenty route lines, all of them
    saw, cnc_routing, edge_banding and laminating. The carcass was cut, banded and routed,
    and no operation anywhere put it together.

    THE CAUSE WAS A FIELD NOBODY READS. The unit's own work was written to
    `summary["assembly_events"]`, and nothing in this engine reads that key — the route
    compiler builds `explicit_assembly_events` from its own payload. A fact recorded under
    one name and read under another, which is the fault this register keeps finding.

    THE RULE WAS ALREADY THERE AND HAD NOTHING TO FIRE ON. `estimate_process_times` mints
    bench fitting on a BOARD ASSEMBLY — "a multi-part board assembly has to be fitted before
    it is packed, whatever the board is" — gated on the part being an assembly parent. A
    render pack presented no parent, so the rule was true and idle. This mints the one thing
    it needs: a parent, with the sighted parts as its children, carrying the unit operations
    the model sighted. The MINUTES are not invented here — the existing rule takes Tony's
    measured joinery bench rate inside its scope and the house allowance outside it, and
    says which on the line.

    THE MATERIAL IS THE CHILDREN'S, because it decides which of those two the rule applies:
    a scoped pilot measured on faced board must not silently govern a plain MDF carcass.
    """
    from document_builder import _empty_part_record                    # noqa: WPS433
    from source_precedence import apply_field                          # noqa: WPS433

    made = [p for p in (parts or [])
            if isinstance(p, dict) and p.get("concept_kind") == "fabricated"]
    if len(made) < 2:
        # One panel is not an assembly, and neither is a pack of bought-ins. Saying so is
        # the honest answer: an assembly event minted over nothing charges for nothing.
        return None

    tally: Dict[str, int] = {}
    for part in made:
        mat = str(part.get("normalized_material") or "").strip().upper()
        if mat:
            tally[mat] = tally.get(mat, 0) + 1
    material = max(tally, key=lambda k: (tally[k], k)) if tally else ""

    product = str((answer.get("product") or {}).get("name") or "").strip() or "UNIT"
    record = _empty_part_record(f"{_slug(stem, 'CONCEPT')}-CPT00",
                                item_number=0, description=f"{product} — unit assembly",
                                quantity=None)
    # THROUGH THE RESOLVER, like every other arbitrated fact this module writes. One of
    # these decides how the build is timed, and a figure that cannot be displaced by a
    # drawing is not a concept figure at all.
    apply_field(record, "quantity", 1, SOURCE,
                note="one product per unit — this line IS the unit")
    record["concept"] = True
    record["concept_kind"] = "assembly"
    record["page_roles"] = ["render"]
    record["concept_seen"] = str((answer.get("product") or {}).get("scale_cue") or "")
    # The three names the assembly rules ask by. Written together, because a parent known
    # to one of them and not the others is the two-names fault again, one level down.
    record["is_assembly_parent"] = True
    record["canonical_kind"] = "assembly"
    record["assembly_children"] = [str(p.get("part_number") or "") for p in made]
    if material:
        apply_field(record, "normalized_material", material, SOURCE,
                    note=f"the board most of the sighted panels are made of ({material})")
    ops = unit_operations(answer)
    if ops:
        record["inferred_operations"] = ops
    record["concept_assumptions"] = []
    # WHICH BOARD THE BUILD IS TIMED AS, SAID OUT LOUD. The bench rule takes the shop's
    # measured faced-board rate inside its scope and the house allowance outside it, and the
    # difference is fifteen times. On a mixed carcass that call is a judgement, so the line
    # names the mix it was made from and the lever that overturns it.
    _mix = ", ".join(f"{n}x {m}" for m, n in sorted(tally.items(), key=lambda kv: -kv[1]))
    record["review_flags"].append(
        f"CONCEPT: this is the product itself, sighted as {len(made)} made part(s) that "
        f"have to be put together. It carries the unit's own work and no material of its "
        f"own — the panels carry that. The build is timed as {material or 'board'} because "
        f"that is most of what it is made of ({_mix or 'no material sighted'}); set "
        f"`estimator_decisions.throughput_per_hour` for the bench department to time it "
        f"yourself")
    return record


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
        # THE BRIEF'S OTHER OPTIONS, NAMED AS NOT COSTED (D-360). "Plywood … or mild steel"
        # is two estimates; this one priced the first, and the book says which it did not.
        "options_not_costed": [str(o) for o in (answer.get("options_not_costed") or [])
                               if str(o).strip()],
    }
