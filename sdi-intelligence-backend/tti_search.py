"""The TTI tracker's everyday questions, as pure functions over workbook rows.

Phase one answered one question: what is leaving SDI on a day. These are the
six things Selina Kuddus, Lee Merril and Sue Rogers do by eye instead, every
day, across seventeen weekly sheets:

    find        search by order number, customer PO, part code, TTI account
    notes       the pick note and delivery note, out of the free-text COMMENTS
    chase       what is blocked, and by what
    overdue     a customer due date that has passed with no departure planned
    morning     what is due out, what has slipped, what is missing
    quality     the cells that cannot be read, and the ones that contradict

── WHY THESE AND NOT A SAGE INTEGRATION ─────────────────────────────────────
Every one is answerable from the workbook that is already the system of
record for TTI despatch. None needs an ERP connection, so none is waiting on
one. What Sage will add later is the half the spreadsheet does not know -
stock, works-order progress, the invoice as finance posted it - and that is a
separate conversation with Marc.

── WHAT IS DELIBERATELY NOT HERE ────────────────────────────────────────────
No writer, no mail, no share. The caller supplies rows that somebody already
had the right to read, and every answer carries the sheet and row it came
from so it can be checked at source. A count this module cannot stand behind
is reported as unknown rather than estimated: a despatch answer that is
confidently wrong is worse than one that says it does not know.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

from sue_despatch import ScheduleDate, SourceRow, _clean, _get, _norm, schedule_date


# The departure column, and the customer's wanted-by column. They are not the
# same question and conflating them is the first mistake available here.
DEPARTS = ("LORRY FROM SDI",)
DUE = ("DUE DATE",)

# The seventeen weekly sheets are the plan; anything else in the book (notes,
# pivot tabs, a stray copy) is not a despatch week.
IDENTITY = ("SDI ORDER NO", "CUSTOMER PO", "PART CODE", "TTI ACCOUNT")


def _row_is_real(row: SourceRow) -> bool:
    return any(_clean(_get(row.cells, name)) for name in
               ("SDI ORDER NO", "PART CODE", "DESCRIPTION"))


def _cell(row: SourceRow, *names: str) -> str:
    return _clean(_get(row.cells, *names))


# ── The free-text column ──────────────────────────────────────────────────────
#
# COMMENTS is where the real state of an order lives, in sentences:
#
#     "Pick note number: 40015908 \nDel Note -"
#
# A pick note means the warehouse has picked it. A delivery note means it went.
# The difference between those two is most of what a chase list is, and today
# it is only visible by reading the cell.
_LABELS = re.compile(
    r"(pick\s*notes?|del(?:ivery)?\s*notes?|invoice|proof\s*of\s*export|booked\s*in)",
    re.I)
_PICK = r"pick\s*notes?"
_DEL = r"del(?:ivery)?\s*notes?"
# "await po", "awaiting PO", "chase PO", "no po yet" - the phrase Selina uses.
_AWAITING_PO = re.compile(r"\b(?:a?wait(?:ing)?|chas(?:e|ing)|need|no)\b[^.\n]{0,20}\bp\.?o\.?\b", re.I)
_NUMBER = re.compile(r"\d{4,}")


def _tail_after(text: str, label: str) -> str:
    """What a label says, up to the next label or the end of its line.

    Cut at the line first and then at the next label, because both forms
    appear: two labels on one line, and one per line.
    """
    for hit in _LABELS.finditer(text):
        if not re.fullmatch(label, hit.group(1), re.I):
            continue
        tail = text[hit.end():].split("\n", 1)[0]
        following = _LABELS.search(tail)
        return (tail[:following.start()] if following else tail).strip(" :-=\t,;")
    return ""


def notes(comments: Any) -> dict:
    """The pick note and delivery note numbers written into COMMENTS.

    "Del Note -" is a dash, not a number: the column has been filled in to say
    there is no delivery note yet. Reading that as a delivery note would turn
    the one row that needs chasing into the one row that looks finished.
    """
    text = str(comments or "")
    found = {}
    for key, label in (("pick_note", _PICK), ("delivery_note", _DEL)):
        tail = _tail_after(text, label)
        numbers = _NUMBER.findall(tail)
        found[key] = numbers[0] if numbers else ""
        found[key + "s"] = numbers
        found[key + "_said"] = tail
    found["awaiting_po"] = bool(_AWAITING_PO.search(text))
    found["comments"] = " ".join(text.split())
    return found


# ── 1 + 2. Search ─────────────────────────────────────────────────────────────

def _haystack(row: SourceRow) -> str:
    return " ".join(_clean(v) for v in row.cells.values() if _clean(v))


def _identifiers(row: SourceRow) -> dict:
    return {name: _cell(row, name) for name in IDENTITY}


def _line(row: SourceRow, *, as_of: date) -> dict:
    """One order line, as every view here reports it.

    Both dates are given, each with how it was read, because "the 8th" in the
    due column and "the 8th" in the departure column mean different things and
    a reader cannot tell which they have been handed otherwise.
    """
    departs = schedule_date(_get(row.cells, *DEPARTS), as_of=as_of)
    due = schedule_date(_get(row.cells, *DUE), as_of=as_of)
    note = notes(_get(row.cells, "COMMENTS"))
    return {
        "source": row.cite(),
        "sheet": row.sheet,
        "order": _cell(row, "SDI ORDER NO"),
        "customer_po": _cell(row, "CUSTOMER PO"),
        "part": _cell(row, "PART CODE"),
        "description": _cell(row, "DESCRIPTION"),
        "tti_account": _cell(row, "TTI ACCOUNT"),
        "who_paying": _cell(row, "WHO PAYING"),
        "qty": _cell(row, "QTY"),
        "made_in": _cell(row, "CHINA,UK OR POLAND MAN", "CHINA UK OR POLAND MAN"),
        "delivery_address": _cell(row, "DEL ADD"),
        "destination": _cell(row, "INTO ELC OR LOCAL DESTNATION",
                             "INTO ELC OR LOCAL DESTINATION"),
        "trailer": _cell(row, "TRAILER"),
        "pallets_as_recorded": _get(row.cells, "PALLETS"),
        "label_and_batch_done": _cell(row, "LABEL + Batch DONE", "LABEL + BATCH DONE"),
        "booked_in_with_tti": _cell(row, "BOOKED IN WITH TTI"),
        "invoice_number": _cell(row, "INVOICE NUMBER"),
        "proof_of_export": _cell(row, "PROOF OF EXPORT"),
        "value_as_recorded": _get(row.cells, "VALUE"),
        "pick_note": note["pick_note"],
        "delivery_note": note["delivery_note"],
        "comments": note["comments"],
        "departs": departs.value.isoformat() if departs.value else None,
        "departs_cell": departs.raw,
        "departs_basis": departs.basis,
        "departs_tentative": departs.tentative,
        "due": due.value.isoformat() if due.value else None,
        "due_cell": due.raw,
        "due_basis": due.basis,
    }


def find(rows: Iterable[SourceRow], query: str, *, as_of: date, limit: int = 60) -> dict:
    """Search every sheet at once for an order number, PO, part code or account.

    ── WHY RANKED RATHER THAN FILTERED ────────────────────────────────────────
    An order number typed into a general search also appears inside comments on
    other lines ("replaces 15194"). Returning those mixed in with the line
    actually asked about makes the caller do the sorting. So an exact match on
    an identifying column comes first, labelled as such, and the looser matches
    follow under their own heading rather than being discarded - because the
    comment that mentions the order is sometimes exactly what was wanted.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", str(query or "").lower()) if len(w) > 1]
    exact: list[dict] = []
    mentions: list[dict] = []
    for row in rows:
        if not _row_is_real(row):
            continue
        ids = {_norm(v) for v in _identifiers(row).values() if v}
        hay = _haystack(row).lower()
        if not words:
            continue
        if all(_norm(w) in ids or any(_norm(w) in i for i in ids) for w in words):
            exact.append(_line(row, as_of=as_of))
        elif all(w in hay for w in words):
            mentions.append(_line(row, as_of=as_of))
    order = lambda line: (line["departs"] or line["due"] or "9999-12-31", line["sheet"])
    exact.sort(key=order)
    mentions.sort(key=order)
    return {
        "question": f"Where does {_clean(query)} appear in the Despatch Plan?",
        "searched_for": _clean(query),
        "match_count": len(exact),
        "matches": exact[:limit],
        "matches_truncated": len(exact) > limit,
        "mention_count": len(mentions),
        "mentions": mentions[:limit],
        "mentions_truncated": len(mentions) > limit,
        "note": ("Matches are lines whose order number, customer PO, part code or TTI "
                 "account is what you searched for. Mentions are lines that merely "
                 "contain the words, usually in the comments."),
    }


