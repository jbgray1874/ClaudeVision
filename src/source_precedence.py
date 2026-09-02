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

from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "rank", "may_overwrite", "apply_field", "source_of", "SOURCE_RANK", "MISSING",
    "corroboration_defends",
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
    # WHAT THE DRAWING OFFICE TYPED ON THE EXPORT THAT GOES TO THE LASER.
    #
    # "11650-04-01A_2MM PETG_REVG.DXF" is not a guess and never was. It is a deliberate
    # label, applied by the person who issued the flat, on the file the machine cuts from —
    # and it was ranked `inference` (20) and applied only into a GAP, which meant that on a
    # part already carrying a material it was never recorded at all.
    #
    # 11650-04 is what that costs. The title block says PETG, an options list says PETG or
    # PC, SIX exports across five revisions are named 2MM PETG, and the parts catalogue
    # stocks 37 rows of it. One SolidWorks model property said ABS and won, because the only
    # other observation the record held was the title block: everything else had been
    # skipped rather than submitted, so the corroboration rule had one source to count where
    # the honest answer was two.
    #
    # Ranked WITH the drawing text, not above it. A filename is as good as the convention
    # behind it, which is exactly what a title block is; it must still lose to a measured
    # DXF or a model on its own. What changes is that it is now an OBSERVATION, and two
    # independent observations are what the quorum is for.
    "dxf_filename": 70,
    # A MATERIAL THE MODEL CARRIES BY APPEARANCE, NOT BY SPEC.
    #
    # SolidWorks reports two kinds of material through the same API field: an EXPLICIT custom
    # property the designer typed (the spec the part is bought to — that stays solidworks_api,
    # rank 90) and the library-APPLIED material, which is the appearance/simulation template
    # the model happens to carry. The applied material is frequently just a default the
    # designer never revisited — "Plain Carbon Steel" on a part the drawing calls MDF, a
    # birch-faced ply visual on a panel the title block calls MDF — so it must NOT overrule an
    # explicit drawing callout. Ranked one step below the drawing text (drawing_deterministic /
    # title_block / dxf_filename, all 70) so a lone SW library material loses to the drawing's
    # word, yet above the PDF's inferred overall (65) and everything reasoned — because it is
    # still a reading off the model, and when the drawing says nothing it is the best material
    # evidence in the pack. The analyser tags which kind it is; an extract that predates the
    # tag carries no applied-material observation and so behaves exactly as before.
    "solidworks_applied_material": 68,
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
    # Below both at the same rank. A filename is a controlled convention like a title block,
    # but it is a NAME rather than a field on the sheet -- so where the two disagree outright
    # the printed drawing is the one that was issued.
    "dxf_filename": 0,
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
    "solidworks_applied_material": "the SolidWorks library material (appearance, not a spec)",
    "dxf":                    "the DXF",
    "dxf_flat_pattern":       "the DXF flat pattern",
    "mirror_of_measured":     "the measured opposite hand",
    "drawing_deterministic":  "the drawing",
    "title_block":            "the title block",
    "dxf_filename":           "the DXF filename the drawing office typed",
    "pdf_overall_dims":       "the drawing's overall dimensions",
    "bom_tree":               "the bill of materials",
    "override_rule":          "an SDI override rule",
    "llm_extract":            "Grok (xAI)",
    "llm_full_extract":       "Grok (xAI)",
    "llm_full_job":           "Grok (xAI)",
    "inference":              "engine inference",
    "geometry_inference":     "engine inference from geometry",
    "compiler_default":       "an engine default",
    # A NAME FOR THE THING THAT WAS CALLED NOTHING.
    #
    # James, reading section 12 of the 10575-02 report — forty-odd operations, every one of them
    # "an unrecorded source", rank 0: "what is an unrecorded source?"
    #
    # They were operations recognised in the drawing's own note text. route_compiler's adapter
    # fell back to "unknown" for the textual_operations field, so a keyword recogniser reading
    # WELD AND DRESS off a note produced a claim indistinguishable from one nobody could account
    # for. The drawing said it; the record did not say the drawing said it.
    #
    # RANK IS DELIBERATELY UNCHANGED AT 0 (this key is absent from SOURCE_RANK, which ranks
    # anything it does not hold at 0). Naming a source is a reporting change; ranking it is a
    # costing change — it decides which claim wins an arbitration and therefore what the job is
    # priced at. Those two must not travel together, least of all in the week before this engine
    # is walked through with the estimators. Whether a recognised note should outrank a bare
    # inference is a real question and it needs a parity run, not a commit message.
    "drawing_notes":          "a note on the drawing",
    "unknown":                "an unrecorded source",
}

