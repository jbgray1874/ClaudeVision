"""Where the pack has no part drawings, the model is the parts list (D-411).

M&S 12675-01, October 2026: three design-intent sheets, no parts list, no part sheets — and
fourteen SolidWorks files beside them: three assemblies (a stacking block model, a block model
and its V2), the bodies they are built from, and the customer's bags modelled for fit. Four runs
priced nothing or priced nonsense; the fifth (D-409) stopped with an empty book and the sentence
that the model is the parts list where the pack has none. James Gray, 8 Oct 2026: "we should be
able to BOM and route a lot from this."

So this takes the parts off the model. ONE DESIGN PER BOOK: the root assembly the run was asked
for (SDI_PRODUCT), else the only root under the drawing number, else the one the GA naming
convention marks; where none of those decides, nothing is minted and the roots are named for a
person to choose. Every body under the chosen root becomes a part record with the body's own
name, counted down the tree; a sub-assembly becomes a parent; a model whose name says it is the
customer's or a reference (config.REFERENCE_MODEL_NAME_WORDS) is set aside and listed. The
records are then stamped by the SAME connector that stamps a drawn part — material, flat, gauge,
bends, section, bought-in, the model's own operation hints — so a model-only part has one reader,
not a second copy of one.

WHAT THIS IS NOT. A take-off from a model is a concept costing: nothing on it has been detailed,
toleranced or released. Every record says so, the summary carries `concept_takeoff`, and the
report, the sheet and the quote carry the label. It outranks a guess from a picture; it does not
outrank a drawing, and a drawn part never comes through here.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

KEY = "concept_takeoff"
SOURCE = "solidworks_model_takeoff"

_DEFAULT_REFERENCE_WORDS = [r"\bCUSTOMER\b", r"\bSUPPLIED\b", r"\bREFERENCE\b", r"\bPLACEHOLDER\b",
                            r"\bDUMMY\b", r"\bENVELOPE\b", r"\bFREE\s+ISSUE\b"]
_DEFAULT_GA_PATTERN = r"(?:^|[\s_-])GA(?:[\s_-]|$)"


def _clean(s: Any) -> str:
    try:
        from source_connectors.solidworks import _clean_pn              # noqa: PLC0415
        return _clean_pn(str(s or ""))
    except Exception:                                                  # noqa: BLE001
        return re.sub(r"\s+", " ", str(s or "")).strip()


def reference_model_words() -> List[str]:
    try:
        import config                                                  # noqa: PLC0415
        words = list(getattr(config, "REFERENCE_MODEL_NAME_WORDS", None) or [])
    except Exception:                                                  # noqa: BLE001
        words = []
    return words or list(_DEFAULT_REFERENCE_WORDS)


def is_reference_model(name: Any) -> Optional[str]:
    """The word that marks this model as the customer's or a reference — or None.

    "12675-M&S Customer Bag" and "… Customer Bag_Estimated Stakable" are the customer's goods,
    modelled so the stand fits them; they are in the tree and they are not parts we make."""
    text = str(name or "").upper()
    for pat in reference_model_words():
        try:
            m = re.search(pat, text, flags=re.I)
        except re.error:
            m = None
        if m:
            return m.group(0).strip()
    return None


def _is_ga_named(name: Any) -> bool:
    try:
        import config                                                  # noqa: PLC0415
        pat = str(getattr(config, "GA_NAME_TOKEN_PATTERN", "") or "") or _DEFAULT_GA_PATTERN
    except Exception:                                                  # noqa: BLE001
        pat = _DEFAULT_GA_PATTERN
    try:
        return bool(re.search(pat, str(name or ""), flags=re.I))
    except re.error:
        return False


def designs_and_reference_roots(job: Any) -> Tuple[List[str], Dict[str, List[str]]]:
    """(the designs, {reference root: its members}). A root is an assembly that is nobody's
    child; one whose members are all reference models is the customer's goods stacked for fit,
    not a design — set aside with them rather than offered as a product, and named."""
    hierarchy = dict(getattr(job, "hierarchy", None) or {})
    asms = {_clean(a) for a in (getattr(job, "assembly_pns", None) or []) if _clean(a)}
    children = {_clean(c) for kids in hierarchy.values() for c, _q in (kids or []) if _clean(c)}
    roots = [p for p in hierarchy if _clean(p) and _clean(p) not in children]
    for a in sorted(asms):
        if a not in children and a not in {_clean(r) for r in roots}:
            roots.append(a)
    top = _clean((getattr(job, "meta", None) or {}).get("top_assembly") or "")
    if top and top not in children and top not in {_clean(r) for r in roots}:
        roots.append(top)
    designs: List[str] = []
    reference: Dict[str, List[str]] = {}
    for r in roots:
        kids = [_clean(c) for c, _q in (hierarchy.get(r) or []) if _clean(c)]
        if kids and all(is_reference_model(c) for c in kids):
            reference[r] = kids
            continue
        designs.append(r)
    return designs, reference


def roots_of(job: Any) -> List[str]:
    """The assemblies that are nobody's child — the designs in the model."""
    return designs_and_reference_roots(job)[0]


