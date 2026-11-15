"""A printed part priced from the AI Print calculator (JG, 15 Nov 2026).

"well it should. next code release put this in. estimating have been waiting for this."

src/print_calculator_sheet.py reads estimating's sheet and works its sums cell for cell. This
module decides WHEN that working is the part's price, and says so either way:

  A PART IS PRINTED WHEN ITS OWN EVIDENCE SAYS SO. Its finish, or a process note on it, or its
  description states print ("PRINTED - SEE PRINT SPEC"). A part only NAMED a graphic ("GRAPHIC
  LENS") is not stated printed: it keeps the price it had and the question is asked, with the
  calculator's figure beside it.

  THE SUBSTRATE IS A ROW ON THE SHEET, FOUND BY THE PART'S OWN MATERIAL AND GAUGE. Every word
  of the part's material is in the row's name, and where the row's name states a gauge the
  part's gauge is that gauge. One row or none: two rows that both fit price nothing.

  THE SIZE IS THE PART'S MEASURED ONE. A provisional blank is not a size.

  ONE PRICE, NOT TWO. A part with a catalogue price of its own keeps it. Where the calculator
  prices the part, its run cost per sheet ("print & cut") stands for the substrate, the print
  and the cut, so the engine's own material and cutting for that part are withdrawn, and the
  figures withdrawn are stated in a question for estimating.

  PROVISIONAL, AND EVERY POINT THE SHEET LEAVES OPEN IS ASKED. The sheet is worked as it
  stands (print_calculator_sheet.points_to_confirm); nothing on it is corrected here.

Nothing is priced when SDI_PRINT_CALCULATOR_XLSX is unset: the estimate is as it was.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import print_calculator_sheet as sheet

SOURCE_KEY = "ai_print_calculator"
SUBJECT = "print_calculator"
_STATES_PRINT = re.compile(r"\bPRINT(?:ED|ING)?\b", re.IGNORECASE)
_NAMES_A_GRAPHIC = re.compile(r"\bGRAPHICS?\b", re.IGNORECASE)
_NOT_PRINTED = re.compile(r"\b(?:NOT|NO|UN)[\s-]*PRINT(?:ED|ING)?\b", re.IGNORECASE)
_GAUGE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*MM\b", re.IGNORECASE)

_READ_CACHE: Dict[str, Dict[str, Any]] = {}


def _read() -> Dict[str, Any]:
    path = sheet.configured_path() or ""
    if path not in _READ_CACHE:
        _READ_CACHE.clear()
        _READ_CACHE[path] = sheet.read_sheet(path or None)
    return _READ_CACHE[path]


def _texts(part: Dict[str, Any], keys: Tuple[str, ...]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for k in keys:
        v = part.get(k)
        for item in (v if isinstance(v, (list, tuple)) else [v]):
            if isinstance(item, str) and item.strip():
                out.append((k, item.strip()))
    return out


def printed_basis(part: Any) -> Optional[Dict[str, str]]:
    """{"how": "stated"|"named", "said", "field"} when the part's own evidence says print, or
    names it a graphic; None otherwise. An assembly is not a printed sheet."""
    if not isinstance(part, dict) or part.get("is_assembly_parent"):
        return None
    for field, text in _texts(part, ("normalized_finish", "surface_finishes", "process_notes",
                                     "description")):
        if _STATES_PRINT.search(text) and not _NOT_PRINTED.search(text):
            return {"how": "stated", "said": text, "field": field}
    for field, text in _texts(part, ("description",)):
        if _NAMES_A_GRAPHIC.search(text):
            return {"how": "named", "said": text, "field": field}
    return None


def _f(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f > 0 else None


def measured_size(part: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], str]:
    """(longer, shorter, where from) of the part's flat size, or (None, None, why not)."""
    if part.get("geometry_provisional"):
        return None, None, "its geometry is provisional, so it has no measured size"
    for lk, wk, label in (("blank_length_mm", "blank_width_mm", "its measured blank"),
                          ("overall_length_mm", "overall_width_mm", "its overall size")):
        a, b = _f(part.get(lk)), _f(part.get(wk))
        if not (a and b):
            continue
        src = " ".join(str(part.get(k + "_source") or "") for k in (lk, wk)).lower()
        if "provisional" in src or "inferred" in src:
            continue
        where = str(part.get(lk + "_source") or part.get("geometry_source") or "").strip()
        return max(a, b), min(a, b), label + (f" ({where})" if where else "")
    return None, None, "no measured length and width are recorded for it"


