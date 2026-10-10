"""
part_identity.py — tolerant part-number / BOM / DXF identity for SDI drawing packs.

Drawing packs routinely use different labels for the same physical item (bay BOM,
detail title block, DXF filename). This module centralises normalisation and
alias resolution so estimators can cope without requiring FD to rename everything first.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

__all__ = [
    "normalize_part_code", "is_placeholder_identity", "dxf_alias_target",
    "resolve_estimate_code", "synthesise_bought_in_code", "is_engine_minted_code",
    "is_engine_minted_record", "is_category_split_identity", "is_engine_derived_identity",
    "parts_list_row_role",
]

# DXF filename / legacy drawing numbers -> BOM detail part
DXF_TO_BOM_ALIASES: Dict[str, str] = {
    "1148": "1448-02",
    "1453-01C": "1453-GA-C",
    "1453": "1453-GA-C",
}

# Assembly / GA codes -> preferred fab detail when only one child exists in scope
GA_TO_DETAIL_PREFERENCE: Dict[str, str] = {
    "1450": "1450-01C",
    "1450-GA": "1450-01C",
    "1453": "1453-01C",
    "1453-GA": "1453-01C",
    "1453-GA-C": "1453-01C",
    "1453-GAC": "1453-01C",
}

# Catalogue tokens: extra description phrases tried against the parts DB / price book
CATALOGUE_DESC_ALIASES: Dict[str, List[str]] = {
    "ELECTRICS": [
        "ELECTRICS 50CM LOOM LIGHTING ELECTRICS",
        "50CM LOOM LIGHTING ELECTRICS",
        "LOOM LIGHTING ELECTRICS",
        "50CM LOOM",
    ],
}

_SPLIT_KICK_RE = re.compile(
    r"(\d+)\s+1453-GA-\s+([A-Z])\s+(500mm\s+KICK\s+PLATE\s+ASSEMBLY)\s+(\d+)\b",
    re.IGNORECASE,
)
_GA_WALL_RE = re.compile(
    r"(\d+)\s+(3886-GA-)\s+WALL\s+(BAY\s+BUDGET\s+LOWER\s+LEG)\s+(\d+)\b",
    re.IGNORECASE,
)
_HEADER_GA_RE = re.compile(
    r"(\d+)\s+(1455-C-)\s+GA\s+(500mm\s+MILWAUKEE\s+HEADER)\s+(\d+)\b",
    re.IGNORECASE,
)
_KICK_ROW_RE = re.compile(
    r"(\d+)\s+(1453-GA-C?)\s+(500mm\s+KICK\s+PLATE\s+ASSEMBLY)\s+(\d+)\b",
    re.IGNORECASE,
)


def split_catalogue_token(code: str) -> str:
    """ELECTRICS50CM -> ELECTRICS (BOM tokens glued to size suffixes)."""
    c = str(code or "").strip().upper().replace(" ", "")
    m = re.match(r"^(ELECTRICS)(50CM|100CM|1M)(.*)$", c, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return c


def normalize_part_code(raw: Any) -> str:
    """Canonical part code: collapse spaces, join spaced GA tokens, strip trailing '-'."""
    s = str(raw or "").strip().upper()
    if not s:
        return ""
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", " ", s).strip()
    # "1450 - GA" / "1450 GA" -> 1450-GA
    m = re.match(r"^(\d{4})\s+(?:-\s*)?GA([A-Z]?)$", s, re.IGNORECASE)
    if m:
        suffix = m.group(2).upper()
        return f"{m.group(1)}-GA{suffix}" if suffix else f"{m.group(1)}-GA"
    m = re.match(r"^(\d{4}-[A-Z0-9]+)\s+GA([A-Z]?)$", s, re.IGNORECASE)
    if m:
        suffix = m.group(2).upper()
        base = m.group(1).upper()
        return f"{base}-GA{suffix}" if suffix else f"{base}-GA"
    # A VERSION MARK IS NOT PART OF THE CODE (D-314). 12645's shelter sheet lists its body as
    # "12645-01GA V2"; the body's own drawing is "12645-01GA". Joined up as "12645-01GAV2" it
    # became a second part, priced by AI at £557 as a bought-in body on top of the body's own
    # 32 fabricated lines. Dropped only when what remains is still a drawing number, and only
    # where the mark is set apart by a space or underscore — "ABC-V2" is left as written.
    _unversioned = re.sub(r"(?:[ _]+(?:V\d{1,2}|REV\.? ?[A-Z0-9]{1,2}))+$", "", s).strip()
    if _unversioned != s:
        try:
            from part_code_conventions import looks_like_a_drawing_number as _lld
        except Exception:                                        # noqa: BLE001
            _lld = None
        if _lld is not None and _lld(_unversioned.replace(" ", "")):
            s = _unversioned
    s = s.replace(" ", "")
    s = re.sub(r"-+$", "", s)
    # STRIP TRAILING DESCRIPTION BLEED ("11650-04-01A-WALL" -> "11650-04-01A"), BUT ONLY WHEN
    # WHAT REMAINS IS STILL A DRAWING NUMBER.
    #
    # The rule was written for codes that begin with a job number, and it silently ate every
    # code that does not. "BI-SCREW", "BI-HEADBOLT", "BI-DOMERIVET", "BI-HEXNUT" and
    # "BI-LEDDOWNLIGHTS" — five distinct lines on 12552 alone — all normalised to "BI", so
    # every BI- bought-in in the job shared one identity. "SA-BRACKET" became "SA" and
    # "M4-NUT" became "M4". Where callers key a dict on this, five lines collide on one slot;
    # where they compare two normalised codes for equality, two different parts test equal.
    #
    # The shape test is the one part_code_conventions already publishes, so this asks the
    # same question as everything else that asks it rather than adding a seventh spelling.
    _trimmed = re.sub(r"-(?!GA$|CGA$)[A-Z]{3,}$", "", s)
    if _trimmed != s:
        try:
            from part_code_conventions import looks_like_a_drawing_number
        except Exception:                                        # noqa: BLE001
            looks_like_a_drawing_number = None                   # noqa: N806
        if looks_like_a_drawing_number is None or looks_like_a_drawing_number(_trimmed):
            s = _trimmed
    if s and s[0].isalpha():
        s = split_catalogue_token(s)
    return s


# Codes a drawing prints where it has no code to print. They are not identities, and a
# BOM line carrying one must never become the canonical target another line merges INTO:
# on job 11350 the M4 wing nut was absorbed into a part numbered "-", which then appeared
# in the hierarchy and in the assembly route as a participant.
_PLACEHOLDER_CODES = frozenset({
    "", "-", "--", "---", ".", "N/A", "NA", "TBC", "TBA", "NONE", "?", "X", "XX",
})


# A drawing labels a BOM cell as often as it fills one: "VITAL PARTS: LOW068" is a label
# and a code, and the label travelled with it all the way to UDEF, which was asked for a
# part called "VITAL PARTS: LOW068" and had nothing. The code is on the right of the colon.
#
# A HYPHEN INSIDE A CODE IS NOT A LABEL (D-379). 12173-03-GA prints "FIXING" in the code
# cell of its two pan-head screw rows (items 5 and 6); "FIXING-3.5-X12MM-PAN-HEAD" is the
# identity category_code_identities gives the x12 row, not a code the drawing printed
# (corrected, D-383). "FIXING-" was read as a label and stripped to "3.5-X12MM-PAN-HEAD",
# while the parts-list edge kept the split identity — so one screw became two lines and the
# ×16 screw's own row read as "stated and not carried". A label is set off by a colon, or
# by a hyphen with space on both sides ("BOUGHT IN - LOW068"); a hyphen joining two parts
# of a code is the code ("FIXING-125", "PART-01", "ITEM-12" stay whole). An identity the
# engine derived (printed_code / identity_source on the row) is never label-stripped at all —
# see is_engine_derived_identity.
_CODE_LABEL_PREFIX = re.compile(
    r"^\s*(?:VITAL\s+PARTS?|STD\s+PARTS?|STANDARD\s+PARTS?|BOUGHT[\s-]?IN|PART\s*(?:NO|CODE)?"
    r"|ITEM|SUPPLIER|FIXINGS?|HARDWARE)(?:\s*:\s*|\s+-\s+)(?=\S)",
    re.IGNORECASE)


def is_engine_derived_identity(row: Any) -> bool:
    """True when a row's code was written by this engine — a category split
    ("FIXING-<article>", printed_code set) or a minted identity (identity_source set) — rather
    than read off a code cell. Such a code is ours, not a labelled cell, and the label
    stripper must never rewrite it (D-383)."""
    return isinstance(row, dict) and bool(row.get("printed_code") or row.get("identity_source"))


def strip_code_label(raw: Any) -> str:
    """The code a labelled BOM cell actually names.

    "VITAL PARTS: LOW068" -> "LOW068". Only a KNOWN label is stripped and only when
    something follows it, so a code that merely contains a colon is untouched and a cell
    holding nothing but a label stays exactly as it was rather than becoming empty.
    """
    text = str(raw or "").strip()
    stripped = _CODE_LABEL_PREFIX.sub("", text).strip()
    return stripped or text


_THREAD = re.compile(r"(?<![A-Z0-9])M(\d+(?:\.\d+)?)(?!\.?\d)")


def thread_sizes(description: Any) -> frozenset:
    """The metric thread sizes a description names: "M4x12mm PEM STUD" -> {"4"}.

    ONE READING OF A THREAD FOR EVERY MATCHER. 11650-06's M4 PEM stud was poured into
    FIXING632, an M6 stud, because a description matcher dropped the thread and kept "PEM",
    "STUD" and "12". D-214 taught the estimator's matcher; the route compiler's alias pass
    tokenised the thread away as well (it drops every M-number), so the same M4 could still
    be aliased onto an M6 identity there. Every matcher asks this one function.
    """
    return frozenset(_THREAD.findall(str(description or "").upper()))


def threads_differ(a: Any, b: Any) -> bool:
    """True when both descriptions name a thread and the threads are not the same."""
    ta, tb = thread_sizes(a), thread_sizes(b)
    return bool(ta and tb and ta != tb)


_IMPERIAL_THREAD = re.compile(
    r"\b(?:WHITWORTH|BSW|BSF|BSP|UNC|UNF|(?:HALF|QUARTER|THREE[\s-]QUARTERS?)\s+INCH)\b"
    r"|\b\d+\s*/\s*\d+\s*(?:\"|IN\b|INCH)", re.IGNORECASE)


def thread_names_disagree(code: Any, description: Any) -> str:
    """Why a line's code and its description name different threads, or "".

    12645-01GA's parts list prints "Half Inch Whitworth Nut" in the code column and "M8 FULL
    NUT BZP GRADE 8" in the description — an imperial nut and a metric one on the same row.
    The line was priced as the code (the Udef row for a half-inch Whitworth nut) and nothing
    asked which is meant. Dave Wright, 18 Sep: "Would need to stop it making presumptions" —
    so the disagreement is put to a person, not settled by whichever column is read first
    (D-347)."""
    c, d = str(code or ""), str(description or "")
    c_imp, d_imp = bool(_IMPERIAL_THREAD.search(c)), bool(_IMPERIAL_THREAD.search(d))
    c_met, d_met = thread_sizes(c), thread_sizes(d)
    if (c_imp and d_met) or (d_imp and c_met):
        return (f"the code '{c}' names an imperial thread and the description '{d}' a "
                f"metric one" if c_imp else
                f"the code '{c}' names a metric thread and the description '{d}' an "
                f"imperial one")
    if c_met and d_met and c_met != d_met:
        return (f"the code '{c}' names M{'/M'.join(sorted(c_met))} and the description "
                f"'{d}' M{'/M'.join(sorted(d_met))}")
    return ""


def stem_duplicate_target(code: Any, others: Any) -> str:
    """The fuller code this one is a truncated stem of, or "" when it stands alone.

    ONE SCREW, TWO LINES, BOTH UNPRICEABLE. 12422-24's BOM carried "79814P613  3.5 x 16mm
    Pan Head Wood Screw" qty 4 AND "79814P  3.5 x 16mm Pan Head Wood Screw" qty 4 — the same
    four screws, extracted twice, once with the code truncated. The stem is not a code, so
    UDEF has no row for it and the line can never be priced; meanwhile the quantity is
    double-counted across two rows an estimator has to notice and merge by hand.

    A code that is a strict PREFIX of another code on the same BOM is a truncation of it.
    Required: the stem must be at least four characters (so "M4" does not swallow "M4X8"),
    and the character the longer code continues with must be alphanumeric — "FIXING" is a
    stem of "FIXING433", while "11350-01" is NOT a stem of "11350-01-02", because the
    continuation there is a separator and that is a real parent/child relationship, not a
    truncation.

    AMBIGUITY IS NOT RESOLVED, IT IS REPORTED. 12422-24 also carries a bare "FIXING", and
    both "FIXING433" and "FIXING51" are on the same BOM. Merging it into either is wrong
    half the time and invisible once done, so a stem with more than one candidate returns ""
    and stays its own visible, unpriced line for an estimator to resolve. Declining a merge
    costs a row somebody can see; inventing one costs a part its identity.
    """
    stem = normalize_part_code(strip_code_label(code))
    if len(stem) < 4:
        return ""
    matches = []
    for other in (others or []):
        full = normalize_part_code(strip_code_label(other))
        if len(full) <= len(stem) or not full.startswith(stem):
            continue
        if not full[len(stem)].isalnum():
            continue          # a separator means hierarchy, not truncation
        if full not in matches:
            matches.append(full)
    return matches[0] if len(matches) == 1 else ""


def is_placeholder_identity(part_number: Any) -> bool:
    """True when a code says 'no code', rather than naming a part."""
    text = str(part_number or "").strip().upper()
    if text in _PLACEHOLDER_CODES:
        return True
    # A code made only of separators is the same statement in another form.
    return bool(text) and not re.search(r"[A-Z0-9]", text)


# A drawing often leaves the part-number cell blank for standard hardware. Those rows still
# need a stable identity BEFORE the canonical graph is built; minting it later in file_scan
# is why 11350's wing nuts and PEM studs were visible in the workbook and absent from the
# hierarchy and the route compiler — two BOM authorities, one of which the estimator sees.
# One shared mapping keeps every ingestion path from inventing a different code for the same
# words. Generic hardware vocabulary, not a job-number exception.
_BOUGHT_IN_CODE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"SELF[\s-]?CLINCH.*NUT|CLINCH.*NUT", "BI-SELFCLINCHNUT"),
    (r"KNURLED.*KNOB", "BI-KNURLEDKNOB"),
    (r"KNURLED.*NUT", "BI-KNURLEDNUT"),
    (r"THREADED.*PEM.*STUD|PEM.*STUD", "BI-PEMSTUD"),
    (r"KEYHOLE.*PEM", "BI-KEYHOLEPEM"),
    (r"MUSHROOM.*THUMB|THUMB.*SCREW", "BI-THUMBSCREW"),
    (r"BUTTON.*HEAD.*SCREW", "BI-BUTTONSCREW"),
    (r"DOME.*RIVET|POP.*RIVET|RIVET", "BI-RIVET"),
    (r"WING.*NUT", "BI-NUT"),
    (r"NUT", "BI-NUT"),
    (r"SCREW", "BI-SCREW"),
    (r"WASHER", "BI-WASHER"),
    (r"BOLT", "BI-BOLT"),
)


def synthesise_bought_in_code(description: Any, fallback: Any = "") -> str:
    """A stable code for an uncoded bought-in row, or "" when the words name nothing.

    A real drawing or catalogue code always wins. A placeholder ("-", "TBC") is not an
    identity, so a description-based BI-* code stands in — and because it is derived from
    the words alone, every path that reads the same row derives the same code.
    """
    fallback_text = str(fallback or "").strip()
    if fallback_text and not is_placeholder_identity(fallback_text):
        fallback_upper = fallback_text.upper()
        # A code with no digits and a generic word in it is a category, not a part.
        vague = {"STD PART", "FIXING", "FIXINGTBC", "STDPART"}
        if fallback_upper not in vague and re.search(r"\d", fallback_upper):
            return fallback_text

    description_upper = " ".join(str(description or "").upper().split())
    for pattern, code in _BOUGHT_IN_CODE_PATTERNS:
        if re.search(pattern, description_upper):
            return code
    return ""


# A CODE THIS MODULE WROTE IS NOT A CODE ANYBODY CAN LOOK UP.
#
# synthesise_bought_in_code above is the right thing to do and it has one bad consequence: the
# placeholder it returns then sits in the code column of every document an estimator reads,
# looking exactly like a part number off the pack.
#
# Tim asked it straight on 11350-02: "M4 Wing Nut / M4 x 8mm Pems -- can it not take of system or
# internet for cost or is spec missing on drawing". Neither. The spec is on the drawing and is
# enough to buy from; there is simply no code for it, so the code arms of the price chain have
# nothing to ask, and the sheet said only "NOT PRICED -- needs a rate", which reads as a lookup we
# forgot. Naming the placeholder as ours is the whole answer.
#
# THE RECOGNISER LIVES BESIDE THE MINTER, deliberately. Put it anywhere else and it becomes a
# second private copy of this module's vocabulary, free to drift from the table above -- which is
# the defect test_one_hardware_vocabulary_serves_every_reader exists to prevent. It is a SHAPE
# test rather than a second list, so a new row added to _BOUGHT_IN_CODE_PATTERNS is recognised the
# moment it is minted, with nothing here to update.
#
# Deliberately NARROW: the prefix followed by LETTERS only. The cost of a false positive is a real
# purchased code called an invention, so a code carrying digits after the prefix keeps them and is
# somebody's.
_MINTED_CODE = re.compile(r"^BI-[A-Z]+$", re.IGNORECASE)

# ── AND THE OTHER MINT IN THIS ENGINE ───────────────────────────────────────────────
#
# concept_scan numbers a sighted part `<JOB>-CPT01` — job slug, then CPT and a sequence —
# because a render has no parts list to take a number from. That is a placeholder
# every bit as much as BI-SCREW is, and this recogniser did not know it: the first full
# concept book told an estimator that
# `5E09BE03B9741E5F-BDAB4AD-C11 CASTOR` "is a real code, so it was put to the purchasing
# catalogue... that is a gap on our side", and sent them to look for a row that could never
# have existed. A wrong diagnosis costs more than no diagnosis, because it is acted on.
#
# NARROW, for the reason above it: the whole string must be the shape concept_scan writes —
# an upper-case slug, then -CPT and exactly two digits, and nothing else. The CPT token is
# there for this test alone: `1234-C01` is a code a drawing could genuinely print, and
# calling somebody's part an invention is the one error this must never make.
_CONCEPT_CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]*-CPT\d{2}$")


_ARTICLE_NOISE = {"THE", "AND", "OF", "WITH", "FOR", "A", "AN", "TO", "IN"}


def _article_words(description: Any) -> List[str]:
    return [w for w in re.findall(r"[A-Z0-9]+(?:\.[0-9]+)?", str(description or "").upper())
            if w not in _ARTICLE_NOISE]


def category_code_identities(rows: Iterable[Any], code_key: str = "part_number",
                             desc_key: str = "description") -> Dict[int, str]:
    """{index: identity} for rows whose code names a CATEGORY shared by different articles.

    12312-01-GA prints nine purchased lines under "P/P" (LED driver, LED tape, grommets,
    Velcro hook, Velcro loop, two EPDM tapes, two cables) and two washers under "FIXING".
    Keyed on the code, every stage from the extract to the workbook kept one record per code,
    so one driver x2 stood in for the lot and the rest carried no line and no price.

    A category code (part_code_conventions.is_category_not_a_code) printed over rows that name
    DIFFERENT articles is not an identity. Each article becomes "<printed code>-<its words>",
    "P/P-LED-POWER-DRIVER-24V", so the line still shows the code the drawing printed and an
    estimator can rename it. Where every row under the code names one article, nothing changes
    and the existing vague-code handling (the BI- alias) applies. Derived from the row alone
    plus its siblings, so every stage that sees the same table derives the same identity.
    """
    try:
        from part_code_conventions import bare_code, is_category_not_a_code
    except Exception:                                               # pragma: no cover
        return {}
    listed = list(rows or [])
    groups: Dict[str, List[int]] = {}
    for i, row in enumerate(listed):
        if not isinstance(row, dict):
            continue
        code = str(row.get(code_key) or "").strip()
        if code and is_category_not_a_code(code):
            groups.setdefault(bare_code(code), []).append(i)
    out: Dict[int, str] = {}
    for idxs in groups.values():
        by_article: Dict[Tuple[str, ...], List[int]] = {}
        for i in idxs:
            words = tuple(_article_words(listed[i].get(desc_key)))
            if words:
                by_article.setdefault(words, []).append(i)
        if len(by_article) < 2:
            continue
        articles = list(by_article)
        slugs: Dict[Tuple[str, ...], str] = {}
        for words in articles:
            n = min(4, len(words))
            while True:
                slug = "-".join(words[:n])
                clash = [o for o in articles if o != words and "-".join(o[:n]) == slug]
                if not clash or n >= len(words):
                    break
                n += 1
            slugs[words] = slug
        used: Dict[str, int] = {}
        for words in articles:
            printed = str(listed[by_article[words][0]].get(code_key) or "").strip().upper()
            ident = f"{printed}-{slugs[words]}"
            used[ident] = used.get(ident, 0) + 1
            if used[ident] > 1:
                ident = f"{ident}-{used[ident]}"
            for i in by_article[words]:
                out[i] = ident
    return out


# Words in a description that do not name a thing: units and dimension markers.
_NOT_A_THING = frozenset({"MM", "X", "DIA", "THK", "THICK", "OD", "ID", "LG", "LONG", "L"})

# The roles a codeless parts-list row can play, in the order they are asked (D-383).
ROW_ROLE_CUT_LIST = "parent_cut_list"      # a piece of the parent's own section cut list
ROW_ROLE_BANDING = "parent_banding"        # the parent's edging, with or without a length
ROW_ROLE_INSTRUCTION = "instruction"       # a note, process or finish instruction, or "TBC"
ROW_ROLE_MATERIAL = "parent_material"      # the parent's own stock, named as a material
ROW_ROLE_SIZE = "parent_size"              # figures only: the parent's blank ("626 x 626")
ROW_ROLE_PART = "part"                     # words that name a thing we buy

# The words a note row opens with. Config (PARTS_LIST_NOTE_LEADS); this is the default.
_NOTE_LEADS_DEFAULT = ("NOTE", "NOTES", "SEE", "REFER")


def _cfg_words(cfg: Any, key: str, default: Iterable[Any]) -> Tuple[str, ...]:
    """A config vocabulary, upper-cased, or the module default when config does not say."""
    return tuple(str(w).upper() for w in ((getattr(cfg, key, None) if cfg is not None else None)
                                          or default))


def _config() -> Any:
    try:
        import config as _cfg
        return _cfg
    except Exception:                                            # noqa: BLE001
        return None


def _note_lead(up: str, cfg: Any = None) -> bool:
    leads = _cfg_words(cfg, "PARTS_LIST_NOTE_LEADS", _NOTE_LEADS_DEFAULT)
    return bool(leads) and bool(re.match(
        r"^\s*(?:" + "|".join(re.escape(w) for w in leads) + r")\b", up))


def _names_a_word(up: str, words: Iterable[Any]) -> str:
    """The first of these words (or phrases) the row names as a whole word, or ""."""
    for w in sorted({str(x).upper() for x in words if str(x).strip()}, key=len, reverse=True):
        pat = re.escape(w).replace(r"\ ", r"[\s-]+")
        if re.search(rf"(?<![A-Z]){pat}(?![A-Z])", up):
            return w
    return ""


def _leads_with(pattern: Any, text: str) -> bool:
    """Does the row OPEN with this reader's pattern? A process word that leads the row is an
    instruction ("WELD ALL ROUND"); the same word later in it qualifies a thing."""
    if not pattern:
        return False
    try:
        return bool(re.match(rf"\s*(?:{pattern})", text))
    except re.error:
        return False


# Words a finish statement uses besides the finish itself. Config may replace the list
# (PARTS_LIST_FINISH_QUALIFIER_WORDS); this is the default.
_FINISH_QUALIFIERS_DEFAULT = (
    "COAT", "COATED", "COATING", "FINISH", "FINISHED", "COLOUR", "COLOR", "COLOURED", "RAL",
    "MATT", "MATTE", "GLOSS", "GLOSSY", "SATIN", "SEMI", "TEXTURED", "SMOOTH", "FINE", "WET",
    "SELF", "MILL", "DIAMOND", "FLAME", "ALL", "OVER", "BOTH", "SIDES", "SIDE", "FACE",
    "FACES", "TOP", "ONLY", "AFTER", "BEFORE", "JET", "BLACK", "WHITE", "GREY", "GRAY",
    "CLEAR", "SILVER", "MICRON", "MICRONS", "BZP")
_FINISH_SUFFIX = r"(?:ED|ING|S|E|D|ISED|IZED|ISE|IZE)?"


def _is_finish_statement(up: str, cfg: Any = None) -> bool:
    """A row that only states a finish ("POWDER COAT RAL9005", "WET SPRAY MATT BLACK").

    The finish reader names a family, and every word of three letters or more is a finish
    word or a word finish statements use. A row that also names a thing is that thing:
    "CHROME HANDLE" and "GALVANISED BRACKET" are bought parts, and "RAWLPLUG" is not RAW."""
    try:
        from finish_rules import FINISH_FAMILIES, finish_families
    except Exception:                                            # noqa: BLE001
        return False
    if not finish_families(up):
        return False
    stems = [t for toks in FINISH_FAMILIES.values() for t in toks if " " not in t and "-" not in t]
    quals = {str(w).upper() for w in (getattr(cfg, "PARTS_LIST_FINISH_QUALIFIER_WORDS", None)
                                      or _FINISH_QUALIFIERS_DEFAULT)}
    for w in re.findall(r"[A-Z]+", up):
        if len(w) < 3 or w in _NOT_A_THING or w in quals:
            continue
        if any(re.fullmatch(re.escape(t) + _FINISH_SUFFIX, w) for t in stems):
            continue
        return False
    return True


# Words that qualify a material rather than name a thing. Config (MATERIAL_QUALIFIER_WORDS) is
# read first; this default keeps the row classifier and the catalogue sheet-rate search reading
# the same list when the key is absent.
_MATERIAL_QUALIFIERS_DEFAULT = (
    "SHEET", "SHEETS", "PLATE", "PANEL", "BOARD", "STOCK", "MATERIAL", "GRADE",
    "CLEAR", "OPAL", "WHITE", "BLACK", "GREY", "GRAY", "MATT", "GLOSS", "SATIN",
    "TEXTURED", "SMOOTH", "MR", "FR", "EXT", "INT", "STD", "THK", "NOM")


def _is_material_statement(up: str, cfg: Any = None) -> bool:
    """A row that names only a material, its qualifiers and figures ("18mm MDF, 626 x 626",
    "MILD STEEL"). The material normaliser reads it, and every word of three letters or more
    is part of a material it reads (a word, or a pair such as MILD STEEL) or a qualifier from
    config MATERIAL_QUALIFIER_WORDS. A row that also names a thing is that thing: "ACRYLIC
    LEAFLET HOLDER A4", "EDGE TRIM, ALUMINIUM" and "CAM LOCK ASSEMBLY" are parts."""
    try:
        from json_normaliser import normalise_material
    except Exception:                                            # noqa: BLE001
        return False
    try:
        if not normalise_material(up):
            return False
    except Exception:                                            # noqa: BLE001
        return False
    quals = set(_cfg_words(cfg, "MATERIAL_QUALIFIER_WORDS", _MATERIAL_QUALIFIERS_DEFAULT))
    words = [w for w in re.findall(r"[A-Z]+", up) if len(w) >= 3 and w not in _NOT_A_THING]
    if not words:
        return False
    covered = [w in quals for w in words]
    try:
        alone = [normalise_material(w) for w in words]
        for i, w in enumerate(words):
            if alone[i]:
                covered[i] = True
            if i + 1 < len(words):
                # A PAIR counts only when it reads as something neither word reads alone
                # (MILD STEEL, OAK VENEER) — so a material word cannot cover its neighbour.
                pair = normalise_material(f"{w} {words[i + 1]}")
                if pair and pair != alone[i] and pair != alone[i + 1]:
                    covered[i] = covered[i + 1] = True
    except Exception:                                            # noqa: BLE001
        return False
    return all(covered)


