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
    dn = _clean(drawing_number).upper()

    # THE NUMBER THE RUN WAS GIVEN IS A JOB, NOT AN ASSEMBLY, UNLESS IT NAMES ONE (D-413). The
    # portal passes the enquiry's Drawing Number as the declared product — "12675-01" — and
    # on the 10:40 run of 8 Oct that prefix matched two roots and this stopped, "names 2
    # assemblies", before the GA rule it was written to reach. A declared name that picks out
    # one root is a choice; one that several roots share is the SCOPE the choice is made in;
    # one that matches nothing is a question — unless it is just the drawing number, which
    # scopes to every root.
    cands = list(roots)
    scope = ""
    if dec:
        hit = [r for r in roots if key[r] == dec] or [r for r in roots if key[r].startswith(dec)]
        if len(hit) == 1:
            return hit[0], "the product this run was asked for (SDI_PRODUCT)", [r for r in roots if r != hit[0]]
        if len(hit) > 1:
            cands, scope = hit, f" under the number this run was given ({declared})"
        elif dec == dn or (dn and dn.startswith(dec)):
            cands, scope = list(roots), f" under this drawing number ({drawing_number})"
        else:
            # ASKED FOR SOMETHING THE MODEL DOES NOT HOLD AS A DESIGN — a stack of the
            # customer's bags, a name not in the tree. Said, not swapped for a design nobody
            # asked for.
            return None, (f"the product this run was asked for ({declared}) is not a design in "
                          f"the model — the designs are: {', '.join(roots)}"), roots
    elif dn:
        hit = [r for r in roots if key[r].startswith(dn)]
        if hit:
            cands, scope = hit, f" under this drawing number ({drawing_number})"

    if len(cands) == 1:
        return cands[0], f"the only assembly in the model{scope}", [r for r in roots if r != cands[0]]
    ga = [r for r in cands if _is_ga_named(r)]
    if len(ga) == 1:
        return ga[0], (f"the assembly the GA naming convention marks as the product"
                       f"{scope}"), [r for r in roots if r != ga[0]]
    top = _clean(top_assembly).upper()
    if top and top in {key[r] for r in cands} and not ga:
        chosen = next(r for r in cands if key[r] == top)
        return chosen, ("the assembly the extract itself chose, nothing in the pack or the "
                        "run saying otherwise — confirm it is the design wanted"), [r for r in roots if r != chosen]
    return None, (f"{len(cands)} designs in the model{scope} and nothing says which to price: "
                  f"{', '.join(cands)} — run with SDI_PRODUCT=<assembly name> for the one wanted"), roots


_STAGED_HASH_PREFIX = re.compile(r"^[0-9a-f]{12,}-", re.I)
# A drawing-number token: digits, then one or more dashed segments — "12675-01", "12675-01-02",
# "12675-01-GA", "12675-01-Block". An enquiry number on its own ("0359972") is not one. The
# boundary is "not a letter or digit", not \b: M&S join the enquiry number to the drawing
# number with an underscore, which \b treats as a word character and reads straight through.
_DRAWING_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z0-9])\d{3,}(?:-[A-Za-z0-9]+)+")


def design_label(name: Any, drawing_number: str = "") -> str:
    """The design a drawing file belongs to, read off its name: the drawing-number token the
    drawing office put in it — preferring one under this job's number, because M&S file their
    sheets enquiry-number first ("0359972_12675-01-02 Block Model V2_Design Intent") — with the
    engine's own staging hash stripped off the front."""
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = _STAGED_HASH_PREFIX.sub("", base.rsplit(".", 1)[0].strip() if "." in base else base.strip())
    tokens = _DRAWING_NUMBER_TOKEN.findall(stem)
    job = _clean(drawing_number).split("-", 1)[0].strip().upper() if drawing_number else ""
    if job:
        under = [t for t in tokens if t.upper().startswith(job)]
        if under:
            return under[0]
    if tokens:
        return tokens[0]
    try:
        from product_identity import drawing_of_file                   # noqa: PLC0415
        num = str((drawing_of_file(base) or {}).get("number") or "").strip()
    except Exception:                                                  # noqa: BLE001
        num = ""
    if not num:
        num = re.split(r"[\s_]+", stem, maxsplit=1)[0]
    return _STAGED_HASH_PREFIX.sub("", num).strip()