# ── 3. The chase list ─────────────────────────────────────────────────────────
#
# Each reason is a pair: a state the row is in, and a thing that should have
# happened by now and has not. The second half is why these can be listed at
# all - "no invoice number" on a line leaving in three weeks is not a chase,
# it is a line leaving in three weeks.

# A cell that has been filled in to say "nothing here yet". Treating these as
# answers is how a blank column comes to look complete.
_EMPTY_ANSWERS = {"", "-", "--", "n/a", "na", "no", "none", "nil", "tbc", "tba",
                  "tbd", "x", "?", "??", "not yet", "pending", "await", "awaiting"}


def _said_yes(value: str) -> bool:
    return bool(_clean(value)) and _norm(value) not in {_norm(v) for v in _EMPTY_ANSWERS}


def _days(line: dict, key: str, *, as_of: date) -> int | None:
    if not line[key]:
        return None
    return (date.fromisoformat(line[key]) - as_of).days


def _when_words(out: int | None) -> str:
    """How near a departure is, in words. "in 0 day(s)" is today, and reading
    that sentence on a chase list is how a reader stops trusting the list."""
    if out is None:
        return "No planned departure"
    if out < 0:
        return f"Planned departure was {-out} day(s) ago"
    if out == 0:
        return "Due to leave today"
    if out == 1:
        return "Due to leave tomorrow"
    return f"Due to leave in {out} days"


