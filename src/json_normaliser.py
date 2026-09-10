from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import part_code_conventions
from source_precedence import apply_field

logger = logging.getLogger(__name__)

V4_SCHEMA = "professional_manufacturing_json.v4"

MATERIAL_NORMALISATION = {
    "MILD STEEL": "MILD_STEEL",
    "MILDSTEEL": "MILD_STEEL",
    "MS": "MILD_STEEL",
    "SHEET STEEL": "MILD_STEEL",
    "STAINLESS": "STAINLESS_STEEL",
    "SS": "STAINLESS_STEEL",
    "ALUMINIUM": "ALUMINIUM",
    "ALUMINUM": "ALUMINIUM",
    "Q195": "MILD_STEEL",
    "Q235": "MILD_STEEL",
    "SPCC": "MILD_STEEL_SPCC",
    "304": "STAINLESS_STEEL_304",
    "316": "STAINLESS_STEEL_316",
    "PLYWOOD": "PLYWOOD",
    "MDF": "MDF",
    "MDF BOARD": "MDF",
    "BIRCH PLY": "BIRCH_PLYWOOD",
    "MARINE PLY": "PLYWOOD",
    "TIMBER": "TIMBER",
    "WOOD": "TIMBER",
    # SPECIES, not families. A title block names the actual timber — "FSC PINE",
    # "SPRUCE", "BEECH" — and never the word TIMBER, so a species-blind vocabulary
    # returns nothing for a stated material and the part falls through unpriced or
    # takes a default. This is what left the Horti Crate's FSC PINE panels with no
    # material. Longest-key-first matching keeps "OAK VENEER MDF" resolving to the
    # veneered board rather than to solid oak.
    "FSC PINE": "TIMBER",
    "PINE": "TIMBER",
    "SPRUCE": "TIMBER",
    "REDWOOD": "TIMBER",
    "WHITEWOOD": "TIMBER",
    "SOFTWOOD": "TIMBER",
    "HARDWOOD": "TIMBER",
    "BEECH": "TIMBER",
    "ASH": "TIMBER",
    "OAK": "TIMBER",
    "MR MDF": "MDF",
    "MRMDF": "MDF",
    # FACED SHEET BOARD — melamine-faced chipboard and its spellings. The commonest
    # shop-fitting board there is, and this lexicon did not have it: on 12422-24 the end
    # cap panel's stated "16mm MFC" resolved to nothing here, so the title-block reader's
    # unknown-callout branch took the raw string and the drawing's boilerplate with it, and
    # the material reached the sheet as "MFC DO NOT".
    #
    # Longest-key-first matching is what keeps the faced spellings ahead of plain MDF, so
    # "MELAMINE FACED MDF" is faced board and not MDF. Deliberately NOT given a density or
    # a price-per-kg: config's per-kg lookup falls back to the MILD STEEL rate for anything
    # it does not know, so inventing an entry would cost a chipboard panel at steel's rate.
    # It stays in the board path and stays honestly unpriced until an estimator sets the
    # sheet rate — which is the same thing the sheet already asks for.
    # THE FACING IS NOT THE SUBSTRATE. MFC is melamine-faced CHIPBOARD; MFMDF is
    # melamine-faced MDF. They are bought as different sheets at different prices and they
    # machine differently — chipboard blows out on a routed edge where MDF does not — so
    # collapsing them onto one code would price one board at the other's rate the moment a
    # sheet rate exists for either. Same facing, two materials.
    # ONLY THE SPELLINGS THAT NAME THEIR SUBSTRATE. "MELAMINE FACED" and "PRE-LAM" on their
    # own say what was done to the sheet and not what the sheet IS, and the two candidates
    # are bought at different prices. Resolving them to MFC because it is the commoner of
    # the two is a guess wearing a fact's clothes — the same reasoning that keeps
    # "finishing" out of the department table. Unresolved, the part reaches the estimator
    # as a visible gap; resolved wrongly, it reaches them as somebody else's board.
    "MELAMINE FACED CHIPBOARD": "MFC",
    "MELAMINE FACED MDF": "MFMDF",
    "PRE LAMINATED CHIPBOARD": "MFC",
    "PRE LAM CHIPBOARD": "MFC",
    "PRE LAMINATED MDF": "MFMDF",
    "PRE LAM MDF": "MFMDF",
    "PRELAM MDF": "MFMDF",
    "MFMDF": "MFMDF",
    "MFC": "MFC",
    "CHIPBOARD": "CHIPBOARD",
    "HDPE": "HDPE_PLASTIC",
    "HIGH IMPACT ACRYLIC": "ACRYLIC",
    "ACRYLIC": "ACRYLIC",
    "PERSPEX": "ACRYLIC",
    "GREENCAST": "ACRYLIC",
    "POLYCARBONATE": "POLYCARBONATE",
    "VENEERED MDF": "VENEERED_MDF",
    "VENEER MDF": "VENEERED_MDF",
    "MDF VENEERED": "VENEERED_MDF",
    "OAK VENEER MDF": "OAK_VENEER_MDF",
    "OAK VENEER": "OAK_VENEER_MDF",
    "OAK MDF": "OAK_VENEER_MDF",
    "PAPER": "BOUGHT_IN",
    "PRINTED PAPER": "BOUGHT_IN",
    "DISPA BOARD": "BOUGHT_IN",
    "DISPABOARD": "BOUGHT_IN",
    "FOAMEX": "BOUGHT_IN",
    "CORREX": "BOUGHT_IN",
    "ERW TUBE": "MILD_STEEL",
    "STEEL TUBE": "MILD_STEEL",
    "MILD STEEL ERW": "MILD_STEEL",
    "CR4": "MILD_STEEL",
    "PETG": "ACRYLIC",
    "PET": "ACRYLIC",
    "POLYSTYRENE": "HIPS",      # HIPS = High Impact PolyStyrene — keep as HIPS
    "HIPS": "HIPS",             # keep HIPS distinct so it prices from live UDEF HIPS
                                # sheet rates (labour still routes acrylic-like via
                                # estimator._ACRYLIC_LIKE — cut/handle as plastic).
}

