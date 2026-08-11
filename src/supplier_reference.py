"""
supplier_reference.py — the manufacturer's own number for a bought-in part, kept as a key.

WHY THIS EXISTS. 11650's bill of materials names its purchased parts the way the drawing
does: "ESSENTRA FOOT-466122", "246.41.745", "KSM4----N3--5A0". Those numbers are the
supplier's primary key. They are read off the sheet, printed in the description, and then
thrown away: the bought-in recogniser mints its own code —

    code_guess = "BI-" + re.sub(r"[^A-Z0-9]", "", phrase.upper())[:18]

— and every price lookup downstream is keyed on BI-BINDINGSCREW. Nothing in any catalogue,
in UDEF, or at any supplier has ever heard of BI-BINDINGSCREW, so the exact-match arm of
every lookup misses by construction and the line falls through to a fuzzy description match
or to nothing at all. The feet, knobs and catches on that job came out at GBP 0.00.

THIS IS THE PREREQUISITE FOR ANY SUPPLIER API, AND IT IS WORTH DOING WITHOUT ONE. An
integration that queries 466122 can return a price; one that queries BI-BINDINGSCREW returns
empty and looks broken, when the fault is a hundred lines upstream of the connector. But the
same key is what makes an account price file loadable — and an account file beats a public
API under this engine's own rules, because it can be ACCOUNT_FEED (reproducible AND firm)
where a public list price is only CATALOGUE (reproducible, never firm). So the reference is
captured for its own sake, and any connector is a later consumer of it.

THE SAFETY PROPERTY THAT MAKES THE MATCHING RULES CHEAP. Everything recognised here is used
for EXACT-MATCH lookups only — never LIKE, never fuzzy, never as tokens for a score. A false
candidate therefore costs one query that returns nothing. A missed candidate costs a real
price. The rules below are tuned in that light: tight enough to keep the noise low, and never
so tight that a real reference is dropped for want of a supplier's name being on a list.

WHAT IS DELIBERATELY NOT HERE. No supplier names, no part numbers, no job numbers, no
prefixes learned from one drawing. A convention is a SHAPE plus the CONTEXT it sits in, so a
supplier nobody has bought from yet is read on the first job that names them.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

from part_code_conventions import looks_like_a_drawing_number

__all__ = [
    "REFERENCE_SCHEMA",
    "CONVENTION_RANK",
    "SYNTHESISED_KEY_PREFIX",
    "synthesise_key",
    "is_synthesised_key",
    "find_references",
    "lookup_keys",
    "describe_keys",
    "attach_references",
    "identity_keys",
    "same_article_groups",
]

REFERENCE_SCHEMA = "supplier_reference.v1"

# ── THE FIVE CONVENTIONS, AND WHY THEY RANK AS THEY DO ──────────────────────────────
#
# Rank is strength of evidence that the token IS a reference, not a preference between
# suppliers. The declared form wins outright because the drawing has said so in words; the
# bare digit run is last because it is the only one whose shape it shares with a dimension.
DECLARED = "declared_reference"      # "PART No. 466122" — the sheet labels it
DOTTED = "dotted_catalogue"          # 246.41.745 — Häfele and most European article numbers
CONFIGURED = "configured_code"       # KSM4----N3--5A0 — a configurator's padded code
PREFIXED = "prefixed_serial"         # DWG491667 — a short alpha prefix then a serial
BARE = "bare_serial"                 # 466122 — digits alone, and the riskiest

CONVENTION_RANK = {DECLARED: 95, DOTTED: 90, CONFIGURED: 80, PREFIXED: 70, BARE: 50}

# ── keys this engine invented ───────────────────────────────────────────────────────
# A minted key is not a reference and must never be presented as one. Reports and unpriced
# reasons ask this so "no price found" can distinguish "we looked up the manufacturer's
# number and nobody had it" from "we never had a number to look up" — different problems,
# different owners, and only the second is ours to fix by reading the drawing better.
SYNTHESISED_KEY_PREFIX = "BI-"


def synthesise_key(phrase: Any) -> str:
    """Mint a stable internal code for a purchase whose real reference we do not have.

    Lives here, beside is_synthesised_key, because the two must agree about the marker. They
    did not need to before: the prefix was written in the recogniser and read nowhere, so
    nothing downstream could tell a minted key from a code off a drawing.
    """
    return SYNTHESISED_KEY_PREFIX + re.sub(r"[^A-Z0-9]", "", str(phrase or "").upper())[:18]


def is_synthesised_key(code: Any) -> bool:
    """True when this part number was minted by this engine rather than read off a drawing."""
    return str(code or "").strip().upper().startswith(SYNTHESISED_KEY_PREFIX)


# ── shapes ──────────────────────────────────────────────────────────────────────────
# A candidate token keeps the characters a reference is allowed to contain: letters, digits,
# dots, slashes and dashes. Splitting on dots or dashes first would destroy 246.41.745 and
# KSM4----N3--5A0, which are the two shapes hardest to recover afterwards.
_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9./\-]*")

# THREE GROUPS MINIMUM, NOT TWO. "246.41.745" is unmistakable; "246.41" is a decimal number
# and there is no way to tell it from one. Accepting two groups would read every price,
# thickness and tolerance on the sheet as an article number.
_DOTTED = re.compile(r"^\d{1,5}(?:\.\d{1,5}){2,}$")

# A configurator pads its options with runs of dashes: MISUMI, Festo and SMC all do it. Two
# consecutive dashes almost never occur in prose or in an SDI code, which is what makes this
# safe to accept on shape alone.
_DOUBLE_DASH = re.compile(r"--")

# A short alpha prefix then a serial: DWG491667, ABC1234. Capped at four letters so SDI's own
# catalogue codes stay out of it — FIXING125 and ELECTRICS are six and nine letters, and
# reading those as manufacturer references would key the lookup on the wrong catalogue.
_PREFIXED = re.compile(r"^[A-Z]{2,4}\d{4,}$")

# FIVE DIGITS MINIMUM. Four-digit runs are years, quantities, drawing sizes and — above all —
# millimetre dimensions, which appear on every sheet in the building. Five is where catalogue
# numbers start and where dimensions have largely stopped.
_BARE = re.compile(r"^\d{5,10}$")

# A year-month stamp reads as a six-digit serial and is not one.
_DATESTAMP = re.compile(r"^(?:19|20)\d{2}(?:0[1-9]|1[0-2])\d{0,2}$")

# An SDI-shaped catalogue code — leading alpha run, optional digits — is a key we already
# hold and route elsewhere. bought_in_pricing splits descriptions on exactly this shape.
_SDI_CATALOGUE_CODE = re.compile(r"^[A-Z]+\d*$")

# ── WHAT A NUMBER IS DOING WHEN IT IS NOT A PART NUMBER ─────────────────────────────
# The words that make a digit run a measurement, a count, a revision or a price. Checked on
# the text either side of the token, because the shape alone cannot tell 466122 from a
# dimension and the sheet almost always says which it means.
_UNITS_AFTER = (
    "MM", "CM", "M", "MTR", "METRE", "KG", "G", "GSM", "THK", "DIA", "DEG", "OFF",
    "NO", "NR", "PCS", "PC", "EA", "LG", "LONG", "WIDE", "HIGH", "CTS", "CRS", "MICRON",
    # A dimension is written with the multiplier on EITHER side of the number it bounds, so
    # the same word has to be refused in both directions: "12000 X 600" and "600 X 12000"
    # are one dimension read from its two ends.
    "X",
)
_CUES_BEFORE = (
    "X", "DIA", "QTY", "QUANTITY", "REV", "SCALE", "SHEET", "THK", "THICKNESS",
    "WIDTH", "HEIGHT", "LENGTH", "DEPTH", "PITCH", "TOL", "OF", "SIZE",
)
# The drawing naming a reference in words. This is the strongest evidence available and it
# is a house style rather than a supplier's, so it inherits to every sheet that uses it.
_REFERENCE_CUES = (
    "PART NO", "PART NUMBER", "PARTNO", "PART N", "P N", "MPN", "MFR NO", "MFG NO",
    "MANUFACTURER PART", "MANUFACTURERS PART", "CAT NO", "CATALOGUE NO", "CATALOG NO",
    "ART NO", "ARTICLE NO", "ARTICLE NUMBER", "ORDER CODE", "ORDER NO", "ORDERING CODE",
    "REF NO", "SUPPLIER REF", "SUPPLIER CODE", "PRODUCT CODE", "ITEM CODE", "STOCK CODE",
    "CODE", "REF",
)
_TRAILING_WORD = re.compile(r"([A-Z0-9 ]{0,24})$")
_LEADING_WORD = re.compile(r"^\s*([A-Z]+)")


def _preceding_words(text: str, start: int) -> List[str]:
    """The last few alphanumeric words before this token, most recent first."""
    before = text[max(0, start - 26):start]
    m = _TRAILING_WORD.search(re.sub(r"[^A-Z0-9 ]+", " ", before))
    words = (m.group(1).split() if m else [])
    return list(reversed(words))


def _declared_here(text: str, start: int) -> bool:
    """True when the sheet labels what follows as a reference: 'PART No. 466122'.

    Compared against the run of text immediately before the token with punctuation flattened,
    so 'PART No.', 'PART-NO:', 'P/N' and 'Part no ' all read alike — a drawing punctuates
    this differently every time and the label is the same fact in each.
    """
    before = re.sub(r"[^A-Z0-9]+", " ", text[max(0, start - 26):start]).strip()
    return any(before.endswith(cue) for cue in _REFERENCE_CUES)


def _is_measurement_context(text: str, start: int, end: int) -> bool:
    """True when the surrounding words make this digit run a measurement, count or revision."""
    after = _LEADING_WORD.match(re.sub(r"[^A-Z]+", " ", text[end:end + 12]))
    if after and after.group(1) in _UNITS_AFTER:
        return True
    if text[end:end + 1] in {"%", "°", "Ø"}:
        return True
    words = _preceding_words(text, start)
    if words and words[0] in _CUES_BEFORE:
        return True
    # A currency marker sits hard against its number and survives no word split.
    return bool(re.search(r"[£$€]\s*$", text[max(0, start - 4):start]))


# A WORD GLUED ONTO A CODE BY THE TEXT EXTRACTOR. 11650's BOM cell reads
# "KSM6----N5--5A0Knob Diameter 19.1 mm" — the code and the next word arrive with no space
# between them, which is ordinary in extracted PDF text where a cell wraps. Every other
# convention here is a whole-token match and is immune; the configured form is recognised by
# SEARCHING for a double dash, so it happily swallows the tail.
#
# Only a trailing ALPHABETIC run following a DIGIT is trimmed. An option group ending in a
# digit is where these codes stop, and three letters is long enough that a real trailing
# option is not mistaken for a word. The raw token is kept on the record either way, so if
# the trim is ever wrong the original is still readable — and because every lookup is exact,
# a wrongly trimmed key costs a query that misses, exactly as the glued one would have.
_GLUED_WORD = re.compile(r"(?<=\d)([A-Z]{3,})$")


def _unglue(token: str) -> str:
    """A configured code with the following word stripped off it."""
    return _GLUED_WORD.sub("", token)


def _could_be_a_code(token: str) -> bool:
    """The floor for a token the DRAWING has already labelled a reference.

    Shape carries the whole burden only when nothing else speaks. Where the sheet says "PART
    No." the label is the evidence, and holding the token to the five-digit floor built for
    unlabelled digit runs would refuse the clearest statement a drawing can make.
    """
    return len(token) >= 3 and any(c.isdigit() for c in token)


def _classify(token: str) -> Optional[str]:
    """Which convention this token matches on shape alone, or None."""
    if _DOTTED.match(token) and sum(c.isdigit() for c in token) >= 6:
        return DOTTED
    if (_DOUBLE_DASH.search(token) and len(token) >= 6
            and any(c.isalpha() for c in token) and any(c.isdigit() for c in token)):
        return CONFIGURED
    if _PREFIXED.match(token):
        return PREFIXED
    if _BARE.match(token) and not _DATESTAMP.match(token):
        return BARE
    return None


def _segments(token: str) -> List[str]:
    """The dash-separated pieces of a token, for references carried inside a phrase.

    "FOOT-466122" is how a drawing writes Essentra's 466122 next to the word for what it is,
    and the reference is only recoverable by looking inside the token. Done as a SECOND pass
    after the whole token fails to classify, so a configured code full of dashes is never
    shredded into its options.
    """
    return [s for s in token.split("-") if s]


def find_references(
    *texts: Any,
    known_part_numbers: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Every manufacturer/supplier reference these texts appear to contain, strongest first.

    Several texts are accepted because the reference reaches us split across fields — a BOM
    row's code cell and its description cell each hold half of "ESSENTRA FOOT-466122"
    depending on which reader produced the row.

    `known_part_numbers` are the codes this job already owns. They are excluded rather than
    ranked down: an SDI drawing number is not a supplier reference under any circumstances,
    and offering one as a lookup key would send the job's own part numbers to a supplier.
    """
    ours = {str(p or "").strip().upper() for p in (known_part_numbers or ()) if p}
    ours.discard("")
    seen: Set[str] = set()
    found: List[Dict[str, Any]] = []

    for raw in texts:
        text = str(raw or "").upper()
        if not text.strip():
            continue
        for m in _TOKEN.finditer(text):
            token = m.group(0).strip(".-/")
            if not token or token in ours:
                continue
            # OUR OWN NUMBERING IS NEVER A SUPPLIER'S. Asked of the whole token before any
            # splitting, because 11650-04-01A only looks like a drawing number while it is
            # still in one piece — in segments it is a five-digit "serial" and two counts.
            # The catalogue-code test is asked SECOND, because a short alpha prefix over a
            # long serial satisfies both shapes: DWG491667 reads as "alpha run then digits"
            # exactly as ELECTRICS001 does. The prefixed convention is the narrower claim —
            # two to four letters, four or more digits — so where both match, it decides, and
            # SDI's own longer-stemmed codes are still excluded.
            if looks_like_a_drawing_number(token) or (
                    _SDI_CATALOGUE_CODE.match(token) and not _PREFIXED.match(token)):
                continue
            declared = _declared_here(text, m.start())
            candidates = [(token, m.start(), m.end())]
            convention = _classify(token)
            if convention is None:
                # Only now look inside. A dash-joined word and number is a phrase, not a code.
                candidates = [
                    (seg, m.start() + token.index(seg), m.start() + token.index(seg) + len(seg))
                    for seg in _segments(token) if seg not in ours
                ]
            for cand, start, end in candidates:
                conv = _classify(cand)
                if conv is None and declared and _could_be_a_code(cand):
                    conv = DECLARED
                if conv is None or cand in ours:
                    continue
                # THE MEASUREMENT GUARD IS NOT WAIVED BY THE LABEL. A digit run is the only
                # shape that collides with a dimension, and it collides whatever word sits in
                # front of it — "PART No. 1200 MM" is a size, not a reference. So the label
                # lowers the length floor and nothing else.
                if cand.isdigit() and _is_measurement_context(text, start, end):
                    continue
                if declared:
                    conv = DECLARED
                cleaned = _unglue(cand) if _DOUBLE_DASH.search(cand) else cand
                if cleaned in seen:
                    continue
                seen.add(cleaned)
                entry = {
                    "schema": REFERENCE_SCHEMA,
                    "reference": cleaned,
                    "convention": conv,
                    "rank": CONVENTION_RANK[conv],
                    "found_in": str(raw),
                }
                if cleaned != cand:
                    entry["raw_token"] = cand      # nothing is hidden by the trim
                found.append(entry)

    found.sort(key=lambda r: (-r["rank"], r["reference"]))
    return found


