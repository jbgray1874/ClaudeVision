"""What a read returned reaches the charged cells of the calculated workbook, or the release is
held (D-596).

THE REQUIREMENT CLASS THE LLM READ WAS MISSING. final_charge_contract proves a section a
drawing prints reaches the sheet; material_charge_contract does the same for blanks and bought
items. Neither knew what the model READ: 0320730's 17:15 book read a drilled hole, a polished
nickel-chrome finish and TIG welds, and lost all three between the read and the sheet while
buying a ticket holder and four screws nobody named. This is the read's own class, in the same
shape and at the same boundary — after Excel, against the calculated rows, the saved file's
cells where it is to hand, raised by a BLOCKING invariant:

    read item -> record -> route and price -> calculated workbook charge

THE LEDGER (captured at the read, `summary["read_ledger"]`). Every item the read returned gets
an identity: each part (R1, R2 …), its quantity, material and size, each feature (folds,
cut-outs, banded edges) and each operation (R2.op.saw), the unit's operations (U.op.welding),
each thing named as not visible (NV1), each print set (PS1), and the finish, polish and weld
process the read or the brief states (S.finish, S.polish, S.weld_process). The raw answer is
kept whole on `concept_read.raw_response` with its sha256 here, so the ledger can always be
checked against the words the model sent.

THE FINAL STATE (audited after Excel, `summary["read_charge_result"]`). Every piece of work
ends as exactly one of:

    charged     a calculated row on the sheet names it, with money (and, for work, hours) on
                it, at the quantity the record holds
    covered     another calculated charge carries it, and the ledger names that charge
    excluded    a person ruled it out for this job, with the reason (answers file read_rulings)
    unresolved  none of these — the release is held

A fact the read gave (a quantity, a material, a size) is CARRIED to the charged line or
CORRECTED by a named source — the brief, the estimator, a measurement — with the read's value,
the value charged and who changed it kept side by side. A change nobody can name is unresolved.

ENGINE ALLOWANCES, APART. Every calculated charge no read item explains is listed as the
engine's, with its basis from config.ENGINE_ALLOWANCE_BASIS. One the shop stated for another
product, a purchase nothing names, or a charge with no stated basis holds the release until a
person confirms it for this job — a flag does not make it this job's time. The minutes a unit
and the hours at every quantity asked for are on the finding.

Faithful does not mean accepting the model: its mistakes are corrected and the correction
shown. Read-only: nothing here prices, edits a record or a workbook, or calls a model.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

import final_charge_contract as fcc

SCHEMA = "read_charge_contract.v1"
LEDGER_SCHEMA = "read_ledger.v1"

CHARGED, COVERED, EXCLUDED, UNRESOLVED = "charged", "covered", "excluded", "unresolved"
# The codes invariants.check_what_the_read_returned_is_accounted_for raises — what a release
# row's check_code says when the read ledger is what holds it (D-598).
LEDGER_CHECK_CODES = frozenset({"read_item_unresolved", "engine_allowance_unconfirmed",
                                "engine_line_unconfirmed", "read_id_stale",
                                "read_charge_unverified", "read_charge_check_failed"})
CARRIED, CORRECTED, REFERENCE = "carried", "corrected", "reference"
WORK_STATES = (CHARGED, COVERED, EXCLUDED, UNRESOLVED)

# The fields of a read line that identify it. A record made from the line carries the same
# fingerprint, so the link survives a line set aside or appended before numbering.
_FINGERPRINT_FIELDS = ("name", "kind", "quantity", "material_guess", "sighted_material",
                       "assumed_blank_mm", "stock", "operations", "cutouts", "folds")
_NOTHING = {"", "none", "no", "n/a", "na", "nil", "-", "not visible", "cannot tell", "unknown",
            "none visible", "not stated", "unclear"}
# The read's own rank: a value set at it is the read's, not a correction.
_READ_SOURCES = {"", "vision_concept"}
_SIZE_FIELDS = (("length", "blank_length_mm"), ("width", "blank_width_mm"),
                ("thickness", "normalized_thickness_mm"))


def _cfg(name: str, default: Any) -> Any:
    try:
        import config                                               # noqa: WPS433
        return getattr(config, name, default)
    except Exception:                                                # noqa: BLE001
        return default


def op_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _pn(value: Any) -> str:
    return str(value or "").strip().upper()


def _words(value: Any) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).split())


def fingerprint(line: Mapping[str, Any]) -> str:
    """The identity of one read line, as the read returned it."""
    stable = {k: line.get(k) for k in _FINGERPRINT_FIELDS if isinstance(line, Mapping) and k in line}
    return hashlib.sha1(json.dumps(stable, sort_keys=True, default=str)
                        .encode("utf-8")).hexdigest()[:16]


def response_id(answer: Any) -> str:
    """The identity of one saved response (D-598): a hash of the answer as parsed from its
    words. A line's place is stable within one response and means nothing across two, so
    every line ID carries the response it was numbered in."""
    return "A" + hashlib.sha256(json.dumps(answer if isinstance(answer, Mapping) else {},
                                           sort_keys=True, default=str, ensure_ascii=False)
                                .encode("utf-8")).hexdigest()[:12]


def read_ids(answer: Any, response: str = "") -> Dict[int, str]:
    """Each read line's source ID, "<response>/R4:<fingerprint>" — the response it came in,
    its place there and what it said — keyed by the line object (D-596e, D-598). A record
    minted from a copy of the answer with lines set aside or added still carries the ID of the
    very line it came from; two lines that read alike are two IDs."""
    parts = answer.get("parts") if isinstance(answer, Mapping) else None
    resp = response or response_id(answer)
    return {id(line): f"{resp}/R{i}:{fingerprint(line)}"
            for i, line in enumerate(parts or [], start=1) if isinstance(line, Mapping)}


def _size_suffix(words: str) -> bool:
    """Words that are only a size — what the engine appends to a bought line's name where the
    brief states its size (D-532): "30 X 15 X 1 5 MM"."""
    toks = words.split()
    return (any(t.isdigit() for t in toks)
            and all(t.isdigit() or t in ("X", "MM") for t in toks))


def _link_records(lines: List[Tuple[str, Mapping[str, Any]]], recs: List[Mapping[str, Any]],
                  response: str = "", stale: Optional[List[Dict[str, Any]]] = None
                  ) -> Dict[str, Dict[str, Any]]:
    """Each read line's record, and how it was found, keyed by "R{i}" (D-596e, D-598).

    1. Its source ID, stamped on the record at mint — the response it was numbered in, its
       place there and its words — exact, whatever the engine later did to the record's
       description.
    2. A record whose ID names another response, or a line this response does not hold, is a
       STALE ID: it goes on `stale` as a finding first, and only then may the line's words
       link it.
    3. A record with no ID this read holds that carries the line's fingerprint, where exactly
       one line and one record carry it.
    4. A record from before the fingerprint, by its name: the read's own, or the read's with a
       size the engine appended — and only where that record answers to this line alone and
       this line to that record alone. Anything else is ambiguous and stays unlinked: a guess
       between two lines that read alike is not a link.
    """
    out: Dict[str, Dict[str, Any]] = {}
    sid_of = {rid: f"{response}/{rid}:{fingerprint(line)}" for rid, line in lines}
    by_sid: Dict[str, List[Mapping[str, Any]]] = {}
    by_fp: Dict[str, List[Mapping[str, Any]]] = {}
    old: List[Mapping[str, Any]] = []
    sids = set(sid_of.values())
    stale_pns: Set[str] = set()
    for r in recs:
        rid_said = str(r.get("read_id") or "")
        if rid_said and rid_said in sids:
            by_sid.setdefault(rid_said, []).append(r)
            continue
        if "/" in rid_said and stale is not None:
            # NOT THIS RESPONSE'S LINE (D-598), said before any other match is tried.
            said_resp = rid_said.split("/", 1)[0]
            stale.append({"record": _pn(r.get("part_number")), "read_id": rid_said,
                          "record_response": said_resp, "ledger_response": response,
                          "why": ("minted from another response" if said_resp != response
                                  else "names a line this response does not hold")})
            stale_pns.add(_pn(r.get("part_number")))
        if r.get("read_fingerprint"):
            # An ID this read does not hold still has its line's words: the fingerprint rule,
            # unique only.
            by_fp.setdefault(str(r["read_fingerprint"]), []).append(r)
        elif (r.get("concept_kind") and not r.get("is_assembly_parent")
              and _engine_origin(r) == "engine:unclassified"):
            old.append(r)
    line_fps: Dict[str, List[str]] = {}
    for rid, line in lines:
        line_fps.setdefault(fingerprint(line), []).append(rid)

    def candidates(line: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        name = _words(line.get("name"))
        hits = []
        for r in old:
            desc = _words(r.get("description"))
            if name and (desc == name or (desc.startswith(name + " ")
                                          and _size_suffix(desc[len(name) + 1:]))):
                hits.append(r)
        return hits

    claims: Dict[int, List[str]] = {}
    cands = {rid: candidates(line) for rid, line in lines}
    for rid, hits in cands.items():
        for r in hits:
            claims.setdefault(id(r), []).append(rid)
    for rid, line in lines:
        fp = fingerprint(line)
        hit = by_sid.get(sid_of[rid]) or []
        if len(hit) == 1:
            out[rid] = {"record": hit[0], "link": "read_id"}
        elif len(hit) > 1:
            out[rid] = {"record": None, "link": "ambiguous", "candidates": hit,
                        "why": f"{len(hit)} records carry this line's read ID"}
        elif by_fp.get(fp):
            if len(by_fp[fp]) == 1 and len(line_fps.get(fp) or []) == 1:
                out[rid] = {"record": by_fp[fp][0],
                            "link": ("fingerprint, after a stale read ID"
                                     if _pn(by_fp[fp][0].get("part_number")) in stale_pns
                                     else "fingerprint")}
            else:
                out[rid] = {"record": None, "link": "ambiguous", "candidates": by_fp[fp],
                            "why": (f"{len(line_fps.get(fp) or [])} read lines and "
                                    f"{len(by_fp[fp])} record(s) read alike, and no record "
                                    f"carries a read ID that tells them apart")}
        elif cands[rid]:
            hits = cands[rid]
            if len(hits) == 1 and claims.get(id(hits[0])) == [rid]:
                out[rid] = {"record": hits[0], "link": "name"}
            else:
                others = sorted({o for r in hits for o in claims.get(id(r), []) if o != rid})
                out[rid] = {"record": None, "link": "ambiguous", "candidates": hits,
                            "why": (f"{len(hits)} record(s) answer to this name"
                                    + (f", and {', '.join(others)} answer(s) to the same"
                                       if others else "")
                                    + " — a record from before the read ID cannot say which "
                                      "line it was")}
    return out


# ── capture: at the read ─────────────────────────────────────────────────────────────

def _finish_statements(answer: Mapping[str, Any], brief: str) -> List[Dict[str, str]]:
    """The finishes the read's sheet facts or the brief state: a plate and a polish as
    concept_scan reads them, and a coat (powder, paint) the sheet's finish note states."""
    out: List[Dict[str, str]] = []
    try:
        import concept_scan as cs                                   # noqa: WPS433
        st = cs.stated_finish(answer, brief)
    except Exception:                                                # noqa: BLE001
        st = {}
    if st.get("plate"):
        out.append({"id": "S.finish", "item": "plate", "text": st["plate"],
                    "said_by": st.get("plate_source") or ""})
    if st.get("polish"):
        out.append({"id": "S.polish", "item": "polish", "text": st["polish"],
                    "said_by": st.get("polish_source") or ""})
    if not st.get("plate"):
        facts = answer.get("sheet_facts") if isinstance(answer.get("sheet_facts"), Mapping) else {}
        text = " ".join(str(facts.get("finish") or "").split())
        try:
            from finish_rules import finish_families                # noqa: WPS433
            fams = finish_families(text) if text else set()
        except Exception:                                            # noqa: BLE001
            fams = set()
        if fams & {"powder", "wet_spray"}:
            out.append({"id": "S.finish", "item": "coat", "text": text,
                        "said_by": "the sheet's finish note, as read"})
    return out