# ── A STOCK SECTION, NAMED AND NOTHING ELSE (review round 2 of D-383) ─────────────────────
# The section reader alone read only a x b x t plus TUBE/RHS/SHS. Every other stock section a
# frame's own table lists ("25.4 dia x 1.5 ROUND TUBE 600", "40 x 40 x 3 ANGLE 600", "25 x 3
# FLAT BAR 450", "12mm DIA BRIGHT BAR 300", "6mm DIA WIRE 450") was minted BI-ROUND, BI-ANGLE,
# BI-FLAT, BI-BRIGHT, BI-WIRE — D-383's own defect on every round-tube, angle and bar frame.
# A row whose words are a stock-section noun (config SECTION_STOCK_NOUNS) and nothing but the
# section's qualifiers (SECTION_STOCK_QUALIFIER_WORDS), a material and its qualifiers is the
# parent's section. Defaults below; config replaces them.
_SECTION_NOUNS_DEFAULT = ("TUBE", "TUBING", "SHS", "RHS", "CHS", "BOX SECTION", "HOLLOW SECTION",
                          "BAR", "ANGLE", "CHANNEL", "PIPE", "ROD", "WIRE")
_SECTION_QUALIFIERS_DEFAULT = (
    "ROUND", "SQUARE", "RECTANGULAR", "RECT", "FLAT", "HOLLOW", "EQUAL", "UNEQUAL", "BRIGHT",
    "BLACK", "ERW", "CDS", "CFHS", "HFHS", "SEAMLESS", "DRAWN", "COLD", "HOT", "ROLLED",
    "FORMED", "PRE", "GALV", "GALVANISED", "GALVANIZED", "MILD", "STEEL", "STAINLESS",
    "ALUMINIUM", "ALUMINUM", "WALL", "LENGTH", "CUT", "DIA", "DIAMETER", "LONG", "OFF", "PCS",
    "PIECE", "PIECES", "GRADE", "MATERIAL", "STOCK", "LEG", "LEGS", "SIDE", "SIDES")
