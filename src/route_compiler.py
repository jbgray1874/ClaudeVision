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
ASSEMBLY_EVENT_OPERATIONS = frozenset({
    "welding", "dress_welds", "powder_coating", "assembly", "handling",
    "hardware_insertion",
})
TUBE_INAPPLICABLE_OPERATIONS = frozenset({
    "laser_cutting", "punch", "guillotine",
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


def clean_part_number(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


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
    """Canonical BOM identities and classifications read by the full-job extract."""
    result: Dict[str, Dict[str, Any]] = {}
    for pool_name in ("bom", "parts"):
        for item in llm_extract.get(pool_name) or []:
            if not isinstance(item, Mapping):
                continue
            identity = clean_part_number(item.get("part_number"))
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
    return result


def _description_tokens(value: Any) -> Set[str]:
    ignored = {"THE", "AND", "FOR", "WITH", "PART", "STD", "MM"}
    return {
        token for token in re.findall(r"[A-Z0-9]+", str(value or "").upper())
        if len(token) >= 3 and token not in ignored and not re.fullmatch(r"M\d+", token)
    }


def _bought_in_record(record: Mapping[str, Any]) -> bool:
    return bool(
        record.get("is_bought_in")
        or "bought_in" in {
            str(item).strip().lower()
            for item in (record.get("page_roles") or [])
        }
        or str(record.get("material_family") or "").strip().lower() == "bought_in"
    )


def _drawing_code_aliases(identities: Iterable[str]) -> Dict[str, str]:
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

    aliases: Dict[str, str] = {}
    for identity in sorted(known):
        # Same part, two spellings: bind the shorter onto the drawing's own.
        _canon = _by_squash.get(_squash(identity))
        if _canon and _canon != identity:
            aliases[identity] = _canon
            continue
        for _t in alias_targets(identity):
            _hit = _by_squash.get(_squash(_t.strip().upper()))
            if _hit and _hit != identity:
                aliases[identity] = _hit
                break
    return aliases


def _raw_identity_aliases(
    raw: Mapping[str, Mapping[str, Any]],
    extracted: Mapping[str, Mapping[str, Any]],
) -> Dict[str, str]:
    """Reconcile generated BI-* identities with the explicit BOM code they came from."""
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
    return aliases


def build_part_graph(
    parts: Sequence[Mapping[str, Any]],
    llm_extract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build canonical nodes and hierarchy edges from the whole job."""
    llm_extract = llm_extract or {}
    raw_original = _raw_parts(parts)
    extracted = _extract_part_records(llm_extract)
    aliases = _raw_identity_aliases(raw_original, extracted)
    # The drawing's BOM is the naming authority; the files carry the same parts under the
    # modelled code. Applied after the BI-* reconciliation and only where the target already
    # exists, so it can merge a duplicate but never invent an identity.
    for _src, _dst in _drawing_code_aliases(
            set(raw_original) | set(extracted)).items():
        aliases.setdefault(_src, _dst)
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

    for assembly in llm_extract.get("assemblies") or []:
        if not isinstance(assembly, Mapping):
            continue
        parent_id = clean_part_number(assembly.get("part_number"))
        if not parent_id:
            continue
        children.setdefault(parent_id, {})
        for edge in assembly.get("children") or []:
            if not isinstance(edge, Mapping):
                continue
            child_id = clean_part_number(edge.get("part_number"))
            if not child_id:
                continue
            qty = number(edge.get("qty"), 1.0) or 1.0
            children[parent_id][child_id] = qty
            parents.setdefault(child_id, set()).add(parent_id)

    top = llm_extract.get("top_assembly") or {}
    top_id = clean_part_number(top.get("part_number") if isinstance(top, Mapping) else top)
    if not top_id:
        roots = sorted(set(children) - set(parents))
        if len(roots) == 1:
            top_id = roots[0]
        else:
            ga_roots = [item for item in roots if re.search(r"(?:^|-)GA$", item)]
            if len(ga_roots) == 1:
                top_id = ga_roots[0]
    identities: Set[str] = set(raw) | set(extracted) | set(children) | set(parents)
    if top_id:
        identities.add(top_id)

    quantities: Dict[str, float] = {}

    def add_descendants(identity: str, factor: float, path: Set[str]) -> None:
        if identity in path:
            return
        quantities[identity] = quantities.get(identity, 0.0) + factor
        next_path = set(path)
        next_path.add(identity)
        for child_id, child_qty in (children.get(identity) or {}).items():
            add_descendants(child_id, factor * child_qty, next_path)

    if top_id:
        add_descendants(top_id, 1.0, set())
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
            },
        ))

    graph_issues = []
    if top_id:
        for node in nodes:
            if (
                node.part_number != top_id
                and not node.parents
                and node.part_number not in {"PACKAGING", "DELIVERY", "POWDER"}
            ):
                graph_issues.append({
                    "code": "bom_node_disconnected",
                    "part_number": node.part_number,
                    "kind": node.kind,
                    "description": node.description,
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
        "top_assembly": top_id,
    }


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
    if len(values) > 1:
        return None, None, {
            "field": field_name,
            "rank": best_rank,
            "values": [repr(value) for value in sorted(values, key=repr)],
            "sources": sorted({item[0].source for item in strongest}),
        }
    winner, value = max(
        strongest,
        key=lambda item: (
            item[0].confidence if item[0].confidence is not None else -1.0,
            item[0].claim_id,
        ),
    )
    if field_name == "participants":
        value = list(value)
    return value, winner.source, None


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

    if len(statuses) > 1:
        status = UNVERIFIED
        conflicts.append({
            "field": "status",
            "rank": strongest_rank,
            "values": sorted(statuses),
            "sources": sorted({claim.source for claim in strongest_status_claims}),
        })
        status_winner = max(
            strongest_status_claims,
            key=lambda claim: (
                claim.confidence if claim.confidence is not None else -1.0,
                claim.claim_id,
            ),
        )
    else:
        status = next(iter(statuses))
        same_status = [
            claim for claim in strongest_status_claims if claim.status == status
        ]
        status_winner = max(
            same_status,
            key=lambda claim: (
                claim.confidence if claim.confidence is not None else -1.0,
                claim.claim_id,
            ),
        )

    metadata: Dict[str, Any] = {}
    provenance: Dict[str, str] = {}
    for field_name in ("route_id", "target_id", "scope", "participants",
                       "qty_per_unit", "sequence"):
        value, source, conflict = _pick_metadata(claims, field_name)
        if conflict:
            conflicts.append(conflict)
            continue
        metadata[field_name] = value
        if source:
            provenance[field_name] = source

    if conflicts:
        status = UNVERIFIED

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
        reason = "conflicting claims require estimator resolution"

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
        confidence=status_winner.confidence,
        reason=reason,
        field_provenance=provenance,
        conflicts=conflicts,
        claims=[asdict(claim) for claim in sorted(
            claims, key=lambda item: (-item.source_rank, item.claim_id))],
    )


def compile_job_route(
    parts: Sequence[Mapping[str, Any]],
    llm_extract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile every route source into one job-level decision graph."""
    llm_extract = llm_extract or {}
    graph = build_part_graph(parts, llm_extract)
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
        for field_name, fallback_source in (
            ("textual_operations", "unknown"),
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
        _is_top = node.part_number == graph["top_assembly"]
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
            sequence=90 if node.part_number == graph["top_assembly"] else 60,
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
    from finish_rules import finish_contradiction, stated_finish
    for event_id, event_claims in list(claims_by_event.items()):
        template = event_claims[0]
        if template.scope != "part":
            continue
        # THE MERGED RECORD, NOT THE RAW ONE.
        #
        # build_part_graph already reconciles the two extraction paths: `records` is the
        # extracted BOM/parts record overlaid with every non-empty raw value. Reading `raw`
        # here meant a stock form or finish that only the extract carried bypassed the gate
        # entirely — the rule was correct and simply never saw the evidence, which is the
        # same failure mode as the gate the cutover switched off.
        record = graph["records"].get(template.target_id) or {}
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
        if not reason:
            # A FINISH THE DRAWING STATES OUTRANKS A FINISH THE LEGEND IMPLIES.
            #
            # The other half of the gates the cutover switched off. These packs carry a
            # range-wide specification legend that applies to the customer's whole product
            # family, which is how a lacquered timber panel came back out of the canonical
            # path with a P.Coat row and a powder-coated face with a Diamond Polish row.
            # Fires only where the part's own finish is stated and unambiguous.
            reason = finish_contradiction(
                template.operation, stated_finish(record))
        if not reason:
            continue
        add_claim(event_id, make_claim(
            template.operation, NOT_APPLICABLE, "drawing_deterministic",
            subject_id=template.target_id,
            target_id=template.target_id,
            scope="part",
            participants=[template.target_id],
            sequence=template.sequence,
            reason=reason,
            route_id=template.route_id,
        ))

    decisions = [
        arbitrate_event(event_id, claims)
        for event_id, claims in claims_by_event.items()
        if claims
    ]
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
    "compile_job_route", "project_priced_route",
]
