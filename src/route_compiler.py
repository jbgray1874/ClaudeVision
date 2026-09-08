"""Job-level manufacturing route compiler.

This module is deliberately independent of workbook rendering. Extraction layers submit
evidence as operation claims; the compiler resolves those claims into one decision per job
event. A job event is owned by a leaf or assembly target and may name several participating
parts without multiplying the work by the participant count.

The first integration is shadow-only. Nothing here changes a price or workbook row.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import bought_in_policy
from source_precedence import rank


ROUTE_SCHEMA = "canonical_route.v1"
PRICED_ROUTE_SCHEMA = "priced_route_shadow.v1"

REQUIRED = "required"
RULED_OUT = "ruled_out"
NOT_APPLICABLE = "not_applicable"
UNVERIFIED = "unverified"

VALID_STATUSES = frozenset({REQUIRED, RULED_OUT, NOT_APPLICABLE, UNVERIFIED})
VALID_SCOPES = frozenset({"part", "assembly"})
NEGATIVE_STATUSES = frozenset({RULED_OUT, NOT_APPLICABLE})

# A hierarchy claim that a node is an assembly outranks inferential claims to perform these
# operations on the parent. A stronger measured claim can still win through source ranking.
LEAF_ONLY_OPERATIONS = frozenset({
    "laser_cutting", "folding", "punch", "hole_machining", "drilling",
    "guillotine", "saw", "tube_cut", "tube_bending",
})

# Older cached extracts predate the scope field. For these operations, several participants
# under one common assembly describe one job event, not one event per participant. The
# inference is retained as an issue so a new extract with explicit scope can supersede it.
# Operations that ARE the act of joining — naming one is naming how the sub-assembly comes
# into existence, which a generic "assembly" event would then charge for a second time.
#
# HARDWARE INSERTION ONLY, deliberately. Welding is already handled by the weld-parent rule
# further down, and adding it here made a SECOND authority for the same question — which
# promptly broke the case that rule exists to protect: a welded TOP assembly still has to be
# packed. One rule per question; this one covers the case 11350 actually showed.
SPECIFIC_JOINING_OPERATIONS = frozenset({"hardware_insertion"})

ASSEMBLY_EVENT_OPERATIONS = frozenset({
    "welding", "dress_welds", "powder_coating", "assembly", "handling",
    "hardware_insertion",
})
TUBE_INAPPLICABLE_OPERATIONS = frozenset({
    "laser_cutting", "punch", "guillotine",
})

# A TUBE IS STILL BENT. These are the flat-sheet bending words a drawing uses; on a tube the
# PROCESS is impossible (no press brake) but the BEND is real, so the operation is replaced by
# the tube bender's own rather than deleted. Dropping it outright took £8.70 of Tubebend off
# 7332-01's leg between two runs and bent the leg for free — the same "remap, not drop" lesson
# the cut already carries in wb_populate._TUBE_OP_REMAP.
TUBE_BEND_SOURCE_OPERATIONS = frozenset({
    "fold", "folding", "linebend", "line_bend",
})

CONFIDENCE_VALUE = {"low": 0.25, "medium": 0.60, "high": 0.90}

OPERATION_ALIASES = {
    "handling": "assembly",
    "insert_hardware": "hardware_insertion",
    "insert_pem": "hardware_insertion",
    "pem_insertion": "hardware_insertion",
    "clinch_insertion": "hardware_insertion",
}

# Shop-order fallback for a required event whose evidence named the work but omitted its
# sequence. It fills only the sequence field after status arbitration; it can never turn a
# negative or uncertain claim into required work.
DEFAULT_OPERATION_SEQUENCE = {
    "laser_cutting": 10,
    "punch": 10,
    "guillotine": 10,
    "saw": 15,
    "tube_cut": 15,
    "hardware_insertion": 18,
    "hole_machining": 20,
    "drilling": 20,
    "tapping": 20,
    "folding": 30,
    "tube_bending": 30,
    "welding": 40,
    "dress_welds": 41,
    "powder_coating": 70,
    "assembly": 90,
}


def _squashed(value: Any) -> str:
    """A-Z0-9 only, uppercased — the spelling that survives wraps, carets and spaces."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


_DRILL_OPS = frozenset({"hole_machining", "drilling", "drill", "hole_drilling"})
_HOLE_NOTE_RE = re.compile(
    r"[Ø⌀]\s*\d|\bDIA(?:METER)?\b|\bDRILL\b|\bTAPPED\b|\bC'?SK\b|\bCOUNTERSUNK\b"
    r"|\bHOLES?\b[^A-Z0-9]{0,12}\d|\d[^A-Z0-9]{0,3}HOLES?\b")


def _unsupported_drill_reason(template, record: Mapping[str, Any]) -> Optional[str]:
    """Why a text-cued drilling operation is not charged on this part, or None.

    NOT A UNIVERSAL BAN. Secondary drilling can be real work that never shows on the
    cutting flat, so a claim survives whenever a note actually calls a hole up — Ø5,
    DRILL, TAPPED, CSK, '4 HOLES'. What does not survive is a bare text cue on a part
    whose measured geometry says zero holes and whose own words never mention one:
    10975-02-A01 carried £13.40 of Drill (Acrylic) with hole_sizes_mm = [] and no hole
    note anywhere on its page."""
    if clean_operation(template.operation) not in _DRILL_OPS:
        return None
    src = str(getattr(template, "source", "") or "").lower()
    if "deterministic" in src or "measured" in src:
        return None                                    # a measured claim stands
    # THE LIVE RECORD'S OWN KEYS. On the 16:37 run this gate existed and never fired: the
    # measured flag lives in geometry_source ("solidworks_flat_pattern") and the hole
    # evidence in hole_sizes_mm / estimated_hole_count, not in the four booleans the first
    # version read. Evidence detection is a union of every spelling the pipeline writes.
    _geom_src = str(record.get("geometry_source") or "").lower()
    _ng = record.get("normalized_geometry") or {}
    measured = bool(record.get("native_flat_pattern") or record.get("dxf_augmented")
                    or record.get("dxf_measured_outline")
                    or record.get("flat_pattern_detected")
                    or "flat_pattern" in _geom_src or "dxf" in _geom_src
                    or (number(record.get("geometry_reliability"), 0.0) >= 0.9
                        and number(_ng.get("blank_length_mm"), 0.0)))
    if not measured:
        return None
    holes = None
    for key in ("hole_count",):
        if record.get(key) is not None:
            holes = record.get(key)
            break
    if holes is None:
        hs = record.get("hole_sizes_mm")
        if isinstance(hs, (list, tuple)):
            holes = len(hs)
    if holes is None:
        # geometry_rollup is the dict the 17:11 run actually carried the count in —
        # estimated_hole_count: 0 on a dxf_flat_pattern read — while the first two are
        # where earlier packs put it. All three spellings, first answer wins.
        for src in (record.get("dxf_raw_geometry") or {},
                    record.get("geometry_rollup") or {}, _ng):
            if isinstance(src, Mapping) and src.get("estimated_hole_count") is not None:
                holes = src.get("estimated_hole_count")
                break
    if holes is None or number(holes, 0.0):
        return None
    bits: List[str] = []
    for key in ("description", "notes", "note_snippets", "combined_notes",
                "textual_notes"):
        v = record.get(key)
        if isinstance(v, (list, tuple)):
            bits.extend(str(x) for x in v)
        elif v:
            bits.append(str(v))
    if _HOLE_NOTE_RE.search(" ".join(bits).upper()):
        return None
    return ("no hole was measured on the flat and no note on this part calls one up — "
            "a text cue alone does not drill. A stated secondary-drilling note "
            "(Ø, DRILL, TAPPED, CSK) brings this back")


def _interleave_of(whole: str, a: str, b: str, min_each: int = 0) -> bool:
    """True when `whole` is a character-perfect interleave of prefixes of `a` and `b`
    (both orders preserved), consuming at least `min_each` characters from each — the
    shape a wrapped BOM row takes when the text extractor zips it with its neighbour.
    min_each=0 with full lengths is the classic whole-string interleave. Standard
    two-sequence DP over positions in `a`."""
    if not whole or not a or not b or len(whole) > len(a) + len(b):
        return False
    states = {0}                                       # chars consumed from a
    for k, ch in enumerate(whole):
        nxt = set()
        for i in states:
            j = k - i                                  # chars consumed from b
            if i < len(a) and a[i] == ch:
                nxt.add(i + 1)
            if 0 <= j < len(b) and b[j] == ch:
                nxt.add(i)
        if not nxt:
            return False
        states = nxt
    n = len(whole)
    return any(i >= min_each and (n - i) >= min_each for i in states)


def _record_by_squashed_key(records: Mapping[str, Any], target_id: Any):
    """The unique record whose squashed key contains, or is contained by, the target's —
    None otherwise. Ten characters of overlap required, so a fragment can find its full
    configured name but a project number cannot claim a part."""
    sq = _squashed(target_id)
    if len(sq) < 10:
        return None
    hits = []
    for key, rec in (records or {}).items():
        ks = _squashed(key)
        if len(ks) >= 10 and ks != sq and (sq in ks or ks in sq):
            hits.append(rec)
    return hits[0] if len(hits) == 1 else None


def clean_part_number(value: Any) -> str:
    """The canonical spelling of a part number, or "" when the code names no part.

    A drawing prints "-" where it has no code to print. That is a statement of absence, not
    an identity, and treating it as one gave job 11350 a part numbered "-" that absorbed the
    M4 wing nut and then appeared in the hierarchy and as a participant in the assembly
    route. Returning "" here drops it at every caller at once, because every caller already
    skips a blank identity."""
    text = re.sub(r"\s+", " ", str(value or "").strip()).upper()
    try:
        from part_identity import is_placeholder_identity

        if is_placeholder_identity(text):
            return ""
    except Exception:
        pass
    return text


def clean_operation(value: Any) -> str:
    cleaned = re.sub(
        r"_+", "_",
        re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()),
    ).strip("_")
    return OPERATION_ALIASES.get(cleaned, cleaned)