# A TUBE ACCESSORY IS A PART: an end cap, insert, plug or glide names the section it fits.
_SECTION_ACCESSORIES_DEFAULT = (
    "CAP", "CAPS", "END CAP", "INSERT", "INSERTS", "PLUG", "PLUGS", "BUNG", "BUNGS", "GLIDE",
    "GLIDES", "FOOT", "FEET", "CLAMP", "CLAMPS", "CONNECTOR", "CONNECTORS", "JOINER", "JOINERS",
    "FERRULE", "FERRULES")
# The process and qualifier words an instruction row is made of ("WELD ALL ROUND").
_INSTRUCTION_WORDS_DEFAULT = (
    "WELD", "WELDS", "WELDED", "WELDING", "FOLD", "FOLDS", "FOLDED", "FOLDING", "BEND", "BENDS",
    "BENT", "HOLE", "HOLES", "SLOT", "SLOTS", "SLOTTED", "ALL", "ROUND", "AROUND", "BOTH",
    "SIDES", "SIDE", "STITCH", "TACK", "SEAM", "FILLET", "CONTINUOUS", "INTERMITTENT", "GRIND",
    "FLUSH", "DRESS", "DRESSED", "CLEAN", "DEBURR", "EDGES", "EDGE", "DOWN", "INSIDE",
    "OUTSIDE", "FULL", "LENGTH", "SHOWN", "PER", "DRAWING", "DRG", "DWG", "PITCH", "CENTRES",
    "CENTERS", "EQUAL", "SPACED", "THRU", "THROUGH", "TAPPED", "TAP", "DRILL", "DRILLED", "CSK",
    "MIG", "TIG", "SPOT", "ONLY", "WHERE", "VISIBLE", "DEG", "DEGREES", "EXT", "INT", "AND",
    "THE", "FROM", "WITH", "NOT")


