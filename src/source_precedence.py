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
    "SOURCE_DISPLAY_NAME", "MEASURED_SOURCES", "display_name", "was_measured",
    "SOURCE_TIEBREAK", "tiebreak_priority",
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
    # A MIRROR OF A MEASUREMENT IS STILL A MEASUREMENT — of the other hand.
    #
    # Job 11350's right arm had no DXF of its own, so it had no blank, so it fell through
    # to a web lookup, so it fell through to an LLM market estimate: GBP 79.04 one run,
    # GBP 86.04 the next, 97% of the whole material total. Its left hand was measured at
    # 258.35 x 84.8 x 2.0 the entire time. A mirrored derivation has the SAME flat pattern
    # as the part it mirrors — same blank, same cut length, same holes, same bends — and
    # that is geometry, not a guess.
    #
    # Ranked just BELOW the flat it came from, and for one reason: it rests on the naming
    # convention holding as well as on the measurement. It must never displace a DXF or a
    # model of the mirror ITSELF, and it beats every inferred and generated source.
    "mirror_of_measured": 75,
    "drawing_deterministic": 70,
    "title_block": 70,
    # The overall size the DETAIL prints, read as a blank. Deterministic — it is a number
    # off the drawing, not a guess — but it is one inference away from a measurement: an
    # overall is the finished part, and only a flat one has the same extent as its blank.
    # So it ranks below anything measured and above anything reasoned, and every consumer
    # must go on showing it as inferred. A pack with no model is priced from this or not
    # priced at all, which is why it exists; it is not a substitute for a flat pattern.
    "pdf_overall_dims": 65,
    "bom_tree": 60,
    "override_rule": 50,
    "llm_extract": 40,
    "llm_full_extract": 40,
    "inference": 20,
    "geometry_inference": 20,
}

# ── WHICH OF TWO EQUALLY-RANKED SOURCES WINS ────────────────────────────────────────
# Only ever consulted WITHIN a rank. Across ranks the waterfall has already decided, and
# this must never be able to reach across one.
#
# WHAT THIS CAN AND CANNOT SETTLE, because it is easy to expect too much of it. Only six
# pairs share a rank at all, and they are the pairs below. "SolidWorks beats the LLM" is
# not in here and never should be — that is the RANK (90 against 40), and writing it here
# too would be a second copy of the waterfall that could drift out of step with the first.
#
# It also cannot break the commonest tie, which is ONE SOURCE DISAGREEING WITH ITSELF: two
# DXF claims about the same fold, two LLM claims about the same weld. Nothing about the
# source name separates those, which is why this is the first key and not the only one.
#
# Higher wins. A source absent from this table scores 0 and falls through to the next key,
# which is the honest default — an ordering nobody can justify is worse than none.
SOURCE_TIEBREAK: Dict[str, int] = {
    # A person in the room beats a stored default. The knowledge base is what we believed
    # before anybody looked at this job.
    "estimator_confirmed": 2,
    "knowledge_base": 1,
    # A FLAT PATTERN IS THE BLANK ITSELF. The model and the generic DXF describe the
    # finished part and may be a view of it; the flat pattern is the thing that goes on the
    # bed. For every question this arbiter actually settles — folds, cut length, blank size
    # — the flat pattern is the more direct measurement of the two.
    "solidworks_flat_pattern": 2,
    "solidworks_api": 1,
    "dxf_flat_pattern": 2,
    "dxf": 1,
    # The title block is a controlled field on the sheet. "Deterministic" covers anything
    # else read off the drawing by rule, including body text, which is looser.
    "title_block": 2,
    "drawing_deterministic": 1,
    # The whole-job pass has seen the pack and can hold one sheet against another; the
    # per-part pass has seen one page. Same model, more context.
    "llm_full_extract": 2,
    "llm_extract": 1,
    # Inference FROM measured geometry rests on something; inference in general does not.
    "geometry_inference": 2,
    "inference": 1,
}


