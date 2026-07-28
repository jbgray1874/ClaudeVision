"""
source_precedence.py — which source is allowed to overwrite which, per datum.

The pipeline runs a dozen passes over one shared list of part records, and each pass writes
what it knows. Nothing arbitrated between them, so the LAST writer won regardless of what it
knew — and the last writer is usually the weakest, because the strong sources (a model, a
measured DXF) are read early and the inferential ones run late. Two live examples:

  - the PDF GA-tree pass overwrote quantities that came from the SolidWorks assembly BOM,
    which is the structure the shop actually builds from;
  - knowledge-base and rule overrides replaced native material, because the reliability test
    listed only knowledge_base and override_rule as strong and had never heard of the model.

Both were silent. A silent overwrite of the best source available is the worst failure this
codebase has, because the result looks exactly like a correct answer.

THE RULE: a lower-ranked source may FILL a datum, never REPLACE a higher-ranked one. Where it
disagrees, the disagreement is recorded on the part and the stronger value kept. Nothing is
resolved by whoever happens to run last.

Ranking, and the reasoning:

  100  estimator_confirmed / knowledge_base   a person looked at it and said so
   90  solidworks_api                         the model itself; what the shop builds from
   80  dxf                                    measured geometry
   70  drawing_deterministic                  printed title-block fields, read exactly
   60  bom_tree                               PDF BOM structure — a reading of a table
   50  override_rule                          a pattern rule, not an observation
   40  llm_extract                            transcribed, cross-checked, still a reading
   20  inference                              provisional by construction
    0  unknown                                fills gaps only

Human confirmation outranks the model deliberately: an estimator correcting a part is the one
signal that carries knowledge the drawing does not.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = [
    "rank", "may_overwrite", "apply_field", "source_of", "SOURCE_RANK", "MISSING",
]


class _Missing:
    """Distinguishes 'no value' from a value that happens to be zero or empty.

    This is not pedantry. `if cut_out_count:` read an explicit model value of ZERO — a plain
    blank with one outer profile — as no data at all, and let a weaker PDF-derived count
    survive against the strongest source available. Truthiness cannot tell "the model says
    none" from "nobody has looked", and those two facts must never resolve the same way.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self):
        return False

    def __repr__(self):
        return "MISSING"


MISSING = _Missing()

# Values that mean "nothing is recorded here". ZERO IS NOT ONE OF THEM, and neither is
# False: both are statements. Compared by identity, because `0 == False` and `"" == ""`
# make `in` unreliable for exactly the cases this has to get right.
_EMPTY = (None, "", (), [], {})


def _is_empty(v: Any) -> bool:
    if v is MISSING:
        return True
    for e in _EMPTY:
        if type(v) is type(e) and v == e:
            return True
    return v is None


def _split(field: str):
    """'geometry_rollup.estimated_pierce_count' -> (['geometry_rollup'], 'estimated_pierce_count')"""
    parts = str(field).split(".")
    return parts[:-1], parts[-1]


def _walk(part: Dict[str, Any], path, create: bool = False) -> Optional[Dict[str, Any]]:
    """The dict a dotted field lives in. Geometry does not sit at the top of a part record —
    pierce counts, blank dimensions and cut lengths live inside geometry_rollup and
    manufacturing_features — so a resolver that can only see top-level keys cannot arbitrate
    the very fields that drive the laser."""
    node = part
    for key in path:
        nxt = node.get(key)
        if not isinstance(nxt, dict):
            if not create:
                return None
            nxt = {}
            node[key] = nxt
        node = nxt
    return node

SOURCE_RANK: Dict[str, int] = {
    "estimator_confirmed": 100,
    "knowledge_base": 100,
    "solidworks_api": 90,
    "solidworks_flat_pattern": 90,
    "dxf": 80,
    "dxf_flat_pattern": 80,
    "drawing_deterministic": 70,
    "title_block": 70,
    "bom_tree": 60,
    "override_rule": 50,
    "llm_extract": 40,
    "llm_full_extract": 40,
    "inference": 20,
    "geometry_inference": 20,
}