def _material_covered(words: List[str]) -> List[bool]:
    """Which of these words the material normaliser reads, alone or as a pair that reads as
    something neither word reads alone (MILD STEEL, OAK VENEER)."""
    covered = [False] * len(words)
    try:
        from json_normaliser import normalise_material
        alone = [normalise_material(w) for w in words]
        for i, w in enumerate(words):
            if alone[i]:
                covered[i] = True
            if i + 1 < len(words):
                pair = normalise_material(f"{w} {words[i + 1]}")
                if pair and pair != alone[i] and pair != alone[i + 1]:
                    covered[i] = covered[i + 1] = True
    except Exception:                                            # noqa: BLE001
        pass
    return covered


def names_only_a_stock_section(description: Any, cfg: Any = None) -> bool:
    """True when a row names a stock section (config SECTION_STOCK_NOUNS) and nothing else:
    every word of three letters or more is a section noun, a section qualifier, a material it
    reads, a material qualifier or a unit. "30.00 x 30.00 x 2.00mm TUBE 1532", "MILD STEEL ERW
    TUBE" and "40 x 40 x 3 EQUAL ANGLE 600" do; "PLASTIC END CAP 25 x 25 x 1.5 TUBE" and "TUBE
    CLAMP 30 x 30 x 2" do not — they name a thing that fits the section."""
    cfg = cfg if cfg is not None else _config()
    up = " ".join(str(description or "").upper().split())
    nouns = _cfg_words(cfg, "SECTION_STOCK_NOUNS", _SECTION_NOUNS_DEFAULT)
    if not up or not _names_a_word(up, nouns):
        return False
    allowed = ({p for n in nouns for p in re.findall(r"[A-Z]+", n)}
               | set(_cfg_words(cfg, "SECTION_STOCK_QUALIFIER_WORDS", _SECTION_QUALIFIERS_DEFAULT))
               | set(_cfg_words(cfg, "MATERIAL_QUALIFIER_WORDS", _MATERIAL_QUALIFIERS_DEFAULT))
               | set(_NOT_A_THING))
    words = [w for w in re.findall(r"[A-Z]+", up) if len(w) >= 3]
    left = [w for w in words if w not in allowed]
    if not left:
        return True
    return all(_material_covered(left))