def tiebreak_priority(source: Any) -> int:
    """Within-rank precedence. 0 means "no published ordering" — fall through."""
    return SOURCE_TIEBREAK.get(str(source or "").strip().lower(), 0)


# ── WHERE A DECISION WAS TAKEN, IN THE ESTIMATOR'S WORDS ────────────────────────────
# The rank keys above are internal join fields. An estimator reading a report needs the
# thing that actually decided it — the model, the flat pattern, the title block, the AI —
# and needs to be able to tell a measurement from a language model at a glance.
#
# ONE OWNER. job_decision_report kept its own eight-entry version of this dict, which is
# how a source the waterfall knows about ("mirror_of_measured", "pdf_overall_dims") renders
# as a blank in the one document written to explain the decision. Anything not named here
# falls back to the raw key rather than to silence — an unfamiliar source is still a source,
# and printing nothing is the failure this exists to prevent.
SOURCE_DISPLAY_NAME: Dict[str, str] = {
    "estimator_confirmed":    "an estimator",
    "knowledge_base":         "SDI's knowledge base",
    "solidworks_api":         "the SolidWorks model",
    "solidworks_flat_pattern": "the SolidWorks flat pattern",
    "dxf":                    "the DXF",
    "dxf_flat_pattern":       "the DXF flat pattern",
    "mirror_of_measured":     "the measured opposite hand",
    "drawing_deterministic":  "the drawing",
    "title_block":            "the title block",
    "pdf_overall_dims":       "the drawing's overall dimensions",
    "bom_tree":               "the bill of materials",
    "override_rule":          "an SDI override rule",
    "llm_extract":            "Grok (xAI)",
    "llm_full_extract":       "Grok (xAI)",
    "llm_full_job":           "Grok (xAI)",
    "inference":              "engine inference",
    "geometry_inference":     "engine inference from geometry",
    "compiler_default":       "an engine default",
    "unknown":                "an unrecorded source",
}

# Sources that MEASURED the part rather than reasoned about it. Reports mark these
# differently because the distinction is the whole point of the waterfall: a number off a
# model can be held against the model, and a number off a language model cannot.
MEASURED_SOURCES = frozenset({
    "estimator_confirmed", "knowledge_base", "solidworks_api", "solidworks_flat_pattern",
    "dxf", "dxf_flat_pattern", "mirror_of_measured", "drawing_deterministic",
    "title_block", "pdf_overall_dims", "bom_tree",
})


def display_name(source: Any) -> str:
    """What to print for `source`. Never empty for a non-empty source."""
    key = str(source or "").strip().lower()
    if not key:
        return ""
    return SOURCE_DISPLAY_NAME.get(key, key.replace("_", " "))


def was_measured(source: Any) -> bool:
    """True when this source read the part rather than reasoned about it."""
    return str(source or "").strip().lower() in MEASURED_SOURCES


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


def _same_value(a: Any, b: Any) -> bool:
    """Do two observations say the same thing? Numbers compare numerically (2 and 2.0 are one
    fact), everything else case- and space-insensitively."""
    try:
        fa, fb = float(str(a).strip()), float(str(b).strip())
        return abs(fa - fb) < 1e-9
    except (TypeError, ValueError):
        pass
    return " ".join(str(a).split()).strip().lower() == " ".join(str(b).split()).strip().lower()


def confidence_of(part: Dict[str, Any], field: str) -> Optional[float]:
    if not isinstance(part, dict):
        return None
    path, leaf = _split(field)
    node = _walk(part, path)
    if node is None:
        return None
    try:
        return float(node.get(f"{leaf}_confidence"))
    except (TypeError, ValueError):
        return None