# Sources that MEASURED the part rather than reasoned about it. Reports mark these
# differently because the distinction is the whole point of the waterfall: a number off a
# model can be held against the model, and a number off a language model cannot.
MEASURED_SOURCES = frozenset({
    "estimator_confirmed", "knowledge_base", "solidworks_api", "solidworks_flat_pattern",
    "solidworks_applied_material",
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


def _observe(part: Dict[str, Any], field: str, value: Any, source: Any,
             applied: bool, displaced_by: Any = None) -> None:
    """Record that a source said this about this field, whatever became of it.

    ONE LIST, ONE QUESTION: what else has been said about this datum. Until now only a
    SUCCESSFUL replacement was recorded, so the evidence base was exactly backwards — a
    reading that lost was kept, and a reading that was REFUSED was written into review_flags
    as English prose and into the record not at all.

    11650-04 is what that costs. The title block says PETG, the options list says PETG or PC,
    six DXF exports are named 2MM PETG, and the parts catalogue stocks PETG — against one
    SolidWorks model property saying ABS. Every one of those PETG readings after the first was
    refused, so nothing could count them, and the question "did independent sources agree
    against the winner" had no data behind it however the rule was written.

    Duplicates are not evidence. The same source saying the same thing twice is one
    observation seen twice, and counting it as two is how a single stale filename would come
    to outvote a model.
    """
    if _is_empty(value) or not str(source or "").strip():
        return
    entry: Dict[str, Any] = {"value": value, "source": str(source), "applied": bool(applied)}
    if displaced_by:
        entry["displaced_by"] = str(displaced_by)
    log = part.setdefault("_displaced", {}).setdefault(field, [])
    for seen in log:
        if str(seen.get("source") or "") == entry["source"] and \
                _norm_value_key(seen.get("value")) == _norm_value_key(value):
            return
    log.append(entry)


def _agree(part: Dict[str, Any], field: str, value: Any, source: Any) -> None:
    """Record that a source CONFIRMED what this field already held.

    Agreement was the one outcome that left no trace. A replacement was logged and (now) a
    refusal is too, but a source arriving and saying "yes, that" returned early from
    apply_field as "nothing to change" — so the value's support was permanently undercounted
    at one, however many readers had confirmed it.

    That is not a bookkeeping detail once a quorum can overrule a singleton: two drawing
    sources would have outvoted a model that two other sources had independently confirmed,
    because only one of those confirmations was on the record. My own test caught it.
    """
    if _is_empty(value) or not str(source or "").strip():
        return
    log = part.setdefault("_agreed", {}).setdefault(field, [])
    for seen in log:
        if str(seen.get("source") or "") == str(source) and \
                _norm_value_key(seen.get("value")) == _norm_value_key(value):
            return
    log.append({"value": value, "source": str(source)})


def support_for(part: Dict[str, Any], field: str, value: Any) -> List[str]:
    """The DISTINCT sources that have named this value for this field, from every direction it
    could have been said: the source currently holding it, sources that confirmed it, and
    sources whose reading of it was overwritten or refused.

    Distinct sources, not distinct readings: two passes of one reader agreeing with itself is
    one observation seen twice, and counting it twice is how a single stale filename would
    come to outvote a model.
    """
    want = _norm_value_key(value)
    sources = {str(e.get("source")) for e in displaced_values(part, field)
               if str(e.get("source") or "") and _norm_value_key(e.get("value")) == want}
    for e in ((part.get("_agreed") or {}).get(field) or []) if isinstance(part, dict) else []:
        if str(e.get("source") or "") and _norm_value_key(e.get("value")) == want:
            sources.add(str(e["source"]))
    _cur = value_of(part, field)
    _cur_src = source_of(part, field)
    if _cur is not MISSING and _cur_src and _norm_value_key(_cur) == want:
        sources.add(str(_cur_src))
    return sorted(sources)


# How many INDEPENDENT sources must agree before they outweigh a single stronger one. Two,
# because that is the smallest number that is not one source seen twice, and because the case
# this exists for is exactly that shape: a drawing and its DXF export against a model.
CORROBORATION_QUORUM = 2


def corroboration_overrules(part: Dict[str, Any], field: str, new_value: Any,
                            new_source: Any) -> Optional[Dict[str, Any]]:
    """Do independent sources agreeing on `new_value` outweigh the single source now held?

    THE RULE, STATED ONCE, FOR EVERY ARBITRATED FIELD. A lone high-ranked reading is evidence;
    it is not proof, and a model's material property is the least reliable thing a model
    carries — it is whatever was assigned in CAD, while the title block is what was ISSUED and
    what the shop buys to.

    It takes a QUORUM against a SINGLETON. Two independent sources beat one; they do not beat
    two, because then nothing distinguishes the sides and order would decide it. Returns the
    evidence when the rule fires, so the caller can write down what outvoted what — a
    precedence rule that silently reverses an earlier decision is worse than the one it
    replaces.
    """
    _cur = value_of(part, field)
    if _cur is MISSING or _same_value(_cur, new_value):
        return None
    against = set(support_for(part, field, new_value)) | {str(new_source or "")}
    against.discard("")
    if len(against) < CORROBORATION_QUORUM:
        return None
    holding = support_for(part, field, _cur)
    if len(holding) >= len(against):
        # NOT A TIE-BREAK. Two against two is a disagreement a person has to settle, and
        # letting the newcomer win would make the answer depend on the order pages were read.
        return None
    return {"value": new_value, "sources": sorted(against),
            "displaced_value": _cur, "displaced_sources": holding}


# A PERSON DECIDING IS NOT A READER, AND IS NEVER OUTVOTED BY READERS.
_DECISION_RANK = 100


def corroboration_defends(part: Dict[str, Any], field: str, new_value: Any,
                          new_source: Any) -> Optional[Dict[str, Any]]:
    """Do independent sources agreeing on the value HELD outweigh a single stronger newcomer?

    THE OTHER HALF OF THE QUORUM RULE, AND THE HALF THE CASES NEEDED.

    `corroboration_overrules` is asked by apply_field only after ordinary precedence has
    REFUSED — that is, only when the newcomer was weaker or equal. So the quorum could
    protect a value from a weaker source, which it never needed protecting from, and could
    do nothing at all when a STRONGER one arrived. Every job cited in this module as the
    reason the rule exists is the stronger-source shape:

      * 11650-04's door — title block, an options list and six DXF exports all say PETG;
        one SolidWorks property says ABS, outranks them 90 to 70, writes, and the part
        goes from GBP 35.28 to GBP 0.00 because ABS has no rate in config.
      * 12349-02-69-04M's gauge — the DXF is named `1.2MM_MS`, the title block reads
        "1.2 THK", and the model's cut list says 6mm. Two readings against one, and the
        one wins by rank: a 1.2mm bracket costed as 6mm plate.

    In both, the losing evidence was recorded, countable, and never counted, because the
    only question asked of a stronger source was its rank.

    A quorum (>= CORROBORATION_QUORUM distinct sources) holding the current value turns a
    stronger singleton's overwrite into a refusal — a flagged conflict for a person to
    settle, not a silent replacement.

    It defends only while it is STRICTLY the larger side. Once as many sources have named
    the challenger's value, the count no longer separates them and the question goes back to
    rank, which is the resolver's ordinary job. That matters: a defence that held at parity
    would be a veto the first two readers could impose on any amount of later evidence, and
    the point of this is to weigh readings, not to freeze whichever arrived first.
    """
    _cur = value_of(part, field)
    if _cur is MISSING or _same_value(_cur, new_value):
        return None
    if rank(new_source) >= _DECISION_RANK:
        return None
    holding = set(support_for(part, field, _cur))
    holding.discard("")
    if len(holding) < CORROBORATION_QUORUM:
        # One source held it. A stronger reading correcting a lone stale filename is
        # precedence working, and nothing here should stand in its way.
        return None
    against = set(support_for(part, field, new_value)) | {str(new_source or "")}
    against.discard("")
    if len(against) >= len(holding):
        return None
    return {"value": _cur, "sources": sorted(holding),
            "refused_value": new_value, "refused_sources": sorted(against)}


def displaced_values(part: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    """Every observation this field does not currently hold, oldest first — refused as well as
    overwritten. Each entry says which it was, in `applied`.

    THE ARBITER KEPT ONLY THE LOSER OF A REFUSAL. When an incoming value was refused the
    disagreement was flagged with both sides; when it WON, whatever it replaced was
    overwritten and nothing recorded that anything had been. So a datum that arrived from
    three sources looked identical to one that arrived from a single source that nobody
    contradicted.

    11650's door is what that costs. The model said ABS, a DXF filename said POLYCARBONATE
    and the drawing text said POLYCARBONATE; the model outranked both and the part went from
    GBP 35.28 to GBP 0.00, because ABS has a sheet size and a density in config and no rate.
    Asking afterwards whether two independent sources had agreed against the winner was
    impossible: the answer had been thrown away at the moment it was needed.

    Recording it changes no outcome. It is the prerequisite for any rule that would.
    """
    if not isinstance(part, dict):
        return []
    record = part.get("_displaced")
    return list((record or {}).get(field) or []) if isinstance(record, dict) else []


def corroboration_against(part: Dict[str, Any], field: str) -> Dict[str, Any]:
    """How many DISTINCT sources named a value other than the one now held, and which.

    Distinct sources, not distinct readings: two passes of the same reader agreeing with
    itself is one observation seen twice, and counting it as two is how a single stale
    filename would come to outvote a model.
    """
    current = value_of(part, field)
    against: Dict[str, set] = {}
    for entry in displaced_values(part, field):
        val, src = entry.get("value"), str(entry.get("source") or "")
        if src and not (current is not MISSING and _same_value(current, val)):
            against.setdefault(_norm_value_key(val), set()).add(src)
    if not against:
        return {"count": 0, "value": None, "sources": []}
    _val_key, _srcs = max(against.items(), key=lambda kv: (len(kv[1]), kv[0]))
    _value = next(e["value"] for e in displaced_values(part, field)
                  if _norm_value_key(e.get("value")) == _val_key)
    return {"count": len(_srcs), "value": _value, "sources": sorted(_srcs)}


def _norm_value_key(value: Any) -> str:
    return str(value).strip().upper().replace("_", " ")


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
        # CONFIRMATION IS EVIDENCE AND HAS TO BE COUNTED. Without this the value's support is
        # stuck at one however many readers confirm it, and a quorum of two would overrule a
        # figure three sources had independently agreed on.
        _agree(part, field, value, source)
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

    # A QUORUM DEFENDS, AS WELL AS OVERRULES. Asked BEFORE precedence, because precedence
    # cannot ask it: by the time a stronger source has been allowed to write, the thing worth
    # weighing — that several independent readers already agreed against it — has been
    # overwritten. Where one source holds the value this is a no-op and rank decides as before.
    _defence = corroboration_defends(part, field, value, source)
    if _defence is not None:
        _observe(part, field, value, source, applied=False)
        part.setdefault("_corroboration", {})[field] = _defence
        part.setdefault("review_flags", []).append(
            f"{field}: '{value}' from {source} was NOT applied although it outranks what is "
            f"held — {len(_defence['sources'])} independent sources say '{_cur}' "
            f"({', '.join(_defence['sources'])}) against it. The stronger single reading has "
            f"been set aside because several others agree against it; confirm which is right")
        return False

    if may_overwrite(part, field, source, new_value=value, new_confidence=confidence):
        node = _walk(part, path, create=True)
        if node is None:
            return False
        # WHAT THIS REPLACED, KEPT. A refusal has always been flagged with both sides; a
        # SUCCESSFUL replacement recorded nothing, so a datum three sources argued over
        # looked exactly like one nobody contradicted. Asking afterwards whether two
        # independent sources had agreed against the winner was impossible — the answer was
        # discarded at the moment it became worth having.
        #
        # Nothing here changes an outcome. It is the prerequisite for any rule that would.
        if _cur is not MISSING and not _same_value(_cur, value):
            _observe(part, field, _cur, _cur_src or "an earlier pass",
                     applied=True, displaced_by=source)
        node[leaf] = value
        node[key] = source
        if confidence is not None:
            node[f"{leaf}_confidence"] = confidence
        if note:
            part.setdefault("review_flags", []).append(note)
        return True

    # REFUSED, AND ON THE RECORD BEFORE THE RULE IS ASKED. Every reading that loses is still
    # a reading, and until now the only trace of one was a sentence in review_flags that
    # nothing could count.
    _observe(part, field, value, source, applied=False)

    # A QUORUM OVERRULES A SINGLETON. Asked only after ordinary precedence has refused, so a
    # stronger source still wins on its own merits and this changes nothing where sources
    # agree. Where they do not, the question stops being "who ranks highest" and becomes "how
    # many independent readings say each thing" -- which is the question an estimator asks in
    # front of the drawing.
    _corr = corroboration_overrules(part, field, value, source)
    if _corr is not None:
        node = _walk(part, path, create=True)
        if node is not None:
            _observe(part, field, _cur, _cur_src or "an earlier pass",
                     applied=True, displaced_by=source)
            node[leaf] = value
            node[key] = source
            if confidence is not None:
                node[f"{leaf}_confidence"] = confidence
            else:
                node.pop(f"{leaf}_confidence", None)
            part.setdefault("review_flags", []).append(
                f"{field}: '{_corr['displaced_value']}' from "
                f"{', '.join(_corr['displaced_sources']) or 'an earlier pass'} was OUTVOTED — "
                f"{len(_corr['sources'])} independent sources say '{value}' "
                f"({', '.join(_corr['sources'])}). The stronger single source has been set "
                f"aside because several weaker ones agree against it; confirm which is right")
            part.setdefault("_corroboration", {})[field] = _corr
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


# ── FACTS THAT ARE BOUGHT TOGETHER ARE DECIDED TOGETHER ──────────────────────────────

# Fields that name ONE THING between them. A material and a gauge are not two independent
# facts about a part: they are a stock key, the thing that gets ordered, and the catalogue is
# keyed on the pair. Resolving them separately lets each half come from a different reading —
# which produces a key that no source ever asserted and no supplier stocks.
CO_ASSERTED_GROUPS: List[Tuple[str, ...]] = [
    ("normalized_material", "normalized_thickness_mm"),
]


def asserted_pairs(part: Dict[str, Any], group: Tuple[str, ...]) -> Dict[str, Tuple[Any, ...]]:
    """What each distinct source said about EVERY field in `group`, as whole readings.

    A source that spoke about only part of the group is recorded with MISSING for the rest —
    a title block naming a material and no gauge has not asserted a pair, and must not be read
    as having agreed to whatever gauge happened to be lying around.
    """
    said: Dict[str, Dict[str, Any]] = {}
    for field in group:
        for entry in displaced_values(part, field):
            src = str(entry.get("source") or "")
            if src:
                said.setdefault(src, {}).setdefault(field, entry.get("value"))
        for entry in ((part.get("_agreed") or {}).get(field) or []) if isinstance(part, dict) else []:
            src = str(entry.get("source") or "")
            if src:
                said.setdefault(src, {}).setdefault(field, entry.get("value"))
        _cur, _src = value_of(part, field), source_of(part, field)
        if _cur is not MISSING and _src:
            said.setdefault(str(_src), {}).setdefault(field, _cur)
    return {src: tuple(vals.get(f, MISSING) for f in group) for src, vals in said.items()}


def settle_companion_facts(part: Dict[str, Any]) -> List[str]:
    """When a reading is overruled, the facts it carried alongside lose the standing they
    borrowed from it.

    11650-04 IS WHAT THIS COSTS, AND IT COST IT TWICE. The panels are read by a SolidWorks
    model saying ABS 2.2mm, by a title block saying PETG, and by six DXF exports named
    `11650-04-01A_2MM PETG_REVG.DXF`. Promoting the filename to a real source let two
    independent readings outvote the model on MATERIAL — correctly — while the gauge stayed at
    2.2 on the model's authority, because only one source had named 2.0 and a quorum needs two.

    The result was PETG at 2.2mm. Nobody said that. The model said ABS at 2.2, the export said
    PETG at 2.0, and the engine took one half from each — then looked up a rate keyed on the
    pair, matched the gauge exactly as it must, found nothing stocked at 2.2, and priced the
    part at nothing. A defensible decision on each field separately, and a purchase order that
    cannot be placed.

    THE RULE, AND IT IS NOT ABOUT SHEET. A source that is overruled on one half of a joint fact
    does not keep its authority over the other half by default: the two came from one reading,
    and that reading has been set aside. Where the sources that WON also named the companion,
    theirs is the one that goes with it, because it is the reading that survived intact.

    NOT A LICENCE TO MIX THE OTHER WAY. A source that never spoke about the companion has not
    lost an argument about it, so a title block naming a material and no gauge leaves the
    model's gauge exactly where it was. Only a reading that asserted BOTH and was overruled on
    one gives up the other.

    Returns the fields it moved, for the caller to report. Changes nothing when no
    corroboration fired, which is almost every part.
    """
    if not isinstance(part, dict):
        return []
    corr = part.get("_corroboration") or {}
    if not corr:
        return []
    moved: List[str] = []
    for group in CO_ASSERTED_GROUPS:
        overruled = [f for f in group if f in corr]
        if not overruled:
            continue
        winners: set = set()
        losers: set = set()
        for f in overruled:
            winners |= {str(s) for s in (corr[f].get("sources") or [])}
            losers |= {str(s) for s in (corr[f].get("displaced_sources") or [])}
        winners.discard("")
        losers.discard("")
        pairs = asserted_pairs(part, group)
        for i, field in enumerate(group):
            if field in overruled:
                continue
            held_src = source_of(part, field)
            # ONLY A READING THAT LOST. A source still holding this field on its own merits,
            # having never been contradicted on the companion, is untouched.
            if not held_src or held_src not in losers:
                continue
            # Being in `losers` IS having asserted both halves: a source only lands there by
            # having named the overruled value, and it is here by holding this one. An extra
            # "did it assert both" check looked prudent and was unreachable — no mutant could
            # kill it, which is the tell. Removed rather than kept as decoration.
            candidates = [(src, pairs[src][i]) for src in sorted(winners)
                          if src in pairs and pairs[src][i] is not MISSING]
            if not candidates:
                # NOTHING TO PUT IN ITS PLACE IS NOT A REASON TO PRETEND. The half-rejected
                # reading stays, and the record says the pair rests on two readings that
                # disagreed — which is a question for a person, not a number to invent.
                part.setdefault("review_flags", []).append(
                    f"{field}: kept '{value_of(part, field)}' from {held_src}, whose reading of "
                    f"{'/'.join(f for f in overruled)} was outvoted. No source that won named "
                    f"a {field}, so this half of the pair rests on a reading that was set "
                    f"aside — confirm it")
                continue
            _src, _val = candidates[0]
            _was, _was_src = value_of(part, field), held_src
            if _same_value(_was, _val):
                continue
            path, leaf = _split(field)
            node = _walk(part, path, create=True)
            if node is None:
                continue
            _observe(part, field, _was, _was_src, applied=True, displaced_by=_src)
            node[leaf] = _val
            node[_source_key(leaf)] = _src
            node.pop(f"{leaf}_confidence", None)
            part.setdefault("review_flags", []).append(
                f"{field}: '{_was}' from {_was_src} replaced by '{_val}' from {_src} — "
                f"{_was_src} was overruled on {'/'.join(overruled)}, and a material and a "
                f"gauge are one stock key. Taking one half from each reading produced "
                f"'{_was}' with a material nobody paired it with, which is not a stock item "
                f"anyone can buy; confirm the pair")
            part.setdefault("_companion_settled", {})[field] = {
                "value": _val, "source": _src, "displaced_value": _was,
                "displaced_source": _was_src, "because_of": sorted(overruled)}
            moved.append(field)
    return moved