def lookup_keys(part: Dict[str, Any]) -> List[str]:
    """The keys to try against a catalogue for this part, strongest first.

    The part's own code comes FIRST when it was read off a drawing and LAST when this engine
    minted it. That ordering is the whole change: a real code is the best key there is, and a
    minted one is the worst, and until now they were the same field and were tried the same
    way.
    """
    keys: List[str] = []
    code = str(part.get("part_number") or "").strip()
    if code and not is_synthesised_key(code):
        keys.append(code)
    for ref in part.get("supplier_references") or []:
        value = str((ref or {}).get("reference") or "").strip()
        if value and value not in keys:
            keys.append(value)
    if code and code not in keys:
        keys.append(code)
    return keys


def describe_keys(part: Dict[str, Any]) -> str:
    """One line naming what this part was looked up BY, for a report or a sheet cell.

    An unpriced line whose only key was invented here is a different fact from one whose
    manufacturer reference was tried and missed, and an estimator can act on the second.
    """
    refs = part.get("supplier_references") or []
    code = str(part.get("part_number") or "").strip()
    if refs:
        named = ", ".join(str(r.get("reference")) for r in refs[:3])
        return f"looked up on manufacturer reference {named}"
    if is_synthesised_key(code):
        return ("no manufacturer reference was found on the drawing — the lookup key "
                f"{code} was synthesised from the description")
    return f"looked up on {code}" if code else "no lookup key of any kind"


