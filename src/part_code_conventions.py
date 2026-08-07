"""
part_code_conventions.py — the codes the FILES use vs the codes the DRAWING's BOM uses.

One part under two names is two parts, and that is the expensive failure. On job 11350 a
five-item BOM compiled to seven nodes: the GA lists "11350-01-01" and "11350-01-02 MIR"
while the model and the DXF are "11350-01-01M" and "Mirror11350-01-02M". The bar and the
right arm each appeared twice — once with the drawing's quantity and hierarchy, once with
the measured geometry — and neither copy had both. The only real blank dimensions on the
job sat on a leaf with no parent, while the part the sheet actually costs had none.

TWO CONVENTIONS, AND ONLY TWO:

  MATERIAL SUFFIX   "<code><T|M|A>" is the drawing's "<code>" cut in that material. The
                    same convention json_normaliser already reads material from
                    (-xxM steel, -xxA acrylic, -xxT MDF).
  MIRROR            SolidWorks writes a mirrored derived part as "Mirror<code>"; the
                    drawing writes the mirrored line as "<code> MIR" / "<code> MIROR".

WHY THIS IS A MODULE AND NOT TWO REGEXES IN ONE FILE. It is needed in two places that sit
either side of the problem. `drawing_job_merge` decides whether a DXF belongs to an existing
BOM line or becomes a NEW part; `route_compiler` decides whether two identities are one
node. Only the first can prevent the phantom — the second can merely repair it — and a
private copy in each is how one of them goes quietly stale.

THE DIRECTION OF SAFETY. A candidate is offered, never asserted: every caller must confirm
the target actually exists before binding to it. Inventing a join costs a part its own
identity; declining one costs a merge an estimator can see and undo.
"""
from __future__ import annotations

import re
from typing import List, Tuple

__all__ = ["base_code", "alias_targets", "is_mirror_code", "mirror_base", "material_suffix"]

# A trailing material letter, and only after a digit — so "11350-01-01M" yields
# "11350-01-01" while a code that simply ends in a letter ("...-GA") is left alone.
_MATERIAL_SUFFIX = re.compile(r"^(.*\d)([TMA])$", re.IGNORECASE)

# "Mirror<code>" / "MIRROR-<code>". The lookahead admits only a DIGIT or a separator —
# [\dA-Z] also matches a letter, which made "MIRRORLIKE-01" read as a mirrored part. A part
# code following the marker starts with a number in every convention seen so far.
_MIRROR_PREFIX = re.compile(r"^MIRROR[\s_-]*(?=[\d-])", re.IGNORECASE)


# The DRAWING's spelling of the same fact: "11350-01-02 MIR", "1449-03-MIRROR". A separator
# is required before the marker so a code that merely ends in those letters is untouched,
# and the marker must end the code — "…-MIRROR-02" is a code, not a marker.
# THE SEPARATOR SURVIVES THE DRAWING AND NOT THE PIPELINE. normalize_part_code collapses
# "11350-01-02 MIR" to "11350-01-02MIR" — so a rule that requires a separator recognises the
# code the drawing prints and not the one every downstream reader holds. On 11350 that is
# why the right arm still reached costing with no blank after the mirror rule was fixed
# twice: the rule was correct and was being handed a spelling it did not accept.
#
# So the marker is accepted with a separator, or directly after a DIGIT. The digit is what
# keeps it safe: a code ending in letters is left whole, so "BRACKET-MIRAGE" and any part
# whose name merely ends in those characters are untouched.
_MIRROR_SUFFIX = re.compile(r"(?:[\s_-]+|(?<=\d))MIR(?:ROR(?:ED)?|ORED|OR)?$",
                            re.IGNORECASE)


def material_suffix(identity: str) -> str:
    """The material letter SDI's numbering convention puts on a part it CUTS — "M", "A",
    "T" — or "" for a code that carries none.

    `base_code` has always stripped this letter; nothing could ask what it SAID. That
    asymmetry is why job 12392's "-01M" and "-02M" brackets reached costing with no material
    at all: the drawing's material text read as "Card", which resolves to nothing in our
    lexicon, and the readers that fall back on the part number only did so when the text was
    BLANK. Unresolvable text is not blank, so the convention never got to speak, and a part
    with no material defaults to bought-in — fabrication labour silently gone from two steel
    brackets we cut ourselves.

    Returned as the LETTER, not a material code. This module knows the drawing's spelling
    conventions and deliberately not the material lexicon: which sheet "M" buys is
    json_normaliser's question, and answering it here would put the lexicon in two places.

    WEAK BY CONSTRUCTION, exactly as `base_code` treats it. A suffix is a naming convention,
    not an observation. Every caller must let a material the drawing actually STATES win.
    """
    match = _MATERIAL_SUFFIX.match(str(identity or "").strip())
    return match.group(2).upper() if match else ""


