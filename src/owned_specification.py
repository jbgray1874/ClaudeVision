"""Preserve owned specifications and require evidence for DXF role multiplicities.

No job numbers, material brands, inferred panel counts or price rules live here.
An unknown printed material is still a specification. A role filename is not a
quantity. These adapters feed the existing record and release invariants.
"""
from __future__ import annotations

import math
import re


def identity(value):
    # Do not erase hyphens: different drawing identities must not alias here.
    return str(value or "").strip().upper()


def own_material(part, pages):
    """Return one unambiguous unresolved title-block callout with its locator."""
    code = identity(part.get("part_number"))
    found = []
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        tb = (page.get("page_analysis") or {}).get("title_block") or {}
        owners = {identity(v) for v in tb.get("drawing_numbers") or []}
        text = str(tb.get("material_stated_unresolved") or "").strip()
        if code and owners == {code} and text:
            found.append({"value": text, "part": code,
                          "page": page.get("page_number"),
                          "source": "drawing_deterministic"})
    if len({x["value"].upper() for x in found}) == 1:
        return found[0]
    return None


def retain_own_material(part, pages, submit):
    evidence = own_material(part, pages)
    if not evidence:
        return False
    part["material_stated"] = evidence["value"]
    part["owned_material_evidence"] = evidence
    # Submit even when a weaker normalised value already exists. Never assign
    # directly over an estimator's stronger correction or a typed CAD spec.
    from json_normaliser import normalise_material
    from drawing_job_merge import material_from_drawing_text
    resolved = (normalise_material(evidence["value"])
                or material_from_drawing_text(evidence["value"]))
    accepted = submit(part, "normalized_material", resolved or evidence["value"],
                      "drawing_deterministic")
    if accepted:
        part["material_text_as_printed"] = evidence["value"]
        if not resolved:
            # Costed under words the book cannot name: never a silent stock or price.
            part.setdefault("review_flags", []).append(
                f"MATERIAL AS PRINTED: {part.get('part_number')}'s own sheet states "
                f"'{evidence['value']}', which the material book does not name. It is "
                f"carried as printed, not replaced by another material. Say its stock "
                f"and its price.")
    return accepted


def _count(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0 and float(value).is_integer())


def valid_role_evidence(entry, parent, role):
    if not isinstance(entry, dict):
        return False
    who = str(entry.get("decided_by") or "").strip()
    return bool(identity(entry.get("parent")) == identity(parent)
                and identity(entry.get("role")) == identity(role)
                and _count(entry.get("quantity")) and entry.get("basis") == "per_parent"
                and str(entry.get("evidence") or "").strip()
                and who and who.lower() not in {"an estimator", "unknown"})


def role_count_preserved(piece):
    e = piece.get("dxf_role_quantity_evidence")
    return bool(valid_role_evidence(e, piece.get("dxf_minted_piece_of"), piece.get("dxf_piece_role"))
                and piece.get("quantity") == e["quantity"]
                and piece.get("bom_parents") == [{"parent": e["parent"], "qty": e["quantity"]}])


def apply_role_counts(summary):
    """Apply named estimator counts per parent, never order or rolled quantities.

    Input: estimator_decisions.dxf_role_quantities is a list with parent, role,
    quantity, basis='per_parent', evidence and decided_by. All are required.
    Duplicate rulings, duplicate role identities and unmatched entries are errors.
    Returns diagnostics, also retained on the summary for the release check.
    """
    parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    decisions = summary.get("estimator_decisions") or {}
    entries = decisions.get("dxf_role_quantities") or []
    problems = []
    if not isinstance(entries, list):
        entries = []
        problems.append("Role quantities must be a list of evidenced per-parent rulings.")
    keys = [(identity(e.get("parent")), identity(e.get("role")))
            for e in entries if isinstance(e, dict)]
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append("Malformed role quantity ruling.")
            continue
        key = identity(entry.get("parent")), identity(entry.get("role"))
        matches = [p for p in parts if isinstance(p, dict)
                   and identity(p.get("dxf_minted_piece_of")) == key[0]
                   and identity(p.get("dxf_piece_role")) == key[1]]
        valid = (all(key) and keys.count(key) == 1 and len(matches) == 1
                 and valid_role_evidence(entry, *key))
        if not valid:
            problems.append(f"Role quantity for {key[0]} / {key[1]} is missing, ambiguous or not evidenced per parent.")
            continue
        piece = matches[0]
        if piece.get("dxf_role_quantity_evidence") == entry and role_count_preserved(piece):
            continue
        existing = piece.get("bom_parents") or []
        if any(not isinstance(e, dict) or identity(e.get("parent")) != key[0]
               for e in existing):
            problems.append(f"Role piece {piece.get('part_number')} has another parent; no count changed.")
            continue
        from source_precedence import apply_field, source_of
        apply_field(piece, "quantity", entry["quantity"], "estimator_confirmed")
        if (piece.get("quantity") == entry["quantity"] and
                source_of(piece, "quantity") == "estimator_confirmed"):
            piece["bom_parents"] = [{"parent": entry["parent"], "qty": entry["quantity"]}]
            piece["dxf_role_quantity_evidence"] = dict(entry)
    for parent in parts:
        if not isinstance(parent, dict) or not parent.get("dxf_pieces"):
            continue
        children = [p for p in parts if isinstance(p, dict) and
                    identity(p.get("dxf_minted_piece_of")) == identity(parent.get("part_number"))]
        expected = {identity(p.get("costed_as")) for p in parent["dxf_pieces"] if isinstance(p, dict)}
        if (children and {identity(p.get("part_number")) for p in children} == expected
                and all(role_count_preserved(p) for p in children)):
            parent["manufacturing_questions"] = [q for q in parent.get("manufacturing_questions") or []
                    if not isinstance(q, dict) or q.get("subject") != "dxf_piece_count"]
    summary["role_quantity_input_issues"] = problems
    return problems


