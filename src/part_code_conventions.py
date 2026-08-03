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

__all__ = ["base_code", "alias_targets", "is_mirror_code"]

# A trailing material letter, and only after a digit — so "11350-01-01M" yields
# "11350-01-01" while a code that simply ends in a letter ("...-GA") is left alone.
_MATERIAL_SUFFIX = re.compile(r"^(.*\d)([TMA])$", re.IGNORECASE)

# "Mirror<code>" / "MIRROR-<code>". The lookahead admits only a DIGIT or a separator —
# [\dA-Z] also matches a letter, which made "MIRRORLIKE-01" read as a mirrored part. A part
# code following the marker starts with a number in every convention seen so far.
_MIRROR_PREFIX = re.compile(r"^MIRROR[\s_-]*(?=[\d-])", re.IGNORECASE)


def is_mirror_code(identity: str) -> bool:
    """True when the code names a mirrored derivation of another part."""
    return bool(_MIRROR_PREFIX.search(str(identity or "").strip()))


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
