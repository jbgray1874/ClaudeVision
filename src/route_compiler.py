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
})
TUBE_INAPPLICABLE_OPERATIONS = frozenset({
    "laser_cutting", "punch", "guillotine",
})

CONFIDENCE_VALUE = {"low": 0.25, "medium": 0.60, "high": 0.90}


def clean_part_number(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def clean_operation(value: Any) -> str:
    return re.sub(
        r"_+", "_",
        re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()),
    ).strip("_")


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
        "source": source or "unknown",
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
        source=str(source or "unknown"),
        source_rank=rank(str(source or "unknown")),
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


def build_part_graph(
    parts: Sequence[Mapping[str, Any]],
    llm_extract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build canonical nodes and hierarchy edges from the whole job."""
    llm_extract = llm_extract or {}
    raw = _raw_parts(parts)
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
    identities: Set[str] = set(raw) | set(children) | set(parents)
    if top_id:
        identities.add(top_id)

    nodes: List[PartNode] = []
    for identity in sorted(identities):
        record = raw.get(identity) or {}
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
            record.get("is_bought_in")
            or "BOUGHT" in type_text
            or identity.startswith("BI-")
        )
        kind = "assembly" if is_assembly else ("bought_in" if is_bought_in else "leaf")
        nodes.append(PartNode(
            part_number=identity,
            description=str(record.get("description") or ""),
            kind=kind,
            parents=sorted(parents.get(identity) or []),
            children=[
                ChildEdge(part_number=child_id, qty=qty)
                for child_id, qty in sorted((children.get(identity) or {}).items())
            ],
            evidence={
                "raw_record_present": identity in raw,
                "is_sub_assembly": bool(record.get("is_sub_assembly")),
                "is_assembly_parent": bool(record.get("is_assembly_parent")),
            },
        ))

    return {
        "nodes": nodes,
        "raw": raw,
        "parents": parents,
        "children": {key: set(value) for key, value in children.items()},
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
    claims_by_event: Dict[str, List[OperationClaim]] = {}
    explicit_memberships: Dict[Tuple[str, str], Set[str]] = {}
    issues: List[Dict[str, Any]] = []

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
                qty_per_unit=route.get("qty_per_unit"),
                sequence=route.get("sequence"),
                confidence=route.get("confidence"),
                reason=route.get("notes") or route.get("description"),
                route_id=route_id,
            )
            add_claim(event_id, claim)
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
        quantities = part.get("operation_qty_per_unit") or {}
        sequences = part.get("operation_sequence") or {}

        seen: Set[Tuple[str, str]] = set()
        for field_name, fallback_source in (
            ("textual_operations", "unknown"),
            ("operations", "unknown"),
            ("inferred_operations", "inference"),
        ):
            for raw_operation in part.get(field_name) or []:
                operation = clean_operation(raw_operation)
                if not operation or (field_name, operation) in seen:
                    continue
                seen.add((field_name, operation))
                source = str(operation_sources.get(operation) or fallback_source)
                event_ids = sorted(
                    explicit_memberships.get((operation, part_number)) or [])
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
                    event_ids = [stable_id("decision", {
                        "origin": "compatibility",
                        "operation": operation,
                        "scope": scope,
                        "target_id": part_number,
                    })]
                for event_id in event_ids:
                    template = (claims_by_event.get(event_id) or [None])[0]
                    target_id = template.target_id if template else part_number
                    scope = template.scope if template else scopes.get(operation, "part")
                    route_id = template.route_id if template else ""
                    claim_status = REQUIRED
                    if (
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
                        qty_per_unit=quantities.get(operation),
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

    decisions = [
        arbitrate_event(event_id, claims)
        for event_id, claims in claims_by_event.items()
        if claims
    ]
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
