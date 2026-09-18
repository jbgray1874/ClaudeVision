"""What a document may print for a line, and where that figure comes from.

James Gray, 18 September 2026, after the fifth surface was found:

    "Use one `displayed_charge` fact per line. Where a workbook sheet owns the charge, every
     renderer gets the workbook amount or a dash — never an engine comparison."
    "Every published currency amount must have a source fact and workbook-cell reference.
     Narrative totals may not use independent engine aggregates."

THE £3.88 WAS FOUND FIVE TIMES, ONE PER RERUN. The HTML report's money cell, the AI Provenance
column, the AI Explanation table, the AI Explanation narrative, and section 11's reassurance
that a dashed row IS costed. Each was fixed alone, each fix was tested green, and the next
book carried it again somewhere else. That is not five bugs: it is one missing fact, asked for
five times in five places, each renderer re-deriving the answer from the raw engine estimate.

AND THE £321.88 IS THE SAME FAULT IN AN AGGREGATE. `AI Explanation!A111` printed "Of the
£321.88 it assembled..." — the engine's own sum over its part estimates, before the sheet's
blocks, its absorption divisor and its customer terms — four sentences from the same paragraph
calling the sheet's £150.32 the real one. Nobody could trace it, because it is on no sheet.

So this module answers both questions once:

    displayed_charge(line)      what this line prints, and from which cell
    publishable_total(record)   what a narrative may call the job total, and from which cell

A renderer that asks these cannot publish an engine figure by accident, because it never sees
one unless the fact says it may. The pattern is `fold_count`'s: separate facts, one resolver,
every consumer asks it, and the losing reading is kept rather than discarded.
"""
from typing import Any, Dict, Mapping, Optional

SHEET_NAME = "Estimate"

# Blocks where an estimator has ruled that the workbook's own formula and rate cell govern.
# On these a second figure is not evidence: the question is closed and a comparator re-opens
# it. Every other block keeps its cross-check, which has caught real faults.
RULED_BLOCKS = {"steel", "sheet steel"}

WORKBOOK = "workbook"
# An engine figure with no workbook cell behind it. Never a publishable currency amount --
# it is an input still wanted, carried as a diagnostic so nobody loses it.
PENDING = "pending"
NOTHING = "none"