def _words(text: Any) -> set:
    return {w for w in re.findall(r"[A-Z]+", str(text or "").upper()) if w != "MM"}


# A TRADE NAME IS THE MATERIAL IT IS SOLD AS. A drawing says FOAMEX; the print sheet's row says
# "Foamed PVC". They are the same board, and a part was told its material "is not a substrate
# on the print calculator" on the name alone (12181-04-04G, 15 Nov 2026).
_SOLD_AS: Dict[str, Tuple[str, ...]] = {"FOAMEX": ("FOAMED", "PVC")}


def rows_named(read: Dict[str, Any], material: Any) -> List[Dict[str, Any]]:
    """The sheet's rows for this material, whatever their gauge."""
    want = _words(material)
    if not want:
        return []
    wants = [want] + [set(v) for k, v in _SOLD_AS.items() if k in want]
    return [s for s in (read.get("substrates") or [])
            if any(w <= _words(s.get("name")) for w in wants)]


def substrate_for(read: Dict[str, Any], material: Any, gauge_mm: Any
                  ) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the sheet's row for this material and gauge, "") or (None, why there is not one)."""
    if not _words(material):
        return None, "the part states no material"
    named = rows_named(read, material)
    if not named:
        return None, f"'{material}' is not a substrate on the print calculator"
    gauge = _f(gauge_mm)
    fits: List[Dict[str, Any]] = []
    for s in named:
        m = _GAUGE.match(str(s.get("name") or ""))
        if m is None:
            fits.append(s)
        elif gauge is not None and abs(float(m.group(1)) - gauge) <= 0.05:
            fits.append(s)
    if not fits:
        rows = ", ".join(s["name"] for s in named)
        return None, (f"the print calculator holds '{material}' only as {rows}, and the part's "
                      + (f"gauge is {gauge:g} mm" if gauge else "gauge is not stated"))
    if len(fits) > 1:
        return None, (f"'{material}' fits {len(fits)} rows of the print calculator "
                      f"({', '.join(s['name'] for s in fits)}); which one is not stated")
    return fits[0], ""


