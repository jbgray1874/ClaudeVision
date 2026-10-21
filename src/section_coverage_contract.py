"""A section schedule printed on a part's own sheet reaches the priced sheet, or the book
says it did not (D-576).

THE CONTRACT. A requirement the engine reads correctly can still be lost on the way through
parts, routes and workbook rows: 401918-01-07M's sheet prints a headed cut list, "ITEM
DESCRIPTION LENGTH QTY / 1 50 x 20 x 2mm TUBE 703 1 / 2 ... 154 2", the text layer carried
it, and four books in a row priced 0 mm of it. Three rules closed three roads it was lost
by, and the fourth book still lost it by another. So, beside the rules, a contract: the
requirement is captured from the sheet's own words once, before costing; a part that holds
no stock and no members is given those pieces through the ordinary precedence (D-557 costs
a memberless weldment as a part); and at the hand-off to the workbook the priced lengths
are reconciled against the requirement, with the cut required to have survived into the
compiled route. Method and audit as proposed in the Codex review package of 21 Oct 2026,
merged into the engine's own structure.

WHAT A FAILURE DOES. The package stopped the run with no workbook and no quotation. The
house pattern is the one the memberless check (D-560) already follows: a BLOCKING invariant
at the top of the decisions list, the release held, the estimator still given the book —
"work towards a price, never a silent nothing". So the audit's findings are recorded on the
record (`section_coverage_result`) and invariants.check_a_section_schedule_reaches_the_sheet
raises them; nothing here aborts, and a headed table this reader cannot parse is a finding,
not a refusal to produce anything.

ONE READER OF A SECTION. The rows are read by section_profile.detect_section_stock, the
reader every other section in the engine goes through, within the gates the package set:
only an explicitly headed ITEM / DESCRIPTION / LENGTH / QTY table, on a sheet whose title
block names exactly one record, read as full rows with consecutive item numbers. Nothing is
guessed: an unreadable row, two tables on a sheet, or two sheets that disagree are issues on
the owner, and the repair declines a record that has members, mixed profiles, a bought-in
standing or a measured flat.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "section_coverage.v1"
HEADER = re.compile(r"^\s*ITEM\s+DESCRIPTION\s+LENGTH\s+QTY\s*$", re.I)
# "<item> <words of the section and its length> <qty>": the item and the count are the
# table's own columns; what lies between is the section reader's.
ROW = re.compile(r"^\s*(\d+)\s+(.+?)\s+(\d+)\s*$")
ROW_STARTS_LIKE_A_SECTION = re.compile(r"^\s*\d+\s+\d+(?:\.\d+)?\s*[x×]", re.I)
CUT_OPERATIONS = {"saw", "tube_cut", "tube_laser", "laser_cutting"}


def code(value: Any) -> str:
    return str(value or "").strip().upper()


def positive(value: Any) -> Optional[float]:
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (ValueError, TypeError):
        return None


def parts_of(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (summary.get("manufacturing_writeup") or {}).get("parts") or []


def profile(stock: Any) -> Optional[Tuple[float, float, float, str]]:
    """The section as a key: (smaller side, larger side, wall, form)."""
    if not isinstance(stock, dict):
        return None
    vals = [positive(stock.get(k)) for k in ("a", "b", "t")]
    if not all(vals):
        return None
    a, b, t = vals
    if t * 2 >= min(a, b):
        return None
    return (round(min(a, b), 4), round(max(a, b), 4), round(t, 4),
            code(stock.get("profile_form")) or "RHS")


def parse_table(text: Any) -> Optional[Dict[str, Any]]:
    """The headed table's rows, read with the engine's section reader, or an error naming
    the line that stopped the read. None where the sheet prints no such table."""
    from section_profile import detect_section_stock
    lines = str(text or "").splitlines()
    starts = [i for i, line in enumerate(lines) if HEADER.fullmatch(line)]
    if not starts:
        return None
    if len(starts) != 1:
        return {"error": "multiple cut-list tables on one sheet"}
    rows: List[Dict[str, Any]] = []
    for line in lines[starts[0] + 1:]:
        if not line.strip():
            continue
        m = ROW.fullmatch(line)
        sec = detect_section_stock(m.group(2)) if m else None
        if not m or not sec or sec.get("detection_path") != "canonical_profile" \
                or not positive(sec.get("length_mm")):
            # A dimension or callout after the table is not another row; a line that
            # begins like a row and cannot be read is a finding, never dropped.
            if ROW_STARTS_LIKE_A_SECTION.match(line):
                return {"error": "unread section row", "text": line.strip()}
            break
        item, qty = int(m.group(1)), int(m.group(3))
        key = profile(sec)
        if not key or qty < 1 or qty > 10000:
            return {"error": "invalid section dimensions or quantity", "text": line.strip()}
        if item != len(rows) + 1:
            return {"error": "non-consecutive/duplicate cut-list items", "text": line.strip()}
        rows.append({"item": item, "profile": list(key), "length_mm": float(sec["length_mm"]),
                     "quantity": qty, "text": line.strip()})
    return {"rows": rows} if rows else {"error": "headed cut list has no readable rows"}


def capture(summary: Dict[str, Any]) -> Dict[str, Any]:
    """The requirements, from each sheet's own text, keyed on the one record its title block
    names — never from a costed record."""
    records = {code(p.get("part_number")) for p in parts_of(summary)}
    requirements: Dict[str, Dict[str, Any]] = {}
    issues: List[Dict[str, Any]] = []
    for page in summary.get("pages") or []:
        if not isinstance(page, dict):
            continue
        if code(page.get("document_role")) in {"REFERENCE", "EXAMPLE", "SUPERSEDED"}:
            continue
        tb = (page.get("page_analysis") or {}).get("title_block") or {}
        owners = {code(x) for x in (tb.get("drawing_numbers") or []) if code(x) in records}
        if len(owners) != 1:              # ambiguous ownership authorises nothing
            continue
        owner = next(iter(owners))
        reading = parse_table(page.get("pdfplumber_text") or page.get("pypdf_text"))
        if reading is None:
            continue
        source = {"file": page.get("source_pdf_name") or page.get("source_pdf_path"),
                  "page": page.get("job_page_number") or page.get("page_number")}
        if "error" in reading:
            issues.append({"part": owner, "code": "unread_cut_list", **reading, "source": source})
            continue
        req = {"part": owner, "rows": reading["rows"], "source": source}
        if owner in requirements and requirements[owner]["rows"] != req["rows"]:
            issues.append({"part": owner, "code": "conflicting_cut_lists", "source": source})
        else:
            requirements[owner] = req
    return {"schema": SCHEMA, "requirements": list(requirements.values()), "issues": issues}


def _pieces(rows: List[Dict[str, Any]]) -> List[float]:
    return sorted(length for r in rows for length in [r["length_mm"]] * r["quantity"])


def prepare(summary: Dict[str, Any]) -> List[str]:
    """Give a record that holds no members and no pieces the schedule its own sheet prints,
    through the ordinary precedence; a stronger reading stands and is recorded as a
    conflict. Returns the records changed."""
    contract = capture(summary)
    summary["section_coverage_contract"] = contract
    records = {code(p.get("part_number")): p for p in parts_of(summary)}
    changed: List[str] = []
    for req in contract["requirements"]:
        owner = req["part"]
        if any(i["part"] == owner for i in contract["issues"]):
            continue
        p = records[owner]
        children = {code(c) for c in p.get("assembly_children") or []} & records.keys()
        children |= {pn for pn, child in records.items() if pn != owner and
                     owner in {code(child.get(k)) for k in
                               ("bom_parent", "owning_assembly", "cut_list_member_of")}}
        profiles = {tuple(r["profile"]) for r in req["rows"]}
        if children or len(profiles) != 1 or p.get("is_bought_in") or \
                p.get("dxf_measured_outline") or p.get("native_flat_pattern"):
            continue
        pieces = _pieces(req["rows"])
        a, b, t, form = next(iter(profiles))
        candidate = deepcopy(p)
        import source_precedence as sp
        for field, value in {"a": a, "b": b, "t": t, "profile_form": form,
                             "cut_lengths_mm": pieces, "length_mm": max(pieces)}.items():
            sp.apply_field(candidate, "section_stock." + field, value, "drawing_deterministic")
        ss = candidate.get("section_stock") or {}
        if profile(ss) != (a, b, t, form) or sorted(ss.get("cut_lengths_mm") or []) != pieces:
            contract["issues"].append({"part": owner, "code": "stronger_section_conflict",
                                       "source": req["source"]})
            continue
        if p.get("weldment_from_own_cut_list") and not p.get("is_assembly_parent") and \
                profile(p.get("section_stock") or {}) == (a, b, t, form) and \
                sorted((p.get("section_stock") or {}).get("cut_lengths_mm") or []) == pieces:
            continue                      # a second pass changes nothing
        ss.update(source="drawing_deterministic", detection_path="canonical_profile",
                  source_text="\n".join(r["text"] for r in req["rows"]))
        # THE RECORD SAYS IT IS A PART, as D-557/D-574 say it: the costing reads these flags.
        candidate.update(is_assembly_parent=False, is_sub_assembly=False,
                         weldment_from_own_cut_list=True)
        if code(candidate.get("canonical_kind")) == "ASSEMBLY":
            candidate["canonical_kind"] = "part"
        if candidate.get("assembly_children"):
            candidate["cut_list_bodies_named_by_model"] = list(candidate["assembly_children"])
            candidate["assembly_children"] = []
        candidate["section_coverage_repair"] = {"source": req["source"], "pieces_mm": pieces}
        _withdraw_provisional_blank(candidate)
        candidate.setdefault("review_flags", []).append(
            f"{p.get('part_number')} holds no member and no pieces, and its own sheet "
            f"(page {req['source'].get('page')}) prints a cut list: costed as a weldment cut "
            f"from those pieces ({', '.join(f'{v:g}' for v in pieces)} mm) (D-576)")
        p.clear()
        p.update(candidate)
        changed.append(owner)
    return changed


_PROVISIONAL_BLANK_WORDS = "PROVISIONAL BLANK, NOT A MEASURED ONE"


def _withdraw_provisional_blank(p: Dict[str, Any]) -> None:
    """A record that is section stock has no sheet blank (D-577). The sheet-size pass had
    given the frame a provisional 803 x 354 blank developed for ten folds, and that
    question stayed open on the book beside the cut list that answers it."""
    try:
        from detail_page_geometry import PROVISIONAL_SOURCE as _prov
    except Exception:                                                 # noqa: BLE001
        _prov = "printed_extents_provisional"
    holders = [p] + ([p["normalized_geometry"]] if isinstance(p.get("normalized_geometry"), dict) else [])
    for h in holders:
        if str(h.get("blank_length_mm_source") or "") == _prov or str(h.get("blank_width_mm_source") or "") == _prov:
            for k in ("blank_length_mm", "blank_width_mm", "blank_length_mm_source", "blank_width_mm_source"):
                h.pop(k, None)
    for k in ("_blank_provisional", "blank_is_inferred", "blank_inferred_reason"):
        p.pop(k, None)
    p["review_flags"] = [f for f in (p.get("review_flags") or [])
                         if not (isinstance(f, str) and f.startswith(_PROVISIONAL_BLANK_WORDS))]
    p["manufacturing_questions"] = [
        q for q in (p.get("manufacturing_questions") or [])
        if not (isinstance(q, dict) and str(q.get("issue") or "").startswith("Blank of ")
                and "provisional" in str(q.get("issue") or ""))]


def _row_code(row: Dict[str, Any]) -> str:
    c = str(row.get("part_code") or row.get("part_number") or "").strip()
    if not c:
        words = str(row.get("description") or "").split()
        c = words[0] if words else ""
    return c.upper()


def audit_sheet(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The second stage (D-577): what the sheet actually wrote, read back. The hand-off
    audit passed 07M on the 18:09 book — the canonical line carried 1011 mm and a price —
    and the writer then left it off as an assembly's material. A requirement is met on the
    sheet when a material row of the owner, or of one of its cut-list members, carries a
    value; where the read-back did not run there is nothing to judge, and nothing is said."""
    contract = summary.get("section_coverage_contract") or capture(summary)
    final = summary.get("final_estimate") if isinstance(summary.get("final_estimate"), dict) else {}
    rows = [r for r in (final.get("material_rows") or []) if isinstance(r, dict)]
    if not rows:
        return []
    records = {code(p.get("part_number")): p for p in parts_of(summary)}
    issues: List[Dict[str, Any]] = []
    for req in contract.get("requirements") or []:
        owner = req["part"]
        members = {owner} | {pn for pn, rec in records.items()
                             if code(rec.get("cut_list_member_of")) == owner}
        value = sum(positive(r.get("total_value_gbp")) or 0.0 for r in rows if _row_code(r) in members)
        if value <= 0:
            expected = sum(r["length_mm"] * r["quantity"] for r in req["rows"])
            issues.append({"part": owner, "code": "section_not_on_the_sheet",
                           "expected_mm_per_owner": expected, "source": req["source"]})
    return issues