# ── TWO LINES, ONE ARTICLE ──────────────────────────────────────────────────────────
# 11650's cabinet BOM carries the same Essentra levelling foot twice:
#
#   ESSENTRA FOOT-466122   "FIXING1081-M8, 25MM FOOT, 25MM THREAD"    GBP 0.00   qty 2
#   FIXING1081             "Essentra Ref. 466122 - Levelling Foot..."  GBP 0.22   qty 2
#
# One line is priced from UDEF and one is not, and each line's description names the OTHER
# line's key. That is survivable only for as long as the second line stays at zero: the
# moment the reference makes it priceable, the job books four feet and pays for two it does
# not buy. So the join and this rule are one change, not two — pricing first would turn a
# visible GBP 0.46 gap into a hidden GBP 0.46 over-charge, which is strictly worse.
#
# AN ARTICLE NUMBER IS AN IDENTITY, WHICH IS WHY THIS IS SAFE. Two lines quoting the same
# manufacturer reference are the same manufactured article by definition — that is what the
# number means. Nothing here merges on description, on family or on supplier: the M4 knob
# (KSM4----N3--5A0) and the M6 knob (KSM6----N5--5A0) sit beside each other on this very
# sheet, same supplier, same words, GBP 0.00 and GBP 0.27, and they are different parts.