def choose_design_sheets(paths: Iterable[Any], *, declared: str = "", drawing_number: str = ""
                         ) -> Dict[str, Any]:
    """ONE DESIGN PER READ (D-413). The concept read takes every page of a pack as one product
    — right for a render pack, wrong for a design-intent pack holding three designs, which it
    would read as one stand. The sheets are grouped by the design their names carry and the
    same rule that picks a design from the model picks one here, so the model take-off and
    its fallback cannot price two different designs of the same pack.

    Returns {"sheets", "design", "chosen_by", "other_designs", "why_not"}; with one design in
    the pack every sheet is that design's."""
    groups: Dict[str, List[str]] = {}
    for p in paths or ():
        s = str(p or "").strip()
        if not s:
            continue
        try:
            from concept_scan import is_brief_page                      # noqa: PLC0415
            if is_brief_page(s):
                continue
        except Exception:                                               # noqa: BLE001
            pass
        groups.setdefault(design_label(s, drawing_number) or "?", []).append(s)
    out: Dict[str, Any] = {"sheets": [], "design": "", "chosen_by": "", "other_designs": [],
                           "why_not": ""}
    if not groups:
        out["why_not"] = "no drawing sheet in the pack to read"
        return out
    if len(groups) == 1:
        label, sheets = next(iter(groups.items()))
        out.update({"sheets": list(sheets), "design": label,
                    "chosen_by": "the only design in the pack"})
        return out
    chosen, how, others = choose_design(list(groups), declared=declared, drawing_number=drawing_number)
    if not chosen:
        out["why_not"] = how
        out["other_designs"] = list(others)
        return out
    out.update({"sheets": list(groups[chosen]), "design": chosen,
                "chosen_by": how.replace("assembly in the model", "design sheet in the pack")
                                .replace("assembly the GA naming convention marks",
                                         "sheet the GA naming convention marks")
                                .replace("designs in the model", "designs in the pack"),
                "other_designs": list(others)})
    return out


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def stock_basis(part: Dict[str, Any]) -> Optional[str]:
    """What this body can be costed from — "flat", "section", "bought-in" — or None (D-414).

    A flat needs its blank AND its gauge; a section needs its length; a bought-in carries its
    own price basis. A body with only an envelope and a material word is a block, and a
    catalogue "each" price on it is a price for nothing."""
    if not isinstance(part, dict):
        return None
    if part.get("is_bought_in"):
        return "bought-in"
    ss = part.get("section_stock")
    if isinstance(ss, dict) and _num(ss.get("length_mm")):
        return "section"
    ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"), dict) else {}
    blank = ((_num(part.get("blank_length_mm")) and _num(part.get("blank_width_mm")))
             or (_num(ng.get("blank_length_mm")) and _num(ng.get("blank_width_mm"))))
    if blank and _num(part.get("normalized_thickness_mm")):
        return "flat"
    return None


