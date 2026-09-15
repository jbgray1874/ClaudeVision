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
                            "refused": []}
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
            # Pad past the last break with the last break itself: the vector must not
            # descend or go blank, or LOOKUP returns the wrong column rather than an error.
            _v = vector[i] if i < len(vector) else vector[-1]
            _cell.value = _v
        done["quantities"] = list(vector)

        _by_row: Dict[int, Dict[str, Any]] = {}
        for ln in (lines or []):
            try:
                _r = int(ln.get("sheet_row") or 0)
            except (TypeError, ValueError):
                continue
            if first_bom <= _r <= last_bom:
                _by_row[_r] = ln

        for bom_row, line in sorted(_by_row.items()):
            target = bom_row + row_offset
            if target < 1:
                continue
            wrote = False
            for i, qty in enumerate(vector):
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