def review_cautions(summary):
    """Evidence that prevents an unqualified clean-report claim, not a release gate."""
    out = []
    for name in ("material_charge_result", "normal_pdf_audit"):
        result = summary.get(name)
        if isinstance(result, dict) and (result.get("passed") is False or
                result.get("issues") or result.get("findings") or result.get("unverified")):
            out.append(f"{name}: unresolved evidence remains ({result.get('mode') or 'audit'}); not an acceptance pass.")
    for issue in (summary.get("invariants") or {}).get("violations") or []:
        if issue.get("code") in {"two_sources_disagree_about_the_material",
                                 "material_priced_from_a_lower_ranked_reading",
                                 "owned_specification_not_preserved"}:
            out.append(str(issue.get("message") or issue["code"]))
    return out


def role_charge_issues(summary, pieces):
    """Check evidenced local counts against the calculated per-product material rows.

    This supplements, not replaces, the existing saved-XLSX/hash contract. It does
    not infer a missing parent count or verify other quantity-break workbooks.
    """
    final = summary.get("final_estimate")
    if not isinstance(final, dict):
        return []  # read-back availability is owned by the existing release checks
    graph = (summary.get("estimate_summary") or {}).get("canonical_route_shadow") or {}
    nodes = graph.get("nodes") or []
    out = []
    for piece in pieces:
        if not role_count_preserved(piece):
            continue
        e = piece["dxf_role_quantity_evidence"]
        parents = [n for n in nodes if identity(n.get("part_number")) == identity(e["parent"])]
        pn = identity(piece.get("part_number"))
        if len(parents) != 1 or not _count(parents[0].get("qty_per_unit")):
            out.append(f"{pn}: cannot establish the parent's per-product count for the charged role.")
            continue
        expected = e["quantity"] * parents[0]["qty_per_unit"]
        rows = [r for r in final.get("material_rows") or []
                if identity(r.get("part_number")) == pn or
                str(r.get("description") or "").upper().startswith(pn + " ")]
        if (len(rows) != 1 or not _count(rows[0].get("qty_per_unit")) or
                rows[0]["qty_per_unit"] != expected):
            out.append(f"{pn}: expected {expected:g} per product from its evidenced role count; calculated material rows do not show exactly one matching charge at that count.")
        else:
            value = rows[0].get("total_value_gbp")
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or value <= 0 or not rows[0].get("charged_cell")):
                out.append(f"{pn}: the role quantity is present but its calculated material charge is not evidenced and positive.")
    return out


# The drawing office's own word for a part's material; mirrors the estimator's rescue guard.
DRAWING_OFFICE_MATERIAL_SOURCES = ("estimator_confirmed", "estimator_read_drawing",
                                   "drawing_deterministic", "title_block", "dxf_filename",
                                   "drawn_on_sheet")


def _same_material(a, b):
    return identity(a).replace("_", " ") == identity(b).replace("_", " ")


def _same_family(a, b):
    """One material by the estimator's own family names: "MR MDF" is priced as MDF, and that
    is the part's own material, not a substitute (D-598p)."""
    try:
        from estimator import _canonical_material_family as family
        return _same_material(family(a) or a, family(b) or b)
    except Exception:                                                # noqa: BLE001
        return _same_material(a, b)