def what_it_lacks(part: Dict[str, Any]) -> str:
    """The plain words for why a body has no stock basis."""
    bits = []
    ng = part.get("normalized_geometry") if isinstance(part.get("normalized_geometry"), dict) else {}
    if not ((_num(part.get("blank_length_mm")) and _num(part.get("blank_width_mm")))
            or (_num(ng.get("blank_length_mm")) and _num(ng.get("blank_width_mm")))):
        bits.append("no flat")
    if not _num(part.get("normalized_thickness_mm")):
        bits.append("no gauge")
    ss = part.get("section_stock")
    if not (isinstance(ss, dict) and _num(ss.get("length_mm"))):
        bits.append("no section")
    bb = [b for b in (_num(v) for v in (part.get("bbox_mm") or [])) if b]
    env = f"; envelope {' × '.join(f'{b:g}' for b in bb)} mm" if bb else ""
    return ", ".join(bits) + env


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
    hierarchy = dict(getattr(job, "hierarchy", None) or {})
    excluded: List[Dict[str, str]] = []
    kept: Dict[str, float] = {}
    for pn, qty in members.items():
        word = is_reference_model(pn)
        if word:
            excluded.append({"part_number": pn, "why": f"named as the customer's / a reference model ('{word}') — "
                                                       f"modelled for fit, not a part we make"})
            continue
        kept[pn] = qty
    # A SUB-ASSEMBLY THAT HOLDS ONLY REFERENCE MODELS IS ONE ITSELF (D-414). 12675-01's GA
    # holds "12675-01-Bag Stack" ×2, whose only member is the customer's bag: the bag was set
    # aside and the empty stack stayed, an assembly line with packing labour in its scope.
    # Repeated until nothing changes, so a stack of stacks goes with them.
    _gone = {_clean(e["part_number"]).upper() for e in excluded}
    _changed = True
    while _changed:
        _changed = False
        for pn in list(kept):
            key = _clean(pn).upper()
            if key not in asm_keys:
                continue
            kids = [_clean(c).upper() for c, _q in (hierarchy.get(pn) or
                                                     next((v for k, v in hierarchy.items()
                                                           if _clean(k).upper() == key), []))]
            if kids and all(k in _gone for k in kids):
                excluded.append({"part_number": pn, "why": "an assembly holding only reference models — "
                                                           "the customer's goods stacked for fit, not a part we make"})
                _gone.add(key)
                kept.pop(pn)
                _changed = True
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
    def _sub_job(keys: set) -> Any:
        sub_hier = {}
        for parent, kids in hierarchy.items():
            if _clean(parent).upper() not in keys:
                continue
            sub_hier[parent] = [(c, q) for c, q in (kids or []) if _clean(c).upper() in keys]
        rows = []
        for pn, qty in kept.items():
            if _clean(pn).upper() not in keys:
                continue
            sig = signals.get(_clean(pn))
            rows.append(NativeBomRow(part_number=_clean(pn), quantity=float(qty),
                                     material=str(getattr(sig, "material", "") or ""),
                                     is_assembly=_clean(pn).upper() in asm_keys))
        return NativeJob(bom=rows, part_signals=signals,
                         assembly_pns=[a for a in (getattr(job, "assembly_pns", None) or [])
                                       if _clean(a).upper() in keys],
                         meta=dict(getattr(job, "meta", None) or {}, top_assembly=chosen),
                         found=True, hierarchy=sub_hier)

    sub_keys = {_clean(pn).upper() for pn in kept} | {_clean(chosen).upper()}
    applied = apply_native_to_pre_estimate(parts, _sub_job(sub_keys))

    # ── A TAKE-OFF IS ONLY A TAKE-OFF WHERE THE MODEL GIVES A STOCK BASIS (D-414) ────────
    # 12675-01, 8 Oct 11:35: the GA's only body was "Stacking Holder Block", 1250 × 600 with no
    # gauge, no flat, no section and no mass — a block model, not a part. It counted as a
    # take-off, a catalogue "each" row priced it at £0.80, no cut, fold, weld or coat could be
    # costed, and because the model door had returned parts the concept read never opened the
    # GA sheet. A body is a part this book can cost only when the model gives it a stock basis:
    # a flat blank with its gauge, a section with its length, or a bought-in. Where NO
    # fabricated body has one, the take-off is refused with the reason and the concept read of
    # the same design's sheet answers instead; where SOME have one, the rest are kept off the
    # bill and asked about on the design, never priced from a catalogue word.
    leaves = [p for p in parts[1:] if not p.get("is_assembly_parent")]
    based = [p for p in leaves if stock_basis(p)]
    undetailed = [p for p in leaves if not stock_basis(p)]
    fabricated_based = [p for p in based if stock_basis(p) != "bought-in"]
    if not fabricated_based:
        lacking = "; ".join(f"{p.get('part_number')} ({what_it_lacks(p)})" for p in undetailed)
        out["why_not"] = (f"the model under {chosen} holds no part with a stock basis — "
                          + (lacking + " — " if lacking else "no fabricated body at all — ")
                          + "so nothing to cut, fold, weld or coat can be costed from it")
        out.update({"design": chosen, "chosen_by": how, "other_designs": list(others),
                    "excluded": excluded, "undetailed": [p.get("part_number") for p in undetailed],
                    "applied": applied})
        # ONE BLOCK IS THE DESIGN'S BODY (D-416). Refused as a part, its envelope is still a
        # measured fact about the product: where the whole design is one undetailed body, that
        # body's size is the holder's, and the concept read of the sheet is held to it.
        _fab_undetailed = [p for p in undetailed if stock_basis(p) != "bought-in"]
        if len(_fab_undetailed) == 1:
            _bb = [b for b in (_num(v) for v in (_fab_undetailed[0].get("bbox_mm") or [])) if b]
            if len(_bb) >= 2:
                out["model_envelope_mm"] = _bb
                out["model_envelope_of"] = str(_fab_undetailed[0].get("part_number") or "")
        return out
    if undetailed:
        _drop = {id(p) for p in undetailed}
        parts = [p for p in parts if id(p) not in _drop]
        for p in undetailed:
            kept.pop(next((k for k in kept if _clean(k).upper() == _clean(p.get("part_number")).upper()), ""), None)
    # an assembly left with nothing under it carries no product and no labour
    _changed = True
    while _changed:
        _changed = False
        keys_now = {_clean(p.get("part_number")).upper() for p in parts}
        for p in list(parts[1:]):
            if not p.get("is_assembly_parent"):
                continue
            k = _clean(p.get("part_number")).upper()
            kids = [_clean(c).upper() for parent, cs in hierarchy.items()
                    if _clean(parent).upper() == k for c, _q in (cs or [])]
            if not any(c in keys_now for c in kids):
                parts.remove(p)
                kept.pop(next((x for x in kept if _clean(x).upper() == k), ""), None)
                _changed = True
    sub_keys = {_clean(p.get("part_number")).upper() for p in parts}
    stamped = apply_native_hierarchy_to_parts(parts, _sub_job(sub_keys))
    if undetailed:
        from source_precedence import raise_manufacturing_question     # noqa: PLC0415
        names = ", ".join(f"{p.get('part_number')} ({what_it_lacks(p)})" for p in undetailed)
        raise_manufacturing_question(
            root_rec,
            f"{len(undetailed)} body(ies) under {chosen} have no stock basis in the model and are "
            f"not on the bill: {names}",
            "left off the bill — a body with no gauge, section or flat is not a part this book can cost",
            "detail them in the model (gauge or section), or give their size and material, then re-run",
            SOURCE)

    out.update({"parts": parts, "design": chosen, "chosen_by": how, "other_designs": list(others),
                "excluded": excluded, "applied": applied, "hierarchy_stamped": stamped,
                "undetailed": [p.get("part_number") for p in undetailed]})

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