def work(part: Dict[str, Any], order_qty: Any, read: Optional[Dict[str, Any]] = None
         ) -> Dict[str, Any]:
    """The calculator's record for one part: applied or not, every figure, and why."""
    read = read if read is not None else _read()
    basis = printed_basis(part) or {}
    pn = str(part.get("part_number") or "")
    rec: Dict[str, Any] = {
        "calculator": "print", "title": f"Print calculator: {pn}", "part_number": pn,
        "description": str(part.get("description") or ""), "source": sheet.SOURCE,
        "path": read.get("path"), "printed_how": basis.get("how"),
        "printed_said": basis.get("said"), "applied": False, "provisional": True,
        "why_not": "", "points_to_confirm": []}
    if not read.get("ok"):
        rec["why_not"] = read.get("why") or "the print calculator was not read"
        return rec
    rec["points_to_confirm"] = sheet.points_to_confirm(read)
    material = part.get("normalized_material") or (part.get("materials") or [None])[0]
    gauge = part.get("normalized_thickness_mm")
    rec["material"], rec["gauge_mm"] = material, gauge
    row, why = substrate_for(read, material, gauge)
    if row is None:
        rec["why_not"] = why
        # THE FIGURE ON THE ROW IT NEARLY IS. Where the sheet holds this material at one other
        # gauge only, the print worked on that row is given beside the question, so estimating
        # sees what the answer is worth. It is not charged: whether a board of another gauge
        # prints at that figure is theirs to say.
        _others = rows_named(read, material)
        _l, _w, _where = measured_size(part)
        if len(_others) == 1 and _l:
            _printed = (_f(part.get("quantity")) or 1.0) * (_f(order_qty) or 1.0)
            _alt = sheet.as_the_sheet_works_it(read, _others[0]["name"], _l, _w, _printed)
            if not _alt.get("ok") and _l != _w:
                _alt = sheet.as_the_sheet_works_it(read, _others[0]["name"], _w, _l, _printed)
            if _alt.get("ok"):
                rec["on_the_other_gauge"] = {"substrate": _others[0]["name"],
                                             "total_gbp": round(float(_alt["total_gbp"]), 2),
                                             "parts_per_sheet": _alt["parts_per_sheet"]}
        return rec
    rec.update(substrate=row["name"], process=row.get("process"), sheet_mm=list(row["sheet_mm"]),
               run_cost_per_sheet_gbp=row["run_cost_per_sheet_gbp"])
    longer, shorter, where = measured_size(part)
    if not longer:
        rec["why_not"] = where
        return rec
    rec["size_source"] = where
    per_unit = _f(part.get("quantity")) or 1.0
    order = _f(order_qty) or 1.0
    printed = per_unit * order
    worked = sheet.as_the_sheet_works_it(read, row["name"], longer, shorter, printed)
    turned = False
    if not worked.get("ok") and longer != shorter:
        # The sheet lays a part one way. A person typing this part into it would turn the
        # part before saying it does not fit; the sums are the sheet's own either way.
        again = sheet.as_the_sheet_works_it(read, row["name"], shorter, longer, printed)
        if again.get("ok"):
            worked, turned = again, True
    rec.update(length_mm=shorter if turned else longer, width_mm=longer if turned else shorter,
               turned=turned, qty_per_unit=per_unit, order_qty=order, quantity_printed=printed)
    if not worked.get("ok"):
        rec["why_not"] = worked.get("why") or "the sheet could not be worked for this part"
        return rec
    total = float(worked["total_gbp"])
    rec.update(parts_per_sheet=worked["parts_per_sheet"], scrap=worked["scrap"],
               cost_per_part_gbp=worked["cost_per_part_gbp"], setup_gbp=worked["setup_gbp"],
               setup_share_gbp=worked["setup_share_gbp"], total_gbp=round(total, 4),
               per_unit_gbp=round(total * per_unit, 2), order_gbp=round(total * printed, 2),
               workable=True)
    return rec


def _own_catalogue_price(estimate: Any) -> str:
    """What the part's own catalogue row says, where its price came from one; else ""."""
    if not isinstance(estimate, dict):
        return ""
    mat = estimate.get("material_estimate") if isinstance(estimate.get("material_estimate"), dict) else {}
    src = mat.get("price_source") if isinstance(mat.get("price_source"), dict) else {}
    # A SUBSTRATE'S SHEET PRICE IS NOT THE PRINTED PART'S OWN PRICE (15 Nov 2026). A graphic
    # stated "PRINTED, FULL" on 5 mm Foamex was priced for its board from the catalogue's sheet
    # rate, and that was taken for the part's own catalogue price: the print went uncharged and
    # unasked. Only a price for the PIECE is the part's own; a sheet or area rate buys the
    # board the print goes on.
    if _f(mat.get("sheet_price_gbp")) or str(mat.get("cost_method") or "").startswith("sheet_rate"):
        return ""
    if _f(mat.get("unit_material_cost_gbp")) and str(src.get("source_class") or "") == "catalogue":
        return str(src.get("source_note") or src.get("source_name") or "a catalogue row")
    return ""