def _engine_origin(rec: Mapping[str, Any]) -> str:
    if str(rec.get("read_origin") or "").startswith("engine:"):
        return str(rec["read_origin"])
    if rec.get("is_assembly_parent") and rec.get("concept"):
        return "unit"
    if rec.get("fixings_allowance"):
        return "engine:fixings_allowance"
    if rec.get("joining_method"):
        return "engine:adhesive_allowance"
    if rec.get("concept_not_visible"):
        return "read:not_visible"
    if rec.get("provisional_allowance"):
        return "read:named_inside_another_line"
    return "engine:unclassified"


def capture(answer: Any, *, records: Iterable[Any] = (), raw_response: str = "",
            read_key: str = "", said_by: str = "llm_read", brief: str = "",
            set_aside: Iterable[Any] = (), replayed_from: str = "",
            response: str = "") -> Dict[str, Any]:
    """The read's items, each with an identity and the record it became. Pure.

    `response`: the response's identity as taken at the read (response_id), so a record minted
    in this run is held to the response it was minted from; computed from `answer` if not
    given."""
    answer = answer if isinstance(answer, Mapping) else {}
    recs = [r for r in (records or []) if isinstance(r, Mapping)]
    resp = str(response or response_id(answer))
    lines = [(f"R{i}", line) for i, line in enumerate(answer.get("parts") or [], start=1)
             if isinstance(line, Mapping)]
    stale: List[Dict[str, Any]] = []
    links = _link_records(lines, recs, resp, stale)
    aside = [dict(a) for a in (set_aside or []) if isinstance(a, Mapping)]
    items: List[Dict[str, Any]] = []
    linked: Set[str] = set()
    ambiguous: Set[str] = set()

    def add(**item: Any) -> None:
        item.setdefault("said_by", said_by)
        items.append(item)

    for rid, line in lines:
        name = str(line.get("name") or rid).strip()
        link = links.get(rid) or {}
        rec = link.get("record")
        pn = _pn(rec.get("part_number")) if rec else ""
        if pn:
            linked.add(pn)
        why_aside = ""
        if link.get("link") == "ambiguous":
            # NOT LINKED BY GUESS (D-596e): the line stays unresolved, its candidates named.
            ambiguous |= {_pn(r.get("part_number")) for r in link.get("candidates") or []}
            why_aside = (f"not linked: {link.get('why')} "
                         f"({', '.join(sorted(_pn(r.get('part_number')) for r in link.get('candidates') or []))})")
        elif rec is None:
            hit = next((a for a in aside if _words(a.get("name")) == _words(name)), None)
            if hit is not None:
                aside.remove(hit)
                why_aside = ("set aside at the read: the sheet does not draw it (a bought line "
                             "with no drawn view), and asked")
        kind = str(line.get("kind") or "").strip().lower()
        described = str((rec or {}).get("description") or "")
        add(id=rid, kind="part", work=True, label=name, record=pn, part_kind=kind,
            set_aside=why_aside, link=str(link.get("link") or ""),
            source_id=f"{resp}/{rid}:{fingerprint(line)}",
            # WHAT THE SHEET CALLS IT, where the engine changed the read's name (D-596d).
            renamed_to=(described if described and _words(described) != _words(name) else ""),
            as_read={k: line.get(k) for k in ("name", "kind", "quantity", "material_guess",
                                               "sighted_material", "assumed_blank_mm", "stock")
                     if k in line})
        add(id=f"{rid}.quantity", kind="quantity", work=False, label=f"{name}: quantity",
            record=pn, of=rid, as_read=line.get("quantity"))
        if str(line.get("material_guess") or "").strip():
            add(id=f"{rid}.material", kind="material", work=False, label=f"{name}: material",
                record=pn, of=rid, as_read=line.get("material_guess"))
        blank = line.get("assumed_blank_mm") if isinstance(line.get("assumed_blank_mm"), Mapping) else {}
        if any(fcc.number(blank.get(k)) for k, _f in _SIZE_FIELDS):
            add(id=f"{rid}.size", kind="size", work=False, label=f"{name}: size", record=pn,
                of=rid, as_read={k: blank.get(k) for k, _f in _SIZE_FIELDS if k in blank})
        seen_ops: List[str] = []
        for raw_op in (line.get("operations") or []):
            op = op_name(raw_op)
            if op and op not in seen_ops:
                seen_ops.append(op)
                add(id=f"{rid}.op.{op}", kind="operation", work=True, item=op,
                    label=f"{name}: {raw_op}", record=pn, of=rid, as_read=raw_op)
        folds = fcc.number(line.get("folds"))
        if folds and folds > 0:
            add(id=f"{rid}.folds", kind="feature", work=True, item="folds",
                label=f"{name}: {folds:g} fold(s)", record=pn, of=rid, as_read=line.get("folds"))
        for j, cut in enumerate(line.get("cutouts") or [], start=1):
            what = (str(cut.get("what") or "cut-out").strip().lower()
                    if isinstance(cut, Mapping) else str(cut))
            add(id=f"{rid}.cutout{j}", kind="feature", work=True, item=what,
                label=f"{name}: {what}", record=pn, of=rid, as_read=cut)
        banded = " ".join(str(line.get("banded_edges") or "").split())
        if banded.lower() not in _NOTHING:
            add(id=f"{rid}.banded", kind="feature", work=True, item="banded edges",
                label=f"{name}: banded edges ({banded})", record=pn, of=rid, as_read=banded)
        # WHAT THE BRIEF STATES FOR THIS PART, FROM ITS WORDS (D-598): a reference code the
        # priced line must be shown to match, and a hole the read did not list, which a cutting
        # row on the part must be shown to cut. Never from the records under audit.
        others = [str(o.get("name") or "") for _r, o in lines if o is not line]
        try:
            import concept_scan as cs                               # noqa: WPS433
            ref, ref_by = cs.stated_item_reference(name, brief, others), "the enquiry brief"
            if not ref:
                ref, ref_by = cs.stated_item_reference(name, " ".join(
                    str(line.get(k) or "") for k in ("name", "seen", "sighted_material")),
                    ()), said_by
            read_dias = [max(fcc.number(c.get("length_mm")) or 0, fcc.number(c.get("width_mm")) or 0)
                         for c in (line.get("cutouts") or []) if isinstance(c, Mapping)
                         and "hole" in str(c.get("what") or "").lower()]
            holes = [h for h in cs.stated_item_holes(name, brief, others)
                     if not any(abs(h["diameter_mm"] - d) <= 0.25 for d in read_dias)]
        except Exception:                                            # noqa: BLE001
            ref, ref_by, holes = "", said_by, []
        # A WELDED PIECE IS A JOINT TO CHARGE ONCE (review of D-598): from the read's own
        # operations or a brief weld sentence naming it, never from the records under audit.
        read_ops = {op_name(o) for o in (line.get("operations") or [])}
        try:
            weld_by = ("the read" if read_ops & set(_families("welding")) else
                       "the enquiry brief" if cs.brief_names_weld_of(name, brief) else "")
        except Exception:                                            # noqa: BLE001
            weld_by = ""
        if weld_by:
            add(id=f"{rid}.joint", kind="joint", work=True, item="weld joint",
                label=f"{name}: welded ({weld_by})", record=pn, of=rid, as_read=weld_by,
                said_by=weld_by)
        if ref:
            add(id=f"{rid}.reference", kind="stated_reference", work=False, item=ref,
                label=f"{name}: reference {ref}", record=pn, of=rid, as_read=ref, said_by=ref_by)
        for k, h in enumerate(holes, start=1):
            add(id=f"{rid}.stated_hole{k}", kind="feature", work=True, item="stated hole",
                label=f"{name}: {h['count']} × Ø{h['diameter_mm']:g} hole (the brief)",
                record=pn, of=rid, as_read=dict(h), said_by="the enquiry brief")

    unit = next((r for r in recs if r.get("is_assembly_parent") and r.get("concept")), None)
    unit_pn = _pn((unit or {}).get("part_number"))
    seen_unit: List[str] = []
    for raw_op in (answer.get("unit_operations") or []):
        op = op_name(raw_op)
        if op and op not in seen_unit:
            seen_unit.append(op)
            add(id=f"U.op.{op}", kind="unit_operation", work=True, item=op,
                label=f"the unit: {raw_op}", record=unit_pn, as_read=raw_op)

    said = [str(x).strip() for x in (answer.get("not_visible") or []) if str(x).strip()]
    try:
        import concept_scan as cs                                   # noqa: WPS433
        cons, ship, _unknown = cs.split_not_visible(said)
    except Exception:                                                # noqa: BLE001
        cons, ship = [], []
    nv_lines = [r for r in recs if r.get("concept_not_visible") and not r.get("joining_method")
                and not r.get("fixings_allowance")]
    for k, text in enumerate(said, start=1):
        cls = "consumable" if text in cons else "shipment" if text in ship else "unknown"
        # A LINE BOUGHT FOR IT IS LINKED WHATEVER ITS CLASS: a thing the product only receives
        # that a line BUYS is the purchase this contract exists to hold, not an engine line.
        hit = next((r for r in nv_lines if _words(text) and (
            _words(text) in _words(r.get("description"))
            or _words(r.get("description")) in _words(text))), None)
        line_pn = _pn((hit or {}).get("part_number"))
        if line_pn:
            linked.add(line_pn)
        add(id=f"NV{k}", kind="not_visible", work=True, item=text, nv_class=cls,
            label=f"not visible: {text}", record=line_pn, as_read=text)

    for k, text in enumerate([str(x).strip() for x in (answer.get("print_sets") or [])
                              if str(x).strip()], start=1):
        add(id=f"PS{k}", kind="print_set", work=True, item=text, label=f"print set: {text}",
            record="", as_read=text)

    for st in _finish_statements(answer, brief):
        add(id=st["id"], kind="stated", work=True, item=st["item"],
            label=f"{st['item']}: {st['text']}", record=unit_pn, as_read=st["text"],
            said_by=st["said_by"] or said_by)
    # FROM THE WORDS, NEVER FROM THE RECORDS (D-596d): taking the process from what the transfer
    # wrote let a transfer that lost it hide the loss — the 17:15 book's TIG went unlisted.
    try:
        import concept_scan as cs                                   # noqa: WPS433
        stated_weld = cs.stated_weld_process(answer, brief)
    except Exception:                                                # noqa: BLE001
        stated_weld = {}
    if stated_weld:
        add(id="S.weld_process", kind="stated", work=True, item="weld_process",
            label=f"weld process: {stated_weld.get('process')}", record=unit_pn,
            as_read=stated_weld.get("word") or stated_weld.get("process"),
            process=str(stated_weld.get("process") or "").upper(),
            said_by=("the enquiry brief" if stated_weld.get("source") == "enquiry_brief"
                     else said_by))

    product = answer.get("product") if isinstance(answer.get("product"), Mapping) else {}
    if product:
        add(id="P", kind=REFERENCE, work=False, label=f"product: {product.get('name') or ''}",
            record=unit_pn, as_read=dict(product))
    facts = answer.get("sheet_facts") if isinstance(answer.get("sheet_facts"), Mapping) else {}
    for key in sorted(facts):
        if facts.get(key) not in (None, "", [], {}, 0):
            add(id=f"SF.{key}", kind=REFERENCE, work=False, label=f"sheet fact: {key}",
                record="", as_read=facts.get(key))

    sids = {f"{resp}/{rid}:{fingerprint(line)}" for rid, line in lines}
    engine_lines = [{"record": _pn(r.get("part_number")),
                     "origin": ("read:link_ambiguous" if _pn(r.get("part_number")) in ambiguous
                                else "read:id_not_in_this_read"
                                if r.get("read_id") and str(r["read_id"]) not in sids
                                else _engine_origin(r)),
                     "description": str(r.get("description") or "")}
                    for r in recs if _pn(r.get("part_number")) not in linked]
    raw = str(raw_response or "")
    return {
        "schema": LEDGER_SCHEMA, "said_by": said_by, "read_key": str(read_key or ""),
        "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else "",
        "raw_chars": len(raw), "replayed_from": str(replayed_from or ""),
        "brief_sha256": (hashlib.sha256(str(brief).encode("utf-8")).hexdigest()
                         if str(brief or "").strip() else ""),
        # WHICH BRIEF (review of D-598): a replay on a revised brief is told apart from one on
        # the original, so added input is never taken for better reading.
        "brief_chars": len(str(brief or "")),
        "unit": unit_pn, "items": items, "engine_lines": engine_lines,
        "response": resp, "stale_read_ids": stale,
    }


