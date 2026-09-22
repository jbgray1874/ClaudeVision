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
CONCEPT_PROMPT_VERSION = "c3"

SOURCE = "vision_concept"

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
_PROMPT_FINGERPRINT = "151638566ab8"


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
            apply_field(record, "normalized_material", guess, SOURCE, note=_why_mat)
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
        wrote_size = False
        for field, key in (("blank_length_mm", "length"), ("blank_width_mm", "width")):
            try:
                value = float(blank.get(key))
            except (TypeError, ValueError):
                continue
            if value > 0:
                apply_field(record, field, value, SOURCE, note=why)
                _assume(field, value, why)
                wrote_size = True
        try:
            thickness = float(blank.get("thickness"))
        except (TypeError, ValueError):
            thickness = 0.0
        if thickness > 0:
            apply_field(record, "normalized_thickness_mm", thickness, SOURCE, note=why)
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
        record["concept_assumptions"] = assumed
        parts.append(record)
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
    record = _empty_part_record(f"{_slug(stem, 'CONCEPT')}-C00 {_slug(product, 'UNIT')}",
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
    }
