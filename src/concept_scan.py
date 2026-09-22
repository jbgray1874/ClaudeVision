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
CONCEPT_PROMPT_VERSION = "c2"

SOURCE = "vision_concept"

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
- Fittings you can see the effect of are lines too: a lid that lifts has a hinge; a unit on
  wheels has castors; panels that meet are screwed or glued.
- Give the quantity PER UNIT (4 castors = one line, quantity 4 — never 4 lines, never "a set").

For every line give the work it needs, from THIS LIST ONLY — any other word is discarded:
{ops}

Sizes: estimate in mm from visible human-scale cues (castors ~75mm, hand-height apertures,
floor tiles, door heights). Every size must name the cue it came from. Integers only.

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
      "seen": "<which image, where>", "why_size": "<the cue this was scaled from>"}}
  ],
  "unit_operations": ["assembly"],
  "print_sets": ["<one line per graphic variant>"],
  "not_visible": ["<what a real unit needs that these images cannot show>"]
}}"""

# The prompt's own hash, so a change without a version bump cannot pass silently. If a test
# tells you this is wrong: bump CONCEPT_PROMPT_VERSION above, then put the new hash here.
_PROMPT_FINGERPRINT = "d7f83e6e40fe"


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
    _ops = "\n".join(f"  {name} — {what}" for name, what in SIGHTABLE_OPERATIONS.items())
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": _PROMPT.format(n=len(png_pages), ops=_ops)}]
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

    for raw in (files or []):
        suffix = Path(str(raw)).suffix.lower()
        if suffix in _MEASURABLE_CAD:
            return (f"the pack contains {Path(str(raw)).name} — measured CAD is never "
                    f"sighted over")

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
        kind = _concept_kind(sighted.get("kind"))
        unclassified = kind == UNKNOWN_KIND
        record = _empty_part_record(
            f"{_slug(stem, 'CONCEPT')}-C{n:02d} {_slug(name, str(n))}",
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
        apply_field(record, "quantity", qty, SOURCE, note=basis)

        sighted_mat = str(sighted.get("sighted_material") or "").strip()
        guess = str(sighted.get("material_guess") or "").strip().upper()
        if kind == "bought_in" and not guess:
            # A sourcing fact, not a zero — the bought-in price chain starts here (D-153).
            guess = "BOUGHT_IN"
        if unclassified:
            # A material on a line nobody has classified prices a guess at a guess.
            guess, sighted_mat = "", ""
        if guess:
            apply_field(record, "normalized_material", guess, SOURCE,
                        note=f"sighted as '{sighted_mat}' on the render" if sighted_mat
                        else "sighted on the render")
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
        seen_ops, unknown = [], []
        for raw in ([] if unclassified else (sighted.get("operations") or [])):
            name = str(raw or "").strip().lower().replace(" ", "_")
            if name in SIGHTABLE_OPERATIONS:
                if name not in seen_ops:
                    seen_ops.append(name)
            elif name:
                unknown.append(str(raw))
        if seen_ops:
            record["inferred_operations"] = seen_ops
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
        if wrote_size or thickness > 0:
            record["review_flags"].append(
                f"CONCEPT: size assumed from the render ({why}) — confirm "
                f"{blank.get('length', '?')} x {blank.get('width', '?')} x "
                f"{blank.get('thickness', '?')}mm before release")
        elif not unclassified:
            # An unclassified line already carries its one action; "enter the dimensions"
            # on top of it asks for a size before anybody has said what the thing is.
            record["review_flags"].append(
                "CONCEPT: no size could be sighted — enter this part's dimensions")
        parts.append(record)
    return parts


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