OPERATION_INFERENCE_MAP = {
    "SPOT WELD": "spot_welding",
    "WELD": "welding",
    "LASER": "laser_cutting",
    "CUT": "laser_cutting",
    "FOLD": "folding",
    "BEND": "folding",
    "WET SPRAYED": "wet_spray",
    "WET SPRAY": "wet_spray",
    "WET-SPRAY": "wet_spray",
    "WET PAINT": "wet_spray",
    "SPRAY SHOP": "wet_spray",
    "CNC ROUT": "cnc",
    "CNC ": "cnc",
    "CNC.": "cnc",
    "BENCH": "bench_work",
    "BENCHWORK": "bench_work",
    "POWDER": "powder_coating",
    "COAT": "powder_coating",
    "ASSEMBLE": "assembly",
    "PACK": "packing",
    "DRILL": "hole_machining",
    "TAP": "tapping",
    "DIAMOND POLISH": "diamond_polish",
    "POLISH": "diamond_polish",
    "DRESS WELD": "dress_welds",
    "GLUE": "glue",
    "GUILLOTINE": "guillotine",
    "PUNCH": "punch",
    "ROLL": "roll",
    "SAW": "saw",
    "LINISH": "linisher",
}

_MATERIAL_KEYS_SORTED = sorted(MATERIAL_NORMALISATION.keys(), key=len, reverse=True)
_OPERATION_KEYS_SORTED = sorted(OPERATION_INFERENCE_MAP.keys(), key=len, reverse=True)

# Part-number suffix conventions used as WEAK material hints. '-M<digit>' is SDI's metal
# detail convention (12120-01-01M etc). There is deliberately no '-J' rule: J reads as
# JOINERY on real jobs, and treating it as a metal "joist" forced the Horti Crate's timber
# panels to steel. See normalise_material for why these can never override a stated material.
_METAL_PANEL_RE = re.compile(r"-\s*M\d", re.IGNORECASE)
_METAL_SA_RE = re.compile(r"-\s*SA\d", re.IGNORECASE)


def _first_material_text(part: Dict[str, Any]) -> str:
    materials = part.get("materials") or []
    if not materials:
        return ""
    first = materials[0]
    if isinstance(first, dict):
        return str(first.get("raw") or first.get("text") or first.get("value") or "")
    return str(first)


def _part_text_blob(part: Dict[str, Any]) -> str:
    desc = str(part.get("description") or "")
    notes = " ".join(str(n) for n in (part.get("process_notes") or []))
    return f"{desc} {notes}".strip()


def _hints_timber(blob_upper: str) -> bool:
    if any(k in blob_upper for k in ["PLYWOOD", "BIRCH PLY", "OAK VENEER", "OAK MDF"]):
        return True
    if "MDF" in blob_upper and "ACRYLIC" not in blob_upper and "PERSPEX" not in blob_upper and "GREENCAST" not in blob_upper:
        if any(k in blob_upper for k in ["PLY", "TIMBER", "WOOD", "OAK", "SHELF BOARD", "JOINERY"]):
            return True
    if ("PLANK" in blob_upper or "SHELF" in blob_upper) and any(
        w in blob_upper for w in ["TIMBER", "WOOD", "PLY", "OAK", "PLYWOOD"]
    ):
        return True
    if "TIMBER" in blob_upper and "MILD STEEL" not in blob_upper:
        return True
    # Named species count as timber evidence. Without this a drawing stating "FSC PINE"
    # gives no timber cue at all, so the part-number and blob steel hints below win by
    # default on a wooden part. Suppressed where the blob also names steel, so a mixed
    # note ("PINE PACKER ON MILD STEEL FRAME") does not flip a steel part to timber.
    _SPECIES = ("FSC PINE", "PINE", "SPRUCE", "REDWOOD", "WHITEWOOD",
                "SOFTWOOD", "HARDWOOD", "BEECH", "OAK", "JOINERY")
    if any(s in blob_upper for s in _SPECIES) and "MILD STEEL" not in blob_upper:
        return True
    return False


