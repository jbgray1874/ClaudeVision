"""One sheet, every quantity — filling in the table SDI has always had and never populated.

    "Let's look at collapsing all the s/sheets into one when we have multiple unit
     quantities. We have estimator example of how this was done."     — James Gray, 15 Sep

Howard's own 0355255 workbook is the specification, and he filled it in BY HAND:

    Bill of Materials (Per Unit)      1        10       50      250     1000
    UPC Sticker                     0.0019   0.0019   0.0019  0.0019   0.0019
    EPDM Closed Cell Tape (10 Mtrs)           4.50     4.50    4.50     4.50
    3050 x 2050 x 2mm Clear XT                45.19    45.19   45.19    45.19
    Poly Bag 12 x 18 x 100G                   17.91    17.91   17.91    17.91
    Large Stock Box                           0.189    0.0378  0.02268  0.01701

One row per purchased material, one column per break, and the Estimate looks the right column
up with LOOKUP($D$6, ...). Change the order quantity and the whole sheet moves. That is what
"one spreadsheet for every quantity" means here, and SDI already had the mechanism.

WHAT WAS ACTUALLY WRONG, measured on 12349-02's book rather than assumed:

    price cells on the break tab      0 non-empty, every row, every column
    break-tab rows available          15 (5-19) against a BOM of 40 rows (11-50)
    rows 14-19                        =_xlfn.SINGLE(Estimate!#REF!)
    Estimate J45:J50                  point at break rows 14-19 — ALREADY USED by BOM
                                      rows 20-25, so six lines would read six others' prices
    Estimate J22,J23,J26,J27,J28      a LITERAL written over the LOOKUP

The engine had never touched it: wb_populate lists the tab under `structural_sheets` with
"NEVER overwrite these". That rule protects the estimators' own layout and it is right; what
it also did was leave the table permanently empty, so every quantity needed its own workbook.
Writing PRICES into a table built to hold prices is using it, not overwriting it — and this
writes only into cells that are EMPTY, so a figure an estimator typed is never displaced.

THE OFFSET IS A NUMBER, NOT AN ASSUMPTION. Break row = BOM row + `row_offset`, read from
config, because the template is being widened and the mapping will change when it is. One
number moves with it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def quantity_vector(breaks: Sequence[int]) -> List[int]:
    """The ascending quantity row the LOOKUP resolves against.

    ALWAYS STARTS AT 1, exactly as Howard's does. LOOKUP against a vector whose first value
    is 10 returns #N/A for an order of 1 — and somebody WILL open the sheet at 1 to sanity
    check a unit cost. His starts at 1 for the same reason.

    Ascending and de-duplicated, because LOOKUP over an unsorted vector does not error, it
    returns the wrong column — the failure this whole area keeps producing.
    """
    out = sorted({int(q) for q in (breaks or ()) if int(q) >= 1})
    if not out:
        return []
    if out[0] != 1:
        out.insert(0, 1)
    return out


def _price_at(line: Dict[str, Any], qty: int) -> Optional[float]:
    """This line's per-unit price at that order quantity.

    PER-ORDER LINES ARE THE ONLY ONES THAT MOVE, and they are the reason the table earns its
    place. On Howard's sheet the tape, the sheet and the poly bag are flat across all four
    breaks; the stock box falls 0.189 -> 0.017 because one box serves ten units and nine
    serve a thousand. A table of five identical columns would be decoration.
    """
    # A METHOD-PRICED LINE KNOWS ITS ORDER COST AT EACH STATED BREAK — the boxes are a
    # step, not a rate, so dividing THIS order's cost by another quantity would smear the
    # step into a slope. Exact breaks only; between them the per-order path below divides
    # what it knows, which is the same behaviour as before this map existed.
    _at = line.get("order_gbp_at") or {}
    _hit = _at.get(qty, _at.get(str(qty)))
    if _hit not in (None, ""):
        try:
            return round(float(_hit) / float(qty), 5) if qty else None
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    _order = line.get("order_gbp")
    if _order not in (None, ""):
        try:
            _o = float(_order)
        except (TypeError, ValueError):
            return None
        # Per-order money divided by the order it is spread over — and by the COUNT of
        # whatever is bought per order where the record states it (1 box for 10 or 50, 3
        # for 250, 9 for 1000 — Howard's own figures, from the record, never inferred).
        _per_order_units = line.get("units_per_order") or {}
        try:
            _n = float(_per_order_units.get(str(qty)) or _per_order_units.get(qty) or 1)
        except (TypeError, ValueError):
            _n = 1.0
        return round(_o * _n / float(qty), 5) if qty else None
    _unit = line.get("unit_gbp")
    if _unit in (None, ""):
        return None
    try:
        return round(float(_unit), 5)
    except (TypeError, ValueError):
        return None


def lines_from_record(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The costed lines, shaped for the break table — per-unit money and per-ORDER money.

    WHICH LINES ACTUALLY MOVE WITH THE QUANTITY, which is the question this table exists to
    answer and the one nobody could answer from the sheet. Measured on 10975-02 at 1 off
    against the same estimate at 50: EVERY material line was identical and every labour line
    moved. There are only three ways a line can move:

        setup, on labour        always — and it is the Estimate's own arithmetic, on the
                                main sheet, already right. Not this table's business.
        bought PER ORDER        a box, a pallet, freight, a minimum charge. Per unit is
                                count x price / quantity, and it moves in STEPS because the
                                count is a whole number.
        a supplier price break  a per-unit material whose purchase price drops at volume.

    Everything else is flat by nature: one unit's worth per unit at a fixed price. Howard's
    own sheet is four flat rows and one that moves — and the four are not padding, they are
    the record of somebody having checked that they do not move.

    So a commercial line's ORDER figure is carried here rather than its per-unit one, because
    that is the number the division has to be done on at each break.
    """
    out: List[Dict[str, Any]] = []
    try:
        from costed_facts import costed_job                            # noqa: PLC0415
        job = costed_job(summary) or {}
    except Exception:                                                  # noqa: BLE001
        return out

    _by_code: Dict[str, Dict[str, Any]] = {}
    for _cl in (summary.get("commercial_lines") or []):
        if isinstance(_cl, dict) and _cl.get("code"):
            _by_code[str(_cl["code"]).strip().upper()] = _cl
    try:
        _counts = dict(getattr(__import__("config"), "PER_ORDER_UNIT_COUNTS", {}) or {})
    except Exception:                                                  # noqa: BLE001
        _counts = {}

    for ln in (job.get("lines") or []):
        if not isinstance(ln, dict):
            continue
        _row = ln.get("sheet_row")
        if not _row:
            continue
        _code = str(ln.get("part_number") or "").strip().upper()
        rec: Dict[str, Any] = {"sheet_row": _row, "code": _code,
                               "description": ln.get("description")}
        _com = _by_code.get(_code)
        if _com and _com.get("order_gbp") not in (None, ""):
            rec["order_gbp"] = _com["order_gbp"]
            if _com.get("order_gbp_at_breaks"):
                # the packing method computed the order cost at each stated break itself
                rec["order_gbp_at"] = _com["order_gbp_at_breaks"]
            if _code in _counts:
                rec["units_per_order"] = _counts[_code]
        else:
            _u = ln.get("charged_unit_gbp")
            if _u in (None, ""):
                _u = ln.get("engine_unit_gbp")
            if _u not in (None, ""):
                rec["unit_gbp"] = _u
        if "order_gbp" in rec or "unit_gbp" in rec:
            out.append(rec)
    return out