def choose_design(roots: Iterable[str], *, declared: str = "", drawing_number: str = "",
                  top_assembly: str = "") -> Tuple[Optional[str], str, List[str]]:
    """(the root to price, how it was chosen, the other roots) — or (None, why not, roots).

    The declared product first, because it is what the run was asked for. Then the drawing
    number: the only root under it is the design. Then the GA convention, which is how the
    drawing office marks the product among its models. A tie is not guessed at: the extract's
    own choice is accepted only when a person gave nothing else, and said so."""
    roots = [r for r in roots if str(r or "").strip()]
    if not roots:
        return None, "the model holds no assembly to take off from", []
    key = {r: _clean(r).upper() for r in roots}

    dec = _clean(declared).upper()
    if dec:
        hit = [r for r in roots if key[r] == dec] or [r for r in roots if key[r].startswith(dec)]
        if len(hit) == 1:
            return hit[0], "the product this run was asked for (SDI_PRODUCT)", [r for r in roots if r != hit[0]]
        if len(hit) > 1:
            return None, (f"the product this run was asked for ({declared}) names "
                          f"{len(hit)} assemblies in the model: {', '.join(hit)}"), roots
        # ASKED FOR SOMETHING THE MODEL DOES NOT HOLD AS A DESIGN — a stack of the customer's
        # bags, a name that is not in the tree. Said, not swapped for a design nobody asked for.
        return None, (f"the product this run was asked for ({declared}) is not a design in the "
                      f"model — the designs are: {', '.join(roots)}"), roots

    dn = _clean(drawing_number).upper()
    cands = [r for r in roots if dn and key[r].startswith(dn)] or roots
    if len(cands) == 1:
        return cands[0], ("the only assembly in the model under this drawing number"
                          if dn else "the only assembly in the model"), [r for r in roots if r != cands[0]]
    ga = [r for r in cands if _is_ga_named(r)]
    if len(ga) == 1:
        return ga[0], "the assembly the GA naming convention marks as the product", [r for r in roots if r != ga[0]]
    top = _clean(top_assembly).upper()
    if top and top in {key[r] for r in cands} and not ga:
        chosen = next(r for r in cands if key[r] == top)
        return chosen, ("the assembly the extract itself chose, nothing in the pack or the "
                        "run saying otherwise — confirm it is the design wanted"), [r for r in roots if r != chosen]
    return None, (f"{len(cands)} designs in the model and nothing says which to price: "
                  f"{', '.join(cands)} — run with SDI_PRODUCT=<assembly name> for the one wanted"), roots


def members_of(job: Any, root: str) -> Dict[str, float]:
    """Every body and sub-assembly under `root`, with its count per product, from the tree."""
    hierarchy = dict(getattr(job, "hierarchy", None) or {})
    by_key = {_clean(p).upper(): p for p in hierarchy}
    totals: Dict[str, float] = {}
    seen_path: List[str] = []

    def _walk(parent: str, mult: float) -> None:
        pk = _clean(parent).upper()
        if pk in seen_path:
            return                                   # a cycle in the extract; never loop
        seen_path.append(pk)
        for child, q in (hierarchy.get(by_key.get(pk, parent)) or []):
            c = _clean(child)
            if not c or _clean(c).upper() == _clean(root).upper():
                continue
            n = float(q) if q and float(q) > 0 else 1.0
            totals[c] = totals.get(c, 0.0) + mult * n
            _walk(c, mult * n)
        seen_path.pop()

    _walk(root, 1.0)
    return totals