def _ask(part: Dict[str, Any], issue: str, assumption: str, action: str) -> None:
    qs = part.setdefault("manufacturing_questions", [])
    if isinstance(qs, list) and not any(isinstance(q, dict) and q.get("issue") == issue for q in qs):
        qs.append({"issue": issue, "assumption": assumption, "action": action,
                   "source": "print_costing.settle", "subject": SUBJECT})


def _flag(part: Dict[str, Any], text: str) -> None:
    flags = part.setdefault("review_flags", [])
    if isinstance(flags, list) and text not in flags:
        flags.append(text)


def _gbp(v: Any) -> str:
    f = _f(v)
    return f"£{f:,.2f}" if f is not None else "nothing"


def settle(original: Dict[str, Any], estimate: Any, order_qty: Any,
           cost: Callable[[Dict[str, Any], Any], Any],
           stub: Callable[[str, str, Any], Dict[str, Any]],
           read: Optional[Dict[str, Any]] = None) -> Any:
    """The part's estimate with the print settled: the calculator's price, or the price it had
    and the reason the calculator was not used. `original` is the part as it stood before
    costing, `estimate` what the engine made of it, `cost` the engine's own part costing and
    `stub` its one maker of a purchased line."""
    basis = printed_basis(original)
    if basis is None or not isinstance(estimate, dict):
        return estimate
    read = read if read is not None else _read()
    if not read.get("path"):
        return estimate                                  # no calculator named: as it was
    pn = str(original.get("part_number") or "")
    rec = work(original, order_qty, read)
    own = _own_catalogue_price(estimate)
    if own:
        rec.update(applied=False, why_not=f"it is priced from its own catalogue row ({own})",
                   charged_instead="its own catalogue price")
        estimate["print_calculator"] = rec
        _flag(estimate, f"print: {pn} keeps its own catalogue price; the AI Print calculator "
                        f"was not used on it")
        return estimate
    if basis["how"] != "stated":
        figure = (f" Worked on the calculator it would be {_gbp(rec.get('total_gbp'))} each "
                  f"({rec.get('substrate')}, {rec.get('parts_per_sheet')} to a sheet)."
                  if rec.get("workable") else "")
        rec.update(applied=False,
                   why_not=f"it is named '{basis['said']}' but nothing on it states it is printed")
        estimate["print_calculator"] = rec
        _ask(estimate, f"{pn} is named '{basis['said']}': is it printed?",
             "no print is charged; the part is priced as its material and cutting only." + figure,
             "confirm whether this part is printed, and on which substrate")
        return estimate
    if not rec.get("workable"):
        estimate["print_calculator"] = rec
        _flag(estimate, f"print: {pn} is stated printed ('{basis['said']}') and the AI Print "
                        f"calculator prices no print for it: {rec['why_not']}. No print is in "
                        f"this line's price")
        _alt = rec.get("on_the_other_gauge") or {}
        _ask(estimate, f"{pn} is printed and no print cost is in its price: {rec['why_not']}",
             "the line carries its material and cutting only, with no print"
             + (f". On the calculator's {_alt['substrate']} row the print would be "
                f"{_gbp(_alt['total_gbp'])} each ({_alt['parts_per_sheet']} to a sheet); that is not "
                f"charged, because the gauge differs" if _alt else ""),
             "price the print, or add this substrate and size to the AI Print calculator")
        return estimate

    # THE CALCULATOR'S PRICE. Costed again as one purchased line at the sheet's total, by the
    # same routine every recognised priced line goes through, so no cutting or material of the
    # engine's own is added to a figure that already holds print and cut.
    mat = estimate.get("material_estimate") if isinstance(estimate.get("material_estimate"), dict) else {}
    lab = estimate.get("labour_estimate") if isinstance(estimate.get("labour_estimate"), dict) else {}
    withdrawn = {"material_gbp": _f(mat.get("unit_material_cost_gbp")),
                 "labour_gbp": _f(lab.get("total_labour_cost_gbp")),
                 "material_method": str(mat.get("cost_method") or "")}
    line = stub(pn, str(original.get("description") or pn), original.get("quantity"))
    for k, v in original.items():
        if k in ("pages", "bom_parent", "bom_parents", "printed_code", "normalized_material",
                 "normalized_thickness_mm", "normalized_finish", "surface_finishes",
                 "overall_length_mm", "overall_width_mm", "blank_length_mm", "blank_width_mm",
                 "dxf_source_file", "drawing_numbers", "quantity_source", "assumed_job_quantity",
                 "owning_assembly", "revision", "item_number", "manufacturing_questions",
                 "review_flags"):
            line[k] = copy.deepcopy(v)
    unit = round(float(rec["total_gbp"]), 2)
    line.update(unit_cost_gbp=unit, unit_material_cost_gbp=unit, source=SOURCE_KEY,
                cost_source=SOURCE_KEY, supplier=sheet.SOURCE, price_verified=False)
    priced = cost(line, order_qty)
    if not isinstance(priced, dict) or _f(priced.get("unit_total_cost_gbp")) is None:
        rec.update(applied=False, why_not="the engine could not carry the calculator's figure")
        estimate["print_calculator"] = rec
        return estimate
    rec.update(applied=True, withdrawn=withdrawn, charged_instead="")
    priced["print_calculator"] = rec
    lay = "turned on the sheet" if rec.get("turned") else "as the sheet lays it"
    _flag(priced,
          f"PROVISIONAL print price from the AI Print calculator: {rec['substrate']}, "
          f"{rec['length_mm']:g} x {rec['width_mm']:g} mm {lay}, {rec['parts_per_sheet']} to a "
          f"{rec['sheet_mm'][0]:g} x {rec['sheet_mm'][1]:g} mm sheet at "
          f"{_gbp(rec['run_cost_per_sheet_gbp'])} a sheet = {_gbp(rec['cost_per_part_gbp'])} each, "
          f"plus {_gbp(rec['setup_share_gbp'])} set-up share over {rec['quantity_printed']:g} "
          f"printed = {_gbp(rec['total_gbp'])} each. Estimating to confirm the sheet")
    _ask(priced,
         f"{pn}: the print calculator's run cost per sheet is headed 'print & cut'. Does it "
         f"hold the substrate too?",
         f"taken to hold the substrate, the print and the cut. The engine's own material "
         f"({_gbp(withdrawn['material_gbp'])} each) and labour ({_gbp(withdrawn['labour_gbp'])} "
         f"each) for this part are withdrawn; the line is {_gbp(rec['total_gbp'])} each",
         "confirm what the run cost covers; if the substrate is bought separately say so")
    if rec.get("turned"):
        _ask(priced,
             f"{pn}: at {rec['width_mm']:g} mm long it does not fit the sheet the way the "
             f"calculator lays a part, so it was worked turned",
             f"{rec['parts_per_sheet']} to a sheet with its {rec['length_mm']:g} mm side as the "
             f"sheet's Length",
             "confirm the part can be printed turned on this sheet")
    for point in rec.get("points_to_confirm") or []:
        _ask(priced, f"AI Print calculator, as it stands: {point}",
             f"the sheet is worked as it stands; {pn} is {_gbp(rec['total_gbp'])} each on it",
             "estimating to confirm or correct the sheet; the next run reads it")
    print(f"   [print] {pn}: {rec['substrate']} {rec['length_mm']:g} x {rec['width_mm']:g} mm, "
          f"{rec['parts_per_sheet']} to a sheet, {_gbp(rec['total_gbp'])} each from the AI Print "
          f"calculator (PROVISIONAL)", flush=True)
    return priced


def records_from(part_estimates: Any) -> List[Dict[str, Any]]:
    """Every part's print calculator record, for the e-mail's calculator section."""
    return [dict(p["print_calculator"]) for p in (part_estimates or [])
            if isinstance(p, dict) and isinstance(p.get("print_calculator"), dict)]
