"""Pure, read-only TTI despatch logic for a future role-gated portal adapter.

The caller supplies rows read from a pinned workbook version. This module never
opens a share, calls Graph, sends mail, or changes either tracker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping


MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


# How far either side of the snapshot a bare "5th Jan" may be read. A despatch
# plan looks weeks ahead and keeps recent history; it does not schedule a year
# out, and a date most of a year in the past is a misread, not a plan.
# Cells that say "no departure date yet" rather than a date this cannot read.
# Telling them apart matters: the first is how a plan normally looks weeks out,
# the second is something to go and check. Reported as one number, the normal
# ones bury the real ones.
NOT_A_DATE_YET = {"", "-", "--", "?", "??", "n/a", "na", "n a", "tbc", "tba",
                  "tbd", "none", "nil", "x", "xx", "not known", "unknown",
                  "await", "awaiting", "no date", "pending"}

BACKWARD_LIMIT = 180
FORWARD_LIMIT = 270


def _month_meant(word: str) -> int | None:
    """A misspelt month - but only one it cannot be mistaken about.

    "FRI 6TH NIV TBC", order 15194. NIV is NOV, and James confirmed it.

    ── WHY THIS IS NOT FUZZY MONTH MATCHING ───────────────────────────────────
    MAR and MAY are one letter apart. So are JAN and JUN. Correcting spellings
    in general would let a despatch slide three months and read as confidently
    as a right one. This only ever looks at a word that is NOT a month, and
    only accepts it when exactly one real month is one letter away - so "mar"
    and "may" never reach here, because both are already months.

    The caller requires the second confirmation: a weekday in the cell that
    agrees with the resulting date. Three things have to line up, and if any
    one does not the line stays unresolved for a person to read.
    """
    three = str(word or "")[:3].lower()
    if three in MONTHS:
        return MONTHS[three]
    near = [number for name, number in MONTHS.items()
            if len(name) == len(three)
            and sum(a != b for a, b in zip(three, name)) == 1]
    return near[0] if len(near) == 1 else None


def _infer_year(day: int, month: int, weekday: str | None, as_of: date) -> date | None:
    """Which year does a bare "Thurs 5th Nov" mean?

    ── NOT SIMPLY THE SNAPSHOT'S YEAR ─────────────────────────────────────────
    It was, and in December a plan reading "Mon 5th Jan" resolved to the January
    eleven months GONE rather than the one a fortnight away. The row then never
    matched the day Sue asked about, and an answer of "nothing due" is
    indistinguishable from a correct one. A tracker rolls over every new year,
    so this would have been wrong every Christmas and right the rest of the
    time, which is the worst shape a bug can have.

    The year nearest the snapshot that fits is taken instead, and a weekday in
    the cell has to agree with it - so "Tue 2nd Nov" when the 2nd is a Monday
    stays unresolved rather than silently becoming a different year's Tuesday.
    None means no nearby year fits, which is a question for a person.
    """
    best = None
    for year in (as_of.year - 1, as_of.year, as_of.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue                      # 29 February in a common year
        if weekday and candidate.strftime("%a").lower()[:3] != weekday.lower()[:3]:
            continue
        behind = (as_of - candidate).days
        if behind > BACKWARD_LIMIT or -behind > FORWARD_LIMIT:
            continue
        gap = abs(behind)
        if best is None or gap < best[0]:
            best = (gap, candidate)
    return best[1] if best else None


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _clean(value).casefold())


def _get(cells: Mapping[str, Any], *names: str) -> Any:
    indexed = {_norm(k): v for k, v in cells.items()}
    for name in names:
        if _norm(name) in indexed:
            return indexed[_norm(name)]
    return None


@dataclass(frozen=True)
class SourceRow:
    sheet: str
    row: int
    cells: Mapping[str, Any]

    def cite(self) -> str:
        return f"{self.sheet}!row {self.row}"


@dataclass(frozen=True)
class ScheduleDate:
    value: date | None
    basis: str
    tentative: bool
    raw: str


def schedule_date(raw: Any, *, as_of: date) -> ScheduleDate:
    """Interpret one date cell, retaining uncertainty instead of inventing one.

    A single day/month without a year uses the snapshot year, disclosed as an
    inference. Compound or moved dates need a human decision.
    """
    if isinstance(raw, datetime):
        return ScheduleDate(raw.date(), "cell date", False, raw.isoformat())
    if isinstance(raw, date):
        return ScheduleDate(raw, "cell date", False, raw.isoformat())
    text = _clean(raw)
    if not text:
        return ScheduleDate(None, "no departure date set", False, text)
    tentative = bool(re.search(r"\b(TBC|await|provision|estimated)\b", text, re.I))
    # A bare "TBC" is not a date this failed to read; it is a plan that has not
    # said yet. "Mon 2nd Nov TBC" is a tentative DATE and carries on below.
    if _norm(text) in {_norm(w) for w in NOT_A_DATE_YET}:
        return ScheduleDate(None, "no departure date set", tentative, text)
    if "\n" in str(raw) or re.search(r"\b(moved|from|until|now to)\b", text, re.I):
        return ScheduleDate(None, "multiple or revised dates", tentative, text)
    try:
        hit = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?: 00:00:00)?", text)
        if hit:
            year, month, day = map(int, hit.groups())
            return ScheduleDate(date(year, month, day), "stated date", tentative, text)
        hit = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", text)
        if hit:
            day, month, year = map(int, hit.groups())
            if year < 100:
                year += 2000
            return ScheduleDate(date(year, month, day), "stated date", tentative, text)
        hit = re.fullmatch(
            r"(?:(Mon|Tue|Tues|Wed|Thu|Thurs|Fri|Sat|Sun)\w*\s+)?"
            r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)"
            r"(?:\s+(\d{2,4}))?(?:\s+TBC)?", text, re.I)
        if hit:
            weekday, day, month_word, year_word = hit.groups()
            month = MONTHS.get(month_word[:3].lower())
            misspelt = ""
            if month is None:
                # A weekday is the second confirmation, and without one there
                # is nothing to check a corrected spelling against.
                month = _month_meant(month_word) if weekday else None
                if month is None:
                    raise ValueError("unknown month")
                misspelt = _clean(month_word)
            if year_word:
                year = int(year_word)
                if year < 100:
                    year += 2000
                result = date(year, month, int(day))
                if weekday and result.strftime("%a").lower()[:3] != weekday.lower()[:3]:
                    return ScheduleDate(None, "weekday disagrees with date", tentative, text)
                return ScheduleDate(result, _said(misspelt, month, "stated date"),
                                    tentative, text)
            inferred = _infer_year(int(day), month, weekday, as_of)
            if inferred is None:
                return ScheduleDate(
                    None,
                    "weekday disagrees with date" if weekday
                    else "no year near this snapshot fits the date",
                    tentative, text)
            return ScheduleDate(inferred,
                                _said(misspelt, month, "year inferred from snapshot"),
                                tentative, text)
    except ValueError:
        pass
    return ScheduleDate(None, "unreadable or non-specific date", tentative, text)


def _said(misspelt: str, month: int, otherwise: str) -> str:
    """A corrected spelling is never silent: the screen shows what was read
    and what it was read as, so Sue can fix the cell rather than live with it."""
    if not misspelt:
        return otherwise
    name = [k for k, v in MONTHS.items() if v == month][0].title()
    return f"“{misspelt}” read as {name}, weekday agrees"


def _business_row(row: SourceRow) -> bool:
    return any(_clean(_get(row.cells, name)) for name in
               ("SDI ORDER NO", "PART CODE", "DESCRIPTION"))


# ── Pallets, added up ─────────────────────────────────────────────────────
#
# Phase one refused to total the PALLETS column: whether rows were separate
# loads, or one load written on several lines, was unknown. Sue Rogers, 29
# October 2026: one order goes in several loads "due to number of pallets that
# can fit on a lorry", and "we often have various rows for the same lorry,
# sometimes just one row just depends on the product". So every row carries its
# own pallets, and adding them up is right - but it counts pallets, not lorries,
# and the answer says so.
PALLET_REASON = ("The PALLETS column added up for these lines. Several lines often go on one "
                 "lorry, so this is pallets, not lorries.")


def _pallets(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(_clean(value).replace(",", ""))
    except ValueError:
        return None


def pallet_count(lines: list[dict]) -> dict:
    """Total pallets on these lines, and which lines could not be counted."""
    total, counted, text, blank = 0.0, 0, [], 0
    for line in lines:
        raw = line.get("pallets_as_recorded")
        number = _pallets(raw)
        if number is not None:
            total += number
            counted += 1
        elif _clean(raw):
            text.append({"source": line["source"], "pallets_as_recorded": _clean(raw)})
        else:
            blank += 1
    return {"pallet_total": int(total) if total.is_integer() else round(total, 1),
            "pallet_lines_counted": counted,
            "pallet_lines_as_text": text,
            "pallet_lines_blank": blank,
            "pallet_total_reason": PALLET_REASON}


def going_out(rows: Iterable[SourceRow], *, day: date, as_of: date) -> dict:
    """Answer 'what is leaving SDI on day?' from dispatch, not due-date, cells."""
    found: list[dict] = []
    ambiguous: list[dict] = []
    not_yet: list[dict] = []
    for row in rows:
        if not _business_row(row):
            continue
        parsed = schedule_date(_get(row.cells, "LORRY FROM SDI"), as_of=as_of)
        line = {
            "source": row.cite(),
            "order": _clean(_get(row.cells, "SDI ORDER NO")),
            "part": _clean(_get(row.cells, "PART CODE")),
            "description": _clean(_get(row.cells, "DESCRIPTION")),
            "pallets_as_recorded": _get(row.cells, "PALLETS"),
            # Booked, a trailer registration, or "loaded" once it has gone.
            "trailer": _clean(_get(row.cells, "TRAILER")),
            "loaded": bool(re.search(r"\bloaded\b", _clean(_get(row.cells, "TRAILER")), re.I)),
            "dispatch_cell": parsed.raw,
            "date_basis": parsed.basis,
            "tentative": parsed.tentative,
        }
        if parsed.value == day:
            found.append(line)
        elif parsed.basis == "no departure date set":
            not_yet.append(line)
        elif parsed.value is None and parsed.raw:
            ambiguous.append(line)
    return {
        "question": f"What is due to leave SDI on {day.isoformat()}?",
        "source_version_date": as_of.isoformat(),
        "lines": found,
        "unresolved_date_count": len(ambiguous),
        "unresolved_date_lines": ambiguous[:25],
        "unresolved_date_truncated": len(ambiguous) > 25,
        # Ordinary, and counted separately so it cannot bury the line above.
        "no_date_count": len(not_yet),
        "no_date_lines": not_yet[:25],
        "no_date_truncated": len(not_yet) > 25,
        "line_count": len(found),
        **pallet_count(found),
        "caveat": "A schedule is not confirmation that goods have left.",
    }


def going_out_week(rows: Iterable[SourceRow], *, day: date, as_of: date) -> dict:
    """'What is leaving SDI this week?': Monday to Friday of the week `day` is in.

    The same reading as going_out, a day at a time, from one copy of the plan.
    A Saturday or Sunday departure is shown too, but only when there is one -
    two empty weekend headings every week would just be noise. The lines whose
    date could not be read, or is not set yet, belong to no day, so they are
    given once for the week rather than five times.
    """
    rows = list(rows)
    monday = day - timedelta(days=day.weekday())
    days, first = [], None
    for offset in range(7):
        on = monday + timedelta(days=offset)
        answer = going_out(rows, day=on, as_of=as_of)
        first = first or answer
        if offset < 5 or answer["line_count"]:
            days.append({"day": on.isoformat(), "line_count": answer["line_count"],
                         "lines": answer["lines"], "pallet_total": answer["pallet_total"]})
    week = {key: first[key] for key in (
        "source_version_date", "unresolved_date_count", "unresolved_date_lines",
        "unresolved_date_truncated", "no_date_count", "no_date_lines", "no_date_truncated",
        "caveat")}
    week.update(pallet_count([line for d in days for line in d["lines"]]))
    week.update({
        "question": f"What is due to leave SDI in the week of {monday.isoformat()}?",
        "week_start": monday.isoformat(),
        "week_end": days[-1]["day"],
        "days": days,
        "line_count": sum(d["line_count"] for d in days),
    })
    return week


def propose_completed_transfer(
    source: SourceRow,
    *,
    dispatched_at: datetime | None,
    dispatch_evidence: str,
    destination_headers: Iterable[str] | None,
    destination_version: str | None,
) -> dict:
    """Describe a transfer for Sue's review; there is deliberately no writer."""
    blockers = []
    if not _business_row(source):
        blockers.append("Source row is not an order line")
    if dispatched_at is None or not dispatch_evidence.strip():
        blockers.append("Actual dispatch time and evidence are required")
    if destination_headers is None or not destination_version:
        blockers.append("Completed Orders structure and version have not been verified")
    order = _clean(_get(source.cells, "SDI ORDER NO"))
    part = _clean(_get(source.cells, "PART CODE"))
    customer_po = _clean(_get(source.cells, "CUSTOMER PO"))
    if not order or not part:
        blockers.append("Order number and part code are required to detect duplicates")
    same_headers = {_norm(h): h for h in (destination_headers or [])}
    proposed_cells = {
        target: value for heading, value in source.cells.items()
        if (target := same_headers.get(_norm(heading))) and value not in (None, "")
    }
    return {
        "state": "blocked" if blockers else "review_required",
        "source": source.cite(),
        "source_identity": {"order": order, "part": part, "customer_po": customer_po},
        "destination_version": destination_version,
        "dispatched_at": dispatched_at.isoformat() if dispatched_at else None,
        "dispatch_evidence": dispatch_evidence.strip(),
        "candidate_cells": proposed_cells,
        "blockers": blockers,
        "warning": "Preview only. No duplicate search, cell write, or email has occurred.",
    }