def _hints_mild_steel_part_number(part_number: str) -> bool:
    u = str(part_number or "").upper()
    # '-J<digit>' removed: it reads as JOINERY on real jobs (Horti Crate -J01..-J08 are
    # timber panels), not the metal "joist" this was named for. See normalise_material.
    if _METAL_PANEL_RE.search(u):
        return True
    if any(k in u for k in ["FRAME", "WELDMENT", "CHANNEL", "TUBE", "SECTION", "STIFFENER", "BRACKET", "BASE"]):
        return True
    return False


def _hints_mild_steel_blob(blob_upper: str) -> bool:
    if any(k in blob_upper for k in ["MILD STEEL", "ZINTEC", "GALVANISE", "GALVANIZE", "S355", "CR4", "LASER CUT"]):
        return True
    return False


# Keys worth trying WORD-ORDER-FREE. A one-word key is excluded deliberately: matching it
# loosely would let a stray token anywhere in a description decide the material, and every
# one-word key already matches as a substring in the pass above, so it has nothing to gain.
_MATERIAL_KEYS_MULTIWORD = [k for k in _MATERIAL_KEYS_SORTED if len(k.split()) > 1]


def normalise_material(text: Optional[str]) -> Optional[str]:
    """The material lexicon, matched first as written and then word-order-free.

    A DRAWING OFFICE MAY WRITE THE SURNAME FIRST. M&S packs state materials inverted —
    "Steel, Mild 2mm", "Steel, Mild Wire Ø8mm", "Steel, Stainless 304" — and this lexicon is
    an ordered SUBSTRING lookup keyed "MILD STEEL". So the material was in the book all along
    and still normalised to None, which is not a harmless miss:

        part["materials"] is only populated `if part.get("normalized_material")`, so a None
        leaves the list EMPTY. document_builder's wire test reads that list for the word
        "WIRE" — so MBY432, whose material cell literally says "Steel, Mild Wire Ø8mm",
        could not be recognised as wire and fell to the sheet path: a Ø8 x 219.6 prong
        nested as plate, 56 off. MBY439 ("Steel, Mild 2mm") lost its material the same way.

    The second pass therefore matches a key when every one of its WORDS appears in the text,
    in any order. It runs ONLY when the direct pass found nothing, so it is safe by
    construction: it can turn a None into a code, and can never change an answer the lexicon
    already gives. Genuine gaps stay gaps — "Corian, 6mm", "Mirror, 6mm" and "Lamainate
    Edging" are not in the book in any word order and still return None, which is the honest
    answer rather than a guess at the nearest entry.
    """
    if not text:
        return None
    cleaned = re.sub(r"[^A-Z0-9 ]", " ", str(text).upper()).strip()
    cleaned = re.sub(r" {2,}", " ", cleaned)
    for key in _MATERIAL_KEYS_SORTED:
        code = MATERIAL_NORMALISATION[key]
        if key in cleaned:
            return code
    tokens = set(cleaned.split())
    if tokens:
        for key in _MATERIAL_KEYS_MULTIWORD:
            if set(key.split()) <= tokens:
                return MATERIAL_NORMALISATION[key]
    return None