def audit(summary: Dict[str, Any], estimates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expected length per product against priced length per product at the hand-off, by
    profile; and, where a route was compiled, a cut on every priced piece. No cost is
    invented; a correctly scoped but unpriced line is a finding."""
    contract = summary.get("section_coverage_contract") or capture(summary)
    issues = deepcopy(contract.get("issues") or [])
    records = {code(p.get("part_number")): p for p in parts_of(summary)}
    costs = {code(p.get("part_number")): p for p in estimates if isinstance(p, dict)}
    route = ((summary.get("estimate_summary") or {}).get("canonical_route_shadow")
             or summary.get("canonical_route_shadow") or {})
    nodes = {code(n.get("part_number")): n for n in route.get("nodes") or [] if isinstance(n, dict)}
    for req in contract.get("requirements") or []:
        owner = req["part"]
        own = costs.get(owner)
        if own is None:
            issues.append({"part": owner, "code": "section_owner_missing_from_costing",
                           "source": req["source"]})
            continue
        qty = positive((nodes.get(owner) or {}).get("qty_per_unit")) or positive(own.get("quantity"))
        if qty is None:
            issues.append({"part": owner, "code": "section_owner_quantity_missing",
                           "source": req["source"]})
            continue
        expected: Counter = Counter()
        for row in req["rows"]:
            expected[tuple(row["profile"])] += row["length_mm"] * row["quantity"] * qty
        actual: Counter = Counter()
        for pn, rec in records.items():
            if pn != owner and code(rec.get("cut_list_member_of")) != owner:
                continue
            cost = costs.get(pn)
            if not cost:
                continue
            mat = cost.get("material_estimate") or {}
            key = profile(rec.get("section_stock") or {})
            if key not in expected:
                continue
            paid = positive(mat.get("unit_material_cost_gbp")) or positive(mat.get("cost_per_part_gbp"))
            length = positive((mat.get("stock_estimate") or {}).get("section_length_mm"))
            count = positive(cost.get("quantity"))
            if not paid or not length or not count or cost.get("set_aside"):
                continue
            actual[key] += length * count
            if route:
                cut_rows = [r for r in route.get("priced_route_rows") or []
                            if isinstance(r, dict) and r.get("operation") in CUT_OPERATIONS
                            and pn in ({code(r.get("target_id"))}
                                       | {code(x) for x in r.get("participants") or []}
                                       | {code(x) for x in r.get("part_numbers") or []})]
                if not cut_rows:
                    issues.append({"part": pn, "code": "section_cut_missing_from_final_route",
                                   "source": req["source"]})
        for key, length in expected.items():
            if not math.isclose(actual[key], length, rel_tol=1e-6, abs_tol=0.01):
                issues.append({"part": owner, "code": "section_material_coverage_mismatch",
                               "profile_mm": list(key[:3]), "expected_mm_per_product": length,
                               "priced_mm_per_product": actual[key], "source": req["source"]})
    return issues


def record_coverage(summary: Dict[str, Any], estimates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Audit at the hand-off and write the result on the record for the invariant to raise.
    Never raises: the book is produced and says what was not priced."""
    try:
        issues = audit(summary, estimates)
    except Exception as exc:                                         # noqa: BLE001
        issues = [{"part": "", "code": "section_coverage_audit_failed",
                   "text": f"{type(exc).__name__}: {exc}"}]
    summary["section_coverage_result"] = {"schema": SCHEMA, "issues": issues,
                                          "passed": not issues}
    if issues:
        print("   [section-coverage] " + "; ".join(
            f"{i.get('part') or 'the audit'}: {i['code']}" for i in issues), flush=True)
    return estimates