# ── the calculated workbook, indexed ─────────────────────────────────────────────────

class _Book:
    """The calculated rows and the records, joined once. Read-only."""

    def __init__(self, summary: Mapping[str, Any], snapshot: Optional[Mapping[str, Any]]):
        self.summary = summary
        self.snapshot = snapshot
        final = summary.get("final_estimate") if isinstance(summary.get("final_estimate"), Mapping) else {}
        self.calculated = final.get("source") == "excel_calculated"
        self.adapter_problems = list(final.get("adapter_problems") or [])
        es = summary.get("estimate_summary") if isinstance(summary.get("estimate_summary"), Mapping) else {}
        ests = (es.get("canonical_part_estimates") if "canonical_part_estimates" in es
                else es.get("part_estimates")) or []
        self.costs = {_pn(p.get("part_number")): p for p in ests if isinstance(p, Mapping)}
        mw = summary.get("manufacturing_writeup") if isinstance(summary.get("manufacturing_writeup"), Mapping) else {}
        self.records = {_pn(p.get("part_number")): p for p in (mw.get("parts") or [])
                        if isinstance(p, Mapping)}
        known = set(self.costs) | set(self.records)
        self.material: Dict[str, List[Mapping[str, Any]]] = {}
        for row in (final.get("material_rows") or []):
            if isinstance(row, Mapping):
                pn = self._material_id(row, known)
                if pn:
                    self.material.setdefault(pn, []).append(row)
        wl = {r.get("workbook_row"): r for r in
              ((summary.get("workbook_labour") or {}).get("rows") or []) if isinstance(r, Mapping)}
        self.labour: List[Dict[str, Any]] = []
        for row in (final.get("labour_rows") or []):
            if not isinstance(row, Mapping):
                continue
            group = wl.get(row.get("workbook_row")) or {}
            ops = {op_name(o) for o in (group.get("engine_operations") or []) if op_name(o)}
            parts = fcc.tokens(row.get("part_numbers")) | {_pn(p) for p in
                                                           (group.get("part_numbers") or [])}
            self.labour.append({"row": row, "ops": ops, "parts": parts,
                                "hours": fcc.cached_number(row.get("batch_hours")),
                                "value": fcc.cached_number(row.get("total_value_gbp")),
                                "cell": row.get("charged_cell"),
                                "wb_row": row.get("workbook_row"),
                                # The holes the row was costed for, where recorded (D-598a).
                                "holes_cut": group.get("holes_cut"),
                                "title": str(row.get("operation") or group.get("wb_operation") or "")})
        dec = summary.get("estimator_decisions") if isinstance(summary.get("estimator_decisions"), Mapping) else {}
        self.rulings = {str(k).strip().lower(): v for k, v in (dec.get("read_rulings") or {}).items()
                        if isinstance(v, Mapping)}
        self.decided_by = str(dec.get("decided_by") or "an estimator")
        self.off = {_pn(k): {op_name(o) for o in (v or [])}
                    for k, v in (dec.get("operations_off") or {}).items()}

    @staticmethod
    def _material_id(row: Mapping[str, Any], known: Set[str]) -> str:
        explicit = _pn(row.get("part_code"))
        if explicit:
            return explicit
        desc = _pn(row.get("description"))
        hits = [pn for pn in known if desc == pn or desc.startswith(pn + " ")]
        return max(hits, key=len) if hits else ""

    def charged_rows(self, pn: str, ops: Iterable[str]) -> List[Dict[str, Any]]:
        want = {op_name(o) for o in ops}
        return [l for l in self.labour if pn in l["parts"] and l["ops"] & want
                and (l["hours"] or 0) > 0 and (l["value"] or 0) > 0]

    def any_rows(self, ops: Iterable[str]) -> List[Dict[str, Any]]:
        want = {op_name(o) for o in ops}
        return [l for l in self.labour if l["ops"] & want
                and (l["hours"] or 0) > 0 and (l["value"] or 0) > 0]

    def saved_cell_agrees(self, row: Mapping[str, Any], pn: str) -> Optional[bool]:
        """None where no saved file was read; else whether its cached cells say the same."""
        if self.snapshot is None:
            return None
        cells = self.snapshot.get("cells") or {}
        address = str(row.get("charged_cell") or "")
        if "!" not in address:
            return False
        actual = fcc.cached_number(cells.get(address))
        recorded = fcc.cached_number(row.get("total_value_gbp"))
        if actual is None or recorded is None or not math.isclose(actual, recorded,
                                                                  rel_tol=0, abs_tol=1e-4):
            return False
        try:
            values = fcc.row_cells(cells, address).values()
        except (ValueError, AttributeError):
            return False
        return any(_pn(v) == pn or _pn(v).startswith(pn + " ") or pn in fcc.tokens(v)
                   for v in values if isinstance(v, str))


def _families(op: str) -> Tuple[str, ...]:
    fam = dict(_cfg("READ_OPERATION_CHARGED_BY", {}) or {})
    return tuple(fam[op]) if op in fam else (op,)