def chase(rows: Iterable[SourceRow], *, as_of: date, horizon: int = 7) -> dict:
    """What is blocked, grouped by what is blocking it.

    `horizon` is how far ahead a thing has to be before it is worth chasing.
    Without it the list is every incomplete cell in the book, which is the same
    as no list at all.
    """
    reasons: dict[str, list[dict]] = {}

    def flag(key: str, line: dict, because: str, urgency: int | None) -> None:
        item = dict(line)
        item["because"] = because
        item["days_to_departure"] = urgency
        reasons.setdefault(key, []).append(item)

    for row in rows:
        if not _row_is_real(row):
            continue
        line = _line(row, as_of=as_of)
        out = _days(line, "departs", as_of=as_of)
        wanted = _days(line, "due", as_of=as_of)
        soon = out is not None and out <= horizon
        gone = out is not None and out < 0
        # Due before it is planned to leave, which is a promise already broken.
        if out is not None and wanted is not None and out > wanted:
            flag("late_against_due_date", line,
                 f"Planned to leave {line['departs']}, customer due date {line['due']} "
                 f"- {out - wanted} day(s) later than wanted.", out)
        if not _said_yes(line["customer_po"]) or notes(line["comments"])["awaiting_po"]:
            flag("awaiting_customer_po", line,
                 "No customer PO recorded"
                 + (" and the comments say it is still awaited." if
                    notes(line["comments"])["awaiting_po"] else "."), out)
        if line["pick_note"] and not line["delivery_note"] and (soon or gone):
            flag("picked_but_not_despatched", line,
                 f"Pick note {line['pick_note']} is recorded but no delivery note is, "
                 + ("and the planned departure has passed." if gone
                    else "and it is planned to leave within the week."), out)
        if gone and not _said_yes(line["invoice_number"]):
            flag("despatched_not_invoiced", line,
                 f"Planned to leave {line['departs']}, which has passed, and no "
                 f"invoice number is recorded.", out)
        if gone and _said_yes(line["invoice_number"]) \
                and not _said_yes(line["proof_of_export"]):
            flag("no_proof_of_export", line,
                 "Invoiced and gone, with no proof of export recorded. This only "
                 "applies if the consignment was exported - the workbook does not "
                 "say which were, so judge it by the destination.", out)
        if soon and not _said_yes(line["booked_in_with_tti"]):
            flag("not_booked_in_with_tti", line,
                 _when_words(out) + ", and it is not booked in with TTI.", out)
        if soon and not _said_yes(line["label_and_batch_done"]):
            flag("labels_not_done", line,
                 _when_words(out) + ", and labels and batch are not marked done.", out)

    groups = []
    for key, items in reasons.items():
        items.sort(key=lambda i: (i["days_to_departure"] is None,
                                  i["days_to_departure"] or 0))
        groups.append({"reason": key, "heading": _HEADINGS[key],
                       "count": len(items), "lines": items})
    groups.sort(key=lambda g: _HEADINGS_ORDER.index(g["reason"]))
    return {
        "question": "What is blocked, and by what?",
        "as_of": as_of.isoformat(),
        "horizon_days": horizon,
        "group_count": len(groups),
        "line_count": sum(g["count"] for g in groups),
        "groups": groups,
        "note": ("A line can appear under more than one heading, because it can be "
                 "blocked by more than one thing. Only lines leaving within "
                 f"{horizon} days (or already past) are chased for paperwork - "
                 "an empty invoice column three weeks out is not a problem."),
    }