def _is_instruction_row(up: str, cfg: Any = None) -> bool:
    """A row that OPENS with the weld, fold, hole or slot reader's pattern and is made of
    nothing but process and qualifier words (config PARTS_LIST_INSTRUCTION_WORDS): "WELD ALL
    ROUND", "FOLD UP 90°". "WELD STUD M6 x 20", "WELD ON HINGE", "FOLD FLAT HINGE" and "FOLD
    DOWN SHELF BRACKET" name a thing and are parts."""
    if not any(_leads_with(getattr(cfg, k, None), up)
               for k in ("WELD_PATTERN", "FOLD_PATTERN", "HOLE_PATTERN", "SLOT_PATTERN")):
        return False
    vocab = (set(_cfg_words(cfg, "PARTS_LIST_INSTRUCTION_WORDS", _INSTRUCTION_WORDS_DEFAULT))
             | set(_NOT_A_THING))
    return all(w in vocab for w in re.findall(r"[A-Z]+", up) if len(w) >= 3)


def _instruction_vocabulary(cfg: Any = None) -> Set[str]:
    return set(_cfg_words(cfg, "PARTS_LIST_INSTRUCTION_WORDS", _INSTRUCTION_WORDS_DEFAULT))


def parts_list_row_role(description: Any) -> str:
    """What a parts-list row with no code IS, asked of the readers the engine already has.

    D-381 named every codeless row with a word of three letters as a bought-in part. On
    12173-03 the two tube frames' own cut lists ("30.00 x 30.00 x 2.00mm TUBE 1532", four
    rows each, BOMs & Routes rows 38-45) became BI-TUBE and two BI-3000X3000... lines hung
    under both frames, and the rail's section row ("10 x 30 x 1.50mm TUBE", 12173-05-01M)
    became BI-10X30X150MMTUBE — tube D-380 already costs as the frames' 3,704 mm, on the bill
    a second time. A note ("SEE NOTE 3"), a process ("WELD ALL ROUND"), a finish, a
    material ("18mm MDF, 626 x 626") and an edging row would all have been named the same way.
    So the row is asked, in order:

      (b) a banding noun and no trim word (edge_banding.is_banding_row) -> the parent's edging
      (c) the shared hardware vocabulary, a tube accessory (config SECTION_ACCESSORY_WORDS)
          or a stock-product word (config PURCHASED_STOCK_PRODUCT_WORDS) -> a part. Asked
          BEFORE the section reader: an end cap names the tube it fits, and read as the
          frame's cut list it was consumed with nothing said
      (a) the section reader (section_profile) reads a canonical profile, or the row names a
          stock section and nothing else (names_only_a_stock_section)  -> the parent's cut
          list, consumed by bom_pipeline.apply_stated_cut_list_to_parts where it can read
          it, else asked; a section named with no figures at all is the parent's material
      (d) a placeholder, a note (config PARTS_LIST_NOTE_LEADS), or a row that OPENS with the
          weld, fold, hole or slot reader's pattern and names nothing but process words
          (config PARTS_LIST_INSTRUCTION_WORDS), or only states a finish -> an instruction
      (e) the material normaliser reads a material                        -> the parent's stock
      (f) anything else with a word                                       -> a part (BI-DOWEL)

    Nothing in (a), (b), (d) or (e) is minted; bom_pipeline raises what no reader consumed
    as a question on the parent. No money moves on a word here."""
    desc = " ".join(str(description or "").split())
    up = desc.upper()
    if not up:
        return ROW_ROLE_SIZE
    _cfg = _config()
    try:
        from edge_banding import is_banding_row
        if is_banding_row(desc):
            return ROW_ROLE_BANDING
    except Exception:                                            # noqa: BLE001
        pass
    if synthesise_bought_in_code(desc, ""):
        return ROW_ROLE_PART
    if _names_a_word(up, _cfg_words(_cfg, "SECTION_ACCESSORY_WORDS", _SECTION_ACCESSORIES_DEFAULT)):
        return ROW_ROLE_PART
    _stock_words = getattr(_cfg, "PURCHASED_STOCK_PRODUCT_WORDS", None) or ()
    if any(re.search(rf"\b{re.escape(str(w).upper())}\b", up) for w in _stock_words):
        return ROW_ROLE_PART
    try:
        from section_profile import detect_section_stock
        _sec = detect_section_stock(desc)
    except Exception:                                            # noqa: BLE001
        _sec = None
    _pure = names_only_a_stock_section(desc, _cfg)
    if _pure and not re.search(r"\d", up):
        return ROW_ROLE_MATERIAL
    if _pure or (_sec and _sec.get("detection_path") == "canonical_profile"):
        return ROW_ROLE_CUT_LIST
    if is_placeholder_identity(desc) or _note_lead(up, _cfg):
        return ROW_ROLE_INSTRUCTION
    if _is_instruction_row(up, _cfg):
        return ROW_ROLE_INSTRUCTION
    if _is_finish_statement(up, _cfg):
        return ROW_ROLE_INSTRUCTION
    if _is_material_statement(up, _cfg):
        return ROW_ROLE_MATERIAL
    words = [w for w in re.findall(r"[A-Z]+", up) if len(w) >= 3 and w not in _NOT_A_THING]
    return ROW_ROLE_PART if words else ROW_ROLE_SIZE