def identity_keys(part: Dict[str, Any]) -> Set[str]:
    """The manufacturer references that identify this line.

    Falls back to reading the part's own text when nothing has been attached yet. A BOM row
    built by a reader that predates the capture would otherwise present as having no identity
    at all — and "no identity" is exactly what makes two lines look like two parts.
    """
    refs = part.get("supplier_references")
    if not refs:
        refs = find_references(part.get("description"), part.get("part_number"))
    keys = {str((r or {}).get("reference") or "").strip().upper() for r in refs}
    keys.discard("")
    return keys


def same_article_groups(parts: Any) -> List[List[int]]:
    """Indices of the lines that name the same article, grouped. Singletons omitted.

    Corroborated ONLY by shared manufacturer reference, and by one line naming another's part
    number as a WHOLE TOKEN. Whole-token matters more than it looks: "FIXING1081-M8" contains
    the characters of FIXING1081 and also the characters of FIXING, which is a different part
    on the same sheet — a nylon washer at GBP 0.66. Substring matching would merge every
    FIXING line on every job into one.
    """
    rows = [p for p in (parts or []) if isinstance(p, dict)]
    codes = {str(p.get("part_number") or "").strip().upper(): i
             for i, p in enumerate(rows) if str(p.get("part_number") or "").strip()}
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_ref: Dict[str, int] = {}
    for i, p in enumerate(rows):
        for key in identity_keys(p):
            if key in by_ref:
                union(by_ref[key], i)
            else:
                by_ref[key] = i
        # A line whose description names another line's part number outright.
        for token in re.findall(r"[A-Z0-9]+(?:[.\-][A-Z0-9]+)*",
                                str(p.get("description") or "").upper()):
            j = codes.get(token)
            if j is not None and j != i:
                union(i, j)

    groups: Dict[int, List[int]] = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(i)
    return [sorted(g) for _root, g in sorted(groups.items()) if len(g) > 1]


def attach_references(part: Dict[str, Any],
                      known_part_numbers: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Record on a part every reference its own text carries. Returns the same part.

    Applied at the single point where a bought-in part is built, so nothing has to remember
    to call it per reader. A part that already carries references is left alone — a reference
    read from a supplier's own feed outranks anything recovered from a description.
    """
    if part.get("supplier_references"):
        return part
    refs = find_references(
        part.get("description"),
        part.get("part_number") if not is_synthesised_key(part.get("part_number")) else "",
        known_part_numbers=known_part_numbers,
    )
    if refs:
        part["supplier_references"] = refs
    part["part_number_is_synthesised"] = is_synthesised_key(part.get("part_number"))
    return part