def _rate_processes(row: Mapping[str, Any]) -> Set[str]:
    """The weld processes a charged row is a rate for (D-596e): those its rate-card title or
    engine operations name, widened by config.WELD_RATE_EQUIVALENT_PROCESSES. A row naming
    processes that are not equivalent is a shared rate, a rate for none of them."""
    vocab = {str(k).upper(): str(v).upper()
             for k, v in (_cfg("WELD_PROCESS_VOCAB", {}) or {}).items()}
    same = {str(k).upper(): {str(p).upper() for p in v}
            for k, v in (_cfg("WELD_RATE_EQUIVALENT_PROCESSES", {}) or {}).items()}
    words = set(_words(row.get("title")).split())
    for op in row.get("ops") or ():
        words |= set(str(op).upper().split("_"))
    named = {vocab[w] for w in words if w in vocab}
    if not named:
        return set()
    groups = [same.get(n, {n}) for n in named]
    if any(not (named <= g) for g in groups):
        return set()
    return set().union(*groups)


def _rates_said(rows: Iterable[Mapping[str, Any]]) -> str:
    said = []
    for l in rows:
        rate = fcc.cached_number(l["row"].get("dept_rate_gbp_per_hour"))
        said.append(f"'{l['title']}'" + (f" (£{rate:.2f}/h)" if rate else ""))
    return ", ".join(sorted(set(said)))


def _covered_elsewhere(op: str) -> bool:
    return op in {op_name(w) for w in (_cfg("CONCEPT_OPERATIONS_COVERED_ELSEWHERE", ()) or ())}


def _source_of(rec: Mapping[str, Any], field: str) -> str:
    try:
        from source_precedence import source_of                     # noqa: WPS433
        return str(source_of(dict(rec), field) or "")
    except Exception:                                                # noqa: BLE001
        return ""


# ── the audit: after Excel ───────────────────────────────────────────────────────────