def _num(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def cell_reference(line: Mapping[str, Any]) -> Optional[str]:
    """`Estimate!M63` — the cell a reader can open to check the figure, or None.

    RECORDED, NOT INFERRED. The first cut of this built the reference from the row number and
    a MONEY_COLUMN constant, on the grounds that every money column in today's template is M.
    That is true today and it is the same bet that shipped wrong twice this afternoon — the
    comparator gate was keyed on the engine's `cost_method`, then on the block's display
    label, both of which also looked obviously correct.

    The read-back locates the value column by reading the block's header and stamps
    `charged_cell` there. Where that is missing, this returns None and the figure is NOT
    publishable: a currency amount with no cell behind it is the £321.88 shape, and the answer
    to it is to say nothing rather than to guess a column.
    """
    if not isinstance(line, Mapping):
        return None
    recorded = str(line.get("charged_cell") or "").strip()
    return recorded or None


def _block_is_ruled(line: Mapping[str, Any]) -> bool:
    block = str((line or {}).get("block") or "").strip().lower()
    if block in RULED_BLOCKS:
        return True
    origin = (line or {}).get("price_origin")
    if isinstance(origin, Mapping):
        if str(origin.get("block") or "").strip().lower() in RULED_BLOCKS:
            return True
    return False


def displayed_charge(line: Mapping[str, Any]) -> Dict[str, Any]:
    """The one fact a renderer needs to print money for a line.

    amount              what to print
    cell                where it came from, for a reader who wants to check
    basis               workbook | engine | none
    diagnostic          the engine's own figure, kept whatever happens to it
    publish_diagnostic  whether a renderer may show it beside the amount
    withheld_reason     why it may not, when it may not

    A renderer prints `amount` and, only when `publish_diagnostic` is true, `diagnostic`. It
    never reaches past this into the raw estimate — that is the whole point.
    """
    if not isinstance(line, Mapping):
        return {"amount": None, "cell": None, "basis": NOTHING, "diagnostic": None,
                "publish_diagnostic": False, "withheld_reason": "no line",
                "label": "no figure"}

    # EITHER SHAPE OF ROW. A costed LINE carries `charged_ext_gbp`; a row straight off the
    # read-back carries `total_value_gbp` — and both are the sheet's own figure, read from the
    # same cell. Refusing the second would throw away a legitimate workbook amount because the
    # caller happened to hold the row rather than the line, which is a renderer's accident and
    # not a fact about the money.
    charged = _num(line.get("charged_ext_gbp"))
    if charged is None:
        charged = _num(line.get("total_value_gbp"))
    engine = _num(line.get("engine_ext_gbp"))
    cell = cell_reference(line)

    if charged is not None and cell:
        amount, basis = charged, WORKBOOK
        label = f"the sheet's own figure, {cell}"
    elif charged is not None:
        # CHARGED, BUT WE CANNOT SAY FROM WHERE. Publishable only in the sense that the sheet
        # calculated it; the cell is missing, so a reader cannot check it. Said, not hidden.
        amount, basis = charged, WORKBOOK
        label = "the sheet's own figure — the cell it was read from was not recorded"
    elif engine:
        # ── AN ENGINE-ONLY AMOUNT IS NOT A PUBLISHABLE CURRENCY AMOUNT ──────────────
        #
        # James Gray, 18 Sep 2026: "Do not let an engine-only amount become a publishable
        # currency amount without a workbook cell. Keep it as a diagnostic/pending input."
        #
        # The first cut returned it as `amount`, so a renderer printed it as money with a
        # caption. That is how £3.88 reached five pages and how £321.88 reached a narrative:
        # a figure with no cell behind it, rendered in pounds, reads as the job's cost. It is
        # carried as a DIAGNOSTIC and the line reads as PENDING — which is what it is.
        amount, basis = None, PENDING
        label = "not yet priced on the sheet — an engine figure is held for diagnosis only"
    else:
        amount, basis = None, NOTHING
        label = "no figure"

    publish, why = False, ""
    if basis == WORKBOOK and engine is not None and engine:
        if _block_is_ruled(line):
            why = ("the estimator has ruled that the workbook's own block and rate cell "
                   "govern this line, so a second figure is not evidence")
        elif abs(engine - charged) < 0.01:
            why = "the two agree, so there is nothing to show"
        else:
            publish = True
    elif basis == PENDING:
        why = ("an engine figure with no workbook cell behind it is not a publishable "
               "currency amount — the line is pending a price")
    elif basis == NOTHING:
        why = "there is no figure on this line"

    return {
        "amount": amount,
        "cell": cell,
        "basis": basis,
        "diagnostic": engine,
        "publish_diagnostic": publish,
        "withheld_reason": why,
        "label": label,
    }


def publishable_total(record: Mapping[str, Any]) -> Dict[str, Any]:
    """What a narrative may call this job's total, and where it comes from.

    THE £321.88 RULE. A document may print the sheet's own total. It may NOT print an engine
    aggregate as though it were the job's cost — `document_total_provisional_gbp` is the sum of
    the engine's part estimates before the sheet's blocks, its absorption divisor and its
    customer terms, and on 401912-02 that was £321.88 against a workbook reading £150.32.

    Where the sheet's total cannot be read, this returns None and says so, which is the honest
    answer: a sentence with no total in it is better than a sentence with an untraceable one.
    """
    if not isinstance(record, Mapping):
        return {"amount": None, "cell": None, "basis": NOTHING,
                "why": "no costed record"}
    run = record.get("run") if isinstance(record.get("run"), Mapping) else {}
    # The cell the read-back located by scanning for the unit-cost label. Not "Estimate!G6" —
    # hard-coding that would be the same guess this whole module refuses to make.
    cell = str(run.get("unit_cell") or record.get("unit_cell") or "").strip() or None
    for holder, key in ((run, "unit_cost_gbp"), (run, "unit_gbp"),
                        (record, "unit_cost_gbp")):
        value = _num((holder or {}).get(key))
        if value is None:
            continue
        if not cell:
            # A total with no cell behind it is the £321.88 shape. Refused, and said.
            return {"amount": None, "cell": None, "basis": NOTHING,
                    "why": ("the sheet's total was read but the cell it came from was not "
                            "recorded, so it cannot be published as a traceable figure")}
        return {"amount": value, "cell": cell, "basis": WORKBOOK, "why": ""}
    return {"amount": None, "cell": None, "basis": NOTHING,
            "why": ("the sheet's own total could not be read, and an engine aggregate is "
                    "not the job's cost")}