_HEADINGS = {
    "despatched_not_invoiced": "Planned departure has passed, not invoiced",
    "picked_but_not_despatched": "Picked, with no delivery note",
    "not_booked_in_with_tti": "Not booked in with TTI",
    "labels_not_done": "Labels and batch not marked done",
    "awaiting_customer_po": "No customer PO",
    "late_against_due_date": "Planned to leave after the customer due date",
    "no_proof_of_export": "No proof of export recorded",
}
_HEADINGS_ORDER = list(_HEADINGS)


# ── 4. A due date that has passed, with no departure planned ─────────────────

def overdue_undated(rows: Iterable[SourceRow], *, as_of: date, limit: int = 100) -> dict:
    """Rows nobody has updated, as distinct from rows nobody has scheduled.

    ── THE DISTINCTION THIS EXISTS TO MAKE ────────────────────────────────────
    Most blank departure cells are normal: a plan that runs seventeen weeks out
    is meant to have blanks at the far end. The ones that matter are the rows
    whose CUSTOMER DUE DATE has already gone by while the departure cell is
    still empty. That is not "not scheduled yet", it is "the date passed and
    the sheet was not touched", and it is invisible in a count of blanks.
    """
    found, unreadable_due = [], 0
    for row in rows:
        if not _row_is_real(row):
            continue
        line = _line(row, as_of=as_of)
        if line["departs"]:
            continue
        if line["due"] is None:
            # No readable due date either: a question for the data-quality view,
            # not evidence of an overdue order. Counted so it cannot hide here.
            if line["due_cell"] and line["due_basis"] not in ("no departure date set",):
                unreadable_due += 1
            continue
        overdue_by = (as_of - date.fromisoformat(line["due"])).days
        if overdue_by > 0:
            line["overdue_by_days"] = overdue_by
            found.append(line)
    found.sort(key=lambda l: -l["overdue_by_days"])
    return {
        "question": "Which lines have a customer due date in the past and no planned departure?",
        "as_of": as_of.isoformat(),
        "line_count": len(found),
        "lines": found[:limit],
        "truncated": len(found) > limit,
        "unreadable_due_date_count": unreadable_due,
        "note": ("A blank departure cell on its own is normal weeks out. These are the "
                 "ones where the date the customer wanted has already gone by, which "
                 "usually means the row was never updated rather than never planned."),
    }


# ── 5. The morning despatch summary ──────────────────────────────────────────