# A drawing number: opens with a digit, then at least one hyphenated segment.
#   12120-01-001  1282-GA  12392-02  3886-GA-C  2085-01
# It deliberately does NOT require three segments. The BOM reader's title-block regex
# did (r"^\d{3,}-\d+-[A-Z0-9]+$"), which is the 12120 house style and not SDI's rule:
# on 1282, 12392-04 and 3886-GA it matched nothing, so every BOM row those pages
# produced arrived with no parent. A row with no parent cannot join a hierarchy, and a
# hierarchy assembled from rows that could not say who owned them is the failure that
# has been read as "the family tree is broken" on job after job.
# THE LEADING RUN IS A JOB NUMBER, AND JOB NUMBERS ARE NOT ONE DIGIT LONG.
# The first version of this asked only for a leading digit. On 12392-02 the title block's
# description row reads "1-WIDE GIFT CARD GATE POST PANEL TESCO IMS ...", and joined up it
# is "1-WIDEGIFTCARDGATEPOSTPANEL..." — which opens with a digit, carries a hyphen, and is
# otherwise letters. It passed. The description won the contest the shape test exists to
# stop it winning, and it beat the real 12392-02-GA sitting at the end of the same row.
#
# Three digits minimum. Every job number here is four or five (1282, 2085, 3886, 11350,
# 12120, 12392), so this costs nothing real and refuses "1-WIDE", "2-OFF", "4-WAY" and
# every other dimension or count that opens a description.
_DRAWING_NUMBER_SHAPE = re.compile(r"^[0-9]{3,}[0-9A-Z]*(?:-[0-9A-Z]+)+$", re.IGNORECASE)


def looks_like_a_drawing_number(text: str) -> bool:
    """True when a token has the shape of an SDI or customer drawing number.

    Shape only. It says a token COULD name a drawing, never that this drawing exists —
    the direction of safety this module keeps everywhere else.
    """
    return bool(_DRAWING_NUMBER_SHAPE.match(str(text or "").strip()))


def bare_code(identity: str) -> str:
    """Match-normalise a code: uppercase, strip ALL separators (spaces and hyphens).

    "1455-C GA", "1455-C-GA", "1455-C- GA" and "1455 C GA" all become "1455CGA".

    A CAD table read through any text extractor splits and re-spaces hyphenated codes
    unpredictably — the same code comes back differently from two readers looking at the
    same page. This is the form in which two readers' codes may be COMPARED. It is
    deliberately not the form in which a code is STORED: it destroys the separators an
    estimator reads, and `_norm_code` in bom_pipeline is what keeps a code presentable.

    It lives here rather than in either reader because the dual-path reconciler compares
    the deterministic reader's codes against the vision reader's, and a comparison whose
    definition sits inside one of the two things being compared cannot survive that reader
    being unavailable — nor stay honest if either side ever edits its own copy.
    """
    return re.sub(r"[\s\-]+", "", str(identity or "").upper())


def is_mirror_code(identity: str) -> bool:
    """True when the code names a mirrored derivation of another part."""
    text = str(identity or "").strip()
    return bool(_MIRROR_PREFIX.search(text)) or bool(_MIRROR_SUFFIX.search(text))


def mirror_base(identity: str) -> str:
    """The code this one mirrors, in EITHER convention, or "" when it mirrors nothing.

    THE FILES SAY IT ONE WAY AND THE DRAWING SAYS IT THE OTHER. SolidWorks writes a
    mirrored derived part as "Mirror<code>"; the GA writes the mirrored line as
    "<code> MIR". `alias_targets` translates the first into the second — this answers the
    question both spellings share: which part is this the other hand of?

    Deliberately does NOT strip a material suffix. "11350-01-02 MIR" mirrors the drawing's
    "11350-01-02"; reducing it further would be a second convention applied on top of a
    guess, and each of those is a chance to name a part that is not there.
    """
    text = str(identity or "").strip()
    if _MIRROR_PREFIX.search(text):
        return _MIRROR_PREFIX.sub("", text).strip()
    if _MIRROR_SUFFIX.search(text):
        return _MIRROR_SUFFIX.sub("", text).strip()
    return ""


def base_code(identity: str) -> Tuple[str, bool]:
    """(the drawing's likely code, whether this was a mirror) for a file's code."""
    text = str(identity or "").strip()
    mirror = is_mirror_code(text)
    if mirror:
        text = _MIRROR_PREFIX.sub("", text).strip()
    match = _MATERIAL_SUFFIX.match(text)
    if match:
        text = match.group(1)
    return text, mirror


def alias_targets(identity: str) -> List[str]:
    """Candidate drawing codes this file code may belong to, best first.

    Empty when the code needs no translation. A MIRRORED file prefers the drawing's own
    mirrored line before the base part: collapsing "Mirror11350-01-02M" onto "11350-01-02"
    would give the left arm the right arm's geometry and lose a BOM line, so the base is
    offered only as the last resort — for packs where the drawing does not list the mirror
    separately.
    """
    text = str(identity or "").strip()
    base, mirror = base_code(text)
    if not base or base.upper() == text.upper():
        return []
    if mirror:
        return [f"{base} MIR", f"{base} MIRROR", f"{base}MIR", f"{base} MIRRORED", base]
    return [base]