def takeoff(summary: Dict[str, Any], job: Any, *, declared: str = "", drawing_number: str = "",
            job_folder_name: str = "") -> Dict[str, Any]:
    """Mint the chosen design's parts from the model and stamp them as the connector would.

    Returns {"parts", "design", "chosen_by", "other_designs", "excluded", "why_not"}. Nothing is
    written to `summary` unless parts were minted; then `concept_takeoff`, `declared_product`
    (when the run gave none) and `solidworks_native` are set so the route, the report, the sheet
    and the quote all know what this book is."""
    out: Dict[str, Any] = {"parts": [], "design": "", "chosen_by": "", "other_designs": [],
                           "excluded": [], "why_not": ""}
    if job is None or not getattr(job, "found", False):
        out["why_not"] = "no SolidWorks extract of this job's own was available to take off from"
        return out
    roots, reference_roots = designs_and_reference_roots(job)
    top = str((getattr(job, "meta", None) or {}).get("top_assembly") or "")
    if not roots and reference_roots:
        # Every assembly in the model is the customer's goods stacked for fit: said with the
        # names, so nobody reads "nothing to take off from" as a model with nothing in it.
        out["why_not"] = ("every assembly in the model is a reference model stack, not a design: "
                          + "; ".join(f"{r} ({', '.join(k)})" for r, k in reference_roots.items()))
        out["excluded"] = [{"part_number": k, "why": "reference model — the customer's goods, modelled for fit"}
                           for kids in reference_roots.values() for k in kids]
        return out
    chosen, how, others = choose_design(roots, declared=declared, drawing_number=drawing_number,
                                        top_assembly=top)
    if not chosen:
        out["why_not"] = how
        out["other_designs"] = list(others)
        return out

    members = members_of(job, chosen)
    if not members:
        out["why_not"] = (f"the model's tree names no member under {chosen} — the extract carries "
                          f"no assembly edges for it")
        out["design"], out["chosen_by"], out["other_designs"] = chosen, how, list(others)
        return out

    from document_builder import _empty_part_record                     # noqa: PLC0415
    from source_precedence import apply_field                           # noqa: PLC0415
    from source_connectors.solidworks import (                          # noqa: PLC0415
        NativeBomRow, NativeJob, SOURCE_NAME, apply_native_hierarchy_to_parts,
        apply_native_to_pre_estimate)

    signals = dict(getattr(job, "part_signals", None) or {})
    asm_keys = {_clean(a).upper() for a in (getattr(job, "assembly_pns", None) or [])}
    excluded: List[Dict[str, str]] = []
    kept: Dict[str, float] = {}
    for pn, qty in members.items():
        word = is_reference_model(pn)
        if word:
            excluded.append({"part_number": pn, "why": f"named as the customer's / a reference model ('{word}') — "
                                                       f"modelled for fit, not a part we make"})
            continue
        kept[pn] = qty
    if not kept:
        out["why_not"] = (f"every member under {chosen} is a reference model: "
                          f"{', '.join(e['part_number'] for e in excluded)}")
        out["design"], out["chosen_by"], out["other_designs"], out["excluded"] = chosen, how, list(others), excluded
        return out

    def _title_of(pn: str) -> str:
        sig = signals.get(_clean(pn))
        return str(getattr(sig, "description", "") or "").strip() or pn

    label = ("CONCEPT TAKE-OFF FROM THE MODEL: no drawing sheet of its own — size, material and "
             f"count are the SolidWorks body's under {chosen}; operations come from the model's "
             "features and are assumptions to confirm; nothing here has been detailed or released")
    parts: List[Dict[str, Any]] = []
    root_rec = _empty_part_record(chosen, item_number=0,
                                  description=f"{_title_of(chosen)} — the design taken off from the model",
                                  quantity=None)
    apply_field(root_rec, "quantity", 1, SOURCE_NAME,
                note="one product per unit — this line IS the design")
    root_rec["is_assembly_parent"] = True
    root_rec["is_sub_assembly"] = True
    root_rec["canonical_kind"] = "assembly"
    root_rec["page_roles"] = ["assembly", "model"]
    root_rec["source"] = SOURCE
    root_rec["model_takeoff"] = True
    root_rec["model_takeoff_design"] = chosen
    root_rec.setdefault("review_flags", []).append(label)
    parts.append(root_rec)
    n = 0
    for pn, qty in kept.items():
        n += 1
        rec = _empty_part_record(pn, item_number=n, description=_title_of(pn), quantity=None)
        q = int(round(qty)) if abs(qty - round(qty)) < 1e-6 else qty
        apply_field(rec, "quantity", q, SOURCE_NAME,
                    note=f"from the SolidWorks tree under {chosen}: {qty:g} per product")
        rec["page_roles"] = ["model"]
        rec["source"] = SOURCE
        rec["model_takeoff"] = True
        rec["model_takeoff_design"] = chosen
        rec.setdefault("review_flags", []).append(label)
        if _clean(pn).upper() in asm_keys:
            rec["is_assembly_parent"] = True
            rec["is_sub_assembly"] = True
            rec["page_roles"] = ["assembly", "model"]
        parts.append(rec)

    # THE SUBTREE AS ITS OWN JOB, so the connector stamps exactly this design: the other roots'
    # edges would otherwise mint their parents over shared members and make a second product.
    sub_keys = {_clean(pn).upper() for pn in kept} | {_clean(chosen).upper()}
    sub_hier = {}
    for parent, kids in (getattr(job, "hierarchy", None) or {}).items():
        if _clean(parent).upper() not in sub_keys:
            continue
        sub_hier[parent] = [(c, q) for c, q in (kids or []) if _clean(c).upper() in sub_keys]
    rows = []
    for pn, qty in kept.items():
        sig = signals.get(_clean(pn))
        rows.append(NativeBomRow(part_number=_clean(pn), quantity=float(qty),
                                 material=str(getattr(sig, "material", "") or ""),
                                 is_assembly=_clean(pn).upper() in asm_keys))
    sub = NativeJob(bom=rows, part_signals=signals,
                    assembly_pns=[a for a in (getattr(job, "assembly_pns", None) or [])
                                  if _clean(a).upper() in sub_keys],
                    meta=dict(getattr(job, "meta", None) or {}, top_assembly=chosen),
                    found=True, hierarchy=sub_hier)
    applied = apply_native_to_pre_estimate(parts, sub)
    stamped = apply_native_hierarchy_to_parts(parts, sub)

    out.update({"parts": parts, "design": chosen, "chosen_by": how, "other_designs": list(others),
                "excluded": excluded, "applied": applied, "hierarchy_stamped": stamped})

    meta = dict(getattr(job, "meta", None) or {})
    summary[KEY] = {
        "source": "solidworks_model", "design": chosen, "design_title": _title_of(chosen),
        "chosen_by": how, "other_designs": list(others), "excluded": excluded,
        "parts": len(parts) - 1, "extract_path": meta.get("extract_path"), "applied": applied,
    }
    if not str(summary.get("declared_product") or "").strip():
        # The design being priced IS the product of this run, so the route resolves it as such.
        summary["declared_product"] = chosen
    sn = summary.setdefault("solidworks_native", {})
    if not isinstance(sn, dict):
        sn = summary["solidworks_native"] = {}
    sn.update({
        "source": "solidworks_api", "found": True, "takeoff": True,
        "refused_wrong_job": False, "refused_own_job": False, "job_has_no_parts": False,
        "top_assembly": chosen, "top_assembly_chosen_by": how,
        "top_assembly_candidates": list(roots), "extract_path": meta.get("extract_path"),
        "counts": meta.get("counts"), "applied": applied,
        "extract_stale": bool(meta.get("extract_stale")),
        "extract_incomplete": bool(meta.get("extract_incomplete")),
        "manifest_absent": bool(meta.get("manifest_absent")),
        "freshness_unverifiable": bool(meta.get("freshness_unverifiable")),
        "fingerprint_folder": meta.get("fingerprint_folder"),
        "source_unreachable": bool(meta.get("source_unreachable")),
        "changed_during_extraction": bool(meta.get("changed_during_extraction")),
        "native_files_present": meta.get("native_files_present"),
        "reason": "",
    })
    summary.setdefault("review_flags", []).append(
        f"CONCEPT TAKE-OFF FROM THE MODEL — not a drawings estimate. This pack has no parts list "
        f"and no part drawings; {len(parts) - 1} part(s) under the SolidWorks assembly {chosen} "
        f"(chosen as {how}) are costed from the model's own bodies, counts and features."
        + (f" Set aside as reference models: {', '.join(e['part_number'] for e in excluded)}."
           if excluded else "")
        + (f" Other designs in the model, not priced in this book: {', '.join(others)} — run with "
           f"SDI_PRODUCT=<name> for each." if others else ""))
    return out


def sentence(t: Any) -> str:
    """One sentence for the sheet, the quote and the report's callout."""
    if not isinstance(t, dict) or not t.get("design"):
        return ""
    return (f"Concept take-off from the SolidWorks model {t['design']} — not a drawings estimate: "
            f"parts, sizes, materials and counts are the model's; operations are assumptions to confirm.")


def banner(t: Any) -> str:
    s = sentence(t)
    return ("CONCEPT TAKE-OFF FROM THE MODEL — " + s[len("Concept take-off from the SolidWorks model "):]) if s else ""