def mint_uncoded_row_identities(rows: Iterable[Any], code_key: str = "part_number",
                                desc_key: str = "description") -> int:
    """An identity for a parts-list row with words and no code (D-381). Returns rows minted.

    12173-03-01J's table prints "4  DOWEL, ø6mm x 20mm  6" with no code column. On a pack the
    model also describes, the placeholder mint in the graph is gated off (it is for
    PDF-primary packs), so the row reached no record and no node: six dowels the base is built
    with were never a line. The row is named by its words through the shared minter
    ("BI-DOWEL"), so every reader derives the same code, and kept visibly ours — a minted code
    is never put to the catalogue as if the drawing had printed it.

    Only a row whose table names its drawing (bom_parent_known) and whose words name a PART
    (parts_list_row_role, D-383): a cut-list row, an edging row, an instruction, a material and
    a size are the parent's, not things we buy, and each row carries the role it was given
    (row_role) so the readers that consume them, and the question for any they do not, can
    find it. A row with a code is untouched."""
    listed = [r for r in (rows or []) if isinstance(r, dict)]
    taken: Dict[str, str] = {}
    for r in listed:
        _c = str(r.get(code_key) or "").strip()
        if _c:
            taken.setdefault(_c.upper(), str(r.get(desc_key) or "").upper())
    n = 0
    for r in listed:
        code = str(r.get(code_key) or "").strip()
        if code and not is_placeholder_identity(code):
            continue
        if r.get("bom_parent_known") is False or not str(r.get("bom_parent") or "").strip():
            continue
        desc = " ".join(str(r.get(desc_key) or "").split())
        role = parts_list_row_role(desc)
        r["row_role"] = role
        if role != ROW_ROLE_PART:
            continue
        words = [w for w in re.findall(r"[A-Z]+", desc.upper())
                 if len(w) >= 3 and w not in _NOT_A_THING]
        if not words:
            continue
        # A PART NAMED AFTER A PROCESS WORD IS NAMED BY ITS THING: "WELD STUD M6 x 20" is a
        # stud (BI-STUD), not BI-WELD. Only the leading process words are passed over.
        _proc = _instruction_vocabulary(_config())
        _named = words
        while len(_named) > 1 and _named[0] in _proc:
            _named = _named[1:]
        ident = synthesise_bought_in_code(desc, code) or f"BI-{_named[0]}"
        _held = taken.get(ident.upper())
        if _held is not None and _held != desc.upper():
            # Two different rows under one word: the figures are what tell them apart. The
            # code then carries digits, so it is recognised as ours by its record
            # (identity_source, is_engine_minted_record), never by its shape.
            ident = "BI-" + re.sub(r"[^A-Z0-9]", "", desc.upper())[:24]
        r.setdefault("printed_code", code)
        r[code_key] = ident
        r["identity_source"] = "uncoded_row"
        taken.setdefault(ident.upper(), desc.upper())
        n += 1
    return n