# ── THE MATERIAL AS PRINTED, READ ONCE, INTO SEPARATE FACTS ─────────────────────────────
# A printed material cell states more than one thing, and collapsing it to a single
# normalised code destroys the rest. MBY432 on 0359342 says:
#
#     "Steel, Mild Wire Ø8mm"
#      \_________/ \__/ \___/
#       material   form   Ø
#
# Normalising that to MILD_STEEL is correct FOR THE RATE and silently discards both the
# stock form and the diameter — and it was the word "Wire" that the wire test was hunting
# for inside the material NAME. So the fix that only repaired normalisation would have made
# the rate resolve and left the routing exactly as broken: a Ø8 x 219.6 prong nested as
# plate, 56 off, carrying a laser and a fold it can never incur.
#
# The facts are therefore kept apart, and each consumer takes the one it needs:
#     material     -> the rate table          (word-order-free, see normalise_material)
#     stock_form   -> the route               (stock_form_rules already makes laser, fold,
#                                              punch, linebend and guillotine impossible on
#                                              "wire" — it only ever needed to be told)
#     diameter_mm  -> the gauge, NOT a sheet thickness
#     text         -> preserved always, so an unrecognised material is still evidence
#
# Neither routing nor pricing depends on finding a form word inside a material name, which
# is the coupling that caused this. LENGTH IS NOT HERE ON PURPOSE: a cell states the section,
# never how much of it, and a length guessed from an outline is kilograms of error on Ø8.
# It comes from the part's own detail drawing, or an estimator states it.
_FORM_WIRE = re.compile(r"\b(WIRE|ROD)\b")
_FORM_BAR = re.compile(r"\bBAR\b")
_FORM_TUBE = re.compile(r"\b(TUBE|TUBULAR|RHS|SHS|CHS|BOX SECTION)\b")
_FORM_FLAT = re.compile(r"\b(SHEET|PLATE|FLAT BAR)\b")
# A DIAMETER CARRIES A UNIT, AND A DRAWING MAY PRINT MORE THAN ONE.
#
# Both halves were silently wrong. "Wire Ø0.25in" read as 0.25 mm rather than 6.35 mm — a
# 25x under-read straight into wire mass — because the number was taken and the unit thrown
# away. And "Wire Ø8mm / Ø10mm" returned 8.0: the FIRST callout won and the disagreement
# disappeared, which is the one outcome a conflicting drawing must never produce.
#
# So every callout is collected with its unit. One value is a diameter; two different values
# are a decision for an estimator, not a coin toss. A fraction ("3/16in") is refused BY NAME
# rather than dropped, because a silent None reads as "the drawing said nothing".
_DIA_PATTERNS = (
    re.compile(r"(?:Ø|\bDIA\.?\s*)\s*(\d+(?:\.\d+)?)\s*(MM|IN|INCH|INCHES|\")?", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*(MM|IN|INCH|INCHES|\")?\s*\bDIA\b", re.I),
)
# FRACTIONS ARE READ FIRST, AND THEN REMOVED FROM THE STRING.
#
# Refusing them in an `elif` after the decimal pass was worse than not handling them at all,
# because the decimal patterns match INSIDE a fraction and the refusal never ran:
#     "Wire Ø3/16in"   -> 3.0 mm    (the numerator)
#     "Wire 3/16in DIA" -> 406.4 mm (the DENOMINATOR, times 25.4)
#     "Wire 1/2\" DIA"  -> 50.8 mm
# all silently, all wrong, and 3/16" is 4.7625 mm. So each fraction is converted where its
# unit is explicit, and its span is masked out before any decimal pattern is allowed to look
# — a number that is part of a fraction is never also a number in its own right.
# A MIXED NUMBER IS ONE VALUE, AND ITS WHOLE PART IS NOT A SEPARATE DIAMETER.
#
# Masking only the fractional half left the whole number sitting there for the decimal
# parser: "Wire Ø1 1/2in" returned 1.0 mm instead of 38.1, "Ø2 3/4in" returned 2.0, and
# "1 1/2in DIA" reported "more than one diameter" — a wrong diagnosis on a drawing that
# states exactly one. The whole part is captured with the fraction, and the mask covers the
# entire span. Both "1 1/2" and "1-1/2" are written by drawing offices.
_MIXED = r"(?:(\d+)\s*[-\s]\s*)?(\d+)\s*/\s*(\d+)"
_DIA_FRACTION_PATTERNS = (
    re.compile(r"(?:Ø|\bDIA\.?\s*)\s*" + _MIXED + r"\s*(MM|IN|INCH|INCHES|\")?", re.I),
    re.compile(_MIXED + r"\s*(MM|IN|INCH|INCHES|\")?\s*\bDIA\b", re.I),
)
# Any remaining fraction, wherever it sits — including its whole part — masked so no piece
# of it can be misread as a decimal in its own right.
_ANY_FRACTION = re.compile(
    r"(?:\d+\s*[-\s]\s*)?\d+\s*/\s*\d+\s*(?:MM|IN|INCH|INCHES|\")?", re.I)
_INCH_UNITS = {"IN", "INCH", "INCHES", '"'}
MM_PER_INCH = 25.4


def read_material_as_printed(text: Optional[str]) -> Dict[str, Any]:
    """Split a printed material cell into the separate facts it states.

    Returns {"text", "material", "stock_form", "diameter_mm"}. `text` is always the cell as
    written — an unrecognised material must not be erased to None, because "we do not know
    this material" and "there was no material" are different facts and only one of them
    needs an estimator.

    stock_form is "" when the cell does not say. That is deliberate: a cell that names no
    section is not evidence of sheet, and inventing "sheet" here would re-create the very
    default this exists to remove. WIRE MESH is excluded (it is a section, not a wire) and a
    plain BAR needs a diameter to count as round — "flat bar" is sheet-like and a bare BAR
    is ambiguous with a crossbar.
    """
    raw = "" if text is None else str(text).strip()
    out: Dict[str, Any] = {"text": raw, "material": None, "stock_form": "",
                           "diameter_mm": None, "diameter_unresolved": "",
                           "material_key": ""}
    if not raw:
        return out
    out["material"] = normalise_material(raw)
    # AN UNRESOLVED MATERIAL IS STILL A DISTINCT MATERIAL. Two cells the lexicon cannot
    # place are not thereby the same stock: "Corian, 6mm" and "Mirror, 6mm" both normalise
    # to None, and comparing rows on that None made a solid-surface tray and a mirror look
    # like corroborating readings of one thing. Where the book has no answer, the cell's own
    # words are the identity — squashed only for spacing and punctuation, never interpreted.
    out["material_key"] = out["material"] or (
        "?" + re.sub(r"[^A-Z0-9]+", " ", raw.upper()).strip())
    upper = re.sub(r'[^A-Z0-9Ø."/ ]', " ", raw.upper())
    upper = re.sub(r" {2,}", " ", upper).strip()

    # FRACTIONS FIRST, then their spans are removed. See _DIA_FRACTION_PATTERNS.
    found_values: List[float] = []
    unresolved_fraction = False
    for pattern in _DIA_FRACTION_PATTERNS:
        for match in pattern.finditer(upper):
            try:
                whole = float(match.group(1)) if match.group(1) else 0.0
                numerator, denominator = float(match.group(2)), float(match.group(3))
            except (TypeError, ValueError):
                continue
            if denominator <= 0 or numerator <= 0:
                continue
            quantity = whole + numerator / denominator
            unit = (match.group(4) or "").strip().upper()
            if unit in _INCH_UNITS:
                value = round(quantity * MM_PER_INCH, 4)
            elif unit == "MM":
                value = round(quantity, 4)
            else:
                # A bare "3/16" states no unit. On Ø that is 4.76 mm or 0.19 mm — a factor
                # of 25.4 on the diameter and 645 on the mass. Not guessed.
                unresolved_fraction = True
                continue
            if value not in found_values:
                found_values.append(value)

    _masked_fractions = bool(_ANY_FRACTION.search(upper))
    masked = _ANY_FRACTION.sub(lambda m: " " * len(m.group(0)), upper)

    # EVERY callout, with its unit — not the first one that matches.
    for pattern in _DIA_PATTERNS:
        for match in pattern.finditer(masked):
            try:
                value = float(match.group(1))
            except (TypeError, ValueError):
                continue
            if value <= 0:
                continue
            unit = (match.group(2) or "").strip().upper()
            if unit in _INCH_UNITS:
                value = round(value * MM_PER_INCH, 4)
            if value not in found_values:
                found_values.append(value)

    diameter = None
    if unresolved_fraction and not found_values:
        out["diameter_unresolved"] = (
            "the material cell states the diameter as a fraction with no unit — 3/16 is "
            "4.76 mm as inches and 0.19 mm as millimetres, a factor of 645 on mass. "
            "State the unit or confirm the stock size")
    elif unresolved_fraction and found_values:
        out["diameter_unresolved"] = (
            "the material cell states a fraction with no unit alongside another diameter — "
            "the readings cannot be reconciled without knowing the unit")
    elif not found_values and _masked_fractions:
        # A fraction that is not tied to a Ø or DIA is not read as a diameter — but it is
        # SAID, because on a round part a bare "3/16in" almost certainly is one and a silent
        # None reads as "the drawing stated no size".
        out["diameter_unresolved"] = (
            "the material cell states a fraction that is not marked as a diameter — it is "
            "not assumed to be one. Confirm the stock size")
    elif len(found_values) == 1:
        diameter = found_values[0]
    elif len(found_values) > 1:
        # TWO DIFFERENT DIAMETERS IS A DECISION, NOT A DEFAULT. Neither is returned: a wire
        # priced on the wrong one of Ø8 and Ø10 is 56% out on mass, and picking silently is
        # how that becomes invisible.
        out["diameter_unresolved"] = (
            "the material cell states more than one diameter ("
            + " and ".join(f"{v:g} mm" for v in sorted(found_values))
            + ") — none is used until an estimator says which applies")

    if _FORM_TUBE.search(upper):
        out["stock_form"] = "tube"
    elif _FORM_WIRE.search(upper) and "WIRE MESH" not in upper:
        out["stock_form"] = "wire"
    elif _FORM_BAR.search(upper) and diameter and not _FORM_FLAT.search(upper):
        out["stock_form"] = "wire"
    elif _FORM_FLAT.search(upper):
        out["stock_form"] = "sheet"

    # A DIAMETER BELONGS TO A ROUND SECTION. Reported only for one, so it can never be
    # handed on as a sheet thickness — the misread that priced a Ø8 prong as 8mm plate.
    if out["stock_form"] == "wire":
        out["diameter_mm"] = diameter
    return out


def normalise_material_for_part(part: Dict[str, Any]) -> Optional[str]:
    """
    Context-aware normalisation to reduce WOOD/TIMBER leakage onto fabricated steel lines.
    Order: explicit metal line tags (-Mxx / -Jxx) -> acrylic/MDF sheet stock cues -> timber joinery text ->
    other steel hints -> lexicon on declared material string.
    """
    raw = _first_material_text(part)
    # DID THE MATERIAL TEXT SAY ANYTHING WE RECOGNISE?
    #
    # This used to be `_REJECT_MAT = {"LED", "CARD", "VINYL", "TAPE"}` — four OCR artefacts,
    # hand-listed, one per job that had gone wrong. Every one of them is simply a token the
    # lexicon does not resolve, so the list was a sample of a rule rather than the rule, and
    # the fifth job brings the fifth token: on 12392 the steel brackets read "Card 2mm", which
    # the exact-match set does not contain. They reached costing with no material at all.
    #
    # The general test is the lexicon itself. Text that resolves to nothing we hold is not a
    # material; it is noise that happens to be non-empty, and it must not outrank what the
    # drawing states elsewhere — least of all its own part-numbering convention.
    #
    # DELIBERATELY NOT BLANKED HERE. The old list cleared `raw`, which is safe for four
    # tokens and wrong in general: "PMMA" and "DISPA" also resolve to nothing, and branches
    # below read them as substrings to reach ACRYLIC and BOUGHT_IN. Blanking every
    # unresolvable token would take those readings with it. The question is asked instead at
    # the two gates that were each approximating it with a list of their own.
    _raw_says_something = normalise_material(raw) is not None
    pn = str(part.get("part_number") or "")
    blob = _part_text_blob(part).upper()
    pn_u = pn.upper()

    # Supplier / stock codes and finishes common on Boots & gondola packs.
    # Bought-in items — check raw material field AND description blob BEFORE
    # timber/steel heuristics so PAPER/DISPA BOARD parts aren't mis-classified.
    _raw_mat_upper = (raw or "").upper()
    if normalise_material(_raw_mat_upper) == "BOUGHT_IN":
        return "BOUGHT_IN"
    if any(k in blob for k in ("SUPPLIED BY M&S", "SUPPLIED BY MARKS", "FOR SIZE REFERENCE ONLY", "SUPPLIED BY CLIENT")):
        return "BOUGHT_IN"
    if "PAPER" in blob and "PRINTED" in blob:
        return "BOUGHT_IN"
    if "DISPA" in blob or "DISPABOARD" in blob:
        return "BOUGHT_IN"
    if any(k in _raw_mat_upper for k in ("PAPER", "DISPA", "FOAMEX", "CORREX")):
        return "BOUGHT_IN"
    # Check surface_finishes — PRINTED finish = customer-supplied printed item
    _finishes_upper = " ".join(str(f) for f in (part.get("surface_finishes") or [])).upper()
    if "PRINTED" in _finishes_upper:
        return "BOUGHT_IN"
    # Description-based: customer-supplied graphics only — not fabricated metal parts
    # like "GRAPHIC CHANNEL" (sheet MS with flat DXF). Require explicit supply wording.
    _desc_upper = str(part.get("description") or "").upper()
    _fabricated_metal = (
        part.get("flat_pattern_detected")
        or part.get("dxf_augmented")
        or "MILD STEEL" in blob
        or _METAL_PANEL_RE.search(pn_u)
    )
    if not _fabricated_metal:
        if any(k in _desc_upper or k in pn_u for k in ("GRAPHIC", "ARTWORK", "POSTER", "PRINT INSERT")):
            return "BOUGHT_IN"
    else:
        if any(k in _desc_upper for k in ("ARTWORK", "POSTER", "PRINT INSERT")):
            return "BOUGHT_IN"
        if "GRAPHIC" in _desc_upper and "SUPPLIED" in _desc_upper:
            return "BOUGHT_IN"
    if "TICKET" in _desc_upper and "PLATE" not in _desc_upper and "HOLDER" not in _desc_upper:
        return "BOUGHT_IN"

    if "PLAS518" in pn_u or "PLAS518" in blob or "GREENCAST" in blob or "CAST ACRYLIC" in blob:
        return "ACRYLIC"
    if "MDFS" in pn_u or ("MDF" in blob and "ACRYLIC" not in blob and "PERSPEX" not in blob and "GREENCAST" not in blob):
        if "MILD STEEL" not in blob and "STAINLESS" not in blob:
            # Preserve VENEERED qualifier so price lookup hits the correct catalog entry
            if any(v in blob for v in ("VENEERED", "VENEER MDF", "MDF VENEERED")):
                return "VENEERED_MDF"
            return "MDF"

    pn_steel = _hints_mild_steel_part_number(pn)
    timber = _hints_timber(blob)
    blob_steel = _hints_mild_steel_blob(blob)

    # PART-NUMBER SUFFIX AS A MATERIAL HINT — weak, and never an override.
    #
    # This used to return MILD_STEEL unconditionally for any '-M<digit>' or '-J<digit>'
    # part number, ahead of every material check, to defeat the M&S title-block legend
    # bleeding WOOD onto steel details. That legend problem is now fixed at source (the
    # boilerplate material scan in extractor_patterns), so the override is no longer
    # needed — and it was doing real harm: the Horti Crate's -J01..-J08 are the TIMBER
    # panels, priced by weight as timber/MDF in the BOM, yet were forced to MILD_STEEL
    # and routed to laser/weld/powder. A suffix is a NAMING CONVENTION, not a material.
    #
    # '-J' is dropped as a steel signal entirely: on this evidence J means JOINERY, and
    # the "joist" reading it was named for is not supported by any job we have. '-M' is a
    # genuine SDI convention for metal detail parts, so it is kept — but demoted to a hint
    # that yields to positive timber evidence, exactly as the '-SA' rule below already
    # does. Where the drawing states a material, that material wins.
    if _METAL_PANEL_RE.search(pn.upper()) and not timber:
        return "MILD_STEEL"

    # HIPS declared explicitly on the drawing (MATERIAL: HIPS) is a distinct plastic
    # with its own sheet price — keep it HIPS rather than collapsing to ACRYLIC via the
    # "LENS" heuristic below. (Labour still routes acrylic-like in the estimator.)
    if "HIPS" in _raw_mat_upper or "HIPS" in _desc_upper:
        return "HIPS"

    # Acrylic / perspex detection — MUST come before timber check because some
    # acrylic parts (e.g. "LENS") have "CLEAR" finish or "SCRAPED EDGES" that
    # otherwise look timber-like and get mis-priced as TIMBER.
    _is_acrylic = (
        any(k in _raw_mat_upper for k in ("ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"))
        or any(k in _desc_upper for k in ("LENS", "ACRYLIC", "PERSPEX"))
        or ("CLEAR" in _finishes_upper and "SCRAPED" in _finishes_upper)
        or ("CLEAR" in _finishes_upper and "LENS" in _desc_upper)
    )
    if _is_acrylic:
        return "ACRYLIC"

    # Wire/tube geometry -> MILD_STEEL override
    # Catches parts where PDF omits explicit material but ops/description
    # reveal fabricated steel (wire basket frames, tube sections, weldments).
    _ops_upper = " ".join(str(o) for o in (part.get("textual_operations") or [])).upper()
    _sizes_upper = " ".join(str(x) for x in (part.get("overall_sizes_mm") or [])).upper()
    _is_wire_tube = (
        "WIRE_FORMING" in _ops_upper
        or "WIRE FORMING" in _ops_upper
        or bool(re.search(r"\d+\s*[Xx]\s*\d+.*TUBE", _desc_upper + " " + _sizes_upper))
        or "WELDMENT" in _desc_upper
        or "WELDMENT" in pn_u
    )
    # The literal list this used to test — "", UNKNOWN, TIMBER, WOOD, NONE — is two ideas:
    # the text said nothing, or it said timber over geometry that cannot be timber. Both
    # survive; unresolvable noise now joins the first, so a wire frame whose material read
    # "Card" is steel for the same reason a blank one is.
    _raw_resolved = normalise_material(raw)
    if _is_wire_tube and (_raw_resolved is None or _raw_resolved == "TIMBER"):
        return "MILD_STEEL"

    # Timber joinery / boards when description clearly says so (before generic SA rule).
    if timber:
        return "TIMBER"

    # Shelf-assembly lines: SAxx can be wood — only force steel if no timber cues.
    if _METAL_SA_RE.search(pn.upper()) and not timber:
        return "MILD_STEEL"

    if pn_steel or blob_steel:
        return "MILD_STEEL"

    # PN suffix inference: -xxM=MILD_STEEL, -xxA=ACRYLIC, -xxT=MDF
    #
    # THE GATE ASKED THE WRONG QUESTION. It asked whether the material text was ABSENT
    # ("", UNKNOWN, NONE) when what it means is whether the text told us anything. Those are
    # the same on a blank drawing and different on a noisy one, and the noisy case is the
    # common one: "Card", "Card 2mm", "N/A", "TBC", "SEE DRAWING" are all non-empty and all
    # resolve to nothing. Under the old gate each of them silently outranked SDI's own
    # numbering convention, and the part went forward with no material — which is how job
    # 12392's -01M and -02M brackets, parts we laser and fold ourselves, came back as
    # purchased components with an AI market estimate standing in for the steel.
    #
    # Still weak, and still last: every branch above — a stated material, timber cues,
    # acrylic cues, wire/tube geometry — has already had its say. A convention only speaks
    # where the drawing did not.
    if not _raw_says_something:
        _sfx = part_code_conventions.material_suffix(pn_u.strip())
        _by_letter = {"M": "MILD_STEEL", "A": "ACRYLIC", "T": "MDF"}
        if _sfx in _by_letter:
            return _by_letter[_sfx]
    return normalise_material(raw)


def infer_operations(text: str) -> List[str]:
    ops: List[str] = []
    upper = text.upper()
    for keyword in _OPERATION_KEYS_SORTED:
        code = OPERATION_INFERENCE_MAP[keyword]
        if keyword in upper and code not in ops:
            ops.append(code)
    return ops


# Boilerplate blocks that appear on every M&S/SDI drawing page border.
# These must be stripped before operation inference so spec text doesn't
# bleed into per-part operations (e.g. "WELD SPECIFICATION" → welding).
_BOILERPLATE_RE = re.compile(
    r"WELD\s+SPECIFICATION[:\s].*"
    r"|FINISH\s+SPECIFICATIONS?[:\s].*"
    r"|CHINA\s+MATERIAL\s+SPECIFICATIONS?[:\s].*"
    r"|GENERAL\s+TOLERANCES?[:\s].*"
    r"|COPYRIGHT\s+M&S.*"
    r"|THIS\s+DRAWING\s+IS\s+THE\s+PROPERTY.*"
    r"|DO\s+NOT\s+SCALE\s+FROM\s+DRAWING.*"
    r"|ALL\s+DIMENSIONS\s+ARE\s+IN\s+MM.*"
    r"|UNLESS\s+OTHERWISE\s+STATED.*"
    r"|MAY\s+NOT\s+BE\s+COPIED.*"
    r"|SPECIFICATION\s+IS\s+\d+\s+GRIT.*"
    r"|RESISTANCE\s+WELDING\s+WIRE\s+TO\s+WIRE.*"
    r"|POWDERCOATING[:\s]+BETWEEN.*"
    r"|CHROME\s+PLATING[:\s].*"
    r"|BRIGHT\s+ZINC\s+PLATING[:\s].*"
    r"|TIMBER\s+PRODUCTS?[:\s].*"
    r"|FSC\s+CERTIFIED.*",
    re.IGNORECASE,
)


def _strip_spec_boilerplate(text: str) -> str:
    """Remove drawing-border spec blocks before operation inference."""
    return _BOILERPLATE_RE.sub(" ", text)


def apply_material_context_normalisation(parts: List[Dict[str, Any]]) -> None:
    """Apply context-aware material codes before costing so estimator sees corrected metals."""
    for part in parts:
        inferred = normalise_material_for_part(part)
        if inferred:
            # INFERENCE, rank 20. This reads the part number, the description and any stated
            # material and picks a family — a reading of text, not an observation of the part.
            # It ran unattributed and unconditionally, so it could overwrite a material the
            # MODEL had supplied simply by running later.
            apply_field(part, "normalized_material", inferred, "inference")


def _resolve_parts(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    writeup_parts = summary.get("manufacturing_writeup", {}).get("parts")
    if isinstance(writeup_parts, list) and writeup_parts:
        return writeup_parts
    top_parts = summary.get("parts")
    if isinstance(top_parts, list) and top_parts:
        return top_parts
    return []


def normalise_json(raw_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-process scan summary into a consistent v4-style view without
    destructively replacing richer upstream fields.
    """
    normalised = dict(raw_json)
    normalised["schema"] = V4_SCHEMA
    normalised["processed_at"] = datetime.now(timezone.utc).isoformat()

    debug_mat = os.getenv("MATERIAL_NORMALISATION_DEBUG", "").lower() in {"1", "true", "yes"}

    parts = _resolve_parts(normalised)
    for part in parts:
        previous = part.get("normalized_material")
        inferred_material = normalise_material_for_part(part)
        if inferred_material:
            apply_field(part, "normalized_material", inferred_material, "inference")

        if debug_mat and inferred_material and inferred_material != previous:
            logger.info(
                "Material normalised: part=%s | %s → %s | desc=%s",
                part.get("part_number"),
                previous,
                inferred_material,
                str(part.get("description") or "")[:80],
            )

        process_notes_text = _strip_spec_boilerplate(" ".join(
            str(n) for n in (part.get("process_notes") or []) + (part.get("textual_operations") or [])
        ))
        inferred_ops = infer_operations(process_notes_text)
        existing_ops = part.get("textual_operations", []) or []
        combined_ops: List[str] = []
        for op in list(existing_ops) + inferred_ops:
            if op not in combined_ops:
                combined_ops.append(op)
        if combined_ops:
            part["textual_operations"] = combined_ops

        if not isinstance(part.get("confidence"), dict) or not part.get("confidence"):
            part["confidence"] = {"overall": 0.0}

        part.setdefault(
            "provenance",
            {
                "source": "pdf_scan_v4",
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "geometry_reliability": part.get("geometry_rollup", {}).get("confidence", {}).get("geometry_reliability", 0.0),
            },
        )

    if parts:
        codes = [p.get("normalized_material") for p in parts if p.get("normalized_material")]
        if codes:
            majority = Counter(codes).most_common(1)[0][0]
            da = normalised.setdefault("document_analysis", {})
            if isinstance(da, dict):
                pf = da.setdefault("primary_fields", {})
                if isinstance(pf, dict):
                    pf.setdefault("normalized_material_majority", majority)

    normalised["normalisation_meta"] = {
        "parts_normalised": len(parts),
        "normalised_at": datetime.now(timezone.utc).isoformat(),
        "schema": V4_SCHEMA,
        "material_context_rules": "horti_v1",
    }

    return normalised