def drawing_office_material(part):
    """The part's material, where the drawing office (or an estimator) named it; else None."""
    material = part.get("normalized_material")
    if not material:
        return None
    from source_precedence import source_of
    won = str(source_of(part, "normalized_material") or "")
    if part.get("owned_material_evidence") or any(
            won.startswith(s) for s in DRAWING_OFFICE_MATERIAL_SOURCES):
        return material
    return None


def priced_as_issues(summary, parts):
    """A specified material is charged as itself, on its own block (D-598o).

    9287-10-005 read SOLID SURFACE from its flat's name, and the pricing step costed it as
    12 mm steel on the Sheet Steel block because steel has a rate. A missing price is a price
    to find; it must never change what the part is made of on the charged row.
    """
    costed = {identity(p.get("part_number")): p
              for p in ((summary.get("estimate_summary") or {}).get("part_estimates") or [])
              if isinstance(p, dict)}
    final = summary.get("final_estimate") if isinstance(summary.get("final_estimate"), dict) else {}
    rows = [r for r in final.get("material_rows") or [] if isinstance(r, dict)]
    out = []
    for part in parts:
        material = drawing_office_material(part)
        if not material:
            continue
        pn = identity(part.get("part_number"))
        # A bad transfer need not leave a substitution stamp. Compare the
        # actual pricing payload too, even when both materials use one block.
        priced = (costed.get(pn) or {}).get("material_estimate")
        if not isinstance(priced, dict):
            priced = part.get("material_estimate")
        actual = priced.get("material") if isinstance(priced, dict) else None
        mismatch = bool(actual and not _same_family(actual, material))
        if mismatch:
            cells = sorted({str(r["charged_cell"]) for r in rows
                            if r.get("charged_cell") and
                            (identity(r.get("part_number") or r.get("part_code")) == pn or
                             str(r.get("description") or "").upper().startswith(pn + " "))})
            location = (f" Calculated material cell(s): {', '.join(cells)}."
                        if cells else " No matching calculated material cell is recorded.")
            out.append(f"{pn}: the drawing office specifies {material}, but the actual "
                       f"material estimate prices {actual}.{location} Reprice the specified "
                       f"material or correct its specification through a sourced ruling.")
        for rec in (part, costed.get(pn) or {}):
            if mismatch:
                break  # the pricing payload already names this failure
            swap = rec.get("material_priced_as")
            if (isinstance(swap, dict) and swap.get("priced_material")
                    and not _same_material(swap["priced_material"], material)):
                out.append(f"{pn}: the drawing office specifies {material}, and it was priced "
                           f"as {swap['priced_material']}. A missing price must not change the "
                           f"material: price {material}, or leave it unpriced and ask.")
                break
        from costed_facts import is_other_sheet_material
        if is_other_sheet_material(material):
            mine = [r for r in rows if identity(r.get("part_number")) == pn
                    or str(r.get("description") or "").upper().startswith(pn + " ")]
            wrong = sorted({str(r.get("block")) for r in mine
                            if r.get("block") and r.get("block") not in ("other_sheet", "bom")})
            if wrong:
                out.append(f"{pn}: {material} is costed by the sheet, and its calculated "
                           f"material row is on the {', '.join(wrong)} block.")
    return out


def audit_owned_specifications(summary):
    """Narrow post-cost guards; these do not enable the broad shadow contracts."""
    out = list(summary.get("role_quantity_input_issues") or [])
    parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    for part in parts:
        if not isinstance(part, dict):
            continue
        pn = str(part.get("part_number") or "?")
        own = own_material(part, summary.get("pages"))
        if own and part.get("material_source") == "solidworks_applied_material":
            out.append(f"{pn}: the drawing states {own['value']}, but a CAD library material owns the costed material. Resolve the specification before release.")
        if part.get("dxf_pieces") and any(isinstance(p, dict) and p.get("piece")
                                         for p in part["dxf_pieces"]):
            children = [p for p in parts if isinstance(p, dict)
                        and identity(p.get("dxf_minted_piece_of")) == identity(pn)]
            expected = {identity(p.get("costed_as")) for p in part["dxf_pieces"] if isinstance(p, dict)}
            if (not children or {identity(p.get("part_number")) for p in children} != expected
                    or any(not role_count_preserved(p) for p in children)):
                out.append(f"{pn}: DXF roles are preserved but their per-parent counts are not all evidenced. One file does not establish one piece per product.")
    out.extend(role_charge_issues(summary, [p for p in parts if isinstance(p, dict)]))
    out.extend(priced_as_issues(summary, [p for p in parts if isinstance(p, dict)]))
    return out