def number(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def confidence_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in CONFIDENCE_VALUE:
            return CONFIDENCE_VALUE[text]
    return number(value)


def stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    serialised = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha1(serialised.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


@dataclass(frozen=True)
class ChildEdge:
    part_number: str
    qty: float = 1.0


@dataclass
class PartNode:
    part_number: str
    description: str = ""
    kind: str = "leaf"  # leaf | assembly | bought_in
    qty_per_unit: float = 1.0
    parents: List[str] = field(default_factory=list)
    children: List[ChildEdge] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OperationClaim:
    claim_id: str
    operation: str
    status: str
    source: str
    source_rank: int
    subject_id: str
    target_id: str
    scope: Optional[str] = None
    participants: List[str] = field(default_factory=list)
    qty_per_unit: Optional[float] = None
    sequence: Optional[float] = None
    confidence: Optional[float] = None
    reason: str = ""
    route_id: str = ""
    # WHAT PUT THIS OPERATION HERE, in the drawing's own words. A finish note, a weld
    # symbol, a bend line count, a cut-list property.
    #
    # `reason` is our prose about the claim; this is the DRAWING's. The difference decides
    # whether an operation can be checked: a claim that quotes the sheet can be held
    # against the sheet, and a bare operation name cannot be argued with at all. It is
    # what makes an LLM claim corroborable rather than merely ranked.
    evidence: str = ""
    evidence_where: str = ""


@dataclass
class OperationDecision:
    decision_id: str
    route_id: str
    operation: str
    status: str
    target_id: str
    scope: Optional[str]
    participants: List[str]
    qty_per_unit: Optional[float]
    sequence: Optional[float]
    source: str
    source_rank: int
    confidence: Optional[float]
    reason: str
    field_provenance: Dict[str, str]
    conflicts: List[Dict[str, Any]]
    claims: List[Dict[str, Any]]
    # The drawing's own words behind this operation, carried from the strongest claim
    # that had any. Empty means nothing quoted the sheet — which is a fact about the
    # decision an estimator should be able to see, not a blank to be filled in.
    evidence: str = ""
    evidence_where: str = ""
    # True when something READ this operation off the drawing or the model, rather than
    # reasoning it from the job. False is not a fault — it is a fact an estimator is
    # entitled to see, and what check_uncorroborated_route_operations weighs.
    corroborated: bool = True
    # ── EVERY MATTER IS RESOLVED ────────────────────────────────────────────────────
    # A disagreement between two equally-ranked sources used to leave the operation
    # UNVERIFIED, which is not a decision — it is the absence of one, handed downstream to
    # a reader that has less to go on than the arbiter did. Nothing costs an UNVERIFIED
    # operation, so an unsettled tie silently priced as zero.
    #
    # So the tie is now BROKEN and the operation carries a status. What must not be lost is
    # that it WAS a tie: `contested` says a real disagreement was resolved rather than
    # absent, `losing_statuses` says what the other side claimed, and `conflicts` still
    # carries the full record. Resolved is not the same as unanimous, and the report has to
    # be able to tell them apart.
    contested: bool = False
    losing_statuses: List[str] = field(default_factory=list)
    # WHERE THE DECISION WAS TAKEN, in the estimator's vocabulary rather than ours:
    # "the SolidWorks model", "the DXF flat pattern", "Grok (xAI)". `source` is the
    # internal key and stays the join field; this is what a person reads.
    decided_by: str = ""
    # WHICH KEY SETTLED A CONTEST, when there was one. Empty on an uncontested decision.
    # "rank" never appears here: rank is the waterfall deciding, and this field exists to
    # expose the cases where the waterfall called two sources equal and the arbiter had to
    # choose. That is the line an estimator should look at when tuning the engine.
    settled_by_key: str = ""


def make_claim(
    operation: Any,
    status: str,
    source: str,
    subject_id: Any,
    target_id: Any,
    *,
    scope: Optional[str] = None,
    participants: Optional[Iterable[Any]] = None,
    qty_per_unit: Any = None,
    sequence: Any = None,
    confidence: Any = None,
    reason: Any = "",
    route_id: str = "",
    evidence: Any = "",
    evidence_where: Any = "",
) -> OperationClaim:
    operation_name = clean_operation(operation)
    status_name = status if status in VALID_STATUSES else UNVERIFIED
    scope_name = str(scope or "").strip().lower() or None
    if scope_name not in VALID_SCOPES:
        scope_name = None
    participant_ids = sorted({
        clean_part_number(item) for item in (participants or [])
        if clean_part_number(item)
    })
    payload = {
        "operation": operation_name,
        "status": status_name,
        "source": str(source or "").strip() or "unknown",
        "subject_id": clean_part_number(subject_id),
        "target_id": clean_part_number(target_id),
        "scope": scope_name,
        "participants": participant_ids,
        "route_id": route_id,
        "reason": str(reason or ""),
    }
    return OperationClaim(
        claim_id=stable_id("claim", payload),
        operation=operation_name,
        status=status_name,
        source=str(source or "").strip() or "unknown",
        source_rank=rank(str(source or "").strip() or "unknown"),
        subject_id=clean_part_number(subject_id),
        target_id=clean_part_number(target_id),
        scope=scope_name,
        participants=participant_ids,
        qty_per_unit=number(qty_per_unit),
        sequence=number(sequence),
        confidence=confidence_value(confidence),
        reason=str(reason or ""),
        route_id=str(route_id or ""),
        evidence=" ".join(str(evidence or "").split())[:300],
        evidence_where=" ".join(str(evidence_where or "").split())[:120],
    )


def _raw_parts(parts: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for part in parts or []:
        if not isinstance(part, Mapping):
            continue
        identity = clean_part_number(part.get("part_number") or part.get("item_number"))
        if identity:
            result.setdefault(identity, part)
    return result


def _extract_part_records(llm_extract: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Canonical BOM identities and classifications read by the full-job extract.

    A DRAWING LEAVES THE CODE CELL BLANK FOR STANDARD HARDWARE, and a blank is not an
    identity — so those rows were dropped here and minted much later, in the dual-path
    reader, AFTER the graph was compiled. That is why 11350's wing nuts and PEM studs sat in
    the workbook and in the reports but not in the canonical BOM: two BOM authorities, and
    the one the estimator reads was the one the hierarchy had never seen.

    The identity is derived from the DESCRIPTION, by the same shared rule the later reader
    uses, so both derive the same code and the hardware enters the graph at the front.
    """
    from part_identity import is_placeholder_identity, synthesise_bought_in_code

    result: Dict[str, Dict[str, Any]] = {}
    for pool_name in ("bom", "parts"):
        for item in llm_extract.get(pool_name) or []:
            if not isinstance(item, Mapping):
                continue
            raw_identity = item.get("part_number")
            identity = clean_part_number(raw_identity)
            # ONLY FOR A ROW THE EXTRACT ITSELF CALLS BOUGHT-IN. Minting a code from the
            # words of an uncoded FABRICATED row would invent a part nobody can make.
            _is_placeholder = is_placeholder_identity(raw_identity)
            if _is_placeholder and _bought_in_record(item):
                identity = clean_part_number(
                    synthesise_bought_in_code(item.get("description"), raw_identity))
            if not identity:
                continue
            record = result.setdefault(identity, {})
            for key, value in item.items():
                if value not in (None, "", [], {}):
                    record[key] = value
            if item.get("qty") is not None and record.get("quantity") is None:
                record["quantity"] = item.get("qty")
            if item.get("is_bought_in"):
                record["is_bought_in"] = True
            if _is_placeholder:
                # Kept so the estimator can see the code was derived, not printed.
                record["is_bought_in"] = True
                record["identity_source"] = "description_bought_in"
                record["raw_placeholder_identity"] = str(raw_identity or "")
    return result


def _description_tokens(value: Any) -> Set[str]:
    ignored = {"THE", "AND", "FOR", "WITH", "PART", "STD", "MM"}
    return {
        token for token in re.findall(r"[A-Z0-9]+", str(value or "").upper())
        if len(token) >= 3 and token not in ignored and not re.fullmatch(r"M\d+", token)
    }


def _bought_in_record(record: Mapping[str, Any]) -> bool:
    """Do we BUY this part, or make it?

    MEASURED GEOMETRY OF ITS OWN OUTRANKS A TRANSCRIBED ROLE. bought_in_policy states the rule
    already — "a part with its own measured flat is a fabricated leaf whatever a transcribed
    hierarchy says" — but it was only ever used to RAISE a conflict for a person, never to
    decide the kind. So 7332-01-001 BASE, which the Sheet Steel block nests as 5mm steel and
    the labour block charges £3.03 of laser to cut, was published as "bought_in" on the
    Canonical BOM and the provenance tab: a part the sheet demonstrably fabricates, described
    to an estimator as one we purchase.

    The costing is unaffected — the money was already on the nest and there is no second charge.
    This is the classification catching up with what the sheet does.
    """
    _stated = bool(
        record.get("is_bought_in")
        or "bought_in" in {
            str(item).strip().lower()
            for item in (record.get("page_roles") or [])
        }
        or str(record.get("material_family") or "").strip().lower() == "bought_in"
    )
    if not _stated:
        return False
    try:
        from bought_in_policy import has_fabrication_evidence
    except Exception:                                                # noqa: BLE001
        return True
    # Its own measured flat means we cut it. The conflict is still flagged for a person by
    # estimator.bought_in_conflict; this only stops the graph publishing the losing answer.
    return not has_fabrication_evidence(dict(record))


def _drawing_code_aliases(identities: Iterable[str],
                          records: Optional[Mapping[str, Mapping[str, Any]]] = None,
                          refused: Optional[List[Dict[str, str]]] = None) -> Dict[str, str]:
    """Join the codes the FILES use to the codes the DRAWING's BOM uses.

    THE SAME PART UNDER TWO NAMES IS TWO PARTS, and that is the expensive failure. On 11350
    the GA BOM lists "11350-01-01" and "11350-01-02 MIR"; the model and DXF are
    "11350-01-01M" and "Mirror11350-01-02M". Unjoined, a five-item BOM compiles to seven
    nodes: the bar and the right arm each appear twice, once with the drawing's quantity and
    hierarchy and once with the measured geometry — and neither copy has both. The measured
    node has no parent at all, so it is a disconnected leaf carrying the only real blank
    dimensions on the job.

    Two conventions, and only two:

      MATERIAL SUFFIX   "<code><T|M|A>" is the drawing's "<code>" cut in that material.
      MIRROR            "Mirror<code>" is the drawing's "<code> MIR" line, or "<code>"
                        where the drawing does not list the mirror separately.

    An alias is only created when the TARGET ALREADY EXISTS as an identity. A code that
    merely looks suffixed but whose base is not on this job stays exactly as it is — the
    safe direction, because inventing a join costs a part its own identity while declining
    one only costs a merge the estimator can see.

    AND NOT ACROSS KINDS. This pass used to receive nothing but strings, so it could not
    ask what the two codes WERE — it merged on the naming convention alone. A material
    suffix says "<code> cut in that material", which is a claim about a part we make; if
    the base code is a bought-in line, the convention has matched a spelling and not a
    part, and following it hands a fabricated leaf's identity — with its route and its
    measured blank — to something we purchase. `records` is how it can now decline, and
    every refusal is recorded rather than silently skipped: a join we would once have made
    and now do not is exactly the thing somebody will need to see.
    """
    from part_code_conventions import alias_targets

    known = {str(i).strip().upper() for i in identities if str(i).strip()}

    # SPACING IS A TYPING ARTEFACT, NOT IDENTITY.
    #
    # Job 11350 carried BOTH "11350-01-02 MIR" and "11350-01-02MIR" — the GA's spelling and
    # the workbook's — as two separate nodes. One held the geometry and the other took an
    # AI market price of GBP 79.04, which was 82% of the material total on a part we have a
    # measured flat for. Matching on the exact string cannot see that they are one part.
    #
    # The squashed form indexes them together; the LONGEST spelling wins as the canonical
    # one, because "11350-01-02 MIR" is what the drawing prints and a code the estimator
    # cannot find on the GA is worse than one with an extra space.
    def _squash(value: str) -> str:
        return re.sub(r"\s+", "", value)

    _by_squash: Dict[str, str] = {}
    for _i in sorted(known, key=lambda v: (-len(v), v)):
        _by_squash.setdefault(_squash(_i), _i)

    _rec = {str(k).strip().upper(): v for k, v in (records or {}).items()
            if isinstance(v, Mapping)}

    def _may_merge(source: str, target: str) -> bool:
        a, b = _rec.get(source), _rec.get(target)
        if a is None or b is None:
            return True          # nothing known about one end; the other tests still hold
        if _kinds_are_compatible(a, b):
            return True
        if refused is not None:
            refused.append({"identity": source, "target": target,
                            "identity_kind": _record_kind(a) or "unstated",
                            "target_kind": _record_kind(b) or "unstated"})
        return False

    aliases: Dict[str, str] = {}
    for identity in sorted(known):
        # Same part, two spellings: bind the shorter onto the drawing's own.
        _canon = _by_squash.get(_squash(identity))
        if _canon and _canon != identity:
            if _may_merge(identity, _canon):
                aliases[identity] = _canon
            continue
        for _t in alias_targets(identity):
            _hit = _by_squash.get(_squash(_t.strip().upper()))
            if _hit and _hit != identity and _may_merge(identity, _hit):
                aliases[identity] = _hit
                break
    return aliases


def _same_description(a: Any, b: Any) -> bool:
    return (" ".join(str(a or "").upper().split())
            == " ".join(str(b or "").upper().split()) != "")


def _quantities_do_not_disagree(a: Optional[float], b: Optional[float]) -> bool:
    """True unless BOTH are stated and they differ. A figure nobody gave is not a conflict."""
    return a is None or b is None or a == b


def _record_kind(record: Mapping[str, Any]) -> str:
    """assembly / bought_in / leaf, from whatever the record already states. '' = unstated.

    EVIDENCE OF FABRICATION OUTRANKS A FLAG. A part we measured a blank on, or read a
    laser and a fold against, is something we CUT — and it stays that whatever a
    canonical_kind field says, because the flag is a classification and the geometry is
    an observation. Asked the other way round, an unstated kind abstained, and abstaining
    is what let a fabricated leaf be aliased onto a bought-in that merely looked like a
    spelling of it: the leaf's route and its measured blank go with its identity.

    The asymmetry is deliberate and it is the safe direction. Calling a bought-in
    "fabricated" costs a route nobody will book, which an estimator sees on the sheet.
    Calling a fabricated leaf "bought-in" deletes the cutting, folding and welding from a
    part we make, and nothing on the sheet says so.
    """
    kind = str(record.get("canonical_kind") or "").lower().strip()
    if record.get("is_sub_assembly") or record.get("is_assembly_parent") \
            or (record.get("assembly_children") or []) or kind == "assembly":
        return "assembly"
    try:
        # The merge-purpose bar, not the make/buy one — see the predicate's own note on
        # why the two differ.
        if bought_in_policy.looks_fabricated_for_identity(dict(record)):
            return "leaf"
    except Exception:                                              # noqa: BLE001
        pass
    if kind in ("bought_in", "leaf"):
        return kind
    if _bought_in_record(record) or record.get("is_bought_in") is True:
        return "bought_in"
    return ""


def _kinds_are_compatible(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Two records of DIFFERENT stated kinds are not two spellings of one part.

    A bought-in fastener and a fabricated leaf are different things however alike their
    codes look, and an assembly is never a spelling of anything it might contain. Where a
    kind is unstated the test abstains — absence is silence here as everywhere else, and
    the description, quantity and hierarchy tests still have to pass.
    """
    _a, _b = _record_kind(a), _record_kind(b)
    return not (_a and _b) or _a == _b


def _prefix_related(a: str, b: str) -> bool:
    """One code is the other with characters missing off the end — a TRUNCATION.

    A SEPARATOR MEANS HIERARCHY, NOT TRUNCATION. "12422-24" is a prefix of "12422-24-01"
    and they are a parent and its child, not one code read twice; collapsing them would
    fold an assembly into one of its own parts. part_identity.stem_duplicate_target has
    guarded this since it was written and this path did not port the guard — the same rule,
    stated twice, drifted the moment there were two copies of it.

    Also requires four characters, so "M4" cannot swallow "M4X8".
    """
    _a, _b = a.upper(), b.upper()
    if _a == _b:
        return False
    _short, _long = (_a, _b) if len(_a) < len(_b) else (_b, _a)
    if len(_short) < 4 or not _long.startswith(_short):
        return False
    return _long[len(_short)].isalnum()


def _numeric_sets_contradict(a: Set[str], b: Set[str]) -> bool:
    """Do two descriptions actually DISAGREE about a figure?

    A recorded conflict becomes a manufacturing decision an estimator has to answer, so it
    must mean a contradiction — 200 on one sheet and 220 on the other. The first version
    fired on ANY difference between the numeric-token sets, and the survivor's own line
    carries its part prefix ("10975") as a bare number, so "…LENGTH: 200.00" against
    "10975 … LENGTH: 200.00" raised a phantom '200 vs 200' decision beside the real
    200-vs-220 one. A superset states the same figures plus context; only two sets that
    EACH hold a number the other lacks are two different answers to one question.
    """
    a = set(a or ())
    b = set(b or ())
    return bool(a - b) and bool(b - a)


def _raw_identity_aliases(
    raw: Mapping[str, Mapping[str, Any]],
    extracted: Mapping[str, Mapping[str, Any]],
    claimed: Any = (),
) -> Dict[str, str]:
    """Reconcile generated BI-* identities with the explicit BOM code they came from.

    AND THE SAME PART SPELLED TWO WAYS ACROSS TWO SOURCES. 12422-24 put "79814P613" in the
    part records and "79814P" in the extract, as a child of the GA — the same four screws,
    the same description, never in the same list. The single-list truncation merge could not
    pair them because neither pool ever held both, so it returned nothing on every run while
    the sheet carried both lines and the graph reported the unclaimed one as disconnected.

    This is where the two sources meet, and where a pair like that has to be resolved: by
    ALIASING, so both identities become one node and every field either record carried is
    merged rather than one row being deleted with its supplier, price and provenance on it.

    The surviving spelling is the one the job hierarchy CLAIMS. Where both are claimed or
    neither is, nothing has said which is better, and both stay visible for an estimator
    rather than one being chosen by length — a coin toss that deletes evidence is worse
    than two rows somebody can see.
    """
    extracted_bought_in = {
        identity: record for identity, record in extracted.items()
        if _bought_in_record(record)
    }
    aliases: Dict[str, str] = {}
    for identity, record in raw.items():
        if identity in extracted or not _bought_in_record(record):
            continue
        tokens = _description_tokens(record.get("description"))
        if len(tokens) < 2:
            continue
        matches = []
        for candidate, candidate_record in extracted_bought_in.items():
            candidate_tokens = _description_tokens(candidate_record.get("description"))
            if not tokens or not candidate_tokens:
                continue
            smaller = tokens if len(tokens) <= len(candidate_tokens) else candidate_tokens
            larger = candidate_tokens if smaller is tokens else tokens
            if not smaller.issubset(larger):
                continue
            matches.append(candidate)
        if len(matches) == 1:
            aliases[identity] = matches[0]

    # ── ONE PART, TWO SPELLINGS, TWO SOURCES ──────────────────────────────────────────
    # Prefix-related codes carrying the SAME description and the SAME quantity are one item
    # read twice. Description and quantity together are what make this safe: 79814P vs
    # 79814P613 both read "3.5 x 16mm Pan Head Wood Screw" qty 4, while a genuine family of
    # codes sharing a prefix describes different parts or different counts.
    _claimed = {str(c).upper() for c in (claimed or ())}
    for identity, record in raw.items():
        if identity in extracted or identity in aliases:
            continue
        # A MEASURED PART IS NOT A SPELLING. Geometry means something read a drawing, and
        # no amount of code similarity may fold that away.
        _ng = record.get("normalized_geometry") or {}
        if number(_ng.get("blank_length_mm"), 0.0) and number(_ng.get("blank_width_mm"), 0.0):
            continue
        # ABSENCE IS SILENCE, NOT DISAGREEMENT. An extract record only carries a quantity
        # when the BOM item it came from stated one, so requiring the two to be EQUAL means
        # a missing figure silently declines the match — the guard would then be strictest
        # exactly where it knows least. A quantity that is stated and different is a real
        # objection and blocks; a quantity nobody stated objects to nothing, and description
        # agreement plus a prefix relation still has to hold.
        _qty = number(record.get("quantity"), None)
        _cands = [
            candidate for candidate, candidate_record in extracted.items()
            if _prefix_related(identity, candidate)
            and _same_description(record.get("description"),
                                  candidate_record.get("description"))
            and _quantities_do_not_disagree(
                _qty, number(candidate_record.get("quantity"), None))
            and _kinds_are_compatible(record, candidate_record)
        ]
        if len(_cands) != 1:
            continue
        _target = _cands[0]
        # THE CLAIMED SPELLING SURVIVES. Both claimed or neither claimed is not a
        # preference, and choosing anyway would delete a row nobody decided against.
        #
        # AND NO HIERARCHY AT ALL IS NOT A LICENCE TO GUESS. This branch used to fall back
        # to the length rule when nothing claimed either spelling, which resolves an
        # ambiguity by heuristic — the exact thing part_identity refuses to do when a stem
        # matches more than one fuller code. A rule that fails visibly in one module and
        # quietly in another is not one rule.
        #
        # The cross-source case earns the stricter standard: a single pool holding two
        # codes is one reader disagreeing with itself, while this is TWO readers, and the
        # weaker evidence should demand the better reason. Declining costs a visible row an
        # estimator can resolve; guessing costs a part its identity, silently.
        if _target.upper() in _claimed and identity.upper() not in _claimed:
            aliases[identity] = _target
        elif identity.upper() in _claimed and _target.upper() not in _claimed:
            aliases[_target] = identity

    # ── A CONFIGURED NAME AND ITS FRAGMENTS ARE ONE PART ─────────────────────────────
    # SolidWorks virtual components are named "Base^OwningAssembly", and a BOM table wraps
    # that long name over printed lines. On 10975-02 the wrap became three identities —
    # the model's full "10975 EPDM Closed Cell Tape^10975-02-GA", a wrapped middle line
    # "CELL TAPE^10975-02-", and a squashed first line "10975EPDMCLOSEDCELL" — so one roll
    # of tape was priced twice, left unpriced once, and the gates missed its record.
    #
    # An identity whose squashed spelling (A-Z0-9 only) is a long substring of a
    # caret-named identity's is a fragment of that name, not a part. Ten characters means
    # a genuine different part cannot satisfy it by accident, and the FULLEST spelling
    # survives so every field lands on one record.
    def _rec_of(ident: str) -> Mapping[str, Any]:
        return raw.get(ident) or extracted.get(ident) or {}

    def _word_tokens(desc: Any) -> Set[str]:
        # Only PURE numbers are set aside (a length value, a quantity). A dimension token
        # like 25X1MM is part of what the thing IS and must agree for a merge — otherwise
        # a 25X1 tape and a 50X2 tape would read as one item with a "numeric conflict".
        return {t for t in _description_tokens(desc)
                if not re.fullmatch(r"[\d.,]+", str(t).upper())}

    _all_ids = [i for i in set(raw) | set(extracted) if i not in aliases]
    _carets = sorted((i for i in _all_ids if "^" in str(i)),
                     key=lambda i: -len(_squashed(i)))
    for identity in _all_ids:
        sq = _squashed(identity)
        if len(sq) < 5:
            continue
        for host in _carets:
            hs = _squashed(host)
            if host == identity or hs == sq or len(hs) <= len(sq):
                continue
            if len(sq) >= 10 and sq in hs:
                aliases[identity] = host
                break
            # A SHORT PREFIX NEEDS A SECOND WITNESS. "10975" alone is the project number;
            # "10975" carrying the caret part's own commodity description ("EPDM TAPE
            # 25X1MM - TAPE 113C LENGTH: 200.00") is the same BOM row read off the other
            # sheet. Both records must classify bought-in and their descriptions must
            # agree word for word once the numerals are set aside — and where the
            # numerals DISAGREE (sheet 1 says LENGTH: 200.00, sheet 4 says 220.00) the
            # conflict is recorded on the surviving record for a person, never chosen
            # silently.
            if hs.startswith(sq):
                ri, rh = _rec_of(identity), _rec_of(host)
                try:
                    from bought_in_policy import is_bought_in as _bi
                except Exception:                                # noqa: BLE001
                    break
                wi, wh = _word_tokens(ri.get("description")), \
                    _word_tokens(rh.get("description"))
                if not (wi and wh and _bi(dict(ri)) and _bi(dict(rh))
                        and (wi <= wh or wh <= wi)):
                    continue
                aliases[identity] = host
                _di = _description_tokens(ri.get("description")) - wi
                _dh = _description_tokens(rh.get("description")) - wh
                if _numeric_sets_contradict(_di, _dh) and isinstance(rh, dict):
                    rh.setdefault("_bom_numeric_conflicts", []).append({
                        "field": "description",
                        "kept": str(rh.get("description") or ""),
                        "other": str(ri.get("description") or ""),
                        "from_identity": identity,
                    })
                break

    # ── ONE CONSUMABLE, MANY SPELLINGS, NO HOST NEEDED ────────────────────────────────
    # On the live 10975 pool the full configured name never appears as an identity, so the
    # caret pass above had no host and the tape stayed three lines: "10975" (priced),
    # "10975EPDMCLOSEDCELL" and "CELL TAPE^10975-02-". What the three share is the
    # draughtsman's own words: every one describes "EPDM TAPE 25X1MM - TAPE 113C". Two
    # bought-in records with no geometry whose descriptions agree word for word (pure
    # numbers set aside) are one item stated twice; the fullest spelling survives, and a
    # differing number (LENGTH: 200 vs 220) is recorded on it as a conflict for a person.
    try:
        from bought_in_policy import is_bought_in as _is_bi
    except Exception:                                            # noqa: BLE001
        _is_bi = None
    if _is_bi is not None:
        _pool = [i for i in (set(raw) | set(extracted)) if i not in aliases]
        _groups: Dict[frozenset, List[str]] = {}
        for ident in _pool:
            rec = _rec_of(ident)
            _ng = rec.get("normalized_geometry") or {}
            if number(_ng.get("blank_length_mm"), 0.0) and \
                    number(_ng.get("blank_width_mm"), 0.0):
                continue                                         # measured = a real part
            words = _word_tokens(rec.get("description"))
            if len(words) < 3 or not _is_bi(dict(rec)):
                continue
            _groups.setdefault(frozenset(words), []).append(ident)
        for _words, members in _groups.items():
            if len(members) < 2:
                continue
            survivor = max(members, key=lambda i: (len(_squashed(i)), i))
            s_rec = _rec_of(survivor)
            s_nums = _description_tokens(s_rec.get("description")) - _word_tokens(
                s_rec.get("description"))
            for ident in members:
                if ident == survivor:
                    continue
                aliases[ident] = survivor
                i_rec = _rec_of(ident)
                i_nums = _description_tokens(i_rec.get("description")) - _word_tokens(
                    i_rec.get("description"))
                if _numeric_sets_contradict(s_nums, i_nums) and isinstance(s_rec, dict):
                    s_rec.setdefault("_bom_numeric_conflicts", []).append({
                        "field": "description",
                        "kept": str(s_rec.get("description") or ""),
                        "other": str(i_rec.get("description") or ""),
                        "from_identity": ident,
                    })
    return aliases


def _code_spellings(value: Any) -> List[str]:
    """Every spelling of one code that a matcher should try, best first.

    THE READER AND THE GRAPH DO NOT SPELL A CODE THE SAME WAY, and this is the third time
    that has cost a correct rule its effect. merge_boms takes the parent from the title block
    verbatim — its own docstring gives "1282 - GA" as the example — while this module's
    clean_part_number only collapses whitespace and uppercases, so it holds "1282 - GA" and
    the graph holds "1282-GA". An edge matched on the first would never find the second, and
    the whole BOM hierarchy source would be a silent no-op on real drawings while passing
    every test written in the graph's own spelling.

    part_identity.normalize_part_code is the reader that knows the drawing's forms — spaced
    hyphens, "1450 GA", trailing separators. Both spellings are offered and the caller takes
    whichever names something it already knows. Offering two spellings cannot invent a match:
    the identity still has to exist.
    """
    out: List[str] = []
    primary = clean_part_number(value)
    if primary:
        out.append(primary)
    try:
        from part_identity import normalize_part_code

        alt = normalize_part_code(value)
        if alt and alt not in out:
            out.append(alt)
    except Exception:
        pass
    return out


def _bom_stated_edges(
    bom_rows: Optional[Sequence[Mapping[str, Any]]],
    aliases: Mapping[str, str],
    known: Set[str],
    rejected: Optional[List[str]] = None,
) -> List[tuple]:
    """(child, parent, qty) for every BOM row that names an owner we already know.

    THE DETERMINISTIC READ OF A BOM TABLE IS THE STRONGEST HIERARCHY EVIDENCE ON A DRAWING
    PACK, and it was the only one this compiler never consulted. bom_pipeline stamps each row
    with the parent page whose table listed it, and says in its own docstring that it does not
    deduplicate because "the same code legitimately recurs across parent BOMs".

    THREE REFUSALS, each one a way this could do harm:

    A PARENT WE DO NOT ALREADY KNOW IS NOT CREATED. merge_boms takes this label from the
    title block verbatim when a reader found one and falls back to "<file>#<page>" when none
    did, so it is usually a part code and sometimes a file name — and a node invented from a
    file name would be a phantom assembly carrying real children.

    THE ONE EXCEPTION IS EVIDENCE, NOT A GUESS: an assembly we know exists because we opened
    its drawing. `known` includes the job's own drawing numbers, so a title block naming
    "12392-04-GA" on a job that read 12392-04-GA.pdf is a general arrangement we have in our
    hands, not a code inferred from a string. That is what lets the second GA of an enquiry
    own its parts when the extract only read the first. A label matching no part and no
    drawing still makes no edge, and the child stays visibly disconnected — the honest
    outcome, because a missing edge can be seen and a wrong one cannot.

    NOTHING IS RE-PARENTED. Applied only where the child has no owner at all (enforced by the
    caller), so this cannot move a part from the assembly the model or the extract put it in.
    The module's rule is that a wrong parent is worse than a missing one; an edge that can
    only ever fill a hole cannot break that.

    source_pdf IS NOT ACCEPTED AS A PARENT HERE, though the rollup merge does accept it for
    telling two lines apart. Distinguishing lines needs only a discriminator; naming an owner
    needs a part. "12392-04-GA.pdf" is a fine discriminator and not an assembly.
    """
    def _resolve(value: Any, must_be_known: bool) -> str:
        """The first spelling of this code the graph recognises; the plain one otherwise."""
        spellings = [aliases.get(s, s) for s in _code_spellings(value)]
        for spelling in spellings:
            if spelling in known:
                return spelling
        return "" if must_be_known else (spellings[0] if spellings else "")

    rejected = rejected if rejected is not None else []
    edges: List[tuple] = []
    for row in bom_rows or []:
        if not isinstance(row, Mapping):
            continue
        child = _resolve(row.get("part_number") or row.get("part_code")
                         or row.get("code"), False)
        _stated = row.get("bom_parent") or row.get("parent") or row.get("parent_code")
        # The parent MUST resolve to something we know — that is the refusal above, and it
        # is why trying two spellings here is safe: neither can name a node that is not there.
        parent = _resolve(_stated, True)
        if _stated and not parent:
            # SAY WHOSE OWNER WE THREW AWAY. This refusal is correct and it was silent, so a
            # run where every GA parent was rejected — because the drawing numbers came from
            # descriptive file names and matched nothing — looked exactly like a run where
            # the drawings stated no hierarchy at all. Six blocking disconnected nodes, and
            # the one fact that explains all six was discarded without a word.
            rejected.append(str(_stated))
        if not child or not parent or child == parent:
            continue
        edges.append((child, parent, number(row.get("quantity") or row.get("qty"), 1.0) or 1.0))
    return edges


def build_part_graph(
    parts: Sequence[Mapping[str, Any]],
    llm_extract: Optional[Mapping[str, Any]] = None,
    bom_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    known_assemblies: Optional[Iterable[str]] = None,
    page_owner: Optional[Mapping[int, str]] = None,
) -> Dict[str, Any]:
    """Build canonical nodes and hierarchy edges from the whole job.

    THREE SOURCES OF HIERARCHY, and until now this read two. The description rule writes
    children onto the part records; the extract states assemblies. The third is the BOM table
    itself: bom_pipeline reads it deterministically and stamps every row with the parent page
    that listed it. That field reached this module in the records and was reported as an
    unread fact in the disconnected-node issue — never used to make an edge.

    On job 12392 the extract read only one of the enquiry's two drawings, so every part on
    the other became a leaf nobody claimed, while the BOM row that named its owner sat in the
    summary unread. `bom_rows` closes that: see _bom_stated_edges for why it can only ever
    connect an orphan.
    """
    llm_extract = llm_extract or {}
    raw_original = _raw_parts(parts)
    extracted = _extract_part_records(llm_extract)
    # The codes some assembly names as a child, read BEFORE aliasing so the alias pass can
    # prefer the spelling the hierarchy actually references over the one it has never named.
    _claimed_codes = {
        clean_part_number(_e.get("part_number") if isinstance(_e, Mapping) else _e)
        for _a in (llm_extract.get("assemblies") or []) if isinstance(_a, Mapping)
        for _e in (_a.get("children") or [])
    }
    _claimed_codes |= {
        clean_part_number(_k)
        for _p in (parts or []) if isinstance(_p, Mapping)
        for _k in (_p.get("assembly_children") or [])
    }
    _claimed_codes.discard("")
    aliases = _raw_identity_aliases(raw_original, extracted, claimed=_claimed_codes)
    # The drawing's BOM is the naming authority; the files carry the same parts under the
    # modelled code. Applied after the BI-* reconciliation and only where the target already
    # exists, so it can merge a duplicate but never invent an identity.
    # THE HIERARCHY'S OWN CODES ARE IDENTITIES TOO. Only BOM and part codes were offered
    # here, so an assembly named by the file's spelling ("11350-01M") was never aliased and
    # became a SECOND parent beside the drawing's — one hierarchy split in two, each holding
    # half the job.
    _hierarchy_codes: Set[str] = set()
    for _asm in (llm_extract.get("assemblies") or []):
        if not isinstance(_asm, Mapping):
            continue
        _hierarchy_codes.add(clean_part_number(_asm.get("part_number")))
        for _e in (_asm.get("children") or []):
            if isinstance(_e, Mapping):
                _hierarchy_codes.add(clean_part_number(_e.get("part_number")))
    _hierarchy_codes.discard("")
    # The records, so the naming convention can be checked against what the two codes ARE
    # rather than only against how they are spelled. Both pools, because a code may be
    # known to one reader and not the other, and the pool that holds it is the pool that
    # knows its kind.
    _kind_records: Dict[str, Mapping[str, Any]] = {}
    for _pool in (extracted, raw_original):
        for _id, _rec in (_pool or {}).items():
            if isinstance(_rec, Mapping):
                _kind_records.setdefault(str(_id).strip().upper(), _rec)
    _refused_cross_kind: List[Dict[str, str]] = []
    for _src, _dst in _drawing_code_aliases(
            set(raw_original) | set(extracted) | _hierarchy_codes,
            _kind_records, _refused_cross_kind).items():
        aliases.setdefault(_src, _dst)
    # THE SAME COLLAPSE, ON THE OTHER SIDE. The alias map was applied to the part records
    # and not to the extract's own BOM rows, so a duplicate spelling that appears ONLY in
    # the extract survived as a node of its own — a leaf with no parent and no geometry,
    # which is the seven-nodes-from-five-lines symptom seen from the other direction.
    _extracted: Dict[str, Dict[str, Any]] = {}
    for identity, record in extracted.items():
        canonical_identity = aliases.get(identity, identity)
        _target = _extracted.setdefault(canonical_identity, {})
        for _k, _v in record.items():
            if _v not in (None, "", [], {}) and _target.get(_k) in (None, "", [], {}):
                _target[_k] = _v
        _target["part_number"] = canonical_identity
    extracted = _extracted

    raw: Dict[str, Mapping[str, Any]] = {}
    for identity, record in raw_original.items():
        canonical_identity = aliases.get(identity, identity)
        canonical_record = dict(record)
        canonical_record["part_number"] = canonical_identity
        _existing = raw.get(canonical_identity)
        if _existing is None:
            raw[canonical_identity] = canonical_record
            continue
        # MERGING TWO NAMES FOR ONE PART MUST NOT THROW AWAY THE MEASUREMENT.
        #
        # setdefault kept whichever record was seen first, and on 11350 that is the GA BOM
        # line "11350-01-01" — the one carrying the hierarchy and the quantity and NO
        # geometry. The model record "11350-01-01M" holds the only measured blank on the
        # job, and joining the two identities discarded it: a correct BOM whose measured
        # part had no dimensions, which is worse than the duplicate it replaced.
        #
        # Gap-fill, never overwrite. The record already in hand keeps every value it has —
        # the same precedence discipline apply_field enforces elsewhere — and the second
        # record supplies only what the first is missing.
        _merged = dict(_existing)
        for _k, _v in canonical_record.items():
            if _k == "part_number":
                continue
            if _v not in (None, "", [], {}) and _merged.get(_k) in (None, "", [], {}):
                _merged[_k] = _v
        raw[canonical_identity] = _merged
    records: Dict[str, Dict[str, Any]] = {
        identity: dict(record) for identity, record in extracted.items()
    }
    for identity, record in raw.items():
        merged = records.setdefault(identity, {})
        for key, value in record.items():
            if value not in (None, "", [], {}):
                merged[key] = value
    children: Dict[str, Dict[str, float]] = {}
    parents: Dict[str, Set[str]] = {}

    def _placeholder_edge_target(edge: Mapping[str, Any]) -> str:
        """An uncoded assembly child, resolved only when exactly one row can be meant.

        The GA lists "- x4" under the top assembly and the BOM table names it "M4 WING NUT".
        The description resolves it by the shared rule; where the edge carries no usable
        description, a UNIQUE bought-in of the same quantity is accepted and nothing else.
        Two candidates means no edge — a wrong parent is worse than a missing one.
        """
        raw_code = edge.get("part_number")
        from part_identity import is_placeholder_identity, synthesise_bought_in_code
        if not is_placeholder_identity(raw_code):
            return ""
        direct = clean_part_number(
            synthesise_bought_in_code(edge.get("description"), raw_code))
        if direct and direct in extracted:
            return direct
        edge_qty = number(edge.get("qty"), 1.0) or 1.0
        matches = [
            identity for identity, record in extracted.items()
            if _bought_in_record(record)
            and identity not in parents
            and abs((number(record.get("quantity") or record.get("qty"), 1.0) or 1.0)
                    - edge_qty) < 1e-9
        ]
        return matches[0] if len(matches) == 1 else ""

    # ── HIERARCHY THE DRAWING STATED IN WORDS ────────────────────────────────────────
    # "TICKET STRIP BAR WITH PEM STUDS" is a sub-assembly whose edge the extract never
    # emitted. drawing_job_merge already decides that, from evidence the extract cannot see
    # (both halves being lines on this BOM), and writes the children onto the part record.
    # This CONSUMES that decision rather than making it a second time: one rule, one place,
    # and a compiler that cannot drift from the merge.
    #
    # BEFORE the extract's own edges, and that ordering is load-bearing. A component this
    # sub-assembly owns is then already parented, so it cannot also be claimed as a loose
    # top-level edge — which is what leaves the GA's uncoded "- x4" with exactly one
    # candidate instead of two.
    _stated_parents = {
        aliases.get(clean_part_number(_a.get("part_number")),
                    clean_part_number(_a.get("part_number")))
        for _a in (llm_extract.get("assemblies") or [])
        if isinstance(_a, Mapping) and (_a.get("children") or [])
    }
    for part in parts or []:
        if not isinstance(part, Mapping):
            continue
        _kids = part.get("assembly_children")
        if not isinstance(_kids, list) or not _kids:
            continue
        _pid = clean_part_number(part.get("part_number"))
        _pid = aliases.get(_pid, _pid)
        # An extract that STATES this parent's children owns it; the description rule only
        # fills a hierarchy nobody expressed.
        if not _pid or _pid in _stated_parents:
            continue
        _edges: Dict[str, float] = {}
        for _kid in _kids:
            _cid = clean_part_number(_kid)
            _cid = aliases.get(_cid, _cid)
            if not _cid or _cid == _pid:
                continue
            _edges[_cid] = number((extracted.get(_cid) or raw.get(_cid) or {}).get("quantity"),
                                  1.0) or 1.0
        if not _edges:
            continue
        children[_pid] = _edges
        for _cid in _edges:
            parents.setdefault(_cid, set()).add(_pid)
        records.setdefault(_pid, {})["is_sub_assembly"] = True
        records[_pid]["hierarchy_source"] = "drawing_description_rule"

    for assembly in llm_extract.get("assemblies") or []:
        if not isinstance(assembly, Mapping):
            continue
        # ALIASED, LIKE EVERY OTHER IDENTITY. The alias map was built and then not applied
        # here, so a hierarchy edge naming the FILE's code ("11350-01-01M") pointed at a node
        # the rest of the graph knows by the DRAWING's code — a parent for one spelling and
        # an orphan for the other.
        parent_id = clean_part_number(assembly.get("part_number"))
        parent_id = aliases.get(parent_id, parent_id)
        if not parent_id:
            continue
        children.setdefault(parent_id, {})
        for edge in assembly.get("children") or []:
            if not isinstance(edge, Mapping):
                continue
            child_id = clean_part_number(edge.get("part_number"))
            child_id = aliases.get(child_id, child_id)
            if not child_id:
                child_id = _placeholder_edge_target(edge)
            if not child_id:
                continue
            qty = number(edge.get("qty"), 1.0) or 1.0
            children[parent_id][child_id] = qty
            parents.setdefault(child_id, set()).add(parent_id)

    # ── HIERARCHY THE BOM TABLE STATED, where nothing else claimed the part ──────────
    # THE DRAWINGS WE ACTUALLY OPENED are assemblies we know exist, whether or not any part
    # record was created for them. On a pack whose second GA the extract never read, this is
    # the difference between an owner and an orphan.
    # Both spellings, for the same reason the edge reader tries both: a drawing named
    # "12392-04 - GA.pdf" must be recognisable as the assembly the graph calls 12392-04-GA.
    _drawings = {s for d in (known_assemblies or []) for s in _code_spellings(d)}
    _drawings.discard("")
    # A PART OWNED BY ANOTHER SOURCE IS NOT RE-OWNED; A PART THE BOM OWNS TWICE IS OWNED
    # TWICE. Those are different facts and one rule was answering both. Refusing any child
    # that already had a parent also refused the SECOND BOM line for a fastener both general
    # arrangements use — so the panel's 16 screws were an edge and the bracket set's 4 were
    # nothing, and the cascade summed 16 where the drawings say 20.
    #
    # The distinction is which source disagreed. An extract or a model that placed this part
    # still wins outright: a wrong parent is worse than a missing one and that has not
    # changed. But two BOM rows naming two owners are not in conflict — they are two
    # assemblies that each use the part, which is the ordinary shape of a fastener.
    _claimed_before_bom = set(parents)
    _rejected_parents: List[str] = []
    _bom_edges = _bom_stated_edges(
        bom_rows, aliases, set(raw) | set(extracted) | set(children) | _drawings,
        _rejected_parents)
    if _rejected_parents:
        _unique = sorted({r for r in _rejected_parents if r})
        print(f"   [bom] {len(_rejected_parents)} row(s) name an owner this job does not "
              f"recognise, so no edge was made for them: {', '.join(_unique[:6])}"
              + (f" (+{len(_unique) - 6} more)" if len(_unique) > 6 else "")
              + ". Their parts will be reported as disconnected.", flush=True)
    for _child_id, _parent_id, _qty in _bom_edges:
        if _child_id in _claimed_before_bom:
            continue
        children.setdefault(_parent_id, {})[_child_id] = _qty
        parents.setdefault(_child_id, set()).add(_parent_id)
        records.setdefault(_parent_id, {})["is_sub_assembly"] = True
        records[_parent_id]["hierarchy_source"] = "bom_table"

    # A RECORD THAT CARRIES ITS OWN TABLE'S OWNER joins the same way. The dual-path ADD
    # writes synthesised BI- records for BOM rows whose code column is a dash — so the
    # row-level edge above can never resolve a child for them — but the record itself
    # knows which parent BOM listed it (11350-01: wing nuts on the GA's table, PEM studs
    # on 101's), and dropping that fact left both fasteners BLOCKING as disconnected.
    # Same refusals as _bom_stated_edges: the parent must already be known, the child
    # must be unowned, and nothing is ever re-parented.
    for _part in (parts or []):
        if not isinstance(_part, Mapping):
            continue
        _pid = clean_part_number(_part.get("part_number") or "")
        _pid = aliases.get(_pid, _pid)
        # STRONGER EVIDENCE IS PROTECTED; EQUAL EVIDENCE ACCUMULATES. The guard here was
        # `_pid in parents`, which also refused a child that had just gained ONE
        # row-level BOM edge — so a stated second owner from this record was dropped
        # even though the row-level path deliberately supports two owners. Only a claim
        # made BEFORE the BOM pass (extract, model) outranks a BOM-stated edge.
        if not _pid or _pid in _claimed_before_bom:
            continue
        # EVERY STATED OCCURRENCE, with its own quantity. The same nut can sit under two
        # assemblies (4 under A-101, 2 under A-102) and both tables are evidence — the
        # first cut of this reader kept only the first owner, which silently halved the
        # hardware. bom_parents carries each distinct occurrence; the single bom_parent
        # stays as the fallback for records that predate the list.
        _bp_entries = []
        for _e in (_part.get("bom_parents") or []):
            if isinstance(_e, Mapping) and str(_e.get("parent") or "").strip():
                _bp_entries.append((str(_e.get("parent")), number(_e.get("qty"), 0) or None))
        if not _bp_entries and _part.get("bom_parent"):
            _bp_entries.append((str(_part.get("bom_parent")), None))
        if not _bp_entries:
            continue
        for _bp_raw, _bq in _bp_entries:
            _bp = ""
            for _spelling in _code_spellings(_bp_raw):
                _spelling = aliases.get(_spelling, _spelling)
                if _spelling in raw or _spelling in extracted or _spelling in children \
                        or _spelling in _drawings:
                    _bp = _spelling
                    break
            if not _bp or _bp == _pid:
                continue
            _q = _bq if _bq else (number(_part.get("quantity"), 1.0) or 1.0)
            # SAME PARENT TWICE IS EITHER CORROBORATION OR A CONFLICT — never an
            # overwrite. A row-level edge saying 4 under FRAME and this record saying 2
            # under the same FRAME silently became 2; two claims about one edge with
            # different figures are a decision for a person, in the same field the BOM
            # duplicate-line conflicts already use, so it reaches the estimator's list.
            _standing = children.get(_bp, {}).get(_pid)
            if _standing is not None:
                if abs(float(_standing) - float(_q)) < 1e-9:
                    continue                              # corroboration, count once
                _part.setdefault("_bom_numeric_conflicts", []).append({
                    "field": "quantity", "kept": _standing, "other": _q,
                    "parent": _bp,
                })
                print(f"   [bom] '{_pid}' under '{_bp}': two claims disagree about the "
                      f"quantity ({_standing:g} kept, {_q:g} recorded as a conflict for "
                      f"a person) — neither overwrites the other", flush=True)
                continue
            children.setdefault(_bp, {})[_pid] = _q
            parents.setdefault(_pid, set()).add(_bp)
            records.setdefault(_bp, {})["is_sub_assembly"] = True
            records[_bp]["hierarchy_source"] = "bom_table"
            print(f"   [bom] '{_pid}' owned by '{_bp}' (qty {_q:g}) — the record carries "
                  f"the parent BOM whose table listed it", flush=True)

    # ── AND THE PAGE A PART WAS LISTED ON, when no reader gave it an owner ────────────
    # The last resort, and it exists because the readers above can all be empty at once.
    # On 12392 the deterministic BOM reader found no rows, so nothing carried bom_parent;
    # the vision extract had read only the first of two drawings, so its assemblies covered
    # half the job; and the rows that reached costing were synthesised from the costed parts
    # with no parent at all. Three hierarchy sources and every one of them silent for the
    # second GA, while each of its parts still knew which page it appeared on.
    #
    # ASSEMBLY PAGES ONLY (see assembly_page_owners): a detail sheet is one part drawn large,
    # not an owner. And still only for a part nothing else claimed, still only to a drawing
    # the job already knows, and never to itself.
    for _part in (parts or []):
        if not isinstance(_part, Mapping):
            continue
        _pid = clean_part_number(_part.get("part_number") or _part.get("item_number"))
        _pid = aliases.get(_pid, _pid)
        if not _pid or _pid in parents or _pid in children:
            continue                      # owned already, or is itself a parent
        # BOTH SPELLINGS OF "WHICH SHEET". A prose-recognised purchase carries pages AND
        # source_page; a BOM row carries source_page alone; and the record that reaches
        # this compiler is not always the one the reader wrote — a costed part estimate can
        # arrive with the page dropped. Reading one key meant a bolt that knew its sheet
        # still had no owner, which is the field existing somewhere the reader was not
        # looking, for the sixth time on this branch.
        _pages = list(_part.get("pages") or [])
        _sp = _part.get("source_page")
        if _sp is not None and _sp not in _pages:
            _pages.append(_sp)
        for _page in _pages:
            try:
                _owner_raw = (page_owner or {}).get(int(_page))
            except (TypeError, ValueError):
                continue
            if not _owner_raw:
                continue
            _owner = ""
            for _spelling in _code_spellings(_owner_raw):
                _spelling = aliases.get(_spelling, _spelling)
                if _spelling in raw or _spelling in extracted or _spelling in children \
                        or _spelling in _drawings:
                    _owner = _spelling
                    break
            if not _owner or _owner == _pid:
                continue
            children.setdefault(_owner, {})[_pid] = number(_part.get("quantity"), 1.0) or 1.0
            parents.setdefault(_pid, set()).add(_owner)
            records.setdefault(_owner, {})["is_sub_assembly"] = True
            records[_owner]["hierarchy_source"] = "assembly_page"
            break

    top = llm_extract.get("top_assembly") or {}
    top_id = clean_part_number(top.get("part_number") if isinstance(top, Mapping) else top)
    top_id = aliases.get(top_id, top_id)
    if not top_id:
        roots = sorted(set(children) - set(parents))
        if len(roots) == 1:
            top_id = roots[0]
        else:
            ga_roots = [item for item in roots if re.search(r"(?:^|-)GA$", item)]
            if len(ga_roots) == 1:
                top_id = ga_roots[0]

    # AN ENQUIRY CAN HAVE MORE THAN ONE THING THAT SHIPS. 12392 is one job with two general
    # arrangements — a panel and a bracket set — and this asked for THE top assembly, singular.
    # The extract had read only the first drawing, so the second GA and everything under it
    # was not the top, had no parent, and was reported as a disconnected node; had the extract
    # read neither, top_id would have been blank and the quantity cascade would not have run
    # at all, leaving every part at its own drawing quantity.
    #
    # A root is a node that owns children and that nothing owns. That is the definition
    # already used above; it is only the "exactly one" that was wrong. Any assembly the
    # extract explicitly named as top stays a root whether or not it has edges yet, so a job
    # with one GA resolves to exactly the same single root as before.
    top_ids: List[str] = [top_id] if top_id else []
    for _root in sorted(set(children) - set(parents)):
        if _root and _root not in top_ids and children.get(_root):
            top_ids.append(_root)

    # ── TWO GENERAL ARRANGEMENTS OF ONE STAND ARE ONE BOM, NOT TWO ──────────────────────
    #
    # A pack can carry the same assembly twice — a colourway pair, e.g. 7332-01-GA (revK) and
    # 7332-01-GA2 (Rev[A]), the same Harrods stand in Champagne Gold. Each GA prints its OWN
    # weldment number (7332-01-101, 7332-01-102), so both land here as roots and the cascade
    # below books every leaf twice (base 1->2, legs 2->4) and mints two weldments' worth of
    # weld/dress/powder. Unit £101.30 was ~1.5-2 stands of material.
    #
    # This is NOT the 12392 case — two DIFFERENT arrangements (a panel and a bracket set) that
    # genuinely both ship, which the multi-root support above exists for. The discriminator is
    # the CHILD SET: a colourway pair shares it exactly; two different arrangements do not. So
    # collapse two roots ONLY when they share an assembly stem AND their children are
    # (near-)identical — keep the highest-revision structure, fold the other into it, and record
    # the dropped one as a colourway variant rather than losing it.
    if len(top_ids) > 1:
        def _assembly_stem(_id: str) -> str:
            return re.sub(r"-[^-]+$", "", str(_id or ""))

        def _rev_rank(_id: str) -> int:
            _r = records.get(_id) or {}
            _let = str(_r.get("revision") or _r.get("drawing_revision") or "").strip().upper()
            _m = re.match(r"([A-Z])", _let)
            if _m:
                return ord(_m.group(1)) - ord("A")
            _names = [str(_r.get("source_pdf_name") or ""), str(_r.get("source_pdf") or "")]
            for _pg in (_r.get("pages") or []):
                if isinstance(_pg, Mapping):
                    _names.append(str(_pg.get("source_pdf_name") or ""))
            for _n in _names:
                _mm = re.search(r"REV(?:ISION)?[\s._()-]*([A-Z])", _n.upper())
                if _mm:
                    return ord(_mm.group(1)) - ord("A")
            return -1

        _by_stem: Dict[str, List[str]] = {}
        for _r in top_ids:
            _by_stem.setdefault(_assembly_stem(_r), []).append(_r)
        _dropped: Dict[str, str] = {}
        for _stem, _group in _by_stem.items():
            if not _stem or len(_group) < 2:
                continue
            # cluster the same-stem roots by near-identical child set (Jaccard >= 0.8)
            _clusters: List[List[str]] = []
            for _r in _group:
                _kids = frozenset(children.get(_r) or {})
                if not _kids:
                    continue                      # a root with no children is not an assembly
                for _cl in _clusters:
                    _ref = frozenset(children.get(_cl[0]) or {})
                    _union = _kids | _ref
                    if _union and len(_kids & _ref) / len(_union) >= 0.8:
                        _cl.append(_r)
                        break
                else:
                    _clusters.append([_r])
            for _cl in _clusters:
                if len(_cl) < 2:
                    continue
                _keep = sorted(_cl, key=lambda i: (-_rev_rank(i), i))[0]
                for _other in _cl:
                    if _other != _keep:
                        _dropped[_other] = _keep
        for _other, _keep in _dropped.items():
            # The keeper already owns the shared leaves; move any child unique to the dropped
            # root onto the keeper first so nothing under it is lost, then remove the duplicate
            # root entirely so it neither cascades nor emits a second weldment.
            for _cid, _q in (children.get(_other) or {}).items():
                children.setdefault(_keep, {}).setdefault(_cid, _q)
                parents.setdefault(_cid, set()).add(_keep)
                (parents.get(_cid) or set()).discard(_other)
            children.pop(_other, None)
            parents.pop(_other, None)
            _krec = records.setdefault(_keep, {})
            _var = records.get(_other) or {}
            _krec.setdefault("colourway_variants", []).append({
                "part_number": _other,
                "description": str(_var.get("description") or ""),
                "revision": str(_var.get("revision") or _var.get("drawing_revision") or ""),
            })
            records.pop(_other, None)
            raw.pop(_other, None)
            extracted.pop(_other, None)
        if _dropped:
            top_ids = [t for t in top_ids if t not in _dropped]
            _msg = "; ".join(f"{o}->{k}" for o, k in sorted(_dropped.items()))
            print(f"   [graph] collapsed {len(_dropped)} duplicate general-arrangement "
                  f"root(s) — same assembly, different colourway: {_msg}. Kept the "
                  f"higher-revision structure; the other(s) recorded as colourway variants.",
                  flush=True)

    identities: Set[str] = set(raw) | set(extracted) | set(children) | set(parents)
    identities.update(t for t in top_ids if t)

    # ── A ZIPPED BOM ROW IS NOT A PART ────────────────────────────────────────────────
    # When a wrapped BOM row's text interleaves with its neighbour's, the extractor mints
    # a chimera: 10975-02's "1100997755-E0P2D-GM0 · 1Closed GRAPHIC" is "10975-02-G01
    # GRAPHIC" and "10975 EPDM Closed" zipped character by character, and it reached the
    # sheet as a real line asking the estimator to price a part that does not exist. An
    # identity that is a perfect interleave of two OTHER identities on this job, and that
    # nothing claims as a child, is that artefact — quarantined with the reason on the
    # graph, never silently.
    _sq_ids = {i: _squashed(i) for i in identities}
    _interleave_issues: List[Dict[str, Any]] = []
    _suspects = []
    for ident, sq in _sq_ids.items():
        if len(sq) < 12 or "^" in ident:
            continue
        # A code that scans as an SDI drawing number is a real part whatever else is true;
        # the chimera's ten-digit head cannot pass this.
        if re.match(r"^\d{4,5}-\d{2}\b", str(ident)):
            continue
        # NO CHILD EXEMPTION. The first version skipped anything the hierarchy claimed as a
        # child — and the zipped BOM row is claimed by the GA precisely BECAUSE it came off
        # the BOM table, so the guard exempted its own target and 1100997755-E0P2D-GM0
        # shipped again. The grammar test above is the protection for real parts; a code
        # that scans as a drawing number never reaches the interleave check at all.
        for a in identities:
            for b in identities:
                if a == b or a == ident or b == ident:
                    continue
                sa, sb = _sq_ids[a], _sq_ids[b]
                if len(sa) < 5 or len(sb) < 5:
                    continue
                if _interleave_of(sq, sa, sb, min_each=5):
                    _suspects.append((ident, a, b))
                    break
            else:
                continue
            break
    for ident, a, b in _suspects:
        identities.discard(ident)
        parents.pop(ident, None)
        children.pop(ident, None)
        for _kids in children.values():
            if isinstance(_kids, dict):
                _kids.pop(ident, None)
        # OUT OF THE RECORD POOLS TOO. Dropping the identity from the graph while its
        # record stayed in `records` left every later lookup able to resolve the chimera —
        # which is exactly how 1100997755-E0P2D-GM0 was "dropped" twice in one log and
        # still reached the Estimate sheet, the price checklist and a blocker asking
        # Design for its drawing. The evidence survives in the issue below.
        records.pop(ident, None)
        raw.pop(ident, None)
        extracted.pop(ident, None)
        _interleave_issues.append({
            "code": "bom_row_interleave_artifact",
            "identity": ident,
            "detail": (f"{ident} is a character interleave of {a} and {b} — a wrapped BOM "
                       f"row zipped with its neighbour by the text extractor, not a part. "
                       f"Dropped from the graph; both real parts remain."),
        })
        print(f"   [graph] dropped interleave artefact {ident} "
              f"(= {a} + {b} zipped)", flush=True)

    quantities: Dict[str, float] = {}

    def add_descendants(identity: str, factor: float, path: Set[str]) -> None:
        if identity in path:
            return
        quantities[identity] = quantities.get(identity, 0.0) + factor
        next_path = set(path)
        next_path.add(identity)
        for child_id, child_qty in (children.get(identity) or {}).items():
            add_descendants(child_id, factor * child_qty, next_path)

    # Each root cascades at one per unit: two GAs on one enquiry are two things that ship,
    # not two halves of one. A part under both accumulates, which is what the += above is for.
    for _root in top_ids:
        add_descendants(_root, 1.0, set())
    for identity in identities:
        if identity not in quantities:
            quantities[identity] = number(
                (records.get(identity) or {}).get("quantity"), 1.0) or 1.0

    nodes: List[PartNode] = []
    for identity in sorted(identities):
        record = records.get(identity) or {}
        is_assembly = bool(
            identity in children
            or identity == top_id
            or record.get("is_sub_assembly")
            or record.get("is_assembly_parent")
        )
        type_text = " ".join(str(record.get(key) or "") for key in (
            "type", "part_type", "source_type", "normalized_material",
        )).upper()
        is_bought_in = bool(
            _bought_in_record(record)
            or "BOUGHT" in type_text
            or identity.startswith("BI-")
        )
        kind = "assembly" if is_assembly else ("bought_in" if is_bought_in else "leaf")
        nodes.append(PartNode(
            part_number=identity,
            description=str(record.get("description") or ""),
            kind=kind,
            qty_per_unit=quantities.get(identity, 1.0),
            parents=sorted(parents.get(identity) or []),
            children=[
                ChildEdge(part_number=child_id, qty=qty)
                for child_id, qty in sorted((children.get(identity) or {}).items())
            ],
            evidence={
                "raw_record_present": identity in raw,
                "extract_record_present": identity in extracted,
                "raw_aliases": sorted(
                    alias for alias, canonical in aliases.items()
                    if canonical == identity
                ),
                "is_sub_assembly": bool(record.get("is_sub_assembly")),
                "is_assembly_parent": bool(record.get("is_assembly_parent")),
                # A COLLAPSED COLOURWAY IS NOT LOST, IT IS RECORDED. When the GA/GA2 collapse
                # folds a duplicate general-arrangement root onto this one (7332-01: the
                # Champagne Gold GA2 onto the kept GA), the dropped root is stored here so a
                # reader can see the same stand also ships in the other colourway rather than
                # the second drawing vanishing without trace.
                "colourway_variants": list(record.get("colourway_variants") or []),
            },
        ))

    graph_issues = list(_interleave_issues)
    # A JOIN WE DECLINED IS EVIDENCE, NOT A NON-EVENT. The naming convention said these
    # two codes are one part and their kinds said otherwise. Either the convention matched
    # a spelling rather than a part — the case this guard exists for — or one of the two
    # records is classified wrongly, and that is worth someone knowing. Silently not
    # merging leaves an estimator looking at two rows with no idea why.
    for _r in _refused_cross_kind:
        graph_issues.append({
            "code": "identity_merge_refused_across_kinds",
            "identity": _r["identity"],
            "target": _r["target"],
            "detail": (f"{_r['identity']} ({_r['identity_kind']}) was not merged into "
                       f"{_r['target']} ({_r['target_kind']}) — the naming convention says "
                       f"they are one part and their kinds say they are not. A part we "
                       f"fabricate does not become one we purchase because their codes "
                       f"match, so both stay visible for a ruling."),
        })
    if top_ids:
        _roots = set(top_ids)
        for node in nodes:
            # A GENERATED ORDER-LEVEL LINE HAS NO PARENT BECAUSE IT HAS NO PLACE IN THE
            # HIERARCHY, and that is not a disconnection to repair. The exemption was a list of
            # names, so the moment the engine generated a line the list had never heard of — a
            # subcontract plating line — the job blocked on a node that is working as intended.
            # Ask what the record IS, not what it is called: a commercial/generated placeholder
            # is exempt whatever its code. The three names stay for records that predate the
            # marker.
            _drec = records.get(node.part_number) or {}
            _generated_line = bool(
                _drec.get("_commercial_placeholder")
                or _drec.get("_plating_placeholder")
                or str(_drec.get("source") or "") == "commercial_placeholder"
            )
            if (
                node.part_number not in _roots
                and not node.parents
                and not _generated_line
                and node.part_number not in {"PACKAGING", "DELIVERY", "POWDER"}
            ):
                # WHY IT HAS NO PARENT IS A DIFFERENT QUESTION FROM WHICH NODE IT IS, and it
                # decides the fix. A node present in the raw records but absent from the
                # extract is usually a phantom — a truncated code, or a word from a drawing
                # read as a part — and the repair is to stop creating it. A node present in
                # BOTH is a real part nobody claimed, and the repair is an ownership edge.
                # The node already carries that evidence; only the issue did not.
                _rec = records.get(node.part_number) or {}
                # A PARENT THE RECORD ALREADY STATES, which the graph did not use, is the
                # most actionable thing this issue can carry: it is not a missing fact, it
                # is an unread one. Reported as what the record SAYS, never as a parent —
                # attaching it here would be the graph believing a field it just failed to
                # join on. Deliberately no candidate is derived from a shared job-code stem:
                # that a component belongs to this job is not evidence of which assembly
                # owns it, and guessing an owner is how a note-only item becomes a BOM line.
                _stated = clean_part_number(_rec.get("parent_part_number") or "")
                # WHICH OWNER THE BOM TABLE NAMED, when one was named and could not be used.
                # Now that BOM edges are joined, an orphan that still carries one means the
                # label named nothing this job knows — the refusal in _bom_stated_edges — and
                # that is the single most actionable fact about why it is still here.
                _bom_stated = clean_part_number(_rec.get("bom_parent") or "")
                graph_issues.append({
                    "code": "bom_node_disconnected",
                    "part_number": node.part_number,
                    "kind": node.kind,
                    "description": node.description,
                    "in_raw_records": bool(node.evidence.get("raw_record_present")),
                    "in_extract": bool(node.evidence.get("extract_record_present")),
                    "aliases": list(node.evidence.get("raw_aliases") or []),
                    "qty_per_unit": node.qty_per_unit,
                    "stated_parent_part_number": _stated,
                    "stated_parent_is_a_known_node": bool(_stated and _stated in identities),
                    "bom_stated_parent": _bom_stated,
                    "bom_stated_parent_is_a_known_node": bool(
                        _bom_stated and _bom_stated in identities),
                    "page_roles": [str(r) for r in (_rec.get("page_roles")
                                                    or _rec.get("roles") or [])],
                    "record_source": str(_rec.get("source")
                                         or _rec.get("bom_source") or ""),
                    "source_page": _rec.get("source_page"),
                    # The fuller codes this one is a prefix of. A code that is a stem of
                    # another code on the same job is the signature of a truncated read, and
                    # naming the candidates turns "why is this here" into one glance.
                    "longer_codes_sharing_this_stem": sorted(
                        other.part_number for other in nodes
                        if other.part_number != node.part_number
                        and len(other.part_number) > len(node.part_number)
                        and other.part_number.upper().startswith(node.part_number.upper())
                    ),
                })

    return {
        "nodes": nodes,
        "raw": raw,
        "records": records,
        "aliases": aliases,
        "issues": graph_issues,
        "parents": parents,
        "children": {key: set(value) for key, value in children.items()},
        "quantities": quantities,
        # top_assembly stays exactly what it was — the single declared or deduced top, blank
        # where there is no single one. Every existing reader keeps its meaning. top_assemblies
        # is the full forest, and the readers for which "is this the thing that ships" is the
        # real question ask that one instead: with two GAs, both of them ship.
        "top_assembly": top_id,
        "top_assemblies": list(top_ids),
    }


def apply_canonical_evidence_to_parts(
    parts: Sequence[Dict[str, Any]],
    llm_extract: Optional[Mapping[str, Any]] = None,
    bom_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    known_assemblies: Optional[Iterable[str]] = None,
    page_owner: Optional[Mapping[int, str]] = None,
    summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make the canonical graph authoritative BEFORE costing, not after it.

    THE COMPILER WAS RIGHT AND TOO LATE. It ran after estimate_part, so on 11350 it could
    state that 11350-01-101 is an assembly while the workbook had already charged it as a
    2.5mm fabricated leaf — its own laser, its own fold, its own material, on top of the bar
    it is made from. A graph that only describes what pricing already did is a report, not
    an authority.

    Same for make/buy: a row the graph calls bought_in but the estimator classified from
    geometry takes a fabrication route it should never have had.

    So the classification is written onto the pre-cost records, where it still changes the
    answer. Deliberately NARROW — kind and hierarchy only. Geometry is not touched here:
    the mirrored-flat rule lives in drawing_job_merge with the DXF binding it depends on,
    and a second copy in this module is how the two would come to disagree.

    Returns the compiled graph so the caller can record what it found.
    """
    graph = build_part_graph(parts, llm_extract, bom_rows, known_assemblies, page_owner)
    # THE EVIDENCE, FILED AT THE FIRST DROP. The refresh recompile may never re-mint the
    # chimera's identity (its record is already gone from the parts), so if this call
    # does not file the quarantine on the summary, the pack-completeness invariant still
    # sends someone to Design for the phantom's drawing off the raw BOM row.
    quarantine_interleave_artefacts(parts, graph.get("issues"), summary=summary)
    nodes = {node.part_number: node for node in graph["nodes"]}
    aliases = graph.get("aliases") or {}
    for part in parts or []:
        if not isinstance(part, dict):
            continue
        source_id = clean_part_number(part.get("part_number") or part.get("item_number"))
        identity = aliases.get(source_id, source_id)
        node = nodes.get(identity) if identity else None
        if node is None:
            continue
        part["canonical_part_number"] = identity
        part["canonical_kind"] = node.kind
        if node.kind == "assembly":
            part["is_sub_assembly"] = True
            part["is_assembly_parent"] = True
            _flags = part.setdefault("review_flags", [])
            _msg = ("canonical hierarchy classifies this record as an assembly parent; its "
                    "material and leaf-only fabrication belong to its children")
            if _msg not in _flags:
                _flags.append(_msg)
            # AND THEN IT WAS CHARGED ANYWAY. The sentence above has been written onto
            # assembly parents for as long as this function has existed, and nothing acted
            # on it — 12392's panel assembly carried CNC routing, edge banding and
            # laminating, read from an MDF title block on another sheet of the pack, onto a
            # thing that is two steel panels bolted together. A flag no pass reads is a
            # comment. Joining and finishing are untouched: they are what an assembly is.
            part["canonical_kind"] = "assembly"   # so every later pass reads one answer
            _dropped = bought_in_policy.strip_leaf_operations(part)
            if _dropped:
                part.setdefault("removed_operations", []).extend(_dropped)
                _flags.append(
                    "removed leaf-only operations that an assembly cannot incur ("
                    + ", ".join(_dropped) + "); they belong to the parts it is made from")
        elif node.kind == "bought_in":
            roles = list(part.get("page_roles") or [])
            if "bought_in" not in {str(role).strip().lower() for role in roles}:
                roles.append("bought_in")
            part["page_roles"] = roles

    # ONE COMMODITY, ONE LINE — ON THE RECORDS, NOT ONLY IN THE GRAPH. The alias passes
    # correctly resolved "10975", "10975EPDMCLOSEDCELL" and "CELL TAPE^10975-02-" to one
    # identity, and the sheet still showed three tape lines: an alias in the graph does
    # nothing to the three part RECORDS the estimator prices. Where several bought-in
    # records resolve to one canonical identity, one record survives; the others fold into
    # it — their evidence (pages, price, source) fills the survivor's gaps, a disagreeing
    # quantity or length is recorded as a conflict for a person, and the duplicates leave
    # the costed population so the item is priced once.
    _by_identity: Dict[str, List[Dict[str, Any]]] = {}
    for part in parts or []:
        if isinstance(part, dict) and part.get("canonical_part_number"):
            _by_identity.setdefault(
                str(part["canonical_part_number"]), []).append(part)
    _folded_ids: Set[int] = set()
    for identity, members in _by_identity.items():
        if len(members) < 2:
            continue
        node = nodes.get(identity)
        if node is None or node.kind == "assembly":
            continue
        # The graph's kind only knows a STATED bought-in role, and the 17:11 tape stated
        # none — it wore the GA's ACRYLIC and classified leaf. The policy's own answer
        # (named consumable, no fabrication evidence) is the second witness: fold only
        # when EVERY record is one we buy, whichever authority says so.
        if node.kind != "bought_in":
            try:
                from bought_in_policy import is_bought_in as _fold_bi
            except Exception:                                    # noqa: BLE001
                continue
            if not all(_fold_bi(dict(m)) for m in members):
                continue
        survivor = next(
            (m for m in members
             if clean_part_number(m.get("part_number") or m.get("item_number")) == identity),
            max(members, key=lambda m: len(str(m.get("description") or ""))))
        for member in members:
            if member is survivor:
                continue
            for key, value in member.items():
                if str(key).startswith("_") or key in (
                        "part_number", "item_number", "quantity", "description",
                        "canonical_part_number", "canonical_kind", "review_flags"):
                    continue
                if not survivor.get(key) and value:
                    survivor[key] = value
            # PRICE PROVENANCE TRAVELS WITH THE FOLD. The generic copy above fills a
            # wholly missing material_estimate, but a survivor with its own estimate and
            # no price_source kept neither — and a line whose provenance is lost stops
            # being counted as a market figure to replace. Nested, so merged explicitly.
            _mme = member.get("material_estimate")
            _sme = survivor.get("material_estimate")
            if isinstance(_mme, dict) and _mme.get("price_source") \
                    and isinstance(_sme, dict) and not _sme.get("price_source"):
                _sme["price_source"] = _mme["price_source"]
                if not _sme.get("cost_method") and _mme.get("cost_method"):
                    _sme["cost_method"] = _mme["cost_method"]
            _mq = number(member.get("quantity"), 0.0)
            _sq2 = number(survivor.get("quantity"), 0.0)
            if _mq and _sq2 and _mq != _sq2:
                survivor.setdefault("_bom_numeric_conflicts", []).append({
                    "field": "quantity", "kept": _sq2, "other": _mq,
                    "from_identity": str(member.get("part_number") or ""),
                })
            survivor.setdefault("review_flags", []).append(
                f"BOM row '{member.get('part_number')}' "
                f"({str(member.get('description') or '').strip()}) is this same purchased "
                f"item stated again — folded into this line rather than priced twice")
            _folded_ids.add(id(member))
            print(f"   [graph] folded duplicate bought-in record "
                  f"'{member.get('part_number')}' into '{survivor.get('part_number')}' — "
                  f"one commodity, one priced line", flush=True)
    if _folded_ids and isinstance(parts, list):
        parts[:] = [p for p in parts if id(p) not in _folded_ids]
    return graph


def interleave_artefact_identities(issues: Any) -> Set[str]:
    """The identities a graph compilation quarantined as zipped-BOM-row chimeras."""
    out: Set[str] = set()
    for issue in issues or []:
        if isinstance(issue, Mapping) and \
                str(issue.get("code") or "") == "bom_row_interleave_artifact":
            ident = clean_part_number(issue.get("identity"))
            if ident:
                out.add(ident)
    return out


def quarantine_interleave_artefacts(part_lists: Any, issues: Any,
                                    summary: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Remove the part RECORDS behind dropped interleave artefacts, keeping the evidence.

    THE DROP HAS TO OUTLIVE THE GRAPH. build_part_graph correctly refused
    1100997755-E0P2D-GM0 — twice in one run — and the workbook still priced it, because
    the graph only forgot the identity while the part record itself stayed in the costed
    population and the dual-path reconciler put its row straight back. Whoever compiles a
    graph now hands its issues here, and the matching records leave every list they are in.

    Accepts one list of part dicts or a list of such lists, mutates them in place, and
    returns the removed records. When a summary is given, the removed records and the
    reason are filed on it under quarantined_interleave_artefacts — evidence preserved,
    never a silent delete — and the pack-completeness invariant reads that file so nobody
    is asked to chase a drawing for a part that does not exist.
    """
    idents = interleave_artefact_identities(issues)
    if not idents:
        return []
    lists = part_lists if isinstance(part_lists, tuple) or (
        isinstance(part_lists, list) and part_lists and isinstance(part_lists[0], list)
    ) else [part_lists]
    removed: List[Dict[str, Any]] = []
    for one in lists:
        if not isinstance(one, list):
            continue
        kept: List[Any] = []
        for part in one:
            pn = clean_part_number(
                part.get("part_number") or part.get("item_number")
            ) if isinstance(part, dict) else ""
            if pn and pn in idents:
                removed.append(part)
            else:
                kept.append(part)
        if len(kept) != len(one):
            one[:] = kept
    if removed:
        _names = sorted({str(p.get("part_number") or "?") for p in removed})
        print(f"   [graph] quarantined {len(removed)} record(s) behind dropped "
              f"interleave artefact(s): {', '.join(_names)} — removed from the costed "
              f"population, evidence kept on the run", flush=True)
        if isinstance(summary, dict):
            _store = summary.setdefault("quarantined_interleave_artefacts", [])
            _stored_ids = {str(e.get("part_number") or "") for e in _store
                          if isinstance(e, dict)}
            for p in removed:
                if str(p.get("part_number") or "") not in _stored_ids:
                    _store.append({
                        "part_number": str(p.get("part_number") or ""),
                        "description": str(p.get("description") or ""),
                        "reason": "bom_row_interleave_artifact",
                        "record": p,
                    })
    return removed


def fold_bom_row_fragments(part_lists: Any, bom_rows: Any,
                           summary: Optional[Dict[str, Any]] = None) -> List[str]:
    """Fold a minted BI- fragment of a wrapped BOM row into the line that owns the row.

    THE SAME ROW, READ THREE TIMES. p.1's wrapped tape row reads "10975 EPDM Closed Cell
    Tape^10975-02-GA EPDM TAPE 25X1MM …", and the late BI- minting pass turned the wrap
    fragments "Cell Tape" and "Closed Cell Tape" into two PRICED lines beside the line
    already carrying the row — £6.80 of phantom material on the 08:08 run. A BI- code with
    no measured geometry whose entire wording sits inside ONE raw BOM row that another
    retained bought-in line demonstrably claims is that row re-read, not a second
    purchase. Evidence lands on the survivor and, when a summary is given, under
    folded_bom_row_fragments — never a silent delete. Returns the folded identities.
    """
    try:
        from bought_in_policy import is_bought_in as _bi
    except Exception:                                            # noqa: BLE001
        return []
    lists = [one for one in (
        part_lists if isinstance(part_lists, list) and part_lists
        and isinstance(part_lists[0], list) else [part_lists]
    ) if isinstance(one, list)]
    if not lists:
        return []
    row_sq: List[tuple] = []
    for r in bom_rows or []:
        if isinstance(r, Mapping):
            text = f"{r.get('part_number') or ''} {r.get('description') or ''}".strip()
            s = _squashed(text)
            if len(s) >= 16:
                row_sq.append((s, text))
    if not row_sq:
        return []
    pool: Dict[str, Dict[str, Any]] = {}
    for one in lists:
        for p in one:
            if isinstance(p, dict) and p.get("part_number"):
                pool.setdefault(clean_part_number(p.get("part_number")), p)
    folded: Dict[str, str] = {}
    for pn, part in pool.items():
        if not pn.upper().startswith("BI-"):
            continue
        _ng = part.get("normalized_geometry") or {}
        if number(_ng.get("blank_length_mm"), 0.0) or not _bi(dict(part)):
            continue
        frag = _squashed(str(part.get("description") or "") or pn[3:])
        if len(frag) < 7:
            continue
        for s, row_text in row_sq:
            if frag not in s or len(frag) >= len(s):
                continue
            for opn, other in pool.items():
                if (opn == pn or opn in folded or opn.upper().startswith("BI-")
                        or not isinstance(other, dict)):
                    continue
                osq_desc = _squashed(str(other.get("description") or ""))
                osq_code = _squashed(opn)
                claims = ((len(osq_desc) >= 8 and osq_desc in s)
                          or (len(osq_code) >= 5 and osq_code in s))
                if not claims or not _bi(dict(other)):
                    continue
                folded[pn] = opn
                other.setdefault("review_flags", []).append(
                    f"BI line '{pn}' ({str(part.get('description') or '').strip()}) is "
                    f"a fragment of this line's own BOM row ('{row_text[:90]}') re-read "
                    f"by a later pass — folded here, not priced as a second purchase")
                if isinstance(summary, dict):
                    summary.setdefault("folded_bom_row_fragments", []).append({
                        "part_number": pn, "into": opn,
                        "description": str(part.get("description") or ""),
                        "bom_row": row_text, "record": part})
                break
            if pn in folded:
                break
    if folded:
        gone = set(folded)
        for one in lists:
            one[:] = [p for p in one
                      if not (isinstance(p, dict)
                              and clean_part_number(p.get("part_number")) in gone)]
        print(f"   [graph] folded {len(folded)} BI fragment line(s) of wrapped BOM "
              f"row(s): " + "; ".join(f"{k} -> {v}" for k, v in sorted(folded.items())),
              flush=True)
    return sorted(folded)


def refresh_canonical_route_after_reconciliation(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Recompile once the late readers have finished adding rows.

    THE OTHER TIMING BOUNDARY. The dual-path table reader adds bought-ins AFTER
    estimate_document has compiled the route — which is how 11350's wing nuts and PEM studs
    reached the Estimate tab and the reports while the canonical BOM had never heard of
    them. Two BOM authorities, and the one an estimator reads was the one outside the graph.

    Recompiling from the FINAL population closes it: the workbook can no longer show a line
    the hierarchy does not know exists.
    """
    estimate_summary = summary.get("estimate_summary") or {}
    final_estimates = estimate_summary.get("part_estimates") or []
    raw_parts = list((summary.get("manufacturing_writeup") or {}).get("parts") or [])
    raw_ids = {
        clean_part_number(item.get("part_number") or item.get("item_number"))
        for item in raw_parts if isinstance(item, Mapping)
    }
    population = raw_parts + [
        item for item in final_estimates
        if isinstance(item, Mapping)
        and clean_part_number(item.get("part_number") or item.get("item_number")) not in raw_ids
    ]
    _da = summary.get("document_analysis") or {}
    # THE OCCURRENCES FIRST, AND THE PROJECTION ONLY AFTER THEM. This preferred
    # bay_bom_rows, on the reasoning that it is the population the sheet is built from —
    # which is exactly why it is the wrong input. bay_bom_rows is a PROJECTION: it is
    # deduped, shadowed rows are dropped from it, and it can only ever hold less hierarchy
    # than the ledger it was made from. document_analysis.bom_rows is what the readers
    # actually recorded, one row per printed line, and it is the only list that can be
    # trusted to still contain a parent the rollup happened to collapse.
    #
    # Both are passed, occurrences first, because the projection also carries rows the
    # occurrences never had — synthesised and catalogue lines. Those state no parent, so
    # they add nothing to the hierarchy and cost nothing to include; where a row appears in
    # both, the edge is identical and adding it twice is a no-op.
    compiled = compile_job_route(population, summary.get("llm_full_extract") or {},
                                 list(_da.get("bom_rows") or [])
                                 + list(_da.get("bay_bom_rows") or []),
                                 job_drawing_numbers(summary),
                                 _assembly_page_owners(summary))
    # THE DROP, AFTER THE LAST READER AS WELL AS BEFORE THE FIRST. The pre-cost pass
    # quarantines the zipped-BOM-row chimera, and the dual-path reconciler then re-adds
    # its row from the raw table read — which is how a part the log twice said was
    # dropped still reached the Estimate sheet. This recompile is the final population,
    # so the purge here is the one nothing can undo.
    _final_lists = [list_ for list_ in (
        (summary.get("manufacturing_writeup") or {}).get("parts"),
        final_estimates if isinstance(final_estimates, list) else None,
    ) if isinstance(list_, list)]
    _removed = list(quarantine_interleave_artefacts(
        _final_lists, compiled.get("issues"), summary=summary))
    # AND THE WRAP FRAGMENTS, AT THE SAME BOUNDARY. The BI- minting pass runs during
    # reconciliation, so only a purge HERE can see what it invented.
    _removed += list(fold_bom_row_fragments(
        _final_lists, list(_da.get("bom_rows") or []), summary=summary))
    if _removed:
        # RECOMPILE FROM THE CLEANED POPULATION. The shadow above was compiled BEFORE the
        # purge, so it still carried a node per removed record — and any consumer that
        # trusts the graph (the workbook's own missing-bought-in mint, the Canonical BOM
        # display) faithfully resurrected them: "folded" in the log, priced on the sheet.
        # The published graph must describe the population that survived.
        raw_parts2 = list((summary.get("manufacturing_writeup") or {}).get("parts") or [])
        raw_ids2 = {clean_part_number(i.get("part_number") or i.get("item_number"))
                    for i in raw_parts2 if isinstance(i, Mapping)}
        population2 = raw_parts2 + [
            i for i in final_estimates
            if isinstance(i, Mapping)
            and clean_part_number(i.get("part_number") or i.get("item_number"))
            not in raw_ids2]
        compiled = compile_job_route(population2, summary.get("llm_full_extract") or {},
                                     list(_da.get("bom_rows") or [])
                                     + list(_da.get("bay_bom_rows") or []),
                                     job_drawing_numbers(summary),
                                     _assembly_page_owners(summary))
    payload = project_priced_route(compiled, final_estimates)
    estimate_summary["canonical_route_shadow"] = payload
    summary["estimate_summary"] = estimate_summary
    return payload


def _assembly_page_owners(summary: Mapping[str, Any]) -> Dict[int, str]:
    """file_scan owns this reading; imported lazily so route_compiler stays importable
    without it, and returns {} rather than raising if it cannot be reached."""
    try:
        from file_scan import assembly_page_owners
        return assembly_page_owners(summary)
    except Exception:                                       # noqa: BLE001
        return {}


def job_drawing_numbers(summary: Mapping[str, Any]) -> List[str]:
    """The drawing numbers this job actually opened, from the file names it read.

    A general arrangement whose PDF we scanned exists — that is not an inference, it is the
    pack in our hands. It is worth stating separately from the part records because a GA can
    perfectly well produce no part record of its own: it is the sheet that lists the parts.
    On 12392 that is precisely what happened to the second drawing, and every part it owned
    was reported as belonging to nothing.

    THE NUMBER IS THE FIRST TOKEN, AND THE REST IS WHAT THE DRAWING IS CALLED. This took the
    whole stem, so "12392-04-GA Mod Bracket Set_revA.pdf" produced the identity "12392-04-GA
    MOD BRACKET SET_REVA", which matches the BOM's parent "12392-04-GA" nowhere. Every part
    on that drawing was then reported as belonging to nothing — and the refusal that caused
    it was written here deliberately, out of a worry about descriptive names, without
    checking what a real SDI file is actually called. Estimating names drawings
    "<number> <what it is>_rev<x>", which is a convention, not prose.

    The safety survives intact, because it was never about the suffix: a token is accepted
    only if it LOOKS like a drawing number — digits and separators, at least one of each.
    "Mod mount bracket set.pdf" still yields nothing, because "Mod" is not a number, and a
    drawing whose number we cannot read must not head a tree. Callers validate the result
    against the identities the job already knows, so a wrong guess here cannot become an edge
    on its own; this only decides whether there is a candidate to check at all.
    """
    names: List[str] = []
    for entry in (summary.get("job_source_pdfs") or []):
        raw = entry.get("name") if isinstance(entry, Mapping) else entry
        stem = str(raw or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if stem.lower().endswith(".pdf"):
            stem = stem[:-4]
        # Split on space AND underscore: "12422-24-GA_End Cap_RevB" separates the number
        # from the description with an underscore, "12392-04-GA Mod Bracket Set" with a
        # space, and the same pack contains both spellings.
        head = re.split(r"[\s_]+", stem.strip(), maxsplit=1)[0]
        # Both the head and the whole stem, each in both spellings — a drawing is filed as
        # "1282 - GA.pdf" as readily as "1282-GA.pdf", and only normalize_part_code joins
        # the spaced form. THE LONGEST that still looks like a number wins: on
        # "12392-04 - GA.pdf" the head alone is "12392-04", which is a perfectly good
        # drawing number and the wrong one. A description cannot win this contest because
        # it does not look like a number at all.
        found = [s for candidate in (head, stem) for s in _code_spellings(candidate)
                 if _looks_like_a_drawing_number(s)]
        if found:
            best = max(found, key=len)
            if best not in names:
                names.append(best)
    return names


# A drawing number carries digits and at least one separator — "12392-04-GA", "1282-GA".
# A word does not. This is the whole of the protection against a descriptive file name being
# read as an assembly, so it is deliberately a positive test rather than a list of things to
# reject: anything that does not look like a number is not one.
def _looks_like_a_drawing_number(text: Any) -> bool:
    # The shape lives in part_code_conventions so the BOM reader's title-block read and
    # this compiler cannot disagree about what a drawing number looks like. They did:
    # the reader required three hyphenated segments, so it found no parent on any
    # two-segment job and the compiler then had nothing to build a hierarchy from.
    import part_code_conventions
    return part_code_conventions.looks_like_a_drawing_number(text)


def _roots_that_ship(graph: Mapping[str, Any]) -> List[str]:
    """Every assembly at the head of the forest — the things an order actually delivers.

    top_assembly is the single declared or deduced top and stays exactly that, because
    several readers mean "the one anchor" by it. This answers the different question three
    of them were really asking: is this node something that ships, and therefore something
    that must be packed and sequenced last. On a one-GA job the two answers are the same set.
    """
    roots = [str(r) for r in (graph.get("top_assemblies") or []) if r]
    if roots:
        return roots
    single = str(graph.get("top_assembly") or "")
    return [single] if single else []


def _ancestor_distances(identity: str, parents: Mapping[str, Set[str]]) -> Dict[str, int]:
    distances = {identity: 0}
    queue = [identity]
    while queue:
        current = queue.pop(0)
        for parent in parents.get(current) or set():
            distance = distances[current] + 1
            if parent not in distances or distance < distances[parent]:
                distances[parent] = distance
                queue.append(parent)
    return distances


def _is_descendant(identity: str, ancestor: str, parents: Mapping[str, Set[str]]) -> bool:
    return identity != ancestor and ancestor in _ancestor_distances(identity, parents)


def _lowest_common_assembly(
    participants: Sequence[str],
    parents: Mapping[str, Set[str]],
    kinds: Mapping[str, str],
) -> str:
    if not participants:
        return ""
    distance_maps = [_ancestor_distances(item, parents) for item in participants]
    common = set(distance_maps[0])
    for distances in distance_maps[1:]:
        common.intersection_update(distances)
    assemblies = {item for item in common if kinds.get(item) == "assembly"}
    if not assemblies:
        return ""
    return min(
        assemblies,
        key=lambda item: (
            max(distances[item] for distances in distance_maps),
            sum(distances[item] for distances in distance_maps),
            item,
        ),
    )


def _ruling_source(part: Mapping[str, Any], operation: str, reason: str) -> str:
    explicit = (part.get("operation_ruling_sources") or {}).get(operation)
    if explicit:
        return str(explicit)
    upper = reason.upper()
    if "SOLIDWORKS" in upper or "NATIVE" in upper or "MODEL" in upper:
        return "solidworks_api"
    if "DXF" in upper or "BEND LINE" in upper or "MEASURED" in upper:
        return "dxf"
    return "unknown"


def _tiebreak_priority(source: Any) -> int:
    """Within-rank source precedence, from the module that owns the ranks."""
    try:
        from source_precedence import tiebreak_priority
        return tiebreak_priority(source)
    except Exception:
        return 0


# The keys of _resolution_key, in order, so a resolution can name the one that settled it.
# WHICH key decided is the audit trail for the every-matter-resolved rule: "rank" is the
# waterfall doing its job, and anything below it is the arbiter choosing between sources the
# waterfall calls equal. An estimator fine-tuning the engine needs to see which.
RESOLUTION_KEYS = ("within-rank source priority", "confidence",
                   "quotes the drawing", "claim id (reproducibility backstop)")


def settled_by(winner: OperationClaim, others: Sequence[OperationClaim]) -> str:
    """Which key first separated `winner` from every other claim.

    Returns the FIRST key on which the winner strictly beats them all -- that is the one
    doing the work. A resolution that reaches "claim id" is a coin flip made reproducible,
    and it should look different in a report from one settled by the drawing's own words.
    """
    win = _resolution_key(winner)
    rivals = [_resolution_key(c) for c in others if c.claim_id != winner.claim_id]
    if not rivals:
        return ""
    for i, name in enumerate(RESOLUTION_KEYS):
        if all(win[i] > r[i] for r in rivals):
            return name
        if any(win[i] < r[i] for r in rivals):
            return name          # cannot happen for a winner, but never lie about it
    return RESOLUTION_KEYS[-1]


def _resolution_key(claim: OperationClaim):
    """The order that settles a tie between equally-ranked claims.

    ONE ORDERING, USED BY STATUS AND BY EVERY METADATA FIELD, so the decision and its
    metadata cannot be settled by different rules and end up describing different claims.

        1. within-rank source    — a published ordering: the flat pattern over the model,
                                   the title block over loose drawing text, the whole-job
                                   pass over the per-part one, a person over a stored
                                   default. Deterministic and explainable in a report,
                                   which is what an estimator needs from a contested line.
        2. confidence            — the claim's own stated certainty
        3. quotes the drawing    — a claim carrying the sheet's own words can be held
                                   AGAINST the sheet; one that does not cannot be argued
                                   with at all. This is what settles the commonest tie of
                                   all, which key 1 cannot touch: ONE SOURCE DISAGREEING
                                   WITH ITSELF — two DXF claims about the same fold.
        4. claim_id              — not decoration. It is what makes the same job compile to
                                   the same route twice, and reproducibility is the property
                                   the whole parallel run rests on. Never remove it.

    WHAT IS DELIBERATELY NOT A KEY: preferring "required" over "ruled_out". It sounds
    prudent and it is a systematic bias toward charging for work that was ruled out on
    evidence — it would have kept the powder line on 11650's PETG panels, which is the
    exact failure this month's work removed.
    """
    return (
        _tiebreak_priority(claim.source),
        claim.confidence if claim.confidence is not None else -1.0,
        1 if str(getattr(claim, "evidence", "") or "").strip() else 0,
        claim.claim_id,
    )


def _display_source(source: Any) -> str:
    """WHERE THE DECISION WAS TAKEN, in the estimator's words — "the SolidWorks model",
    "the DXF flat pattern", "Grok (xAI)".

    Read from source_precedence, which owns the ranks, so the name and the rank cannot
    disagree about what a source is. Best-effort: a display name is never worth failing a
    compile over, and the raw key is a usable answer if the import is unavailable."""
    try:
        from source_precedence import display_name
        return display_name(source)
    except Exception:
        return str(source or "").replace("_", " ")


def _metadata_value(claim: OperationClaim, field_name: str) -> Any:
    return getattr(claim, field_name)


def _normalise_metadata_value(field_name: str, value: Any) -> Any:
    if field_name == "participants":
        return tuple(sorted(value or []))
    return value


def _pick_metadata(
    claims: Sequence[OperationClaim],
    field_name: str,
) -> Tuple[Any, Optional[str], Optional[Dict[str, Any]]]:
    candidates = []
    for claim in claims:
        value = _metadata_value(claim, field_name)
        if value is None or value == "" or value == []:
            continue
        candidates.append((claim, value))
    if not candidates:
        return None, None, None

    best_rank = max(item[0].source_rank for item in candidates)
    strongest = [item for item in candidates if item[0].source_rank == best_rank]
    values = {
        _normalise_metadata_value(field_name, item[1])
        for item in strongest
    }
    conflict = None
    if len(values) > 1:
        # RESOLVED, NOT ABANDONED. Returning None here left the field absent, and an absent
        # qty_per_unit then took the compiler's default of 1.0 — so a disagreement about
        # how many times an operation happens was settled by a constant that had read
        # neither claim. Taking the strongest claim's value is worse than unanimity and
        # better than a default, and the disagreement still travels with the decision.
        conflict = {
            "field": field_name,
            "rank": best_rank,
            "values": [repr(value) for value in sorted(values, key=repr)],
            "sources": sorted({item[0].source for item in strongest}),
            "resolution": "highest confidence at the top rank; claim_id breaks a "
                          "confidence tie so the job compiles the same way twice",
        }
    winner, value = max(strongest, key=lambda item: _resolution_key(item[0]))
    if field_name == "participants":
        value = list(value)
    return value, winner.source, conflict


def arbitrate_event(
    decision_id: str,
    claims: Sequence[OperationClaim],
) -> OperationDecision:
    """Resolve status by source rank and gap-fill metadata field by field."""
    if not claims:
        raise ValueError("an operation decision requires at least one claim")

    strongest_rank = max(claim.source_rank for claim in claims)
    strongest_status_claims = [
        claim for claim in claims if claim.source_rank == strongest_rank
    ]
    statuses = {claim.status for claim in strongest_status_claims}
    conflicts: List[Dict[str, Any]] = []

    # ── EVERY MATTER IS RESOLVED ────────────────────────────────────────────────────
    # A tie between two equally-ranked sources used to yield UNVERIFIED. That is not a
    # decision, it is the absence of one — and it was handed to a reader with less to go
    # on than the arbiter had. Nothing prices an UNVERIFIED operation, so an unsettled
    # disagreement left the shop doing work nobody charged for.
    #
    # So the tie is broken here, deterministically: highest confidence, then claim_id. The
    # claim_id fallback is not arbitrary decoration — it is what makes the same job compile
    # to the same route twice, and reproducibility is the property the whole parallel run
    # rests on.
    #
    # WHAT MUST NOT BE LOST IS THAT IT WAS A TIE. The conflict record, `contested` and
    # `losing_statuses` all survive, so a report can say "resolved, and here is what the
    # other source claimed". Resolved is not unanimous, and the two must stay tellable
    # apart — a decision taken over an objection is exactly the one an estimator should
    # look at first.
    contested = False
    losing_statuses: List[str] = []
    if len(statuses) > 1:
        contested = True
        conflicts.append({
            "field": "status",
            "rank": strongest_rank,
            "values": sorted(statuses),
            "sources": sorted({claim.source for claim in strongest_status_claims}),
            "resolution": "highest confidence at the top rank; claim_id breaks a "
                          "confidence tie so the job compiles the same way twice",
        })
        status_winner = max(strongest_status_claims, key=_resolution_key)
        status = status_winner.status
        losing_statuses = sorted(statuses - {status})
        settled = settled_by(status_winner, strongest_status_claims)
        conflicts[-1]["settled_by"] = settled
    else:
        status = next(iter(statuses))
        same_status = [
            claim for claim in strongest_status_claims if claim.status == status
        ]
        status_winner = max(same_status, key=_resolution_key)

    metadata: Dict[str, Any] = {}
    provenance: Dict[str, str] = {}
    for field_name in ("route_id", "target_id", "scope", "participants",
                       "qty_per_unit", "sequence"):
        value, source, conflict = _pick_metadata(claims, field_name)
        if conflict:
            conflicts.append(conflict)
            contested = True
        metadata[field_name] = value
        if source:
            provenance[field_name] = source

    # A CONTESTED FIELD NO LONGER BLANKS THE STATUS. It used to: any metadata disagreement
    # — a sequence number, a participant list — demoted the whole operation to UNVERIFIED
    # and it stopped being priced. An argument about WHEN an operation happens is not
    # doubt about WHETHER it happens, and answering the second question with the first is
    # how a real operation came off the sheet over a disagreement about its ordering.

    # ── WHETHER ANYTHING READ THIS, OR WE ONLY REASONED IT ──────────────────────────
    #
    # Recorded, NOT enforced. The first version of this demoted an uncorroborated REQUIRED
    # operation to UNVERIFIED and broke eight tests, correctly: the extract is today the
    # primary route source, so demoting all of it collapses the route to nothing anybody
    # would price.
    #
    # The BOM does not work that way either, and it is the model to copy. A row only one
    # reader saw is not dropped — it is emitted, flagged, and an invariant blocks when the
    # money behind the doubt is material. Weight belongs where the cost is known, and that
    # is not here.
    #
    # So: a decision is corroborated when any claim behind it was READ rather than
    # reasoned, or quotes the drawing's own words. Everything else is proposed, and says so.
    _reasoned_sources = {"llm_full_extract", "llm_extract", "inference", "geometry_inference"}
    _read_it = [c for c in claims
                if str(c.source or "").strip().lower() not in _reasoned_sources]
    _quoted_it = [c for c in claims if str(getattr(c, "evidence", "") or "").strip()]
    _corroborated = bool(_read_it or _quoted_it)

    # Multiplicity exists only for required work. Participant count is never a fallback.
    qty = metadata.get("qty_per_unit") if status == REQUIRED else None
    if status == REQUIRED and qty is None:
        qty = 1.0
        provenance["qty_per_unit"] = "compiler_default"

    participants = metadata.get("participants") or sorted({
        participant for claim in claims for participant in claim.participants
    })
    operation = claims[0].operation
    reason = status_winner.reason
    if conflicts:
        _fields = sorted({str(c.get("field") or "?") for c in conflicts})
        reason = (f"{reason or status_winner.status} — resolved over a disagreement on "
                  f"{', '.join(_fields)}; see conflicts")

    # THE EVIDENCE OF THE STRONGEST CLAIM THAT HAS ANY. A decision assembled from several
    # claims should quote the drawing where any of them could, not only where the winner
    # happened to. Measured sources rank first, so this prefers a cut-list property or a
    # bend count over a note, and a note over nothing.
    _ev = ""
    _ev_where = ""
    for _c in sorted(claims, key=lambda c: -(c.source_rank or 0)):
        if getattr(_c, "evidence", ""):
            _ev, _ev_where = _c.evidence, getattr(_c, "evidence_where", "")
            break

    return OperationDecision(
        decision_id=decision_id,
        route_id=str(metadata.get("route_id") or status_winner.route_id or ""),
        operation=operation,
        status=status,
        target_id=clean_part_number(
            metadata.get("target_id") or status_winner.target_id),
        scope=metadata.get("scope") or status_winner.scope,
        participants=sorted(set(participants)),
        qty_per_unit=qty,
        sequence=metadata.get("sequence"),
        source=status_winner.source,
        source_rank=strongest_rank,
        evidence=_ev,
        evidence_where=_ev_where,
        corroborated=_corroborated,
        contested=contested,
        losing_statuses=losing_statuses,
        decided_by=_display_source(status_winner.source),
        settled_by_key=(conflicts[0].get("settled_by", "") if conflicts else ""),
        confidence=status_winner.confidence,
        reason=reason,
        field_provenance=provenance,
        conflicts=conflicts,
        claims=[asdict(claim) for claim in sorted(
            claims, key=lambda item: (-item.source_rank, item.claim_id))],
    )


def _record_stock_form(record: Any) -> str:
    """The stock form the gates read: the record's own, else its material estimate's.

    estimate_part writes 'tube' onto the part when it costs a hollow section, and the material
    estimate carries it too; a reader that consults only one of the two misses the tube half the
    time, which is how a gate keyed on stock form silently never fires."""
    if not isinstance(record, Mapping):
        return ""
    return str(
        record.get("stock_form")
        or (record.get("material_estimate") or {}).get("stock_form")
        or ""
    ).strip().lower()


def weldment_finish_for_gate(record: Mapping[str, Any], target_id: str,
                             graph: Mapping[str, Any]) -> str:
    """The finish to test a part against in the powder/plate gate — a weldment parent inherits
    its members' finish when it states none of its own.

    A WELDMENT CARRIES NO FINISH OF ITS OWN. The drawing states it once for the whole object,
    so stated_finish() on the parent record is empty and an INFERRED powder on the parent is
    never contradicted — 7332-01-101 kept a £15.92 P.Coat row while the drawing said PLATED,
    even though its own back panel (008) correctly dropped powder for exactly that reason.

    When the parent has no finish of its own, inherit the one its MEMBERS agree on: only when
    the members that state a finish resolve to a SINGLE recognised family (ignoring 'bare' — a
    raw member is finished AT assembly, e.g. 7332-01-001 "raw then plated on the weldment") and
    that family is not powder. A mixed set, or a powder set, leaves the parent's own (empty)
    finish untouched, so a genuinely powder-coated weldment is unaffected. A part that states
    its own finish is returned as-is, so leaves are unchanged."""
    from finish_rules import stated_finish, finish_families
    own = stated_finish(record)
    if own:
        return own
    records = graph.get("records") or {}
    kids = (graph.get("children") or {}).get(target_id) or ()
    fams: Set[str] = set()
    for kid in kids:
        kf = stated_finish(records.get(kid) or {})
        if kf:
            fams |= finish_families(kf)
    fams.discard("bare")
    if len(fams) == 1 and "powder" not in fams:
        fam = next(iter(fams))
        for kid in kids:
            kf = stated_finish(records.get(kid) or {})
            if kf and fam in finish_families(kf):
                return kf
    return own


def compile_job_route(
    parts: Sequence[Mapping[str, Any]],
    llm_extract: Optional[Mapping[str, Any]] = None,
    bom_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    known_assemblies: Optional[Iterable[str]] = None,
    page_owner: Optional[Mapping[int, str]] = None,
) -> Dict[str, Any]:
    """Compile every route source into one job-level decision graph."""
    llm_extract = llm_extract or {}
    graph = build_part_graph(parts, llm_extract, bom_rows, known_assemblies, page_owner)
    raw: Dict[str, Mapping[str, Any]] = graph["raw"]
    kinds = {node.part_number: node.kind for node in graph["nodes"]}
    graph_quantities = graph["quantities"]
    claims_by_event: Dict[str, List[OperationClaim]] = {}
    explicit_memberships: Dict[Tuple[str, str], Set[str]] = {}
    explicit_assembly_events: Dict[str, List[Tuple[str, str]]] = {}
    issues: List[Dict[str, Any]] = list(graph.get("issues") or [])

    def add_claim(event_id: str, claim: OperationClaim) -> None:
        claims_by_event.setdefault(event_id, []).append(claim)

    # The explicit extracted route establishes job-event identity.
    for route_index, route in enumerate(llm_extract.get("routes") or []):
        if not isinstance(route, Mapping):
            continue
        operation = clean_operation(route.get("operation"))
        participants = [
            clean_part_number(item)
            for item in (route.get("part_numbers") or [])
            if clean_part_number(item)
        ]
        if not operation or not participants:
            continue
        stated_scope = str(route.get("scope") or "").strip().lower()
        scope_was_inferred = False
        if stated_scope in VALID_SCOPES:
            declared_scope = stated_scope
        elif operation in ASSEMBLY_EVENT_OPERATIONS and len(participants) > 1:
            declared_scope = "assembly"
            scope_was_inferred = True
        else:
            declared_scope = "part"
        source = "inference" if route.get("inferred") else "llm_full_extract"
        base_route_id = str(route.get("route_id") or stable_id("route", {
            "operation": operation,
            "sequence": number(route.get("sequence")),
            "participants": sorted(participants),
        }))
        if scope_was_inferred:
            issues.append({
                "code": "route_scope_inferred_from_hierarchy",
                "route_id": base_route_id,
                "operation": operation,
                "participants": participants,
                "inferred_scope": declared_scope,
            })

        targets: List[Tuple[str, str, List[str]]] = []
        if declared_scope == "part":
            targets = [("part", participant, [participant])
                       for participant in participants]
        else:
            target_hint = clean_part_number(
                route.get("target_id")
                or route.get("assembly_id")
                or route.get("target_part_number")
            )
            assembly_participants = [
                item for item in participants if kinds.get(item) == "assembly"
            ]
            if target_hint:
                targets = [("assembly", target_hint, participants)]
            elif assembly_participants:
                covered: Set[str] = set()
                for assembly_id in assembly_participants:
                    members = [
                        item for item in participants
                        if item == assembly_id
                        or _is_descendant(item, assembly_id, graph["parents"])
                    ]
                    if (
                        operation == "assembly"
                        and members == [assembly_id]
                        and graph["children"].get(assembly_id)
                    ):
                        members = sorted(graph["children"][assembly_id])
                    covered.add(assembly_id)
                    covered.update(members)
                    targets.append(("assembly", assembly_id, members))
                # Mixed assembly routes (for example powder) can also name standalone leaves.
                # Those leaves are separate targets, not extra participant-count charges.
                for participant in participants:
                    if participant not in covered:
                        targets.append(("part", participant, [participant]))
                issues.append({
                    "code": "mixed_scope_route_split",
                    "route_id": base_route_id,
                    "operation": operation,
                    "targets": [item[1] for item in targets],
                })
            else:
                target = _lowest_common_assembly(
                    participants, graph["parents"], kinds)
                if target:
                    targets = [("assembly", target, participants)]
                else:
                    target = f"@ROUTE-{route_index + 1}"
                    targets = [("assembly", target, participants)]
                    issues.append({
                        "code": "assembly_scope_without_target",
                        "route_id": base_route_id,
                        "operation": operation,
                        "participants": participants,
                    })

        for target_index, (scope, target_id, members) in enumerate(targets):
            route_id = (
                base_route_id if len(targets) == 1
                else f"{base_route_id}:{target_index + 1}"
            )
            event_id = stable_id("decision", {
                "route_id": route_id,
                "operation": operation,
                "scope": scope,
                "target_id": target_id,
            })
            claim = make_claim(
                operation, REQUIRED, source,
                subject_id=target_id,
                target_id=target_id,
                scope=scope,
                participants=members,
                # WHAT THE DRAWING SAID, if the extract quoted it. A claim carrying the
                # sheet's own words can be held against the sheet; a bare operation name
                # cannot be argued with, only ranked.
                evidence=(route.get("evidence") or route.get("drawing_note")
                          or route.get("quote") or ""),
                evidence_where=(route.get("evidence_where") or route.get("where") or ""),
                # A ROUTE-GROUP QUANTITY IS NOT EACH TARGET'S QUANTITY.
                #
                # 2085's tube_cut names both tubes and states qty_per_unit 2 -- two tubes
                # per product. Splitting that into a decision per tube while copying the
                # group total onto each gave 2085-02 x2 and 2085-03 x2, a workbook total of
                # four cuts on two tubes: 18.25 batch hours and GBP 3.24 where the honest
                # figure is 9.25 and GBP 1.64. Over half the labour on this job.
                #
                # Where the line resolves to ONE target, its stated quantity is that
                # target's. Where it splits across several, each takes its own multiplicity
                # from the canonical BOM -- which is the only place that knows how many of
                # each part the product contains.
                qty_per_unit=(
                    route.get("qty_per_unit")
                    if (route.get("qty_per_unit") is not None and len(targets) == 1)
                    else graph_quantities.get(target_id, 1.0)
                ),
                sequence=route.get("sequence"),
                confidence=route.get("confidence"),
                reason=route.get("notes") or route.get("description"),
                route_id=route_id,
            )
            add_claim(event_id, claim)
            if scope == "assembly":
                explicit_assembly_events.setdefault(operation, []).append(
                    (target_id, event_id))
            # The target is a member of its own event for compatibility joins. Otherwise an
            # existing operation on assembly 101 becomes a second part-level weld alongside
            # the explicit assembly event it was describing.
            for member in set(members) | {target_id}:
                explicit_memberships.setdefault(
                    (operation, member), set()).add(event_id)

    # Compatibility adapter: every existing operation and ruling becomes evidence. It does
    # not mutate the old fields; source writers can migrate to native claims incrementally.
    for part_number, part in raw.items():
        operation_sources = part.get("operation_sources") or {}
        scopes = part.get("operation_scope") or {}
        operation_quantities = part.get("operation_qty_per_unit") or {}
        sequences = part.get("operation_sequence") or {}

        seen: Set[str] = set()
        # WHERE "an unrecorded source" CAME FROM, and why only one of these three changes.
        #
        # textual_operations is populated by infer_operations() over the drawing's cleaned note
        # text — a keyword recogniser reading WELD AND DRESS, TAP M4, FOLD off the sheet's own
        # words. That is a reading of the drawing. Falling back to "unknown" made it
        # indistinguishable from a claim nobody could account for, and section 12 printed forty
        # of them: "an unrecorded source", rank 0, for operations the drawing states.
        #
        # `operations` keeps "unknown" because it is written by several passes with different
        # provenance and this adapter cannot tell which wrote a given entry. Naming it would be
        # a guess, and a wrong source name is worse than an honest absence — the whole point of
        # the column is that it can be relied on.
        #
        # drawing_notes is absent from SOURCE_RANK and therefore still ranks 0, so nothing
        # arbitrates differently. This names the source; it does not promote it.
        for field_name, fallback_source in (
            ("textual_operations", "drawing_notes"),
            ("operations", "unknown"),
            ("inferred_operations", "inference"),
        ):
            for raw_operation in part.get(field_name) or []:
                operation = clean_operation(raw_operation)
                if not operation or operation in seen:
                    continue
                seen.add(operation)
                source = str(operation_sources.get(operation) or fallback_source)
                event_ids = sorted(
                    explicit_memberships.get((operation, part_number)) or [])
                if not event_ids and operation in ASSEMBLY_EVENT_OPERATIONS:
                    # A child record often repeats its parent's finish/weld wording. If an
                    # explicit assembly event already owns that operation, the child word is
                    # corroboration of that event, not a second charge on the child. Choose
                    # the most-specific owning assembly when nested events exist.
                    ancestor_events = [
                        (target_id, event_id)
                        for target_id, event_id in (
                            explicit_assembly_events.get(operation) or [])
                        if _is_descendant(part_number, target_id, graph["parents"])
                    ]
                    most_specific = [
                        (target_id, event_id)
                        for target_id, event_id in ancestor_events
                        if not any(
                            other_target != target_id
                            and _is_descendant(
                                other_target, target_id, graph["parents"])
                            for other_target, _ in ancestor_events
                        )
                    ]
                    if len(most_specific) == 1:
                        event_ids = [most_specific[0][1]]
                # Dressing is one event attached to the weld event, not a separate dressing
                # charge on every participant which happened to carry the inferred word.
                if not event_ids and operation == "dress_welds":
                    for weld_event_id in sorted(
                        explicit_memberships.get(("welding", part_number)) or []
                    ):
                        weld_claim = claims_by_event[weld_event_id][0]
                        derived_route_id = (
                            f"{weld_claim.route_id}:dress_welds"
                            if weld_claim.route_id
                            else stable_id("route", {
                                "parent_decision": weld_event_id,
                                "operation": "dress_welds",
                            })
                        )
                        dress_event_id = stable_id("decision", {
                            "route_id": derived_route_id,
                            "operation": "dress_welds",
                            "scope": weld_claim.scope,
                            "target_id": weld_claim.target_id,
                        })
                        if dress_event_id not in claims_by_event:
                            derived_sequence = (
                                weld_claim.sequence + 1
                                if weld_claim.sequence is not None else None
                            )
                            add_claim(dress_event_id, make_claim(
                                "dress_welds", REQUIRED, "override_rule",
                                subject_id=weld_claim.target_id,
                                target_id=weld_claim.target_id,
                                scope=weld_claim.scope,
                                participants=weld_claim.participants,
                                qty_per_unit=weld_claim.qty_per_unit,
                                sequence=derived_sequence,
                                reason="dress welds inherits the owning welding event",
                                route_id=derived_route_id,
                            ))
                            for member in (
                                set(weld_claim.participants)
                                | {weld_claim.target_id}
                            ):
                                explicit_memberships.setdefault(
                                    ("dress_welds", member), set()
                                ).add(dress_event_id)
                        event_ids.append(dress_event_id)
                if not event_ids:
                    scope = str(scopes.get(operation) or "part").strip().lower()
                    if scope not in VALID_SCOPES:
                        scope = "part"
                    compatibility_target = part_number
                    finish_text = str(
                        part.get("normalized_finish")
                        or part.get("finish")
                        or ""
                    ).upper()
                    finish_defers_to_assembly = (
                        operation == "powder_coating"
                        and "SEE ASSEMBLY" in finish_text
                    )
                    if finish_defers_to_assembly:
                        immediate_parents = sorted(graph["parents"].get(part_number) or [])
                        if len(immediate_parents) == 1:
                            scope = "assembly"
                            compatibility_target = immediate_parents[0]
                    event_ids = [stable_id("decision", {
                        "origin": "compatibility",
                        "operation": operation,
                        "scope": scope,
                        "target_id": compatibility_target,
                    })]
                for event_id in event_ids:
                    template = (claims_by_event.get(event_id) or [None])[0]
                    target_id = (
                        template.target_id if template else compatibility_target
                    )
                    scope = template.scope if template else scopes.get(operation, "part")
                    route_id = template.route_id if template else ""
                    claim_status = REQUIRED
                    if template is None and operation == "assembly":
                        # Generic per-record handling is a pricing default, not evidence that
                        # every leaf and bought-in line is assembled independently. Canonical
                        # assembly events are created from the hierarchy below.
                        claim_status = NOT_APPLICABLE
                    elif (
                        template is None
                        and operation == "powder_coating"
                        and "SEE ASSEMBLY" in str(
                            part.get("normalized_finish")
                            or part.get("finish")
                            or ""
                        ).upper()
                    ):
                        # The leaf explicitly delegates its finish, but no extracted route
                        # owns it. Pricing it on the leaf would be a guess and can duplicate
                        # a later assembly coat; keep the unresolved event visible instead.
                        claim_status = UNVERIFIED
                    elif (
                        template is None
                        and kinds.get(part_number) == "assembly"
                        and source == "unknown"
                        and operation not in {"assembly", "handling"}
                    ):
                        # An unattributed operation stranded on an assembly record is exactly
                        # the old flattening symptom. Preserve it, but do not silently assert
                        # that the parent performs it.
                        claim_status = UNVERIFIED
                    add_claim(event_id, make_claim(
                        operation, claim_status, source,
                        subject_id=part_number,
                        target_id=target_id,
                        scope=scope,
                        # Corroboration describes the already-established event. A singleton
                        # participant here would conflict at equal rank with the full route.
                        participants=(
                            template.participants if template else [part_number]),
                        # THE SECOND PLACE THE GROUP TOTAL LEAKED IN.
                        #
                        # operation_qty_per_unit on a part record is what the ROUTE LINE
                        # said, stamped onto every participant by the fold. For 2085's
                        # tube_cut that is 2 -- two tubes per product -- and reading it back
                        # per part gave 2085-02 x2 and 2085-03 x2 again, through the
                        # compatibility adapter this time rather than the route split
                        # fc3c9b2 fixed. One defect, two doors, and the first fix only
                        # closed one of them.
                        #
                        # A PART-scoped event happens once per instance of that part, so its
                        # quantity is the part's own BOM multiplicity. The route's stated
                        # figure describes the group and is kept only where the event covers
                        # the group -- an assembly-scoped event, which has one target.
                        qty_per_unit=(
                            operation_quantities.get(operation)
                            if (operation_quantities.get(operation) is not None
                                and scope != "part")
                            else graph["quantities"].get(target_id, 1.0)
                        ),
                        sequence=sequences.get(operation),
                        reason=f"{field_name} on existing part record",
                        route_id=route_id,
                    ))

        for raw_operation, raw_reason in (
            part.get("operations_ruled_out") or {}
        ).items():
            operation = clean_operation(raw_operation)
            reason = str(raw_reason or "operation ruled out")
            source = _ruling_source(part, operation, reason)
            candidates = []
            for event_id in sorted(
                explicit_memberships.get((operation, part_number)) or []
            ):
                template = claims_by_event[event_id][0]
                # A ruling about one participant does not cancel a separate assembly event.
                if template.scope == "part" or template.target_id == part_number:
                    candidates.append(event_id)
            if not candidates:
                candidates = [stable_id("decision", {
                    "origin": "ruling",
                    "operation": operation,
                    "target_id": part_number,
                })]
            for event_id in candidates:
                template = (claims_by_event.get(event_id) or [None])[0]
                add_claim(event_id, make_claim(
                    operation, RULED_OUT, source,
                    subject_id=part_number,
                    target_id=template.target_id if template else part_number,
                    scope=template.scope if template else "part",
                    participants=[part_number],
                    sequence=template.sequence if template else None,
                    reason=reason,
                    route_id=template.route_id if template else "",
                ))

    # Pressed fasteners are a route fact carried by the BOM, not a workbook-side guess.
    # One insertion event belongs to the lowest assembly containing the PEM/clinch items;
    # the number of inserts remains visible through the participant quantities.
    insertion_parts = []
    for part_number, part in graph["records"].items():
        if kinds.get(part_number) != "bought_in":
            continue
        description = " ".join((
            str(part.get("part_number") or ""),
            str(part.get("description") or ""),
        )).upper()
        if any(token in description for token in (
            "SELF-CLINCH", "SELF CLINCH", "CLINCH NUT", "PEM STUD",
            "PEM NUT", "PRESS-IN", "PRESS IN",
        )):
            insertion_parts.append(part_number)
    if insertion_parts:
        existing_insertions = [
            (event_id, event_claims[0])
            for event_id, event_claims in claims_by_event.items()
            if event_claims and event_claims[0].operation == "hardware_insertion"
        ]
        if existing_insertions:
            for insertion_event_id, template in existing_insertions:
                add_claim(insertion_event_id, make_claim(
                    "hardware_insertion", REQUIRED, "bom_tree",
                    subject_id=template.target_id,
                    target_id=template.target_id,
                    scope=template.scope,
                    participants=template.participants,
                    qty_per_unit=template.qty_per_unit,
                    sequence=template.sequence,
                    reason="PEM/self-clinch BOM corroborates the extracted insertion event",
                    route_id=template.route_id,
                ))
        else:
            insertion_target = (
                _lowest_common_assembly(
                    insertion_parts, graph["parents"], kinds)
                or graph["top_assembly"]
                or (_roots_that_ship(graph) or [""])[0]
                or insertion_parts[0]
            )
            insertion_route_id = stable_id("route", {
                "operation": "hardware_insertion",
                "target_id": insertion_target,
                "participants": sorted(insertion_parts),
            })
            insertion_event_id = stable_id("decision", {
                "route_id": insertion_route_id,
                "operation": "hardware_insertion",
                "scope": "assembly",
                "target_id": insertion_target,
            })
            # ONE EVENT, NOT ONE PER FASTENER. qty_per_unit here is the EVENT's
            # multiplicity; the four-stud workload is already charged downstream,
            # where the projection multiplies the participants' own insert count
            # into the batch hours (11350-01 row 99: 0.633 bh = 15 min set-up +
            # 4 studs x 15 s x 23 units). Raising this qty double-counts.
            add_claim(insertion_event_id, make_claim(
                "hardware_insertion", REQUIRED, "bom_tree",
                subject_id=insertion_target,
                target_id=insertion_target,
                scope="assembly",
                participants=insertion_parts,
                qty_per_unit=graph_quantities.get(insertion_target, 1.0),
                sequence=18,
                reason="PEM/self-clinch hardware in the BOM requires a pressed insertion event",
                route_id=insertion_route_id,
            ))

    # Every non-welded assembly node is an actual assembly event. This replaces the old
    # blanket `handling` operation copied onto every leaf and bought-in line.
    current_decisions = [
        arbitrate_event(event_id, event_claims)
        for event_id, event_claims in claims_by_event.items()
        if event_claims
    ]
    existing_assembly_targets = {
        decision.target_id for decision in current_decisions
        if decision.operation == "assembly" and decision.status == REQUIRED
    }
    welded_targets = {
        decision.target_id for decision in current_decisions
        if decision.operation == "welding" and decision.status == REQUIRED
    }
    for node in graph["nodes"]:
        # WELDING REPLACES THE JOINING STEP, NOT THE FINAL PACK.
        #
        # Excluding every welded parent is right for an INTERMEDIATE assembly -- welding
        # 12120-01-02M to -03M IS how 101 gets assembled, and a separate assemble event on
        # top of it would charge the same work twice.
        #
        # It is wrong for the TOP assembly, which is the thing that ships. 2085-GA owns the
        # weld, so it received no assembly event at all and the sheet carried no
        # Assemble/pack row: a welded bracket that nobody handles or packs. The invariant
        # was right to report handling as unpriced -- there was genuinely nothing charging
        # for it.
        # BOTH GAs SHIP. This asked whether the node is THE top assembly, which on a
        # two-GA enquiry is true of at most one of them — so the other, if it owned a weld,
        # lost its assembly event and the sheet carried no Assemble/pack row for something
        # somebody still has to box. The question is whether this node is a root.
        _is_top = node.part_number in _roots_that_ship(graph)
        if (
            node.kind != "assembly"
            or not node.children
            or node.part_number in existing_assembly_targets
            or (node.part_number in welded_targets and not _is_top)
        ):
            continue
        assembly_route_id = stable_id("route", {
            "operation": "assembly",
            "target_id": node.part_number,
            "participants": [edge.part_number for edge in node.children],
        })
        assembly_event_id = stable_id("decision", {
            "route_id": assembly_route_id,
            "operation": "assembly",
            "scope": "assembly",
            "target_id": node.part_number,
        })
        add_claim(assembly_event_id, make_claim(
            "assembly", REQUIRED, "bom_tree",
            subject_id=node.part_number,
            target_id=node.part_number,
            scope="assembly",
            participants=[edge.part_number for edge in node.children],
            qty_per_unit=node.qty_per_unit,
            sequence=90 if _is_top else 60,
            reason=("the top assembly is packed whatever joined it"
                    if _is_top else "non-welded BOM parent requires one assembly event"),
            route_id=assembly_route_id,
        ))

    # A vague weld word stranded on a parent does not create a second weld when a specific
    # descendant assembly already owns the extracted welding event.
    explicit_weld_targets = {
        decision.target_id
        for event_id, event_claims in claims_by_event.items()
        for decision in [arbitrate_event(event_id, event_claims)]
        if decision.operation == "welding"
        and decision.status == REQUIRED
        and decision.source != "unknown"
    }
    for event_id, event_claims in list(claims_by_event.items()):
        template = event_claims[0]
        if (
            template.operation == "welding"
            and template.status == UNVERIFIED
            and kinds.get(template.target_id) == "assembly"
            and any(
                _is_descendant(
                    weld_target, template.target_id, graph["parents"])
                for weld_target in explicit_weld_targets
            )
        ):
            add_claim(event_id, make_claim(
                "welding", NOT_APPLICABLE, "bom_tree",
                subject_id=template.target_id,
                target_id=template.target_id,
                scope=template.scope,
                participants=template.participants,
                sequence=template.sequence,
                reason="a specific descendant assembly owns the welding event",
                route_id=template.route_id,
            ))

    # ── THE COAT IS ONE SCOPE, NOT ONE DECISION PER NAME ─────────────────────────────
    # 11350: powder decisions landed on both arms, the sub-assembly AND the top assembly,
    # while the bar — whose own sheet says SEE ASSEMBLY DRAWING — got only an UNVERIFIED
    # pointer decision. The priced row then charged four objects including two parents
    # and omitted the largest coated part. Same pattern as the stranded weld above, in
    # two halves:
    #
    # (a) POINTER RESOLUTION. An unverified powder decision targeting an assembly with a
    #     fabricated-leaf participant is the "SEE ASSEMBLY DRAWING" read. When that
    #     assembly's own finish evidence is a REQUIRED powder decision, the member IS
    #     coated: the leaf gets its own required event, and the pointer is recorded as
    #     resolved rather than left blocking.
    # (b) PARENT DEDUP. A required powder decision on an assembly whose fabricated
    #     descendants carry their own required powder is the product's finish statement,
    #     not a second object in the booth — the members' areas are the coat. A welded
    #     assembly whose members are RAW keeps its decision: there the parent IS the
    #     coated object.
    def _powder_required_assembly_targets() -> Set[str]:
        return {
            d.target_id for eid, ecs in claims_by_event.items()
            for d in [arbitrate_event(eid, ecs)]
            if d.operation == "powder_coating" and d.status == REQUIRED
        }

    def _powder_required_scopes() -> Dict[str, str]:
        """target -> scope of its required powder decision. The scope is the
        distinguisher between two legitimate shapes: an EXPLICIT assembly-scope coat is
        a finishing stage the weldment itself goes through (the booth object is the
        assembly — never dedup it, never re-home it onto members), while a part-scope
        statement on an assembly record is the product's finish read off a title block,
        which the members carry."""
        return {
            d.target_id: str(d.scope or "") for eid, ecs in claims_by_event.items()
            for d in [arbitrate_event(eid, ecs)]
            if d.operation == "powder_coating" and d.status == REQUIRED
        }

    # THE POINTER IS VERIFIED, NOT ASSUMED. An unverified assembly-target powder event is
    # only the "SEE ASSEMBLY DRAWING" read when the LEAF'S OWN record carries the
    # deferral wording — the same field the compatibility path read to create the event —
    # and a leaf whose own evidence states a conflicting finish (RAW) is a question for a
    # person, never a mint.
    _PW_POINTER_HINTS = ("SEE ASSEMBLY", "REFER TO ASSEMBLY", "SEE ASSY")

    def _leaf_finish_text(_pn: str) -> str:
        _r = raw.get(_pn) or {}
        return " ".join(
            [str(_r.get("normalized_finish") or ""), str(_r.get("finish") or "")]
            + [str(x) for x in (_r.get("surface_finishes") or [])]).upper()

    def _pw_assembly_stage(_t: str, _scope: str) -> bool:
        """Is this assembly-scope coat a genuine finishing STAGE the assembly itself
        goes through? The scope label alone cannot say: 11350-02's inference and LLM
        claims carry scope "assembly" for a SCREWED product whose members plainly hold
        the coat. The shop's own rule decides — welded components become ONE object on
        the booth line — so the protection needs welding evidence (a required welding
        decision on the target, or weldment wording on its record), not a label."""
        if _scope != "assembly":
            return False
        if _t in welded_targets:
            return True
        _r = raw.get(_t) or {}
        _txt = (str(_r.get("description") or "") + " "
                + str(_r.get("part_number") or "")).upper()
        return "WELD" in _txt

    _pw_scopes = _powder_required_scopes()
    for event_id, event_claims in list(claims_by_event.items()):
        _d = arbitrate_event(event_id, event_claims)
        if (_d.operation == "powder_coating" and _d.status == UNVERIFIED
                and kinds.get(_d.target_id) == "assembly"
                and _d.target_id in _pw_scopes
                and not _pw_assembly_stage(_d.target_id,
                                           _pw_scopes.get(_d.target_id, ""))):
            _minted = []
            for _leaf in (_d.participants or []):
                if kinds.get(_leaf) != "leaf":
                    continue
                _ft = _leaf_finish_text(_leaf)
                if not any(h in _ft for h in _PW_POINTER_HINTS):
                    continue          # this event is not the pointer read for this leaf
                # \bRAW\b, because "SEE ASSEMBLY DRAWING" contains the letters R-A-W —
                # the conflict test must match the word, not the substring.
                if re.search(r"\bRAW\b", _ft):
                    continue          # the leaf's own evidence conflicts — person rules
                _pr_route = stable_id("route", {
                    "operation": "powder_coating", "target_id": _leaf,
                    "participants": [_leaf]})
                _pr_event = stable_id("decision", {
                    "route_id": _pr_route, "operation": "powder_coating",
                    "scope": "part", "target_id": _leaf})
                add_claim(_pr_event, make_claim(
                    "powder_coating", REQUIRED, "bom_tree",
                    subject_id=_leaf, target_id=_leaf, scope="part",
                    participants=[_leaf],
                    qty_per_unit=graph_quantities.get(_leaf, 1.0),
                    sequence=70,
                    reason="the part's sheet defers its finish to the assembly, and "
                           "the assembly's own evidence states the coat — the member "
                           "is coated",
                    route_id=_pr_route,
                ))
                _minted.append(_leaf)
            if _minted:
                add_claim(event_id, make_claim(
                    "powder_coating", NOT_APPLICABLE, "bom_tree",
                    subject_id=_d.target_id, target_id=_d.target_id, scope=_d.scope,
                    participants=list(_d.participants or []),
                    sequence=_d.sequence,
                    reason="pointer resolved: the assembly's finish corroborates the "
                           "member's coat, minted as the member's own requirement",
                    route_id=_d.route_id or "",
                ))

    # (a2) THE LEAF POINTER WITHOUT ITS EVENT. The compatibility path creates the
    # unverified assembly-target event only when the deferral sits in normalized_finish;
    # a leaf whose SEE ASSEMBLY wording lives in surface_finishes never got one — the
    # 15:36 bar had NO powder decision at all, so pass (a) had nothing to resolve. The
    # pointer is the leaf's own record either way: walk fabricated leaves directly —
    # deferral wording present, no RAW conflict, no powder decision of their own — and
    # when an ancestor assembly carries required powder, the member is coated.
    _pw_scopes = _powder_required_scopes()
    _pw_decided = {
        d.target_id for eid, ecs in claims_by_event.items()
        for d in [arbitrate_event(eid, ecs)]
        if d.operation == "powder_coating"
    }
    for _pn, _kind in list(kinds.items()):
        if _kind != "leaf" or _pn in _pw_decided:
            continue
        _ft = _leaf_finish_text(_pn)
        if not any(h in _ft for h in _PW_POINTER_HINTS):
            continue
        if re.search(r"\bRAW\b", _ft):
            continue
        if not any(kinds.get(a) == "assembly"
                   and not _pw_assembly_stage(a, _pw_scopes.get(a, ""))
                   and _is_descendant(_pn, a, graph["parents"])
                   for a in _pw_scopes):
            continue
        _pr_route = stable_id("route", {
            "operation": "powder_coating", "target_id": _pn, "participants": [_pn]})
        _pr_event = stable_id("decision", {
            "route_id": _pr_route, "operation": "powder_coating",
            "scope": "part", "target_id": _pn})
        add_claim(_pr_event, make_claim(
            "powder_coating", REQUIRED, "bom_tree",
            subject_id=_pn, target_id=_pn, scope="part",
            participants=[_pn],
            qty_per_unit=graph_quantities.get(_pn, 1.0),
            sequence=70,
            reason="the part's sheet defers its finish to the assembly, and the "
                   "assembly's own evidence states the coat — the member is coated",
            route_id=_pr_route,
        ))

    # PARENT DEDUP NEEDS COMPLETE COVERAGE. `any` coated member was the overreach the
    # probe found: a welded frame with one coated child and one RAW child lost the
    # frame's coat entirely. The parent's decision stands down only when EVERY
    # fabricated leaf under it carries its own required powder — that is the finish
    # statement fully delegated. Mixed evidence is a coating-scope question for a
    # person: the parent keeps its charge and the question is recorded, because a
    # deleted operation cannot be reviewed and an over-charge can.
    _pw_required = _powder_required_assembly_targets()
    for event_id, event_claims in list(claims_by_event.items()):
        _d = arbitrate_event(event_id, event_claims)
        if not (_d.operation == "powder_coating" and _d.status == REQUIRED
                and kinds.get(_d.target_id) == "assembly"):
            continue
        if _pw_assembly_stage(_d.target_id, str(_d.scope or "")):
            # A WELDED assembly's coat is a finishing stage the assembly itself goes
            # through — the reviewer's "separately specified stage". Members' deferring
            # words corroborate it; complete coverage cannot stand it down. A scope
            # label without welding evidence is a title-block statement, not a stage.
            continue
        _leaf_desc = {pn for pn, k in kinds.items()
                      if k == "leaf" and _is_descendant(pn, _d.target_id,
                                                        graph["parents"])}
        _coated_desc = {pn for pn in _leaf_desc if pn in _pw_required}
        if _leaf_desc and _coated_desc == _leaf_desc:
            add_claim(event_id, make_claim(
                "powder_coating", NOT_APPLICABLE, "bom_tree",
                subject_id=_d.target_id, target_id=_d.target_id, scope=_d.scope,
                participants=list(_d.participants or []),
                sequence=_d.sequence,
                reason="the assembly's finish is carried by its coated members' own "
                       "requirements — one coat, not a second object in the booth",
                route_id=_d.route_id or "",
            ))
        elif _coated_desc:
            issues.append({
                "code": "powder_scope_mixed_members",
                "part_number": _d.target_id,
                "coated_members": sorted(_coated_desc),
                "uncoated_members": sorted(_leaf_desc - _coated_desc),
                "message": (f"powder is required on {_d.target_id} AND on "
                            f"{', '.join(sorted(_coated_desc))} while "
                            f"{', '.join(sorted(_leaf_desc - _coated_desc))} carry no "
                            f"coat of their own — the scope is genuinely mixed and a "
                            f"person must rule whether the assembly coat covers the "
                            f"coated members (drop their lines) or is a separate stage "
                            f"(keep both). Both charges stand until ruled."),
            })

    # Hierarchy is a source claim too. It records why leaf work is inapplicable to a parent
    # instead of deleting evidence from whichever record happens to be in hand.
    for event_id, event_claims in list(claims_by_event.items()):
        template = event_claims[0]
        if (
            template.operation in LEAF_ONLY_OPERATIONS
            and kinds.get(template.target_id) == "assembly"
        ):
            add_claim(event_id, make_claim(
                template.operation, NOT_APPLICABLE, "bom_tree",
                subject_id=template.target_id,
                target_id=template.target_id,
                scope=template.scope,
                participants=template.participants,
                sequence=template.sequence,
                reason="assembly parent has no independently measured fabricated leaf",
                route_id=template.route_id,
            ))

    # Tube stock is cut by the tube process. A page-level Laser word on a CHS/RHS record is
    # not a second profile-cutting event. Keep the positive claim in the audit trail and let
    # the deterministic stock-form claim rule it not applicable.
    for event_id, event_claims in list(claims_by_event.items()):
        template = event_claims[0]
        raw_part = raw.get(template.target_id) or {}
        section = raw_part.get("section_stock") or {}
        profile = str(section.get("profile_form") or "").upper()
        description = str(raw_part.get("description") or "").upper()
        is_tube = bool(
            profile in {"CHS", "RHS", "SHS", "TUBE"}
            or any(word in description for word in (
                "TUBE", "CHS", "RHS", "SHS", "BOX SECTION",
            ))
        )
        if (
            is_tube
            and template.scope == "part"
            and template.operation in TUBE_INAPPLICABLE_OPERATIONS
        ):
            add_claim(event_id, make_claim(
                template.operation, NOT_APPLICABLE, "drawing_deterministic",
                subject_id=template.target_id,
                target_id=template.target_id,
                scope="part",
                participants=[template.target_id],
                sequence=template.sequence,
                reason="section stock is cut by the tube process, not sheet profiling",
                route_id=template.route_id,
            ))

    # SOLID BAR AND ACRYLIC — the other two stock forms that cannot have work done to them.
    #
    # These rules already existed, inside wb_populate's legacy labour loop. The canonical
    # cutover replaced that loop wholesale (`for pe in ([] if _canonical_cutover else
    # labour_parts)`), so they stopped running the moment the cutover was switched on, and
    # nothing failed — a gate nobody asks reports nothing. A solid 8mm round bar came back
    # out of the canonical path carrying a Laser (Metal) row, which is precisely the misread
    # (diameter taken for sheet thickness) the wire rules were written to catch.
    #
    # Expressed the same way the tube block above expresses it: a deterministic claim that
    # the operation is NOT APPLICABLE, so the positive claim stays in the audit trail and
    # the reason travels with the decision. A route line that simply vanishes is
    # indistinguishable from one that was never read.
    #
    # The rules themselves are in stock_form_rules, read by both the compiler and the
    # workbook renderer — a second copy here is how one of them goes quietly stale.
    from stock_form_rules import impossibility_reason
    from finish_rules import finish_contradiction
    for event_id, event_claims in list(claims_by_event.items()):
        template = event_claims[0]
        # A FINISH IS GATED ON A PART AND ON AN ASSEMBLY ALIKE.
        #
        # Powder-coating a weldment is an ASSEMBLY-scope op — the whole object goes in the oven
        # — so 7332-01-101's powder claim is scope 'assembly', and a gate that only looked at
        # scope 'part' never saw it. The leaf 008 (part scope) correctly dropped powder for a
        # PLATED finish while the weldment 101, PLATED on its own record, kept a £15.92 P.Coat
        # row. The stock-form impossibility stays part-only (an assembly has no stock form), but
        # the FINISH contradiction now runs for an assembly too.
        if template.scope not in ("part", "assembly"):
            continue
        # THE MERGED RECORD, NOT THE RAW ONE.
        #
        # build_part_graph already reconciles the two extraction paths: `records` is the
        # extracted BOM/parts record overlaid with every non-empty raw value. Reading `raw`
        # here meant a stock form or finish that only the extract carried bypassed the gate
        # entirely — the rule was correct and simply never saw the evidence, which is the
        # same failure mode as the gate the cutover switched off.
        #
        # AND A GATE THAT CANNOT FIND THE RECORD MUST STILL LOOK. On 10975-02 the tape's
        # wrapped BOM name shattered ("CELL TAPE^10975-02-" vs the model's full configured
        # name), the exact-key lookup returned {}, material read "", and powder coating on
        # an ACRYLIC-labelled foam tape sailed through every rule written to stop it. When
        # the key misses, a unique record whose squashed spelling contains (or is contained
        # by) the target's is the same part under a fuller name — found, not guessed: the
        # fallback demands uniqueness and ten matching characters, or it stays empty.
        record = graph["records"].get(template.target_id) or \
            _record_by_squashed_key(graph["records"], template.target_id) or {}
        # UNRESOLVED OWNERSHIP FAILS VISIBLY. A part-scope claim whose record cannot be
        # found — even under a fuller spelling — is a decision the gates never examined,
        # and that is a fact the run must state rather than a silence: the reviewer's
        # rule is "missing records make decisions unverified", never "missing records
        # skip the safety checks quietly".
        if not record and template.scope == "part":
            issues.append({
                "code": "route_claim_without_record",
                "identity": template.target_id,
                "operation": template.operation,
                "detail": (f"{template.operation} is claimed on {template.target_id}, but "
                           f"no part record could be found under that name or any fuller "
                           f"spelling of it — the material, finish and stock-form gates "
                           f"never examined this decision. Resolve the identity before "
                           f"trusting the route."),
            })
        # THE STATED FINISH IS ASKED FIRST, because its reason is the more useful one.
        #
        # A FINISH THE DRAWING STATES OUTRANKS A FINISH THE LEGEND IMPLIES. These packs carry a
        # range-wide specification legend for the whole product family, which is how a lacquered
        # timber panel came back with a P.Coat row and a powder-coated face with a Diamond
        # Polish row. weldment_finish_for_gate reads the part's own finish, or a weldment
        # parent's inherited from its members. finish_contradiction returns None for a
        # non-finish op, so this is a no-op on welding/cutting/etc.
        reason = finish_contradiction(
            template.operation,
            weldment_finish_for_gate(record, template.target_id, graph))
        if not reason and template.scope == "part":
            # The physical stock-form rule is part-only — it catches the panel whose finish
            # nobody read (12422-24's Egger laminate, no finish family, oven would destroy it).
            # A bar is recognised from its own drawing's bar schedule, upstream of costing, and
            # only where no flat pattern was detected — a part with a flat blank is not a bar.
            stock_form = "wire" if (
                record.get("_bar_recognised")
                or record.get("bar_schedule")
            ) else str(record.get("stock_form")
                       or (record.get("material_estimate") or {}).get("stock_form") or "")
            material = str(
                record.get("normalized_material") or record.get("material") or "")
            reason = impossibility_reason(template.operation, stock_form, material)
        if not reason and template.scope == "part":
            reason = _unsupported_drill_reason(template, record)
        if not reason:
            continue
        add_claim(event_id, make_claim(
            template.operation, NOT_APPLICABLE, "drawing_deterministic",
            subject_id=template.target_id,
            target_id=template.target_id,
            scope=template.scope,
            participants=template.participants or [template.target_id],
            sequence=template.sequence,
            reason=reason,
            route_id=template.route_id,
        ))

        # THE PRESS BRAKE IS WHAT IS IMPOSSIBLE, NOT THE BEND.
        #
        # Ruling folding out on a tube removed the only claim wb_populate._TUBE_OP_REMAP had to
        # relabel as Tubebend (TBEN), and under the cutover a labour row exists only where a
        # REQUIRED decision does — so the bend came off the sheet entirely and 7332-01's leg was
        # bent for free (£8.70 of labour lost between two runs, labour £36.00 -> £27.30). The
        # drawing's intent was real; only the process was wrong. Raise the tube bender's own
        # operation in its place, exactly as the cut is remapped rather than dropped. Fold,
        # line-bend and punch stay impossible on a tube; this adds the one that IS possible.
        # Keyed on the stock form, never on a part number.
        if (template.scope == "part"
                and clean_operation(template.operation) in TUBE_BEND_SOURCE_OPERATIONS
                and _record_stock_form(record) == "tube"):
            tube_route_id = (
                f"{template.route_id}:tubebend" if template.route_id
                else stable_id("route", {"parent_decision": event_id,
                                         "operation": "tubebend"})
            )
            tube_event_id = stable_id("decision", {
                "route_id": tube_route_id,
                "operation": "tubebend",
                "scope": "part",
                "target_id": template.target_id,
            })
            if tube_event_id not in claims_by_event:
                add_claim(tube_event_id, make_claim(
                    "tubebend", REQUIRED, "drawing_deterministic",
                    subject_id=template.target_id,
                    target_id=template.target_id,
                    scope="part",
                    participants=[template.target_id],
                    qty_per_unit=template.qty_per_unit,
                    sequence=template.sequence,
                    reason=("the drawing states a bend and the stock form is tube — bent on the "
                            "tube bender, not the press brake"),
                    route_id=tube_route_id,
                ))

    decisions = [
        arbitrate_event(event_id, claims)
        for event_id, claims in claims_by_event.items()
        if claims
    ]

    # ── A GENERIC ASSEMBLE DOES NOT REPEAT THE JOINING WE ALREADY NAMED ────────────────
    #
    # 11350 charged 11350-01-101 twice: a hardware_insertion that presses the PEM studs into
    # the bar, and a generic assembly on the same node. The insertion IS how that
    # sub-assembly comes into existence — its children are the bar and the studs and nothing
    # else — so the second row pays to make it a second time.
    #
    # NARROW BY CONSTRUCTION. This only fires when every child of the target is already
    # accounted for by the specific joining operation or is the part being joined TO. An
    # assembly with any other child still needs its generic event, because something has to
    # put that child on. Ruled out, never deleted: the decision keeps its id and carries the
    # reason, so the estimator can see the judgement and reverse it.
    _specific_by_target: Dict[str, List[OperationDecision]] = {}
    for _d in decisions:
        if _d.status == REQUIRED and _d.operation in SPECIFIC_JOINING_OPERATIONS:
            _specific_by_target.setdefault(_d.target_id, []).append(_d)
    for _d in decisions:
        if _d.status != REQUIRED or _d.operation != "assembly":
            continue
        # NEVER THE TOP ASSEMBLY. It is the thing that ships, and it is packed however it
        # was joined — 2085-GA owned its weld, lost its assembly event, and the sheet
        # carried no Assemble/pack row for a bracket somebody still has to box.
        if _d.target_id in _roots_that_ship(graph):
            continue
        _specific = _specific_by_target.get(_d.target_id) or []
        if not _specific:
            continue
        _kids = set(graph["children"].get(_d.target_id) or {})
        if not _kids:
            continue
        _covered: Set[str] = set()
        for _s in _specific:
            _covered |= {str(p) for p in (_s.participants or [])}
        _remaining = _kids - _covered
        # What is left must be the thing being joined TO — one part, already a participant.
        if len(_remaining) > 1:
            continue
        _d.status = NOT_APPLICABLE
        _d.reason = (
            f"{', '.join(sorted({s.operation for s in _specific}))} on {_d.target_id} is how "
            f"this sub-assembly is made: its children are "
            f"{', '.join(sorted(_kids))} and that operation already covers them. A generic "
            f"assemble here would charge for building it twice.")
        _d.field_provenance["status"] = "specific_joining_covers_this_assembly"

    for decision in decisions:
        if (
            decision.status == REQUIRED
            and decision.sequence is None
            and decision.operation in DEFAULT_OPERATION_SEQUENCE
        ):
            decision.sequence = float(DEFAULT_OPERATION_SEQUENCE[decision.operation])
            decision.field_provenance["sequence"] = "shop_sequence_rule"
    decisions.sort(key=lambda item: (
        item.sequence is None,
        item.sequence if item.sequence is not None else 10**9,
        item.operation,
        item.target_id,
        item.decision_id,
    ))

    return {
        "schema": ROUTE_SCHEMA,
        "mode": "shadow",
        "nodes": [asdict(node) for node in graph["nodes"]],
        "decisions": [asdict(decision) for decision in decisions],
        "issues": issues,
        "counts": {
            "nodes": len(graph["nodes"]),
            "decisions": len(decisions),
            REQUIRED: sum(item.status == REQUIRED for item in decisions),
            RULED_OUT: sum(item.status == RULED_OUT for item in decisions),
            NOT_APPLICABLE: sum(
                item.status == NOT_APPLICABLE for item in decisions),
            UNVERIFIED: sum(item.status == UNVERIFIED for item in decisions),
        },
    }


def project_priced_route(
    route_graph: Mapping[str, Any],
    part_estimates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Compare decisions with legacy costs without altering either."""
    estimates = _raw_parts(part_estimates)
    rows: List[Dict[str, Any]] = []
    issues = list(route_graph.get("issues") or [])
    memberships: Dict[Tuple[str, str], Set[str]] = {}

    for decision in route_graph.get("decisions") or []:
        if not isinstance(decision, Mapping):
            continue
        operation = clean_operation(decision.get("operation"))
        target_id = clean_part_number(decision.get("target_id"))
        participants = [
            clean_part_number(item)
            for item in (decision.get("participants") or [])
            if clean_part_number(item)
        ]
        status = str(decision.get("status") or UNVERIFIED)

        if status != REQUIRED:
            # A negative decision with a legacy cost is a direct resurrection signal.
            for part_id in dict.fromkeys([target_id] + participants):
                costs = ((estimates.get(part_id, {}).get("labour_estimate") or {})
                         .get("costs_gbp") or {})
                if operation in costs:
                    issues.append({
                        "code": "forbidden_decision_priced",
                        "decision_id": decision.get("decision_id"),
                        "status": status,
                        "part_number": part_id,
                        "operation": operation,
                        "legacy_cost_gbp": number(costs.get(operation), 0.0) or 0.0,
                    })
            continue

        candidate_ids = (
            [target_id]
            if decision.get("scope") == "part"
            else list(dict.fromkeys([target_id] + participants))
        )
        legacy_cost_parts = []
        for part_id in candidate_ids:
            costs = ((estimates.get(part_id, {}).get("labour_estimate") or {})
                     .get("costs_gbp") or {})
            if operation not in costs:
                continue
            legacy_cost_parts.append({
                "part_number": part_id,
                "legacy_cost_gbp": number(costs.get(operation), 0.0) or 0.0,
            })
            memberships.setdefault(
                (part_id, operation), set()).add(str(decision.get("decision_id")))

        price_status = (
            "required_unpriced"
            if not legacy_cost_parts
            else "legacy_cost_available"
        )
        if price_status == "required_unpriced":
            issues.append({
                "code": "required_operation_unpriced",
                "decision_id": decision.get("decision_id"),
                "target_id": target_id,
                "operation": operation,
            })
        if decision.get("scope") == "assembly" and len(legacy_cost_parts) > 1:
            issues.append({
                "code": "assembly_operation_costed_on_multiple_participants",
                "decision_id": decision.get("decision_id"),
                "target_id": target_id,
                "operation": operation,
                "legacy_cost_parts": [
                    item["part_number"] for item in legacy_cost_parts],
            })

        rows.append({
            "decision_id": decision.get("decision_id"),
            "operation": operation,
            "target_id": target_id,
            "scope": decision.get("scope"),
            "participants": participants,
            "qty_per_unit": decision.get("qty_per_unit"),
            "sequence": decision.get("sequence"),
            "price_status": price_status,
            "legacy_cost_gbp": round(sum(
                item["legacy_cost_gbp"] for item in legacy_cost_parts), 6),
            "legacy_cost_parts": legacy_cost_parts,
        })

    for (part_id, operation), decision_ids in memberships.items():
        if len(decision_ids) > 1:
            issues.append({
                "code": "legacy_cost_maps_multiple_decisions",
                "part_number": part_id,
                "operation": operation,
                "decision_ids": sorted(decision_ids),
            })

    canonical_memberships = {
        (clean_part_number(part_id), clean_operation(decision.get("operation")))
        for decision in route_graph.get("decisions") or []
        if isinstance(decision, Mapping) and decision.get("status") == REQUIRED
        for part_id in (
            [decision.get("target_id")] + list(decision.get("participants") or [])
        )
        if clean_part_number(part_id)
    }
    for part_id, estimate in estimates.items():
        costs = ((estimate.get("labour_estimate") or {}).get("costs_gbp") or {})
        for operation, cost in costs.items():
            key = (part_id, clean_operation(operation))
            if key not in canonical_memberships:
                issues.append({
                    "code": "legacy_cost_without_canonical_decision",
                    "part_number": part_id,
                    "operation": clean_operation(operation),
                    "legacy_cost_gbp": number(cost, 0.0) or 0.0,
                })

    return {
        "schema": PRICED_ROUTE_SCHEMA,
        "mode": "shadow",
        "route_schema": route_graph.get("schema"),
        "nodes": list(route_graph.get("nodes") or []),
        "decisions": list(route_graph.get("decisions") or []),
        "priced_route_rows": rows,
        "issues": issues,
        "counts": {
            "priced_route_rows": len(rows),
            "required_unpriced": sum(
                row["price_status"] == "required_unpriced" for row in rows),
            "forbidden_priced": sum(
                issue.get("code") == "forbidden_decision_priced"
                for issue in issues),
            "assembly_multi_cost": sum(
                issue.get("code")
                == "assembly_operation_costed_on_multiple_participants"
                for issue in issues),
            "legacy_orphans": sum(
                issue.get("code") == "legacy_cost_without_canonical_decision"
                for issue in issues),
        },
    }


__all__ = [
    "ROUTE_SCHEMA", "PRICED_ROUTE_SCHEMA",
    "REQUIRED", "RULED_OUT", "NOT_APPLICABLE", "UNVERIFIED",
    "PartNode", "OperationClaim", "OperationDecision",
    "build_part_graph", "make_claim", "arbitrate_event",
    "interleave_artefact_identities", "quarantine_interleave_artefacts",
    "fold_bom_row_fragments",
    "compile_job_route", "project_priced_route",
    "apply_canonical_evidence_to_parts",
    "refresh_canonical_route_after_reconciliation",
]