def split_category_code_rows(rows: Iterable[Any], code_key: str = "part_number",
                             desc_key: str = "description") -> int:
    """Apply category_code_identities in place, keeping the printed code. Returns rows changed."""
    listed = list(rows or [])
    new = category_code_identities(listed, code_key, desc_key)
    for i, ident in new.items():
        row = listed[i]
        if str(row.get(code_key) or "") != ident:
            row.setdefault("printed_code", row.get(code_key))
            row[code_key] = ident
    return len(new)


def is_sighted_code(identity: Any) -> bool:
    """True when this code was minted for a part SIGHTED on a render (concept_scan)."""
    return bool(_CONCEPT_CODE.match(str(identity or "").strip().upper()))


def is_engine_minted_code(identity: Any) -> bool:
    """True when this module wrote the code, rather than a drawing printing it.

    The counterpart of part_code_conventions.is_category_not_a_code: that one says the drawing
    printed a CLASS where a code belongs, this one says WE printed a placeholder where the drawing
    printed nothing. Both mean the line cannot be priced by code, and an estimator is owed the
    difference -- one is answered by putting a code on the pack, the other by loading the
    catalogue or pricing the line by hand.
    """
    return bool(_MINTED_CODE.match(str(identity or "").strip())) \
        or is_sighted_code(identity)


# The identity sources this module and the graph write for a code the drawing did not print.
_MINTED_IDENTITY_SOURCES = frozenset({"uncoded_row", "description_bought_in"})


def is_engine_minted_record(record: Any) -> bool:
    """True when a RECORD's code was minted by the engine — by its shape, or by the record
    saying so (D-383).

    The shape test above is deliberately narrow (letters only after BI-), and a clash in
    mint_uncoded_row_identities keeps the row's figures to tell two rows apart
    ("BI-DOWEL8MMX30MM"). By shape that reads as somebody's code, and the explainer told an
    estimator it was "a real code ... put to the purchasing catalogue". The record carries
    identity_source from the row it was minted for, and that is the answer wherever the
    record is in hand."""
    if not isinstance(record, dict):
        return is_engine_minted_code(record)
    if str(record.get("identity_source") or "") in _MINTED_IDENTITY_SOURCES:
        return True
    return any(is_engine_minted_code(record.get(k)) for k in ("part_number", "identity")
               if record.get(k))


def is_category_split_identity(record: Any) -> bool:
    """True when a record's identity was derived from a CLASS word the drawing printed
    ("FIXING", "P/P") plus its article's words — category_code_identities' split — rather
    than printed whole (D-383).

    12173-03-GA prints "FIXING" against both pan-head screws; "FIXING-3.5-X12MM-PAN-HEAD" is
    the split. A report that calls it "the code the drawing printed" sends an estimator to
    look for a code that is not on the sheet."""
    if not isinstance(record, dict):
        return False
    try:
        from part_code_conventions import bare_code, is_category_not_a_code
    except Exception:                                            # noqa: BLE001
        return False
    pc = str(record.get("printed_code") or "").strip()
    return bool(pc) and is_category_not_a_code(pc) \
        and bare_code(str(record.get("part_number") or "")) != bare_code(pc)


def dxf_alias_target(part_number: str) -> Optional[str]:
    key = normalize_part_code(part_number)
    return DXF_TO_BOM_ALIASES.get(key)


def resolve_estimate_code(
    code: str,
    description: str,
    available: Iterable[str],
) -> Optional[str]:
    """Map a BOM / GA code to a per-part estimate key when labels differ."""
    norm = normalize_part_code(code)
    if not norm:
        return None
    avail = {normalize_part_code(c): c for c in available if c}
    if norm in avail:
        return avail[norm]

    pref = GA_TO_DETAIL_PREFERENCE.get(norm)
    if pref:
        pn = normalize_part_code(pref)
        if pn in avail:
            return avail[pn]

    # 1450-GA style: numeric prefix + detail suffix in scope
    prefix_m = re.match(r"^(\d{4})(?:-GA.*)?$", norm)
    if prefix_m:
        prefix = prefix_m.group(1)
        children = [
            avail[k]
            for k in avail
            if k.startswith(prefix + "-") and not k.endswith("-GA") and "-GA" not in k[5:]
        ]
        if len(children) == 1:
            return children[0]

    # Kick / peg families by description when GA code missing
    desc_u = str(description or "").upper()
    if "KICK" in desc_u and "PLATE" in desc_u:
        for key in ("1453-01C", "1453-GA-C", "1453-GA"):
            pn = normalize_part_code(key)
            if pn in avail:
                return avail[pn]
    if "PEG PANEL" in desc_u and "HALF" not in desc_u:
        if "1449-01C" in avail.values() or normalize_part_code("1449-01C") in avail:
            return avail.get(normalize_part_code("1449-01C"))
    if "HALF" in desc_u and "PEG" in desc_u:
        pn = normalize_part_code("2621-01C")
        if pn in avail:
            return avail[pn]

    return None