# Where a datum's source is recorded. Falling back to a per-field convention
# ("<field>_source") keeps this usable for fields that have no dedicated key yet.
_SOURCE_FIELDS = {
    "normalized_material": "material_source",
    "quantity": "quantity_source",
    "normalized_thickness_mm": "thickness_source",
}


def rank(source: Any) -> int:
    """Rank of a source name. Unknown or absent sources rank 0, so they fill gaps but
    never displace anything. Matched on a prefix so a decorated value such as
    'knowledge_base (92%)' or 'override_rule:timber_panels' still resolves."""
    s = str(source or "").strip().lower()
    if not s:
        return 0
    if s in SOURCE_RANK:
        return SOURCE_RANK[s]
    for name, r in sorted(SOURCE_RANK.items(), key=lambda kv: -len(kv[0])):
        if s.startswith(name) or name in s:
            return r
    return 0


def _source_key(leaf: str) -> str:
    return _SOURCE_FIELDS.get(leaf, f"{leaf}_source")


def value_of(part: Dict[str, Any], field: str) -> Any:
    """The current value of a datum, MISSING when there is none. Never conflates a recorded
    zero with an absent value."""
    if not isinstance(part, dict):
        return MISSING
    path, leaf = _split(field)
    node = _walk(part, path)
    if node is None or leaf not in node:
        return MISSING
    v = node.get(leaf)
    return MISSING if _is_empty(v) else v


def source_of(part: Dict[str, Any], field: str) -> str:
    """The recorded source for one datum on a part."""
    if not isinstance(part, dict):
        return ""
    path, leaf = _split(field)
    node = _walk(part, path)
    if node is None:
        return ""
    return str(node.get(_source_key(leaf)) or "")


def may_overwrite(part: Dict[str, Any], field: str, new_source: Any) -> bool:
    """May `new_source` replace the value already on this part?

    Yes when the datum is empty (anything may fill a gap), or when the new source ranks at
    least as high as the one that wrote it. A tie is allowed: two passes of equal standing
    refining each other is normal, and the later one usually knows more.

    A recorded ZERO is a value, not a gap. A model reporting no cut-outs has answered the
    question, and a weaker source must not treat that answer as an opening."""
    if not isinstance(part, dict):
        return False
    if value_of(part, field) is MISSING:
        return True
    return rank(new_source) >= rank(source_of(part, field))


def apply_field(part: Dict[str, Any], field: str, value: Any, source: str,
                note: Optional[str] = None, confidence: Optional[float] = None) -> bool:
    """Set a datum if this source is entitled to, and record where it came from.

    `field` may be dotted for nested records — "geometry_rollup.estimated_pierce_count" —
    because the fields that drive cost mostly do not live at the top of a part.

    An explicit zero IS a value and will be written, and will be defended afterwards against
    weaker sources. Only MISSING, None and genuinely empty containers count as no-data.

    Returns True if the value was written. When it was not, the disagreement is flagged on
    the part with both values and both sources — the estimator can then see that two sources
    disagreed and which one was kept, instead of only ever seeing the survivor."""
    if not isinstance(part, dict) or _is_empty(value):
        return False
    path, leaf = _split(field)
    key = _source_key(leaf)
    if may_overwrite(part, field, source):
        node = _walk(part, path, create=True)
        if node is None:
            return False
        node[leaf] = value
        node[key] = source
        if confidence is not None:
            node[f"{leaf}_confidence"] = confidence
        if note:
            part.setdefault("review_flags", []).append(note)
        return True
    _cur = value_of(part, field)
    _cur_src = source_of(part, field) or "an earlier pass"
    if str(_cur).strip() != str(value).strip():
        part.setdefault("review_flags", []).append(
            f"{field}: '{value}' from {source} NOT applied — '{_cur}' from {_cur_src} is the "
            f"stronger source and was kept. The two disagree; confirm which is right")
    return False