def may_overwrite(part: Dict[str, Any], field: str, new_source: Any,
                  new_value: Any = MISSING, new_confidence: Optional[float] = None) -> bool:
    """May `new_source` REPLACE a value that disagrees with it?

    Yes when the datum is empty — anything may fill a gap. Otherwise only a STRICTLY stronger
    source may replace a value it disagrees with.

    Equal rank used to be enough, on the reasoning that two passes of equal standing refining
    each other is normal and the later one usually knows more. That is not true of this
    pipeline. Two title-block readings of the same rank disagreeing is not refinement, it is
    a conflict — and resolving it by letting the later one win makes the answer depend on page
    order, silently, with no flag raised because the write succeeded. The first observation is
    kept and the disagreement recorded, unless the newcomer carries a strictly higher
    confidence, which is a real reason to prefer it rather than an accident of ordering.

    A recorded ZERO is a value, not a gap. A model reporting no cut-outs has answered the
    question, and a weaker source must not treat that answer as an opening."""
    if not isinstance(part, dict):
        return False
    _cur = value_of(part, field)
    if _cur is MISSING:
        return True
    _new_rank, _cur_rank = rank(new_source), rank(source_of(part, field))
    if _new_rank > _cur_rank:
        return True
    if _new_rank < _cur_rank:
        return False
    # Equal rank. Agreement is not a replacement at all, so it is allowed and handled by
    # apply_field as a provenance question.
    if new_value is not MISSING and _same_value(_cur, new_value):
        return True
    _cur_conf = confidence_of(part, field)
    if new_confidence is not None and _cur_conf is not None and new_confidence > _cur_conf:
        return True
    return False


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
    _cur = value_of(part, field)
    _cur_src = source_of(part, field)

    # AGREEMENT UPGRADES PROVENANCE. A source that confirms the value already present has
    # told us something real: this datum now rests on stronger evidence than it did. Callers
    # used to skip the resolver entirely when the numbers matched — "nothing to change" — and
    # the datum kept the weaker source's name, so a later medium-ranked pass could still
    # displace a figure the model had independently confirmed. Submitting agreement is how
    # the strong source's rank actually attaches to the value.
    if _cur is not MISSING and _same_value(_cur, value):
        _new_rank, _cur_rank = rank(source), rank(_cur_src)
        node = _walk(part, path, create=True)
        if node is not None:
            if _new_rank > _cur_rank:
                # SOURCE AND CONFIDENCE MOVE TOGETHER. Updating the source while leaving the
                # weaker source's confidence behind produces a datum labelled with a strong
                # source and scored with a weak one — a record that reads as better evidence
                # than anything actually supplied. When the stronger source gives no
                # confidence, the stale figure is cleared rather than inherited.
                node[key] = source
                if confidence is not None:
                    node[f"{leaf}_confidence"] = confidence
                else:
                    node.pop(f"{leaf}_confidence", None)
            elif _new_rank == _cur_rank and confidence is not None:
                # Corroboration at equal rank. Two independent readings agreeing is a
                # genuine strengthening even though neither outranks the other, so the
                # higher confidence stands. The source is unchanged: nothing was replaced.
                _prev = confidence_of(part, field)
                if _prev is None or confidence > _prev:
                    node[f"{leaf}_confidence"] = confidence
        # The value did not change, so this is not a change to report. Callers gate their
        # audit messages on the return, and "SolidWorks replaced X with X" is noise at best
        # and a false claim at worst.
        return False

    if may_overwrite(part, field, source, new_value=value, new_confidence=confidence):
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

    _cur_src_txt = _cur_src or "an earlier pass"
    if rank(source) == rank(_cur_src):
        # EQUAL RANK, DIFFERENT ANSWERS. Neither observation outranks the other, so nothing
        # here can resolve it — and letting the later one win would make the result depend on
        # the order pages happened to be read in. Keep the first, and say so.
        part.setdefault("review_flags", []).append(
            f"{field}: two sources of equal standing disagree — '{_cur}' from "
            f"{_cur_src_txt} was kept, '{value}' from {source} was not applied. Neither "
            f"outranks the other; a person must decide which is right")
    else:
        part.setdefault("review_flags", []).append(
            f"{field}: '{value}' from {source} NOT applied — '{_cur}' from {_cur_src_txt} is "
            f"the stronger source and was kept. The two disagree; confirm which is right")
    return False