def morning(rows: Iterable[SourceRow], *, day: date, as_of: date) -> dict:
    """What is due out today, what has slipped, and what is missing.

    Sue asked for this first, before anything else: the three things she
    assembles by reading the week's sheet every morning. It is produced as
    text, and deliberately not sent - who it goes to and from which mailbox is
    a decision for Sue and Selina, not for this module.
    """
    going, slipped, incomplete, unreadable = [], [], [], []
    for row in rows:
        if not _row_is_real(row):
            continue
        line = _line(row, as_of=as_of)
        out = _days(line, "departs", as_of=day)
        if line["departs"] is None and line["departs_cell"] \
                and line["departs_basis"] != "no departure date set":
            unreadable.append(line)
            continue
        if out == 0:
            missing = _missing_before_departure(line)
            if missing:
                line = dict(line)
                line["missing"] = missing
                incomplete.append(line)
            going.append(line)
        elif out is not None and out < 0 and not _said_yes(line["invoice_number"]):
            # Planned to go before today and still not invoiced: either it did
            # not go, or it went and the sheet has not caught up. Both are a
            # thing to say out loud in a morning summary.
            line = dict(line)
            line["slipped_by_days"] = -out
            slipped.append(line)
    going.sort(key=lambda l: (l["order"], l["part"]))
    slipped.sort(key=lambda l: -l["slipped_by_days"])
    return {
        "question": f"What does the despatch morning summary say for {day.isoformat()}?",
        "day": day.isoformat(),
        "as_of": as_of.isoformat(),
        "due_out_count": len(going),
        "due_out": going,
        "slipped_count": len(slipped),
        "slipped": slipped,
        "incomplete_count": len(incomplete),
        "incomplete": incomplete,
        "unreadable_date_count": len(unreadable),
        "unreadable_date_lines": unreadable[:25],
        "note": ("Slipped lines are planned to have left before today with no invoice "
                 "number recorded - which is either a departure that did not happen or "
                 "a sheet that has not caught up. The two look identical from here."),
    }


def _missing_before_departure(line: dict) -> list[str]:
    """What a line going out today has not got. Only the cells that stop it."""
    lacking = []
    if not _said_yes(line["booked_in_with_tti"]):
        lacking.append("not booked in with TTI")
    if not _said_yes(line["label_and_batch_done"]):
        lacking.append("labels and batch not marked done")
    if not _said_yes(line["customer_po"]):
        lacking.append("no customer PO")
    if not _clean(str(line["pallets_as_recorded"] or "")):
        lacking.append("no pallet count")
    if not _said_yes(line["delivery_address"]) and not _said_yes(line["destination"]):
        lacking.append("no delivery address or destination")
    return lacking


def summary_text(answer: dict) -> str:
    """The morning summary as the plain sentences it would be emailed as.

    Written here rather than in the page or the connector so the screen, the
    voice answer and anything pasted into an email say the same thing.
    """
    when = date.fromisoformat(answer["day"]).strftime("%A %d %B %Y")
    out = [f"TTI despatch - {when}", ""]
    if answer["due_out_count"]:
        out.append(f"Due to leave SDI today: {answer['due_out_count']} line(s).")
        for line in answer["due_out"]:
            bits = [line["order"] or "(no order no)", line["part"], line["description"]]
            tail = f"  - {' / '.join(b for b in bits if b)}"
            if line.get("missing"):
                tail += f"   [{'; '.join(line['missing'])}]"
            out.append(tail + f"   ({line['source']})")
    else:
        out.append("Nothing in the plan is set to leave SDI today.")
    out.append("")
    if answer["slipped_count"]:
        out.append(f"Planned to have left and not invoiced: {answer['slipped_count']} line(s).")
        for line in answer["slipped"][:15]:
            out.append(f"  - {line['order'] or '(no order no)'} {line['part']}"
                       f"   {line['slipped_by_days']} day(s) ago"
                       f"   ({line['source']})")
        if answer["slipped_count"] > 15:
            out.append(f"  ... and {answer['slipped_count'] - 15} more.")
        out.append("")
    if answer["incomplete_count"]:
        out.append(f"Going today with something missing: {answer['incomplete_count']} line(s)."
                   " See the brackets above.")
        out.append("")
    if answer["unreadable_date_count"]:
        out.append(f"{answer['unreadable_date_count']} line(s) have a departure date this "
                   f"cannot read, so they can be neither included nor ruled out.")
        out.append("")
    out.append(f"Read from the Despatch Plan as saved {answer['as_of']}. "
               f"A plan is not confirmation that goods have left.")
    return "\n".join(out)


# ── 6. Data quality ──────────────────────────────────────────────────────────

def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(str(value).strip().replace(",", ""))
        return True
    except (TypeError, ValueError):
        return False