def is_vision(t: Any) -> bool:
    """The fallback: the vision model sighted one design's sheet(s) with the brief."""
    return isinstance(t, dict) and str(t.get("source") or "") == "vision_concept"


def unchecked_figure(t: Any) -> Optional[bool]:
    """True where a vision read's bill did not pass the sheet check, False where it agreed, and
    None where no check was recorded (a book from before D-415, or a model take-off)."""
    if not is_vision(t):
        return None
    _sc = t.get("sheet_check") if isinstance(t.get("sheet_check"), dict) else None
    if not _sc:
        return None
    return not bool(_sc.get("agrees"))


def sentence(t: Any) -> str:
    """One sentence for the sheet, the quote and the report's callout."""
    if not isinstance(t, dict) or not t.get("design"):
        return ""
    if is_vision(t):
        # WITH THE BRIEF ONLY WHERE THERE WAS ONE, AND WHAT THE SHEET CHECK FOUND (D-415).
        _with = " with the enquiry brief" if t.get("brief_used", True) else ""
        _sc = t.get("sheet_check") if isinstance(t.get("sheet_check"), dict) else {}
        _held = ""
        if _sc.get("failures"):
            _held = (" The bill does not agree with the sheet: "
                     + "; ".join(str(f) for f in _sc["failures"])
                     + ". This is an unchecked concept figure, not a checked budget.")
        elif _sc.get("unverified"):
            _held = (" Nothing in the bill contradicts the sheet, but it is unverified: "
                     + "; ".join(str(f) for f in _sc["unverified"])
                     + ". This is an unchecked concept figure, not a checked budget.")
        elif _sc.get("agrees"):
            _held = (" The bill was checked against the sheet's body, goods, labelled parts, "
                     "gauge, finish and weight, and agrees.")
        return (f"Concept read of the design-intent sheet {t['design']} by the vision model{_with} "
                f"— not a drawings estimate: every size, material and count was read off the sheet "
                f"or sighted, none measured; operations are assumptions to confirm.{_held}")
    return (f"Concept take-off from the SolidWorks model {t['design']} — not a drawings estimate: "
            f"parts, sizes, materials and counts are the model's; operations are assumptions to confirm.")


def banner(t: Any) -> str:
    s = sentence(t)
    if not s:
        return ""
    if is_vision(t):
        # AN UNCHECKED FIGURE SAYS SO FIRST (D-417): beside the Unit Cost an estimator must not
        # be able to read a bill the check could not pass as a checked budget.
        _lead = "" if unchecked_figure(t) is False else "UNCHECKED CONCEPT FIGURE — "
        return (_lead + "CONCEPT READ OF A DESIGN-INTENT SHEET — "
                + s[len("Concept read of the design-intent sheet "):])
    return "CONCEPT TAKE-OFF FROM THE MODEL — " + s[len("Concept take-off from the SolidWorks model "):]