def audit(summary: Mapping[str, Any], snapshot: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Every read item's final state, the engine's allowances apart, and the findings that hold
    the release. Mutates nothing; never returns a verdict kept from an earlier workbook."""
    ledger = summary.get("read_ledger") if isinstance(summary.get("read_ledger"), Mapping) else {}
    result: Dict[str, Any] = {"schema": SCHEMA,
                              "applicable": bool(ledger.get("items") or ledger.get("error")),
                              "issues": [], "items": [], "allowances": [], "engine_lines": []}
    if ledger.get("error"):
        # A READ WHOSE LEDGER WAS NOT CAPTURED IS NOT A JOB WITH NO READ: it holds.
        result["issues"].append({"code": "read_ledger_not_captured", "item": "", "part": "",
                                 "why": str(ledger["error"])})
        result.update(passed=False, verified=False, counts={})
        return result
    if not result["applicable"]:
        result.update(passed=None, verified=False,
                      scope=("no read ledger on this job — no LLM read was taken, so this "
                             "contract checked nothing. That is coverage, not acceptance."))
        return result
    book = _Book(summary, snapshot)
    issues = result["issues"]
    if not book.calculated:
        issues.append({"code": "calculated_workbook_missing", "item": "", "part": ""})
    if book.adapter_problems:
        issues.append({"code": "workbook_readback_incomplete", "item": "", "part": "",
                       "problems": book.adapter_problems})
    traced_labour: Set[Tuple[Any, str, str]] = set()
    traced_material: Set[str] = set()
    out_items: List[Dict[str, Any]] = result["items"]
    part_state: Dict[str, str] = {}

    def done(item: Mapping[str, Any], state: str, how: str, rows: Iterable[Mapping[str, Any]] = (),
             **extra: Any) -> Dict[str, Any]:
        cells = [str(r.get("cell") or r.get("charged_cell") or "") for r in rows]
        entry = {"id": item["id"], "kind": item["kind"], "label": item.get("label"),
                 "record": item.get("record") or "", "said_by": item.get("said_by"),
                 "as_read": item.get("as_read"), "state": state, "how": how,
                 "cells": [c for c in cells if c], **extra}
        if item.get("link"):
            entry["link"] = item["link"]
        if item.get("renamed_to"):
            # A NAME THE ENGINE CHANGED IS SHOWN BESIDE THE READ'S (D-596d).
            entry["renamed_to"] = item["renamed_to"]
            entry["how"] = f"{how}; the sheet calls it '{item['renamed_to']}', not the read's name"
        out_items.append(entry)
        return entry

    def labour_evidence(rows: List[Dict[str, Any]], op_set: Iterable[str], pn: str) -> Optional[str]:
        """Trace the rows, and say why not where the saved file disagrees."""
        for l in rows:
            for op in l["ops"] & {op_name(o) for o in op_set}:
                traced_labour.add((l["wb_row"], op, pn))
            if book.saved_cell_agrees(l["row"], pn) is False:
                return f"the saved workbook's cell {l['cell']} does not agree with the read-back"
        return None

    read_parts = {_pn(i.get("record")) for i in (ledger.get("items") or [])
                  if isinstance(i, Mapping) and i.get("kind") == "part" and i.get("record")}

    def scope(item: Mapping[str, Any]) -> Set[str]:
        """The parts a charge must name to carry this item: its own record and the host its
        weld or coat moved to, and the unit, whose bench work carries a piece's fitting; for a
        requirement of the whole product (a stated finish, a unit operation), the unit and the
        read's parts."""
        pn = _pn(item.get("record"))
        unit = _pn(ledger.get("unit"))
        if item.get("kind") in ("stated", "unit_operation", "print_set", "not_visible") or not pn:
            return ({unit} if unit else set()) | read_parts
        rec = book.records.get(pn) or book.costs.get(pn) or {}
        hosts = {_pn(rec.get(k)) for k in ("weld_charged_on", "coat_charged_on") if rec.get(k)}
        return {pn} | hosts | ({unit} if unit else set())

    def ruled(item: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        r = book.rulings.get(str(item["id"]).lower())
        if not r:
            return None
        if r.get("ruling") == "excluded":
            return done(item, EXCLUDED, f"ruled out by {book.decided_by}: {r.get('reason')}")
        if (r.get("ruling") == "covered" and not str(r.get("evidence") or "").strip()
                and any(str(item["id"]).lower().startswith(str(k).lower())
                        for k in (_cfg("READ_RULINGS_NEEDING_EVIDENCE", ()) or ()))):
            # A SHARED OR SUBSTITUTE RATE IS ACCEPTED ONLY ON EVIDENCE (review of D-596e): an
            # estimator may rule a stated weld process covered by another rate, and the ruling
            # names who confirmed it and where, or it covers nothing.
            return done(item, UNRESOLVED,
                        f"ruled covered by {op_name(r.get('covered_by'))} with no evidence — this "
                        f"needs a ruling that names its evidence (who confirmed the rate or the "
                        f"minutes, and where)")
        if r.get("ruling") == "covered":
            # A REASON DOES NOT MAKE A COVER (review of D-596). The named charge must be on the
            # calculated sheet with hours and money, on a part that carries this item, at that
            # part's quantity, and agree with the saved file — or the ruling explains away a
            # missing charge. Its rows are not traced to the item: a covering charge the engine
            # added stays an allowance, and holds on its own basis until confirmed.
            by = op_name(r.get("covered_by"))
            parts = scope(item)
            rows = [l for l in book.labour if by in l["ops"] and l["parts"] & parts
                    and (l["hours"] or 0) > 0 and (l["value"] or 0) > 0]
            mats = [m for m in book.material.get(_pn(r.get("covered_by")), [])
                    if (fcc.cached_number(m.get("total_value_gbp")) or 0) > 0]
            if not rows and not mats:
                elsewhere = [l for l in book.labour if by in l["ops"]
                             and (l["hours"] or 0) > 0 and (l["value"] or 0) > 0]
                return done(item, UNRESOLVED,
                            f"ruled covered by {by}, and {by} is charged only on "
                            f"{', '.join(sorted({p for l in elsewhere for p in l['parts']}))}, "
                            f"which does not carry it" if elsewhere else
                            f"ruled covered by {by}, and no calculated row charges {by}")
            pn = _pn(item.get("record"))
            want = fcc.number((book.costs.get(pn) or {}).get("quantity")) if pn else None
            for l in rows:
                got = fcc.cached_number(l["row"].get("qty_per_unit"))
                if (want is not None and l["parts"] == {pn} and got is not None
                        and not math.isclose(got, want, rel_tol=0, abs_tol=1e-8)):
                    return done(item, UNRESOLVED, f"ruled covered by {by}, and that row charges "
                                                  f"{got:g} against {want:g} on the record", [l])
                if book.saved_cell_agrees(l["row"], next(iter(l["parts"] & parts))) is False:
                    return done(item, UNRESOLVED, f"ruled covered by {by}, and the saved "
                                                  f"workbook's cell {l['cell']} does not agree")
            return done(item, COVERED, f"covered by {by} on "
                                       f"{', '.join(sorted({p for l in rows for p in l['parts'] & parts})) or _pn(r.get('covered_by'))}, "
                                       f"ruled by {book.decided_by}: {r.get('reason')}"
                                       + (f" (evidence: {r.get('evidence')})" if r.get("evidence") else ""),
                        rows or [{"cell": m.get("charged_cell")} for m in mats])
        return None

    def plating_lines(pn: str = "") -> List[Mapping[str, Any]]:
        lines = []
        for mpn, rows in book.material.items():
            if not mpn.endswith("-PLATE"):
                continue
            rec = book.costs.get(mpn) or book.records.get(mpn) or {}
            members = {_pn(m) for m in (rec.get("_plating_members") or [])}
            host = _pn(rec.get("_plating_weldment"))
            if not pn or pn in members or pn == host or mpn == f"{pn}-PLATE":
                lines.extend(rows)
                traced_material.add(mpn)
        return lines

    def money(rows: Iterable[Mapping[str, Any]]) -> Optional[float]:
        vals = [fcc.cached_number(r.get("total_value_gbp")) for r in rows]
        return None if any(v is None for v in vals) else sum(vals)

    def work_state(item: Mapping[str, Any], op: str, pn: str) -> None:
        if not book.calculated:
            done(item, UNRESOLVED, "the calculated workbook was not read back")
            return
        if ruled(item):
            return
        rec = book.records.get(pn) or book.costs.get(pn) or {}
        if pn and op in book.off.get(pn, set()):
            done(item, EXCLUDED, f"taken off by {book.decided_by} (answers file operations_off)")
            return
        if not pn:
            done(item, UNRESOLVED, "no record carries it, so nothing on the sheet can")
            return
        if op == "plating":
            lines = plating_lines(pn)
            total = money(lines)
            if lines and (total or 0) > 0:
                done(item, COVERED, "the subcontract plating line carries it",
                     [{"cell": l.get("charged_cell")} for l in lines])
            elif lines:
                done(item, UNRESOLVED, "the plating line is on the sheet with no price — the "
                                       "plater's price is awaited")
            else:
                done(item, UNRESOLVED, "no plating line on the calculated sheet")
            return
        fam = _families(op)
        rows = book.charged_rows(pn, fam) if fam else []
        if rows:
            bad = labour_evidence(rows, fam, pn)
            done(item, UNRESOLVED if bad else CHARGED,
                 bad or f"{', '.join(sorted({l['title'] for l in rows}))} row(s) charge it", rows)
            return
        host = _pn(rec.get("weld_charged_on")) if op in _families("welding") or op == "welding" else ""
        if not host and op in ("powder_coating", "wet_spray"):
            host = _pn(rec.get("coat_charged_on"))
        if host and host != pn:
            rows = book.charged_rows(host, fam)
            if rows:
                bad = labour_evidence(rows, fam, host)
                done(item, UNRESOLVED if bad else COVERED,
                     bad or f"charged on {host}, which carries it ({', '.join(sorted({l['title'] for l in rows}))})",
                     rows)
                return
        if op in ("hole_machining", "drilling"):
            rows = book.charged_rows(pn, _cfg("READ_PROFILE_CUTS", ()))
            if rows:
                labour_evidence(rows, _cfg("READ_PROFILE_CUTS", ()), pn)
                done(item, COVERED, f"the profile cut cuts its holes "
                                    f"({', '.join(sorted({l['title'] for l in rows}))})", rows)
                return
        if (_covered_elsewhere(op) or op in ("assembly", "bench_work")) and ledger.get("unit"):
            unit = _pn(ledger.get("unit"))
            rows = book.charged_rows(unit, _cfg("READ_UNIT_WORK_CHARGES", ()))
            if rows and unit != pn:
                labour_evidence(rows, _cfg("READ_UNIT_WORK_CHARGES", ()), unit)
                done(item, COVERED, f"the unit's bench and pack work on {unit} carries it", rows)
                return
            if op in ("packing", "pack", "packaging") and money(book.material.get("PACKAGING") or []):
                traced_material.add("PACKAGING")
                done(item, COVERED, "the PACKAGING line carries it",
                     [{"cell": m.get("charged_cell")} for m in book.material["PACKAGING"]])
                return
        done(item, UNRESOLVED, "the read names it and no calculated row charges it")

    def part_work(item: Mapping[str, Any]) -> None:
        pn = _pn(item.get("record"))
        if ruled(item):
            part_state[item["id"]] = out_items[-1]["state"]
            return
        if not pn:
            done(item, UNRESOLVED, item.get("set_aside") or "no record was made of this line")
        elif not book.calculated:
            done(item, UNRESOLVED, "the calculated workbook was not read back")
        elif pn not in book.costs:
            done(item, UNRESOLVED, "made a record, and no costed line carries it — set aside or "
                                   "dropped after the read")
        elif (book.costs[pn] or {}).get("set_aside"):
            done(item, UNRESOLVED, f"set aside: {book.costs[pn].get('set_aside_reason') or 'by the graph'}")
        else:
            rows = book.material.get(pn) or []
            total = money(rows)
            if len(rows) > 1:
                done(item, UNRESOLVED, f"{len(rows)} material rows carry it where one is required", rows)
            elif rows and (total or 0) > 0:
                traced_material.add(pn)
                agrees = book.saved_cell_agrees(rows[0], pn)
                done(item, UNRESOLVED if agrees is False else CHARGED,
                     ("the saved workbook's cell does not agree with the read-back"
                      if agrees is False else "its material row charges it"),
                     [{"cell": rows[0].get("charged_cell")}])
            elif rows:
                why = rows[0].get("unpriced_reason") or "no price"
                done(item, UNRESOLVED, f"on the sheet with {why}", [{"cell": rows[0].get("charged_cell")}])
            else:
                done(item, UNRESOLVED, "no material row on the calculated sheet")
        part_state[item["id"]] = out_items[-1]["state"]

    def fact(item: Mapping[str, Any]) -> None:
        pn = _pn(item.get("record"))
        rec = book.records.get(pn) or {}
        cost = book.costs.get(pn) or {}
        parent = part_state.get(str(item.get("of") or ""), "")
        if item["kind"] == "quantity":
            read_q = fcc.number(item.get("as_read"))
            rec_q = fcc.number(cost.get("quantity")) if cost else fcc.number(rec.get("quantity"))
            rows = book.material.get(pn) or []
            row_q = fcc.cached_number(rows[0].get("qty_per_unit")) if len(rows) == 1 else None
            if rec_q is None or read_q is None:
                done(item, UNRESOLVED, "no quantity to compare: the read or the record has none")
                return
            if rows and (row_q is None or not math.isclose(row_q, rec_q, rel_tol=0, abs_tol=1e-8)):
                done(item, UNRESOLVED, f"the sheet charges {row_q} against {rec_q:g} on the record",
                     [{"cell": rows[0].get("charged_cell")}])
                return
            if math.isclose(read_q, rec_q, rel_tol=0, abs_tol=1e-8):
                done(item, CARRIED, f"{read_q:g} as read" + ("" if rows else
                                                            " (its line is not charged)"))
                return
            by = _source_of(rec, "quantity")
            if by in _READ_SOURCES:
                done(item, UNRESOLVED, f"changed from {read_q:g} to {rec_q:g} and no source "
                                       f"names the change")
            else:
                done(item, CORRECTED, f"{read_q:g} as read, {rec_q:g} charged — by {by}",
                     corrected={"from": read_q, "to": rec_q, "by": by})
            return
        if item["kind"] == "stated_reference":
            # A STATED REFERENCE IS MATCHED, OR THE MATCH IS ASKED (D-598): the priced line must
            # carry the code — a catalogue row's supplier code — or a person rules on it.
            if ruled(item):
                return
            ref = str(item.get("as_read") or "")
            me = cost.get("material_estimate") if isinstance(cost.get("material_estimate"), Mapping) else {}
            codes = [me.get("supplier_code"), cost.get("supplier_code"), rec.get("supplier_code")]
            if not pn:
                done(item, UNRESOLVED, f"{item.get('said_by')} names {ref}, and no record carries "
                                       f"the line")
            elif any(_words(c).replace(" ", "") == _words(ref).replace(" ", "") for c in codes if c):
                done(item, CARRIED, f"priced on {ref}")
            else:
                done(item, UNRESOLVED, f"{item.get('said_by')} names {ref}, and no priced line "
                                       f"carries that code — the item priced is not shown to be "
                                       f"{ref}; the supplier match is unproven")
            return
        if item["kind"] == "material":
            held = rec.get("normalized_material") or cost.get("normalized_material")
            if not held:
                done(item, UNRESOLVED if parent != EXCLUDED else EXCLUDED,
                     "the record holds no material")
            elif _words(held) == _words(item.get("as_read")):
                done(item, CARRIED, f"{held} as read")
            else:
                by = _source_of(rec, "normalized_material")
                done(item, CORRECTED, f"{item.get('as_read')} as read, {held} held — by "
                                      f"{by or 'the engine'}'s material vocabulary"
                     if by in _READ_SOURCES else f"{item.get('as_read')} as read, {held} held — by {by}",
                     corrected={"from": item.get("as_read"), "to": held,
                                "by": by or "material vocabulary at the read's rank"})
            return
        if item["kind"] == "size":
            read = item.get("as_read") if isinstance(item.get("as_read"), Mapping) else {}
            changes, unnamed = [], []
            for key, field in _SIZE_FIELDS:
                a, b = fcc.number(read.get(key)), fcc.number(rec.get(field))
                if not a or b is None or math.isclose(a, b, rel_tol=0, abs_tol=0.5):
                    continue
                by = _source_of(rec, field)
                changes.append({"field": key, "from": a, "to": b, "by": by or "unnamed"})
                if by in _READ_SOURCES:
                    unnamed.append(key)
            if unnamed:
                done(item, UNRESOLVED, f"{', '.join(unnamed)} changed and no source names the "
                                       f"change", corrected=changes)
            elif changes:
                done(item, CORRECTED, "; ".join(f"{c['field']} {c['from']:g} as read, "
                                                f"{c['to']:g} held — by {c['by']}" for c in changes),
                     corrected=changes)
            else:
                done(item, CARRIED, "as read")

    def feature(item: Mapping[str, Any]) -> None:
        pn = _pn(item.get("record"))
        what = str(item.get("item") or "")
        if not book.calculated:
            done(item, UNRESOLVED, "the calculated workbook was not read back")
            return
        if ruled(item):
            return
        if what == "folds":
            work_state(item, "folding", pn)
        elif what == "banded edges":
            work_state(item, "edge_banding", pn)
        else:
            if "hole" in what:
                hole_cover(item, pn)
                return
            rows = book.charged_rows(pn, _cfg("READ_PROFILE_CUTS", ()))
            if rows:
                labour_evidence(rows, set(_cfg("READ_PROFILE_CUTS", ())) | set(_families("hole_machining")), pn)
                done(item, COVERED, f"cut with the part ({', '.join(sorted({l['title'] for l in rows}))})", rows)
            else:
                done(item, UNRESOLVED, "no calculated cutting row on its part cuts it")

    def hole_cover(item: Mapping[str, Any], pn: str) -> None:
        """A HOLE IS COVERED BY WHAT OWNS AND CUTS IT, NOT BY A ROW THAT CUTS SOME HOLE (review of
        D-598). Its owning part's record must carry a hole of the stated diameter at the stated
        count, a cutting or drilling row on that part must charge it, and where the row records
        the holes it was costed for, at least that many — or it is unresolved."""
        said = item.get("as_read") if isinstance(item.get("as_read"), Mapping) else {}
        dia = fcc.number(said.get("diameter_mm")) or max(fcc.number(said.get("length_mm")) or 0,
                                                         fcc.number(said.get("width_mm")) or 0)
        count = int(fcc.number(said.get("count")) or 0)
        if not pn:
            done(item, UNRESOLVED, "no record carries its part, so nothing on the sheet can cut it")
            return
        rec = book.records.get(pn) or book.costs.get(pn) or {}
        held = [(max(fcc.number(c.get("length_mm")) or 0, fcc.number(c.get("width_mm")) or 0),
                 int(fcc.number(c.get("count")) or 0))
                for c in (rec.get("concept_cutout_dims") or []) if isinstance(c, Mapping)
                and str(c.get("what") or "").lower().startswith("hole")]
        held += [(fcc.number(d) or 0, 0) for d in (rec.get("hole_sizes_mm") or [])]
        size = f"Ø{dia:g}" if dia else "the"
        match = [h for h in held if not dia or abs(h[0] - dia) <= 0.25]
        if not match:
            done(item, UNRESOLVED, f"{pn}'s record carries no {size} hole — nothing charged "
                                   f"cuts this hole")
            return
        have = sum(n for _d, n in match)
        if count and 0 < have < count:
            done(item, UNRESOLVED, f"{pn}'s record carries {have} {size} hole(s) against {count} "
                                   f"required")
            return
        ops = set(_cfg("READ_PROFILE_CUTS", ())) | set(_families("hole_machining"))
        rows = book.charged_rows(pn, ops)
        if not rows:
            done(item, UNRESOLVED, f"{size} hole on {pn}'s record, and no cutting or drilling row "
                                   f"on {pn} charges it")
            return
        qty = fcc.number((book.costs.get(pn) or {}).get("quantity")) or 1
        need = (count or max(have, 1)) * qty
        counted = [l for l in rows if l.get("holes_cut") is not None]
        if counted and sum(fcc.number(l.get("holes_cut")) or 0 for l in counted) < need:
            done(item, UNRESOLVED,
                 f"{size} hole on {pn}'s record, and {', '.join(sorted({l['title'] for l in counted}))} "
                 f"on {pn} was costed for {sum(fcc.number(l.get('holes_cut')) or 0 for l in counted):g} "
                 f"hole(s) against {need:g} — the hole is not in the cut", counted)
            return
        labour_evidence(rows, ops, pn)
        done(item, COVERED,
             f"{count or have or 'its'} × {size} hole on {pn}'s record, cut by "
             f"{', '.join(sorted({l['title'] for l in rows}))}"
             + ("" if counted else " — the row does not state the holes it was costed for (saved "
                                   "before D-598a)"), rows)

    def not_visible(item: Mapping[str, Any]) -> None:
        if not book.calculated:
            done(item, UNRESOLVED, "the calculated workbook was not read back")
            return
        if ruled(item):
            return
        cls = item.get("nv_class")
        pn = _pn(item.get("record"))
        rows = book.material.get(pn) or [] if pn else []
        if rows:
            traced_material.add(pn)
        if cls == "consumable":
            if rows and (money(rows) or 0) > 0:
                done(item, CHARGED, "its consumable line charges it",
                     [{"cell": r.get("charged_cell")} for r in rows])
            else:
                done(item, UNRESOLVED, "named as a consumable, and no priced line carries it")
        elif cls != "shipment" and rows:
            done(item, UNRESOLVED, "bought on its own line, and nothing shows SDI supplies it — "
                                   "a purchase with no supply-scope evidence",
                 [{"cell": r.get("charged_cell")} for r in rows])
        elif cls == "shipment":
            rows = (book.material.get("PACKAGING") or []) + (book.material.get("DELIVERY") or [])
            if rows:
                done(item, COVERED, "the commercial PACKAGING / DELIVERY lines carry it",
                     [{"cell": r.get("charged_cell")} for r in rows])
            else:
                done(item, UNRESOLVED, "shipment scope, and no commercial line is on the sheet")
        else:
            done(item, UNRESOLVED, "named by the read, shown nowhere, and nothing says whether "
                                   "SDI supplies it — asked, not bought")

    def print_set(item: Mapping[str, Any]) -> None:
        if not book.calculated:
            done(item, UNRESOLVED, "the calculated workbook was not read back")
            return
        if ruled(item):
            return
        # WHAT THE PRINT SET IS OF, BEFORE ANY CHARGE IS TAKEN FOR IT (D-596e). A print set that
        # describes a read part that is not a graphic line — a bought label — may be that
        # part's own print (shared coverage) or separate printing and application work; which,
        # only a person can say. It stays open, the part named, until a ruling settles it.
        text = set(_words(item.get("as_read")).split())
        generic = {str(w).upper() for w in (_cfg("CONCEPT_NAME_GENERIC_WORDS", ()) or ())}
        relates = []
        for i in items:
            if i.get("kind") != "part":
                continue
            sig = [w for w in _words(i.get("label")).split()
                   if len(w) >= 3 and w not in generic and not w.isdigit()]
            if sig and sig[-1] in text and 2 * sum(w in text for w in sig) >= len(sig):
                relates.append(i)
        others = [i for i in relates if i.get("part_kind") != "graphic"]
        about = "; ".join(f"{i['id']} '{i.get('label')}' ({i.get('part_kind') or 'part'}"
                          f"{', ' + i['record'] if i.get('record') else ''})" for i in others)
        graphics = [pn for pn, r in book.records.items() if r.get("concept_kind") == "graphic"]
        rows = [r for pn in graphics for r in (book.material.get(pn) or [])
                if (fcc.cached_number(r.get("total_value_gbp")) or 0) > 0]
        if others:
            done(item, UNRESOLVED,
                 f"it describes {about}: rule whether that line carries this print (covered, "
                 f"covered_by its record) or it is separate printing or application work, "
                 f"which then needs its own charge", relates_to=[i["id"] for i in others])
        elif rows:
            done(item, COVERED, f"the graphic line(s) {', '.join(sorted(graphics))} carry the print",
                 [{"cell": r.get("charged_cell")} for r in rows])
        else:
            done(item, UNRESOLVED, "no priced graphic line carries this print set, and no read "
                                   "part it describes was found — rule what it is")

    def stated(item: Mapping[str, Any]) -> None:
        if not book.calculated:
            done(item, UNRESOLVED, "the calculated workbook was not read back")
            return
        if ruled(item):
            return
        what = item.get("item")
        if what == "plate":
            lines = plating_lines("")
            total = money(lines)
            if lines and (total or 0) > 0:
                done(item, COVERED, "the subcontract plating line prices it",
                     [{"cell": l.get("charged_cell")} for l in lines])
            elif lines:
                done(item, UNRESOLVED, "stated, and the plating line carries no price — the "
                                       "plater's price is awaited")
            else:
                done(item, UNRESOLVED, "stated, and no plating line is on the calculated sheet")
        elif what == "coat":
            rows = book.any_rows(("powder_coating", "oven", "wet_spray"))
            done(item, COVERED if rows else UNRESOLVED,
                 "the coating rows carry it" if rows else "stated, and no coating row charges it",
                 rows)
        elif what == "polish":
            rows = book.any_rows(_families("polishing"))
            done(item, CHARGED if rows else UNRESOLVED,
                 "polishing rows charge it" if rows else
                 "stated, and no polishing row charges it — brushing before plating is not this "
                 "sequence", rows)
        elif what == "weld_process":
            # THE PROCESS STATED, HELD TO THE RATE CHARGED (D-596e). The process comes from the
            # words; the charge is the weld row's own rate — its rate-card title and engine
            # operation, never its description, which names a stated TIG beside the CO2 rate it
            # rides on. Only a row that is a rate for the stated process satisfies it.
            proc = str(item.get("process") or "").upper()
            rows = book.any_rows(_families("welding"))
            evidenced = [l for l in rows if proc and proc in _rate_processes(l)]
            if not rows:
                done(item, UNRESOLVED, f"{proc} stated, and no weld row is charged")
            elif evidenced:
                # A TITLE IS NECESSARY, NOT SUFFICIENT (review of D-596e): the row must also
                # carry a stated rate (and the card's, where config states one for the
                # process), hours, the welded part's quantity, and every welded piece's joints.
                for l in evidenced:
                    for p in l["parts"]:
                        traced_labour.add((l["wb_row"], "welding", p))
                short = weld_proof_gaps(evidenced, proc)
                done(item, UNRESOLVED if short else COVERED,
                     (f"{proc} stated, and {_rates_said(evidenced)} names it — but "
                      + "; ".join(short)) if short else
                     f"{proc} stated, and {_rates_said(evidenced)} is a {proc} rate that charges "
                     f"it, at the welded part's quantity, covering every welded piece", evidenced)
            else:
                named = sorted({p for l in rows for p in _rate_processes(l)})
                done(item, UNRESOLVED,
                     f"{proc} stated, and the weld is charged at {_rates_said(rows)} — "
                     + (f"a {'/'.join(named)} rate" if named else "a rate that names no process")
                     + f", not a {proc} rate; give the {proc} rate or the minutes at it, or rule "
                       f"how it is covered", rows)
        else:
            done(item, UNRESOLVED, "a stated requirement no rule here can account for")

    def weld_rows_for(pn: str) -> List[Dict[str, Any]]:
        """The charged weld rows that carry this piece's joint: on the piece, on the host it is
        welded to, or on the unit that owns its members' joints (D-531)."""
        rec = book.records.get(pn) or {}
        unit = _pn(ledger.get("unit"))
        hosts = ({_pn(rec.get("weld_charged_on"))}
                 | {_pn(h) for h in (rec.get("welded_to_hosts") or [])}) - {""}
        return [l for l in book.any_rows(_families("welding"))
                if l["parts"] & ({pn} | hosts | ({unit} if unit else set()))]

    def joint_cover(item: Mapping[str, Any]) -> None:
        """A WELDED PIECE'S JOINT IS CHARGED EXACTLY ONCE (review of D-598): on one weld row —
        none is a lost joint, two is the same joint charged twice. The runs per joint (one side
        or both) are not counted on the sheet, and the state says so."""
        if not book.calculated:
            done(item, UNRESOLVED, "the calculated workbook was not read back")
            return
        if ruled(item):
            return
        pn = _pn(item.get("record"))
        if not pn:
            done(item, UNRESOLVED, f"{item.get('said_by')} has it welded, and no record carries it")
            return
        rows = weld_rows_for(pn)
        wb_rows = {l["wb_row"] for l in rows}
        if not rows:
            done(item, UNRESOLVED, f"{item.get('said_by')} has it welded, and no weld row charges "
                                   f"{pn}, its host or the unit")
        elif len(wb_rows) > 1:
            done(item, UNRESOLVED, f"{pn}'s joint is charged on {len(wb_rows)} weld rows "
                                   f"({', '.join(sorted({l['title'] for l in rows}))}) — a joint "
                                   f"is charged once", rows)
        else:
            bad = labour_evidence(rows, _families("welding"), next(iter(rows[0]["parts"])))
            done(item, UNRESOLVED if bad else CHARGED,
                 bad or f"charged once, on {rows[0]['title']} on "
                        f"{', '.join(sorted(rows[0]['parts']))}; the runs per joint are not "
                        f"counted on the sheet", rows)

    def weld_proof_gaps(rows: List[Dict[str, Any]], proc: str) -> List[str]:
        """What a row titled for the stated process still has to show (D-598, D-598a): a rate
        with a documented source — config WELD_PROCESS_RATES_GBP names the rate and where it
        came from; an estimator's evidenced ruling is the other way — the welded part's quantity,
        and every welded piece's joint on such a row, charged once."""
        short: List[str] = []
        spec = (_cfg("WELD_PROCESS_RATES_GBP", {}) or {}).get(proc)
        card = fcc.number(spec.get("gbp_per_hour")) if isinstance(spec, Mapping) else None
        source = str(spec.get("source") or "").strip() if isinstance(spec, Mapping) else ""
        arc = {str(p).upper() for p in ((_cfg("WELD_RATE_EQUIVALENT_PROCESSES", {}) or {})
                                        .get("CO2") or ())}
        if spec is None and proc in arc:
            # The card's own arc-weld row is the documented rate for the processes it is a rate
            # for (config HOURLY_RATES_GBP, read from the template's rate block).
            card = fcc.number((_cfg("HOURLY_RATES_GBP", {}) or {}).get("welding"))
            source = "the rate card's arc-weld row"
        for l in rows:
            rate = fcc.cached_number(l["row"].get("dept_rate_gbp_per_hour"))
            if not rate or rate <= 0:
                short.append(f"'{l['title']}' states no rate")
            elif not card:
                short.append(f"no documented {proc} rate holds its £{rate:.2f}/h — give the rate "
                             f"and its source (config WELD_PROCESS_RATES_GBP), or rule it with "
                             f"evidence")
            elif not source:
                short.append(f"the configured {proc} rate names no source")
            elif not math.isclose(rate, card, rel_tol=0, abs_tol=0.005):
                short.append(f"'{l['title']}' charges £{rate:.2f}/h against the card's "
                             f"£{card:.2f}/h for {proc} ({source})")
            got = fcc.cached_number(l["row"].get("qty_per_unit"))
            if len(l["parts"]) == 1 and got is not None:
                pn = next(iter(l["parts"]))
                want = fcc.number((book.costs.get(pn) or {}).get("quantity"))
                if want is not None and not math.isclose(got, want, rel_tol=0, abs_tol=1e-8):
                    short.append(f"'{l['title']}' charges {got:g} of {pn} against {want:g} on "
                                 f"the record")
        evidenced = {l["wb_row"] for l in rows}
        welded = {_pn(i.get("record")) for i in items if i.get("kind") == "joint"}
        for i in items:
            pn = _pn(i.get("record"))
            rec = book.records.get(pn) or {}
            if i.get("kind") == "part" and pn and (
                    "welding" in {op_name(o) for o in (list(rec.get("inferred_operations") or [])
                                                       + list(rec.get("operations") or []))}
                    or rec.get("weld_charged_on") or rec.get("welded_to_hosts")):
                welded.add(pn)
        for pn in sorted(welded - {""}):
            mine = weld_rows_for(pn)
            if not {l["wb_row"] for l in mine} & evidenced:
                short.append(f"{pn}'s weld is on no {proc} row")
            elif len({l["wb_row"] for l in mine}) > 1:
                short.append(f"{pn}'s joint is charged on {len({l['wb_row'] for l in mine})} weld "
                             f"rows")
        return short

    items = [i for i in (ledger.get("items") or []) if isinstance(i, Mapping)]
    for item in items:
        if item.get("kind") == "part":
            part_work(item)
    for item in items:
        kind = item.get("kind")
        if kind == "part":
            continue
        if kind in ("quantity", "material", "size", "stated_reference"):
            fact(item)
        elif kind in ("operation", "unit_operation"):
            work_state(item, op_name(item.get("item")), _pn(item.get("record")))
        elif kind == "feature":
            feature(item)
        elif kind == "joint":
            joint_cover(item)
        elif kind == "not_visible":
            not_visible(item)
        elif kind == "print_set":
            print_set(item)
        elif kind == "stated":
            stated(item)
        else:
            done(item, REFERENCE, "recorded as read; not a charge")

    _allowances(summary, book, ledger, traced_labour, traced_material, result)

    # A STALE READ ID IS A FINDING BEFORE IT IS A FALLBACK (D-598): a record minted from
    # another response, or naming a line this response does not hold, is said and holds,
    # whatever its words later linked it to.
    for s in ledger.get("stale_read_ids") or []:
        if isinstance(s, Mapping):
            issues.append({"code": "read_id_stale", "item": str(s.get("read_id") or ""),
                           "part": str(s.get("record") or ""),
                           "why": (f"{s.get('record')} carries read ID {s.get('read_id')}, "
                                   f"{s.get('why')} (this ledger's response is "
                                   f"{s.get('ledger_response')}) — any link to it is by the "
                                   f"line's words, not its ID")})
    for e in out_items:
        if e["state"] == UNRESOLVED:
            issues.append({"code": "read_item_unresolved", "item": e["id"], "part": e["record"],
                           "label": e.get("label"), "why": e["how"]})
    for a in result["allowances"]:
        if a.get("holds"):
            issues.append({"code": "engine_allowance_unconfirmed", "item": f"allowance:{a['operation']}",
                           "part": a.get("part") or "", "class": a["class"],
                           "minutes_per_product": a.get("minutes_per_product"),
                           "gbp_per_unit": a.get("gbp_per_unit"),
                           "hours_at": a.get("hours_at"), "basis": a.get("basis")})
    for line in result["engine_lines"]:
        if line.get("holds"):
            issues.append({"code": "engine_line_unconfirmed", "item": f"line:{line['record']}",
                           "part": line["record"], "class": line["class"],
                           "basis": line.get("basis")})
    counts = {s: sum(1 for e in out_items if e["state"] == s)
              for s in WORK_STATES + (CARRIED, CORRECTED, REFERENCE)}
    result.update(counts=counts, passed=not issues, verified=book.calculated,
                  workbook_sha256=(snapshot or {}).get("sha256"),
                  raw_sha256=ledger.get("raw_sha256"), read_key=ledger.get("read_key"))
    return result


def _quantities(summary: Mapping[str, Any]) -> List[int]:
    qs: Set[int] = set()
    sweep = summary.get("quantity_sweep") if isinstance(summary.get("quantity_sweep"), Mapping) else {}
    for q in [summary.get("requested_order_quantity")] + [
            s.get("quantity") for s in (sweep.get("rows") or []) if isinstance(s, Mapping)]:
        n = fcc.number(q)
        if n and n >= 1:
            qs.add(int(n))
    for q in str(os.environ.get("SDI_QUANTITY_BREAKS") or "").split(","):
        n = fcc.number(q.strip()) if q.strip() else None
        if n and n >= 1:
            qs.add(int(n))
    return sorted(qs) or [1]


def _allowances(summary: Mapping[str, Any], book: _Book, ledger: Mapping[str, Any],
                traced_labour: Set[Tuple[Any, str, str]], traced_material: Set[str],
                result: Dict[str, Any]) -> None:
    """Every calculated charge no read item explains, with its basis and whether it holds."""
    basis_of = dict(_cfg("ENGINE_ALLOWANCE_BASIS", {}) or {})
    holding = set(_cfg("ENGINE_ALLOWANCE_HOLDING_CLASSES", ()) or ())
    read_parts = {_pn(i.get("record")) for i in (ledger.get("items") or [])
                  if isinstance(i, Mapping) and i.get("kind") == "part" and i.get("record")}
    unit = _pn(ledger.get("unit"))
    quantities = _quantities(summary)
    cut_ops = set(_cfg("READ_PROFILE_CUTS", ())) | {"saw", "guillotine", "tube", "tube_laser"}

    def follows(source: str, pn: str) -> bool:
        """A derived charge stands only where what it follows from is charged on that part:
        the part itself is a read part (its own cut), its cut is charged (its deburr), or the
        operation it follows is charged on it (dressing after welding)."""
        if source == "part":
            return pn in read_parts or pn == unit
        if source == "cut":
            return pn in read_parts and bool(book.charged_rows(pn, cut_ops))
        if source:
            return bool(book.charged_rows(pn, _families(source)))
        return True

    seen: Set[Tuple[str, str]] = set()
    for l in book.labour:
        if not ((l["hours"] or 0) > 0 or (l["value"] or 0) > 0):
            continue
        for op in sorted(l["ops"]):
            for pn in sorted(l["parts"]):
                if (l["wb_row"], op, pn) in traced_labour or (op, pn) in seen:
                    continue
                seen.add((op, pn))
                spec = basis_of.get(op) or {}
                cls = str(spec.get("class") or "unclassified")
                note = str(spec.get("basis") or "no basis stated for this engine charge")
                source = str(spec.get("from") or "")
                if cls == "derived" and not follows(source, pn):
                    cls = "unclassified"
                    note = f"{note} — and nothing it follows from is charged for {pn}"
                cost = book.costs.get(pn) or {}
                pe = cost.get("process_estimate") if isinstance(cost.get("process_estimate"), Mapping) else {}
                per_piece = fcc.number((pe.get("run_times_min_per_unit") or {}).get(op))
                qty = fcc.number(cost.get("quantity")) or 1.0
                minutes = round(per_piece * qty, 2) if per_piece is not None else None
                ruling = book.rulings.get(f"allowance:{op}")
                confirmed = bool(ruling and ruling.get("ruling") == "confirmed")
                dedicated = l["ops"] == {op} and l["parts"] == {pn}
                # ITS COST A UNIT, at the row's own department rate where the sheet states one,
                # else the rate card's: run minutes only — the row's set-up is spread by Excel.
                rate = (fcc.cached_number(l["row"].get("dept_rate_gbp_per_hour"))
                        or fcc.number((_cfg("HOURLY_RATES_GBP", {}) or {}).get(op)))
                gbp = round(minutes / 60.0 * rate, 2) if minutes is not None and rate else None
                result["allowances"].append({
                    "operation": op, "part": pn, "class": cls, "basis": note,
                    "row": l["title"], "cell": l["cell"],
                    "minutes_per_product": minutes,
                    "hours_at": ({str(q): round(minutes * q / 60.0, 1) for q in quantities}
                                 if minutes is not None else {}),
                    "rate_gbp_per_hour": rate, "gbp_per_unit": gbp,
                    "gbp_per_unit_on_sheet": l["value"] if dedicated else None,
                    "confirmed": (f"confirmed for this job by {book.decided_by}: "
                                  f"{ruling.get('reason')}" if confirmed else ""),
                    "holds": cls in holding and not confirmed})
    origins = {_pn(e.get("record")): e for e in (ledger.get("engine_lines") or [])
               if isinstance(e, Mapping)}
    for pn, rows in sorted(book.material.items()):
        if pn in traced_material or pn in read_parts:
            continue
        cost = book.costs.get(pn) or book.records.get(pn) or {}
        origin = str((origins.get(pn) or {}).get("origin") or "")
        try:
            from commercial_lines import is_commercial_line          # noqa: WPS433
            commercial = bool(is_commercial_line(cost)) or pn in ("PACKAGING", "DELIVERY")
        except Exception:                                            # noqa: BLE001
            commercial = pn in ("PACKAGING", "DELIVERY")
        if commercial:
            cls, note = "shop_standard", "a commercial line on its own basis (the order's packing and carriage)"
        elif pn.endswith("-PLATE") or cost.get("_plating_placeholder"):
            cls, note = "derived", "the plating a stated finish asks for"
        elif pn == "PLATERFREIGHT":
            cls, note = "derived", "carriage to and from the plater, which the plating needs"
        elif origin in ("unit", "engine:print_line", "engine:adhesive_allowance",
                        "read:named_inside_another_line", "read:not_visible"):
            cls, note = "derived", {
                "unit": "the product as an assembly of the read's parts",
                "engine:print_line": "a print the read's own words describe on a panel",
                "engine:adhesive_allowance": "the adhesive of a bonded joint the read states",
                "read:named_inside_another_line": "a component the read names inside another line",
                "read:not_visible": "a consumable the read names as not visible"}[origin]
        elif origin in ("engine:implied_fitting", "engine:fixings_allowance"):
            cls, note = "inferred_purchase", ("a fitting no read item names, implied by a rule"
                                              if origin == "engine:implied_fitting" else
                                              "fixings no read item names")
        elif origin in ("read:link_ambiguous", "read:id_not_in_this_read"):
            cls, note = "unclassified", (
                "a record more than one read line could be, linked to none — rule which line "
                "it is" if origin == "read:link_ambiguous" else
                "a record made from a read line this read does not contain")
        else:
            cls, note = "unclassified", "an engine line with no stated basis"
        ruling = book.rulings.get(f"line:{pn}".lower())
        confirmed = bool(ruling and ruling.get("ruling") == "confirmed")
        result["engine_lines"].append({
            "record": pn, "class": cls, "basis": note,
            "gbp_on_sheet": sum(fcc.cached_number(r.get("total_value_gbp")) or 0 for r in rows),
            "cells": [r.get("charged_cell") for r in rows],
            "holds": cls in holding and not confirmed})
    _held_cost(summary, result, quantities)


def _held_cost(summary: Mapping[str, Any], result: Dict[str, Any], quantities: List[int]) -> None:
    """What the held allowances cost, and the priced subtotal excluding them (review of D-596).
    Holding the release is right; a headline that carries 867 unconfirmed hours at 1,000 off is
    still not a budget, so the record says how much of each unit cost rests on them and what
    the unit cost is without them — at the sheet's quantity and at every break the sweep
    calculated. The subtotal is NOT a supported cost: the work still unresolved is priced in
    neither figure, so it is counted and named beside them, never folded in."""
    held = [a for a in result.get("allowances") or [] if a.get("holds")]
    lines = [l for l in result.get("engine_lines") or [] if l.get("holds")]
    if not held and not lines:
        result["held_allowances"] = {}
        return
    per_unit = round(sum(a.get("gbp_per_unit") or 0 for a in held)
                     + sum(l.get("gbp_on_sheet") or 0 for l in lines), 2)
    unpriced = sorted({a["operation"] for a in held if a.get("gbp_per_unit") is None})
    final = summary.get("final_estimate") if isinstance(summary.get("final_estimate"), Mapping) else {}
    unit = fcc.cached_number((final.get("totals") or {}).get("unit_gbp"))
    sweep = summary.get("quantity_sweep") if isinstance(summary.get("quantity_sweep"), Mapping) else {}
    at_breaks = []
    for row in (sweep.get("rows") or []):
        q, u = fcc.number((row or {}).get("quantity")), fcc.number((row or {}).get("unit"))
        if q and u is not None:
            at_breaks.append({"quantity": int(q), "unit_gbp": round(u, 2),
                              "held_gbp_per_unit": per_unit,
                              "unit_excluding_held_gbp": round(u - per_unit, 2)})
    hours: Dict[str, float] = {}
    for a in held:
        for q, h in (a.get("hours_at") or {}).items():
            hours[q] = round(hours.get(q, 0.0) + float(h or 0), 1)
    result["held_allowances"] = {
        "operations": sorted({a["operation"] for a in held}),
        "lines": sorted(l["record"] for l in lines),
        "minutes_per_unit": round(sum(a.get("minutes_per_product") or 0 for a in held), 2),
        "hours_at": hours, "gbp_per_unit": per_unit,
        "not_costed": unpriced,
        "unit_gbp": unit,
        "unit_excluding_held_gbp": round(unit - per_unit, 2) if unit is not None else None,
        "at_breaks": at_breaks,
        "unresolved_work": [e["id"] for e in result.get("items") or []
                            if e.get("state") == UNRESOLVED],
        "note": ("run minutes at the row's department rate; each row's set-up is spread by "
                 "Excel and is not separated here")}


def record(summary: Dict[str, Any], workbook_path: Any = None) -> Dict[str, Any]:
    """Audit against the saved workbook and write the result on the record. A failure of the
    checker is a finding; a workbook not to hand where a ledger exists is a finding."""
    try:
        snapshot = fcc.snapshot_xlsx(workbook_path) if workbook_path else None
        result = audit(summary, snapshot)
        if result.get("applicable") and not workbook_path:
            result["issues"].append({"code": "final_workbook_not_verified", "item": "", "part": ""})
            result["passed"] = False
    except Exception as exc:                                         # noqa: BLE001
        result = {"schema": SCHEMA, "applicable": True, "passed": False, "items": [],
                  "allowances": [], "engine_lines": [],
                  "issues": [{"code": "read_charge_audit_failed", "item": "", "part": "",
                              "text": f"{type(exc).__name__}: {exc}"}]}
    summary["read_charge_result"] = result
    if result.get("applicable"):
        c = result.get("counts") or {}
        held = [a for a in result.get("allowances") or [] if a.get("holds")]
        print(f"   [read-ledger] {sum(c.get(s, 0) for s in WORK_STATES)} item(s) of work the read "
              f"returned: {c.get(CHARGED, 0)} charged, {c.get(COVERED, 0)} covered, "
              f"{c.get(EXCLUDED, 0)} excluded, {c.get(UNRESOLVED, 0)} unresolved; facts "
              f"{c.get(CARRIED, 0)} carried, {c.get(CORRECTED, 0)} corrected; "
              f"{len(held)} engine allowance(s) holding the release", flush=True)
        for i in (result.get("issues") or [])[:12]:
            print(f"   [read-ledger] {i.get('item') or i.get('code')}: "
                  f"{i.get('why') or i.get('basis') or i.get('code')}", flush=True)
    return result