def data_quality(rows: Iterable[SourceRow], *, as_of: date, limit: int = 40) -> dict:
    """The cells that cannot be read, and the ones that disagree with each other.

    This is not tidiness. Every item here is a place where one of the other
    five answers goes quiet rather than wrong: an unreadable date cannot be
    included in a day's list or excluded from it, a pallet count stored as
    text cannot be totalled, and two rows with the same order and part mean a
    chase list counts one order twice.
    """
    problems: dict[str, list[dict]] = {}
    seen: dict[tuple, list[str]] = {}
    written: dict[tuple, tuple[str, str]] = {}      # as typed, not as normalised
    corrections: list[dict] = []

    def note(key: str, row: SourceRow, what: str, cell: Any = None) -> None:
        problems.setdefault(key, []).append(
            {"source": row.cite(), "sheet": row.sheet,
             "order": _cell(row, "SDI ORDER NO"), "part": _cell(row, "PART CODE"),
             "what": what, "cell": _clean(cell) if cell is not None else ""})

    for row in rows:
        if not _row_is_real(row):
            continue
        for column, names in (("departure", DEPARTS), ("due", DUE)):
            parsed: ScheduleDate = schedule_date(_get(row.cells, *names), as_of=as_of)
            if parsed.value is None and parsed.raw \
                    and parsed.basis != "no departure date set":
                note(f"unreadable_{column}_date", row,
                     f"The {names[0]} cell reads “{parsed.raw}”: {parsed.basis}.",
                     parsed.raw)
            elif parsed.value is not None and "read as" in parsed.basis:
                # A spelling this corrected. It is used, and it is reported, so
                # the cell gets fixed rather than relied on.
                corrections.append(
                    {"source": row.cite(), "order": _cell(row, "SDI ORDER NO"),
                     "column": names[0], "cell": parsed.raw,
                     "read_as": parsed.value.isoformat(), "basis": parsed.basis})
        pallets = _get(row.cells, "PALLETS")
        if _clean(pallets) and not _is_number(pallets):
            note("pallets_not_a_number", row,
                 f"PALLETS reads “{_clean(pallets)}”, which is not a number, so it "
                 f"cannot be counted.", pallets)
        qty = _get(row.cells, "QTY")
        if _clean(qty) and not _is_number(qty):
            note("qty_not_a_number", row,
                 f"QTY reads “{_clean(qty)}”, which is not a number.", qty)
        order, part = _cell(row, "SDI ORDER NO"), _cell(row, "PART CODE")
        if order and part:
            # Matched on the normalised pair, because "ABC-1" and "abc 1" are
            # the same part; reported with the spelling the sheet actually has,
            # because that is what somebody will search the workbook for.
            key = (_norm(order), _norm(part))
            seen.setdefault(key, []).append(row.cite())
            written.setdefault(key, (order, part))
        if not order:
            note("no_order_number", row,
                 "The line has a part or description but no SDI order number, so it "
                 "cannot be found by order.")

    duplicates = [{"order": written[key][0], "part": written[key][1],
                   "count": len(where), "sources": where}
                  for key, where in seen.items() if len(where) > 1]
    duplicates.sort(key=lambda d: -d["count"])

    groups = [{"problem": key, "heading": _QUALITY_HEADINGS.get(key, key),
               "count": len(items), "lines": items[:limit],
               "truncated": len(items) > limit}
              for key, items in sorted(problems.items(), key=lambda kv: -len(kv[1]))]
    return {
        "question": "Which cells in the Despatch Plan cannot be read or contradict each other?",
        "as_of": as_of.isoformat(),
        "group_count": len(groups),
        "problem_count": sum(g["count"] for g in groups) + len(duplicates),
        "groups": groups,
        "duplicate_order_lines": duplicates[:limit],
        "duplicate_count": len(duplicates),
        "duplicates_truncated": len(duplicates) > limit,
        "spelling_corrections": corrections[:limit],
        "spelling_correction_count": len(corrections),
        "note": ("Each of these is a place where another answer here goes quiet rather "
                 "than wrong. A duplicate order and part across two rows may be a "
                 "genuine split delivery - it is listed so it can be told apart from "
                 "a line entered twice, not assumed to be a mistake."),
    }


_QUALITY_HEADINGS = {
    "unreadable_departure_date": "Departure dates that cannot be read",
    "unreadable_due_date": "Customer due dates that cannot be read",
    "pallets_not_a_number": "Pallet counts stored as text",
    "qty_not_a_number": "Quantities stored as text",
    "no_order_number": "Order lines with no order number",
}