def preprocess_bom_text(text: str) -> str:
    """Repair common OCR/layout splits before BOM regex extraction."""
    if not text:
        return text
    t = re.sub(r"\s+", " ", str(text))

    t = _SPLIT_KICK_RE.sub(r"\1 1453-GA-\2 \3 \4", t)
    t = _GA_WALL_RE.sub(r"\1 3886-GA WALL \3 \4", t)
    t = _HEADER_GA_RE.sub(r"\1 1455-C-GA \3 \4", t)

    # "1453-GA- 4 500mm..." — digit is item no, not revision letter
    t = re.sub(
        r"\b1453-GA-\s+(\d+)\s+(500mm\s+KICK\s+PLATE\s+ASSEMBLY)\s+(\d+)\b",
        r"\1 1453-GA-C \2 \3",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"\bELECTRICS\s*50\s*CM\b", "ELECTRICS 50CM", t, flags=re.IGNORECASE)
    t = re.sub(r"\bELECTRICS50CM\b", "ELECTRICS 50CM", t, flags=re.IGNORECASE)
    return t


def normalize_bom_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    pn = normalize_part_code(row.get("part_number"))
    if pn:
        out["part_number"] = pn
    desc = str(row.get("description") or "").strip()
    if pn == "3886-GA" and desc.upper().startswith("WALL"):
        out["description"] = desc[4:].strip() or "WALL BAY BUDGET LOWER LEG"
    return out


def inject_missing_bay_rows(rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Add top-level bay lines that layout/OCR dropped (e.g. split kick plate row)."""
    out = [normalize_bom_row(r) for r in rows]
    codes = {normalize_part_code(_row_code(r)) for r in out}

    blob_parts: List[str] = []
    for page in summary.get("pages") or []:
        blob_parts.append(page.get("normalized_text") or "")
        blob_parts.append(page.get("pdfplumber_text") or "")
    blob = preprocess_bom_text(" ".join(blob_parts))

    for m in _KICK_ROW_RE.finditer(blob):
        item, pn, desc, qty = m.groups()
        code = normalize_part_code(pn)
        if not code or code in codes:
            continue
        out.append(
            {
                "item_number": item,
                "part_number": code if code.startswith("1453") else "1453-GA-C",
                "description": desc.strip(),
                "quantity": int(qty),
                "source": "bay_bom_stitch",
            }
        )
        codes.add(normalize_part_code("1453-GA-C"))

    return out


def _row_code(row: Dict[str, Any]) -> str:
    return normalize_part_code(row.get("part_number") or row.get("code") or "")


def catalogue_search_descriptions(code: str, desc: str) -> List[str]:
    c = normalize_part_code(code) or str(code or "").strip().upper()
    d = str(desc or "").strip()
    variants = [d, f"{c} {d}".strip(), c]
    variants.extend(CATALOGUE_DESC_ALIASES.get(c, []))
    seen: Set[str] = set()
    out: List[str] = []
    for v in variants:
        key = v.upper()
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def score_dxf_candidate(part: Dict[str, Any], path: Any, *, cut_length_mm: float = 0.0) -> float:
    """Prefer credible peg/spigot flats when several DXFs share a numeric family."""
    from pathlib import Path

    p = Path(path)
    name = p.name.upper()
    pn = normalize_part_code(part.get("part_number") or "")
    score = 0.0
    if "PEG" in name and "1449" in pn:
        score += 3.0
        if "50CM" in name or "500" in name:
            score += 2.0
        if cut_length_mm >= 2500:
            score += 2.0
        elif cut_length_mm < 1800:
            score -= 2.0
    if "SPIGOT" in name and pn == "1448-02":
        score += 4.0
    if "1148" in name and pn == "1448-02":
        score += 4.0
    if "KICK" in name and "1453" in pn:
        score += 4.0
    if "1450" in pn and ("BASE" in name or "PLATE" in name):
        score += 2.0
        desc_digits = "".join(c for c in str(part.get("description") or "") if c.isdigit())
        prefer_650 = "650" in desc_digits
        if "650" in name:
            score += 4.0 if prefer_650 else -4.0
        if "500" in name or "50CM" in name:
            score += -1.0 if prefer_650 else 3.0
        if "REV" in name and "500" not in name and "650" not in name:
            score -= 0.5
    return score


def same_row_read_as_one_cell(code_a: Any, desc_a: Any, code_b: Any, desc_b: Any) -> bool:
    """Two identities that are ONE parts-list row read two ways (D-435, D-443).

    A wrapped code cell ("FIXING M6x12mm" over "THREADED INSERT, HEADED HEX DRIVE") is read by
    one reader as code + description and by another as the whole cell for a code. An identity
    whose squashed spelling is EXACTLY another's code and description joined is that row read
    as one cell — a structural identity, not a near match. Either side may be the whole-cell
    reading. A trailing separator left on a code ("KINGDOM:") is not a second code.
    """
    def _sq(value: Any) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

    ca, cb = _sq(code_a), _sq(code_b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    ja, jb = _sq(str(code_a or "") + " " + str(desc_a or "")), _sq(str(code_b or "") + " " + str(desc_b or ""))
    return (len(cb) >= 10 and cb == ja and ja != ca) or (len(ca) >= 10 and ca == jb and jb != cb)



def fold_one_cell_duplicates(parts: Any) -> List[Tuple[str, str]]:
    """Fold every record that is another's row read as one cell onto that record, in place
    (D-451). The coded spelling survives (the shorter squashed code, the one a catalogue
    holds); its quantity, its price chain and its parents stand; the folded identity is kept
    on it as a raw alias and said in a flag. Two records whose stated quantities disagree are
    two lines, and are left alone. Returns [(folded, kept)]."""
    if not isinstance(parts, list):
        return []

    def _sq(value: Any) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

    def _qty(p: Any) -> Optional[float]:
        try:
            v = float(p.get("quantity"))
            return v if v > 0 else None
        except (TypeError, ValueError, AttributeError):
            return None

    folded: List[Tuple[str, str]] = []
    i = 0
    while i < len(parts):
        a = parts[i]
        if not isinstance(a, dict) or not a.get("part_number"):
            i += 1
            continue
        hit = None
        for b in parts:
            if b is a or not isinstance(b, dict) or not b.get("part_number"):
                continue
            if _sq(a["part_number"]) == _sq(b["part_number"]):
                continue
            if not same_row_read_as_one_cell(a["part_number"], a.get("description"),
                                             b["part_number"], b.get("description")):
                continue
            qa, qb = _qty(a), _qty(b)
            if qa and qb and abs(qa - qb) > 1e-9:
                continue
            hit = b
            break
        if hit is None:
            i += 1
            continue
        keep, drop = (a, hit) if len(_sq(a["part_number"])) <= len(_sq(hit["part_number"])) else (hit, a)
        for k, v in drop.items():
            if keep.get(k) in (None, "", [], {}) and v not in (None, "", [], {}) and k != "part_number":
                keep[k] = v
        aliases = keep.setdefault("raw_aliases", [])
        if isinstance(aliases, list) and drop["part_number"] not in aliases:
            aliases.append(drop["part_number"])
        note = (f"{drop['part_number']} is this row read as one cell — the code and the "
                f"description of {keep['part_number']} joined; one line, not two")
        if note not in (keep.get("review_flags") or []):
            keep.setdefault("review_flags", []).append(note)
        folded.append((str(drop["part_number"]), str(keep["part_number"])))
        parts.remove(drop)
        i = 0
    return folded