def write_price_breaks(wb: Any, lines: Sequence[Dict[str, Any]], breaks: Sequence[int],
                       cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fill the quantity row and every line's price at every break. Returns what it did.

    Never raises into a run: this makes an estimate more useful and may not damage it.
    """
    cfg = dict(cfg or {})
    sheet = str(cfg.get("sheet") or "Material Price Break")
    est_name = str(cfg.get("estimate_sheet") or "Estimate")
    row_offset = int(cfg.get("row_offset", -6))
    first_bom = int(cfg.get("first_bom_row", 11))
    last_bom = int(cfg.get("last_bom_row", 50))
    qty_first = str(cfg.get("qty_vector_first_cell") or "F180")
    first_col = int(cfg.get("first_price_col", 4))          # D
    last_col = int(cfg.get("last_price_col", 14))           # N

    done: Dict[str, Any] = {"quantities": [], "rows": 0, "skipped_occupied": 0,
                            "outside_table": [], "refused": []}
    vector = quantity_vector(breaks)
    if not vector:
        done["refused"].append("no quantities asked for")
        return done
    if len(vector) > (last_col - first_col + 1):
        # SAY IT, DO NOT TRUNCATE. A break table quietly missing its last column is the
        # exact complaint Howard raised from the other end.
        done["refused"].append(
            f"{len(vector)} quantities asked for and the table has "
            f"{last_col - first_col + 1} columns — widen it or ask for fewer")
        return done
    try:
        if sheet not in wb.sheetnames or est_name not in wb.sheetnames:
            done["refused"].append(f"no '{sheet}' or '{est_name}' sheet on this workbook")
            return done
        ws = wb[sheet]
        est = wb[est_name]

        # THE QUANTITY ROW IS WRITTEN ON THE ESTIMATE, NOT HERE. The break tab's header
        # reads =Estimate!F180..F190, so the numbers belong in the Estimate's own Qty Breaks
        # column — which the engine already owns. Nothing of the estimators' layout is
        # touched to change which quantities the sheet offers.
        import re as _re
        _m = _re.match(r"([A-Z]+)(\d+)", qty_first.upper())
        if not _m:
            done["refused"].append(f"cannot read the quantity cell '{qty_first}'")
            return done
        _qcol, _qrow = _m.group(1), int(_m.group(2))
        for i in range(last_col - first_col + 1):
            _cell = est[f"{_qcol}{_qrow + i}"]
            # PAD WITH THE LAST BREAK. This has now been wrong in BOTH directions and the
            # run settled it.
            #
            # It first padded; that was changed to blanks, reasoning from Howard's own sheet
            # — his row reads 1, 10, 50, 250, 1000, 1250, 1500 and then stops, and LOOKUP
            # ignores cells after the end. True of HIS sheet, where row 4 holds literal
            # numbers. Ours does not: the break tab's row 4 is =Estimate!F180..F190, and a
            # formula pointing at an empty cell returns 0. The 14:23 book came out
            #
            #     1, 10, 50, 250, 1000, 0, 0, 0, 0, 0, 0
            #
            # which DESCENDS, and LOOKUP over a descending vector does not error — it
            # returns the wrong column. Six columns headed 0 were the visible half of it.
            #
            # So the padding stays, and the reason is that our header is computed where his
            # is typed. Repeated 1000s read as "the table ends at 1000", which is true, and
            # they keep the vector non-descending, which is what LOOKUP requires.
            _cell.value = vector[i] if i < len(vector) else vector[-1]
        done["quantities"] = list(vector)

        # A BROKEN REFERENCE IS NOT A PRICE, AND IT SPREADS.
        #
        # The 15:40 book carried, on two empty BOM rows:
        #
        #     J19  =LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,'Material Price Break'!#REF!)
        #
        # — the template's own formulas, left pointing at nothing after the break tab was
        # widened by hand. Rows 17 and 18 survived the same edit pointing at break rows 43
        # and 44 instead of 11 and 12. Nothing the engine wrote; everything the estimator
        # opens. #REF! propagates through =(J19*K19)*(100%+L19) into M, and M is what the
        # block totals sum, so two untouched empty rows can take the Total Material cell out.
        #
        # ONLY ON A ROW WITH NOTHING ON IT. A row carrying a part is the estimator's line and
        # a broken formula there is a fact to report, not to tidy away — it is named in
        # `refused` and left exactly as it is.
        _jcol = int(cfg.get("price_col", 10))
        _codecols = (int(cfg.get("code_col", 8)), int(cfg.get("desc_col", 3)))
        # AND A REFERENCE THAT SURVIVED THE EDIT POINTING AT THE WRONG ROW IS WORSE.
        #
        # #REF! at least LOOKS broken. The 16:07 book also carried, from the same hand-edit,
        #
        #     J17  =LOOKUP(...,'Material Price Break'!D43:N43)     expected D11:N11
        #     J50  =LOOKUP(...,'Material Price Break'!D74:N74)     expected D44:N44
        #
        # — every row from 17 down shifted 32 rows low, valid formulas all, silently reading
        # whatever happens to be 32 rows below their own break line. The engine masks it on
        # rows it prices (a literal overwrites the formula); the row it does NOT mask is the
        # one an estimator adds by hand, whose typed break prices then feed somebody else's
        # row. That is the estimator's own mechanism broken inside a delivered book.
        #
        # SAME RULE AS #REF!: an empty row is repaired to the row-offset pattern and named;
        # a row carrying a part is reported and left exactly as it is. And repaired IN THIS
        # BOOK only — the blank template is the estimators' document, so the run says out
        # loud, every time, that the blank still needs fixing.
        _range_pat = _re.compile(r"!(\$?)([A-Z]+)(\$?)(\d+):(\$?)([A-Z]+)(\$?)(\d+)")
        for _r in range(first_bom, last_bom + 1):
            _c = est.cell(row=_r, column=_jcol)
            _v = _c.value
            if not isinstance(_v, str):
                continue
            # #REF! is judged on any formula — Excel can eat the sheet name along with the
            # reference, so requiring the name here would skip exactly the broken ones. The
            # misroute check below IS scoped to formulas naming the break sheet, because a
            # reference into any other sheet is not this mechanism's to judge.
            if "#REF!" not in _v and sheet not in _v:
                continue
            _occupied = any(str(est.cell(row=_r, column=_cc).value or "").strip()
                            for _cc in _codecols)
            _want = _r + row_offset
            if "#REF!" in _v:
                if _occupied:
                    done["refused"].append(
                        f"{est.title}!{_c.coordinate} is #REF! on a row that carries a "
                        f"part — left alone; the template's break-tab reference needs "
                        f"repairing")
                    continue
                _c.value = None
                done.setdefault("cleared_broken_refs", []).append(_c.coordinate)
                continue
            # The formula holds two ranges on the break sheet: the header ($D$4:$N$4) and
            # this row's prices. The header names the fixed header row; only a range whose
            # BOTH rows should equal this row's break line is judged, so the header itself
            # is never "repaired".
            _ranges = list(_range_pat.finditer(_v))
            if not _ranges:
                continue
            _last = _ranges[-1]
            _r1, _r2 = int(_last.group(4)), int(_last.group(8))
            if _want < 1 or (_r1 == _want and _r2 == _want):
                continue
            if _occupied:
                done["refused"].append(
                    f"{est.title}!{_c.coordinate} reads break row {_r1} and should read "
                    f"{_want}, on a row that carries a part — left alone; the template's "
                    f"break-tab reference needs repairing")
                continue
            _fixed = (_v[:_last.start()]
                      + f"!{_last.group(1)}{_last.group(2)}{_last.group(3)}{_want}"
                        f":{_last.group(5)}{_last.group(6)}{_last.group(7)}{_want}"
                      + _v[_last.end():])
            _c.value = _fixed
            done.setdefault("repaired_lookups", []).append(
                f"{_c.coordinate}: break row {_r1} -> {_want}")

        _by_row: Dict[int, Dict[str, Any]] = {}
        for ln in (lines or []):
            try:
                _r = int(ln.get("sheet_row") or 0)
            except (TypeError, ValueError):
                continue
            if first_bom <= _r <= last_bom:
                _by_row[_r] = ln
            elif _r > last_bom:
                # NO SILENT CAP. The break table is shorter than the BOM block, so a line
                # below its last row cannot be priced across the quantities — and a table
                # that is simply missing a material reads as "this one does not move",
                # which is the one thing it must never say by accident.
                done["outside_table"].append(
                    f"{ln.get('code') or ln.get('description') or '?'} (sheet row {_r})")

        for bom_row, line in sorted(_by_row.items()):
            target = bom_row + row_offset
            if target < 1:
                continue
            wrote = False
            # PAD THE PRICES THE SAME WAY THE HEADER IS PADDED, and for the same reason.
            #
            # THE 15:40 BOOK PRICED EVERY BREAK-DRIVEN LINE AT ZERO AT ITS TOP QUANTITY.
            # The header runs the full width of the table — 1, 10, 50, 250, 1000, then 1000
            # repeated to column N, so the vector never descends. The prices stopped at the
            # fifth column. LOOKUP resolves to the LAST cell holding the largest value not
            # above $D$6, so an order of 1000 landed on column N, and column N was empty:
            #
            #     header   1   10   50   250   1000   1000   1000   1000   1000   1000   1000
            #     prices  .09  .09  .09   .09    .09      -      -      -      -      -      -
            #                                                                        ^ £0.00
            #
            # It was invisible at 250 and correct at 1 — the two quantities anyone checks.
            # Padding one row and not the other is what made a table that looked right and
            # answered wrong at exactly the quantity it exists to answer.
            _cols = last_col - first_col + 1
            for i in range(_cols):
                qty = vector[i] if i < len(vector) else vector[-1]
                cell = ws.cell(row=target, column=first_col + i)
                # ONLY INTO AN EMPTY CELL. An estimator's own figure outranks anything the
                # engine derived, and on this tab a typed number is the estimator working.
                if cell.value not in (None, ""):
                    done["skipped_occupied"] += 1
                    continue
                price = _price_at(line, qty)
                if price is None:
                    continue
                cell.value = price
                wrote = True
            if wrote:
                done["rows"] += 1
        return done
    except Exception as exc:                                      # noqa: BLE001
        done["refused"].append(f"{type(exc).__name__}: {exc}")
        return done
