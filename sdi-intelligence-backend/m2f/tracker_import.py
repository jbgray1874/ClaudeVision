"""
Read the account director's tracker workbook into Monday2Friday records.

Nothing is guessed. Where the workbook does not say something unambiguously,
the record keeps the raw value and an ImportIssue says what needs a decision.

  * Forecast months get their year from the tab's own "FYnn" headers, walking
    the month sequence either side of them.
  * Forecast status comes from the colour legend at the top of each tab. Cell
    and legend colours are compared as the colour Excel shows (theme colours
    resolved through the workbook theme), so a theme green and the same RGB
    green are one status. A colour that is not on the legend stays unclassified.
  * Sub-accounts (BUK, Sigma, BOPS, Hearingcare) come from the row ranges the
    "Forcasting Total" sheet itself sums for each of them.
  * reconcile() re-adds every monthly total the tracker reports and says where
    our figure differs and why.

Usage:
  python -m m2f.tracker_import <tracker.xlsx> --out <folder>
"""
from __future__ import annotations

import argparse
import colorsys
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import openpyxl
from openpyxl.styles.colors import COLOR_INDEX
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

STATUSES = ("Risk", "TBC", "Confirmed", "Invoiced")

MONTH_WORDS = {
    "JAN": 1, "JANUARY": 1, "FEB": 2, "FEBRUARY": 2, "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4, "MAY": 5, "JUN": 6, "JUNE": 6, "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8, "SEP": 9, "SEPT": 9, "SEPTEMBER": 9, "OCT": 10,
    "OCTOBER": 10, "NOV": 11, "NOVEMBER": 11, "DEC": 12, "DECEMBER": 12,
}
_MONTH_LABEL = re.compile(r"([A-Za-z]+)\.?\s*(?:FY\s*(\d{2}))?")

# A tab's "FY27" means calendar 2027 (Jan FY27 = January 2027). The tracker's
# own "Forcasting Total" sheet labels Oct-Dec before "Jan FY26" as "FY 25",
# and reconcile() checks every label against the columns its formulas read.
FY_CENTURY = 2000

LIVE_TABS = {
    # normalised tab title: (review key prefix, segment, default account or None = use Client column)
    "current -boots": ("BUK", "Boots UK", "Boots UK"),
    "current opticians v2": ("BOP", "Boots Opticians", "Boots Opticians"),
    "hearingcare": ("BHC", "Boots Hearingcare", "Boots Hearingcare"),
    "beauty brands - projects": ("BTY", "Beauty", None),
    "luxury brands - projects (2)": ("LUX", "Luxury", None),
}
ARCHIVE_TABS = {
    "complete": "completed work, kept in the source workbook",
    "didn't go ahead": "lost or cancelled work, kept in the source workbook",
    "costs and po's": "cost build-ups, kept in the source workbook",
}
BRANDS_TAB = "brands - accounts"
TOTALS_TAB = "forcasting total"

BOOTS_GROUP = "Boots"
SUB_ACCOUNT_LABELS = {
    "BUK": "Boots UK",
    "SIGMA": "Sigma",
    "BOPS": "Boots Opticians",
    "HEARINGCARE": "Boots Hearingcare",
}

FIELD_EXACT = {
    "project": "name", "pm": "pm", "am": "am", "client": "client",
    "dwg no.": "drawing", "sales order": "sales_order", "project code": "project_code",
    "status": "stage_text", "contact": "contact", "next key steps": "next_step",
    "sdi notes": "sdi_notes", "boots notes": "client_notes", "technial notes": "technical_notes",
    "brief date": "brief_date", "job type": "job_type", "boots code": "client_code",
    "boots unit codes": "client_unit_codes", "qty": "qty", "delivery date": "delivery_date",
    "delivery details": "delivery_details", "margin %": "margin_pct",
    "po": "po_ref", "po number": "po_ref", "po value": "po_value",
}
FIELD_PREFIX = (
    ("total sell price", "sell_value"),
    ("total cost inc", "cost_value"),
    ("shopping cart", "cart_ref"),
    ("upcoming/ potential sales", "potential_sales"),
    ("general project notes", "notes"),
    ("handover notes", "handover_notes"),
    ("client to do", "client_todo"),
    ("inhouse / outsou", "sourcing"),
)
_AM_TODO = re.compile(r"^(?:\w+ )?to do$")

_MONEY = re.compile(r"^£?\s*-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_SINGLE_REF = re.compile(r"^=\s*'?([^'!]+?)'?!\$?([A-Z]{1,3})\$?(\d+)\s*$")
_ANY_REF = re.compile(r"'?([^'!+(=]+?)'?!\$?([A-Z]{1,3})\$?(\d+)")
_SUM_RANGE = re.compile(r"^=\s*SUM\(\s*\$?([A-Z]{1,3})\$?(\d+)\s*:\s*\$?([A-Z]{1,3})\$?(\d+)\s*\)\s*$", re.I)
_NAME_SPLIT = re.compile(r"\s*(?:/|&|,|\band\b)\s*", re.I)


# ── Records ─────────────────────────────────────────────────────────────────
@dataclass
class ImportIssue:
    code: str
    severity: str            # "decision" needs a person; "check" needs a look; "info" is context
    message: str
    tab: str = ""
    cell: str = ""
    review_key: str = ""


@dataclass
class Project:
    review_key: str
    tab: str
    row: int
    hidden: bool
    segment: str
    account: str
    name: str
    fields: dict = field(default_factory=dict)   # mapped columns, raw values
    extra: dict = field(default_factory=dict)    # every other non-empty column, by header


@dataclass
class ForecastLine:
    review_key: str
    tab: str
    cell: str
    period: str | None          # "YYYY-MM"
    amount: str | None          # decimal as text
    raw: str
    value_type: str             # "value" or "formula result"
    status: str | None          # from the legend, None when the colour is not on it
    fill: str                   # the colour Excel shows, "none" for no fill


@dataclass
class TrackerImport:
    source: str
    projects: list = field(default_factory=list)
    forecast_lines: list = field(default_factory=list)
    accounts: list = field(default_factory=list)
    brands: list = field(default_factory=list)
    people: list = field(default_factory=list)
    reconciliation: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    skipped_tabs: dict = field(default_factory=dict)

    def issue(self, *a, **k):
        self.issues.append(ImportIssue(*a, **k))


# ── Small helpers ───────────────────────────────────────────────────────────
def norm(text) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def parse_month_label(text) -> tuple[int, int | None] | None:
    """'JAN FY27' -> (1, 2027); 'OCT' -> (10, None); 'Oct FY 25' -> (10, 2025)."""
    if text is None:
        return None
    m = _MONTH_LABEL.fullmatch(str(text).strip())
    if not m or m.group(1).upper() not in MONTH_WORDS:
        return None
    fy = FY_CENTURY + int(m.group(2)) if m.group(2) else None
    return MONTH_WORDS[m.group(1).upper()], fy


def resolve_periods(month_cols: list[tuple[int, int, int | None]]):
    """month_cols: [(column, month, explicit_year_or_None)] in column order.

    Returns ({column: (year, month)}, [problems]). Years run forward from each
    explicit header (a month that is not later than the one before starts a new
    year) and backward before the first one."""
    n = len(month_cols)
    anchors = [i for i, (_, _, y) in enumerate(month_cols) if y]
    if not anchors:
        return {}, ["no month header carries a year (FYnn), so no month can be dated"]
    months = [m for _, m, _ in month_cols]
    years: list[int | None] = [None] * n
    for i in anchors:
        years[i] = month_cols[i][2]
    problems = []
    for k, a in enumerate(anchors):
        stop = anchors[k + 1] if k + 1 < len(anchors) else n
        y = years[a]
        for i in range(a + 1, stop):
            if months[i] <= months[i - 1]:
                y += 1
            years[i] = y
        if stop < n:
            expected = y + (1 if months[stop] <= months[stop - 1] else 0)
            if expected != years[stop]:
                col = get_column_letter(month_cols[stop][0])
                problems.append(f"column {col} says {years[stop]} but the month sequence before it gives {expected}")
    y = years[anchors[0]]
    for i in range(anchors[0] - 1, -1, -1):
        if months[i] >= months[i + 1]:
            y -= 1
        years[i] = y
    return {month_cols[i][0]: (years[i], months[i]) for i in range(n)}, problems


def theme_palette(wb) -> list[str]:
    """Theme colour index -> RRGGBB, in Excel's index order (lt1, dk1, lt2, dk2, accents, links)."""
    raw = getattr(wb, "loaded_theme", None)
    if not raw:
        return []
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    scheme = ET.fromstring(raw).find(".//a:clrScheme", ns)
    if scheme is None:
        return []
    by_name = {}
    for child in scheme:
        name = child.tag.split("}")[1]
        srgb = child.find("a:srgbClr", ns)
        sys_ = child.find("a:sysClr", ns)
        if srgb is not None:
            by_name[name] = srgb.get("val").upper()
        elif sys_ is not None:
            by_name[name] = (sys_.get("lastClr") or "000000").upper()
    order = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3",
             "accent4", "accent5", "accent6", "hlink", "folHlink"]
    return [by_name.get(k, "") for k in order]


def _apply_tint(rgb: str, tint: float) -> str:
    if not tint:
        return rgb
    r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, lum, s = colorsys.rgb_to_hls(r, g, b)
    lum = lum * (1 + tint) if tint < 0 else lum * (1 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, lum, s)
    return "".join(f"{round(v * 255):02X}" for v in (r, g, b))


def shown_fill(cell, palette: list[str]) -> str:
    """The cell's fill as the colour Excel shows: 'RRGGBB', or 'none'."""
    f = cell.fill
    if f is None or f.fill_type in (None, "none"):
        return "none"
    c = f.fgColor
    if c is None:
        return "none"
    if c.type == "rgb" and isinstance(c.rgb, str):
        return c.rgb[-6:].upper()
    if c.type == "theme" and palette and 0 <= c.theme < len(palette) and palette[c.theme]:
        return _apply_tint(palette[c.theme], c.tint or 0.0)
    if c.type == "indexed" and isinstance(c.indexed, int) and c.indexed < len(COLOR_INDEX):
        return COLOR_INDEX[c.indexed][-6:].upper()
    return f"unresolved:{c.type}"


def to_amount(value) -> tuple[Decimal | None, str]:
    """Return (amount, raw). Text is accepted only when it is unambiguously money."""
    if isinstance(value, bool):
        return None, str(value)
    if isinstance(value, (int, float)):
        return Decimal(repr(value)).quantize(Decimal("0.01")), repr(value)
    raw = str(value).strip()
    if _MONEY.fullmatch(raw):
        try:
            return Decimal(raw.replace("£", "").replace(",", "").strip()).quantize(Decimal("0.01")), raw
        except InvalidOperation:
            pass
    return None, raw


def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def _find_header_row(ws, key: str, scan: int = 6) -> int | None:
    for r in range(1, min(scan, ws.max_row) + 1):
        for c in range(1, ws.max_column + 1):
            if ws.cell(r, c).value is not None and norm(ws.cell(r, c).value) == key:
                return r
    return None


def _field_for(header: str) -> str | None:
    h = norm(header)
    if h in FIELD_EXACT:
        return FIELD_EXACT[h]
    for prefix, name in FIELD_PREFIX:
        if h.startswith(prefix):
            return name
    if _AM_TODO.match(h):
        return "am_todo"
    return None


# ── Sub-account bands from the tracker's own totals sheet ───────────────────
def sub_account_bands(wb_formulas, result: TrackerImport) -> dict[str, list[tuple[int, int, str]]]:
    """{tab title: [(first_row, last_row, account)]} from 'Forcasting Total' label/total pairs."""
    bands: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    totals = next((ws for ws in wb_formulas.worksheets if norm(ws.title) == TOTALS_TAB), None)
    if totals is None:
        result.issue("no_totals_sheet", "check", "No 'Forcasting Total' sheet, so sub-accounts cannot be derived.")
        return bands
    for row in totals.iter_rows():
        for cell in row:
            m = _SINGLE_REF.match(str(cell.value)) if isinstance(cell.value, str) else None
            if not m:
                continue
            label = next((totals.cell(cell.row, c).value for c in range(cell.column - 1, 0, -1)
                          if isinstance(totals.cell(cell.row, c).value, str)), None)
            account = SUB_ACCOUNT_LABELS.get(norm(label).upper()) if label else None
            if not account:
                continue
            tab, col, r = m.group(1), m.group(2), int(m.group(3))
            target_ws = next((w for w in wb_formulas.worksheets if norm(w.title) == norm(tab)), None)
            target = target_ws[f"{col}{r}"].value if target_ws is not None else None
            rng = _SUM_RANGE.match(str(target)) if isinstance(target, str) else None
            if not rng:
                result.issue("sub_account_total_unreadable", "check",
                             f"'{label}' total points at {tab}!{col}{r}, which is not a SUM of a range.",
                             tab=TOTALS_TAB, cell=cell.coordinate)
                continue
            c1, r1, c2, r2 = rng.group(1), int(rng.group(2)), rng.group(3), int(rng.group(4))
            if r1 == r2:
                # Adds across one row of monthly subtotals: no row band, but every
                # month in the span needs a subtotal or that month counts as zero.
                span = range(column_index_from_string(c1), column_index_from_string(c2) + 1)
                empty = [get_column_letter(c) for c in span if target_ws.cell(r1, c).value in (None, "")]
                if empty:
                    result.issue("account_total_misses_months", "check",
                                 f"'{label}' total ({cell.coordinate}) adds {tab.strip()}!{c1}{r1}:{c2}{r1}, but "
                                 f"{', '.join(f'{e}{r1}' for e in empty)} are empty, so those months count as £0.",
                                 tab=TOTALS_TAB, cell=cell.coordinate)
                continue
            band = (r1, r2, account)
            if band not in bands[target_ws.title]:
                bands[target_ws.title].append(band)
    for tab, items in bands.items():
        items.sort()
        for (a1, a2, x), (b1, b2, y) in zip(items, items[1:]):
            if b1 <= a2 and x != y:
                result.issue("sub_account_overlap", "decision",
                             f"Rows {b1}-{a2} are counted in both {x} and {y}.", tab=tab)
    return bands


# ── Live project tabs ───────────────────────────────────────────────────────
def _read_project_tab(ws_v, ws_f, prefix, segment, default_account, bands, palette, result: TrackerImport):
    header_row = _find_header_row(ws_v, "project")
    if header_row is None:
        result.issue("no_header", "check", "Could not find a 'Project' column header.", tab=ws_v.title)
        return

    # Legend: status words above the header row, keyed by the colour Excel shows.
    legend: dict[str, str] = {}
    for r in range(1, header_row):
        for c in range(1, ws_v.max_column + 1):
            cell = ws_v.cell(r, c)
            word = norm(cell.value) if cell.value is not None else ""
            status = next((s for s in STATUSES if s.lower() == word), None)
            if not status:
                continue
            colour = shown_fill(cell, palette)
            if legend.get(colour, status) != status:
                result.issue("legend_conflict", "decision",
                             f"Colour {colour} is used for both {legend[colour]} and {status}.",
                             tab=ws_v.title, cell=cell.coordinate)
            legend[colour] = status
    if not legend:
        result.issue("no_legend", "check", "No Risk/TBC/Confirmed/Invoiced legend above the headers.", tab=ws_v.title)

    headers = {c: ws_v.cell(header_row, c).value for c in range(1, ws_v.max_column + 1)}
    month_cols = []
    for c, h in headers.items():
        parsed = parse_month_label(h)
        if parsed:
            month_cols.append((c, parsed[0], parsed[1]))
    periods, problems = resolve_periods(month_cols)
    for p in problems:
        result.issue("period_conflict", "check", p, tab=ws_v.title)
    if month_cols and not periods:
        result.issue("periods_undated", "decision",
                     "No month header has a year, so this tab's forecast cannot be dated.", tab=ws_v.title)
    month_set = {c for c, _, _ in month_cols}

    name_col = next(c for c, h in headers.items() if h is not None and norm(h) == "project")
    unnamed_with_values, numeric_names = [], []
    for r in range(header_row + 1, ws_v.max_row + 1):
        name = ws_v.cell(r, name_col).value
        if name is None or not str(name).strip():
            vals = [f"{get_column_letter(c)}{r}" for c in month_set
                    if isinstance(ws_v.cell(r, c).value, (int, float)) and ws_v.cell(r, c).value
                    and not str(ws_f.cell(r, c).value).startswith("=")]
            unnamed_with_values += vals
            continue
        key = f"{prefix}-{r:03d}"
        hidden = bool(ws_v.row_dimensions[r].hidden)
        if re.fullmatch(r"\d+(\.\d+)?", str(name).strip()):
            numeric_names.append(r)
        fields, extra = {}, {}
        for c, h in headers.items():
            if c in month_set or c == name_col:
                continue
            v = ws_v.cell(r, c).value
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            f = _field_for(h) if h is not None else None
            if f:
                fields[f] = _jsonable(v)
            else:
                extra[str(h).strip() if h is not None else get_column_letter(c)] = _jsonable(v)

        if default_account:
            account = default_account
            tab_bands = bands.get(ws_v.title, [])
            if tab_bands:
                hit = [acc for r1, r2, acc in tab_bands if r1 <= r <= r2]
                if len(hit) == 1:
                    account = hit[0]
                else:
                    result.issue("sub_account_unconfirmed", "decision",
                                 f"Row {r} sits outside the rows the totals sheet assigns to a sub-account.",
                                 tab=ws_v.title, cell=f"A{r}", review_key=key)
        else:
            account = str(fields.get("client", "")).strip()
            if not account:
                account = segment
                result.issue("no_client", "decision", "Brand project has no client.", tab=ws_v.title,
                             cell=f"A{r}", review_key=key)

        result.projects.append(Project(key, ws_v.title, r, hidden, segment, account, str(name).strip(), fields, extra))

        for c in sorted(month_set):
            v = ws_v.cell(r, c).value
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            coord = f"{get_column_letter(c)}{r}"
            amount, raw = to_amount(v)
            colour = shown_fill(ws_v.cell(r, c), palette)
            status = legend.get(colour)
            period = periods.get(c)
            line = ForecastLine(
                review_key=key, tab=ws_v.title, cell=coord,
                period=f"{period[0]}-{period[1]:02d}" if period else None,
                amount=str(amount) if amount is not None else None, raw=raw,
                value_type="formula result" if str(ws_f.cell(r, c).value).startswith("=") else "value",
                status=status, fill=colour,
            )
            result.forecast_lines.append(line)
            if amount is None:
                result.issue("amount_unreadable", "decision", f"'{raw}' is not a clear amount.",
                             tab=ws_v.title, cell=coord, review_key=key)
            elif isinstance(v, str):
                result.issue("amount_typed_as_text", "check",
                             f"'{raw}' is typed as text, so the tracker's own totals leave it out.",
                             tab=ws_v.title, cell=coord, review_key=key)
            elif amount == 0:
                result.issue("amount_zero", "info", "Forecast cell holds 0.", tab=ws_v.title, cell=coord, review_key=key)
            if status is None:
                result.issue("status_unclassified", "decision",
                             f"Colour {colour} is not on this tab's legend.", tab=ws_v.title, cell=coord, review_key=key)

    if numeric_names:
        result.issue("name_is_number", "decision",
                     f"{len(numeric_names)} projects are named only by a number (rows {numeric_names[0]}-{numeric_names[-1]}), "
                     "usually an order or PO number. Each needs a name people will recognise.",
                     tab=ws_v.title, cell=f"{get_column_letter(name_col)}{numeric_names[0]}")
    if unnamed_with_values:
        result.issue("values_on_unnamed_rows", "check",
                     f"{len(unnamed_with_values)} typed forecast values sit on rows with no project name: "
                     + ", ".join(unnamed_with_values[:12]) + ("…" if len(unnamed_with_values) > 12 else ""),
                     tab=ws_v.title)


# ── Brands and accounts tab ─────────────────────────────────────────────────
def _read_brands(ws, result: TrackerImport, include_sensitive: bool):
    header_row = _find_header_row(ws, "brand")
    if header_row is None:
        result.issue("no_header", "check", "Could not find a 'Brand' column header.", tab=ws.title)
        return
    headers = {c: norm(ws.cell(header_row, c).value) for c in range(1, ws.max_column + 1)
               if ws.cell(header_row, c).value is not None}
    for r in range(header_row + 1, ws.max_row + 1):
        row = {h: ws.cell(r, c).value for c, h in headers.items()}
        if not row.get("brand") or not str(row["brand"]).strip():
            continue
        record = {"source_row": r, "brand": str(row["brand"]).strip()}
        for h, v in row.items():
            if v is None or h == "brand":
                continue
            if h.startswith("credit limit"):
                record["has_credit_limit"] = True
                if include_sensitive:
                    record["credit_limit_raw"] = _jsonable(v)
                continue
            record[h] = _jsonable(v)
        contact = " ".join(str(row.get(h) or "") for h in headers.values() if "contact" in h)
        record["emails"] = sorted(set(_EMAIL.findall(contact)))
        result.brands.append(record)


# ── People named in the PM / AM columns ─────────────────────────────────────
def _collect_people(result: TrackerImport):
    variants: dict[str, Counter] = defaultdict(Counter)
    roles: dict[str, set] = defaultdict(set)
    for p in result.projects:
        for role in ("pm", "am"):
            raw = p.fields.get(role)
            if not raw:
                continue
            for name in _NAME_SPLIT.split(str(raw).strip()):
                name = name.strip()
                if not name or norm(name) in {"tbc", "na", "n/a"}:
                    continue
                variants[norm(name)][name] += 1
                roles[norm(name)].add(role.upper())
    for key, spellings in sorted(variants.items(), key=lambda kv: -sum(kv[1].values())):
        result.people.append({
            "key": key,
            "spellings": dict(spellings),
            "projects": sum(spellings.values()),
            "roles": sorted(roles[key]),
        })


# ── Reconciliation against the tracker's own monthly totals ─────────────────
def reconcile(wb_values, wb_formulas, result: TrackerImport):
    """Re-add every month total on 'Forcasting Total' from our forecast lines,
    and check each tab's monthly total row for values it leaves out."""
    totals_f = next((ws for ws in wb_formulas.worksheets if norm(ws.title) == TOTALS_TAB), None)
    if totals_f is None:
        return
    totals_v = wb_values[totals_f.title]
    sheets = {norm(ws.title): ws for ws in wb_formulas.worksheets}

    by_tab_period = defaultdict(Decimal)   # (tab, "YYYY-MM") -> our total
    rows_of = defaultdict(list)            # (tab, column letter) -> [(row, amount)]
    period_of = {}                         # (tab, column letter) -> "YYYY-MM"
    for line in result.forecast_lines:
        col = re.match(r"[A-Z]+", line.cell).group(0)
        k = (norm(line.tab), col)
        period_of[k] = line.period
        if line.amount is not None:
            by_tab_period[(norm(line.tab), line.period)] += Decimal(line.amount)
            rows_of[k].append((int(line.cell[len(col):]), Decimal(line.amount)))

    # Month totals sit under a "Tracker" header whose row starts with the year
    # ("FY26 | Budgeted | Tracker | Debs Loaded"); month labels are in column A.
    tracker_cols = [(cell.row, cell.column) for row in totals_f.iter_rows() for cell in row
                    if isinstance(cell.value, str) and norm(cell.value) == "tracker"
                    and re.fullmatch(r"fy\s*\d{2}", norm(totals_f.cell(cell.row, 1).value or ""))]
    total_rows = defaultdict(set)          # tab -> rows holding that tab's monthly totals

    for header_row, tcol in tracker_cols:
        for trow in range(header_row + 1, totals_f.max_row + 1):
            label_cell = totals_f.cell(trow, 1)
            if isinstance(label_cell.value, str) and norm(label_cell.value).startswith("total"):
                break
            label = parse_month_label(label_cell.value)
            if not label or not label[1]:
                continue
            label_text = str(label_cell.value).strip()
            label_period = f"{label[1]}-{label[0]:02d}"
            cell = totals_f.cell(trow, tcol)
            if isinstance(cell.value, (int, float)):
                result.issue("total_typed", "info",
                             f"{label_text} tracker total is a typed {cell.value}, not a formula.",
                             tab=TOTALS_TAB, cell=cell.coordinate)
                continue
            if not (isinstance(cell.value, str) and cell.value.startswith("=") and "!" in cell.value):
                continue
            reported = totals_v[cell.coordinate].value
            entry = {"label": label_text, "period": label_period, "cell": cell.coordinate,
                     "reported": _jsonable(reported), "parts": []}
            tabs = []
            for tab, col, r in _ANY_REF.findall(cell.value):
                ws_f = sheets.get(norm(tab))
                part = {"ref": f"{tab.strip()}!{col}{r}"}
                entry["parts"].append(part)
                if ws_f is None:
                    part["problem"] = "tab not found"
                    continue
                tabs.append(norm(tab))
                target = ws_f[f"{col}{r}"].value
                held = period_of.get((norm(tab), col))
                if held and held != label_period:
                    part["problem"] = f"column {col} holds {held}, not {label_period}"
                    result.issue("total_reads_wrong_month", "check",
                                 f"{label_text} total reads {part['ref']}, which is in the {held} column.",
                                 tab=TOTALS_TAB, cell=cell.coordinate)
                if target in (None, ""):
                    part["problem"] = "points at an empty cell"
                    result.issue("total_reads_empty_cell", "check",
                                 f"{label_text} total reads {part['ref']}, which is empty, so it shows 0.",
                                 tab=TOTALS_TAB, cell=cell.coordinate)
                elif isinstance(target, str) and (m := _SUM_RANGE.match(target)) and m.group(1) == m.group(3) == col:
                    total_rows[norm(tab)].add(int(r))
                elif not (isinstance(target, str) and target.startswith("=")):
                    part["problem"] = "total is a typed number, not a formula"
            ours = sum((by_tab_period[(t, label_period)] for t in dict.fromkeys(tabs)), Decimal("0"))
            entry["ours"] = str(ours.quantize(Decimal("0.01")))
            if isinstance(reported, (int, float)):
                entry["difference"] = str((ours - Decimal(repr(reported))).quantize(Decimal("0.01")))
            result.reconciliation.append(entry)

    # Every month column of a tab should be covered by that tab's total row.
    for tab, rows in total_rows.items():
        ws_f = sheets[tab]
        for (t, col), period in sorted(period_of.items()):
            if t != tab:
                continue
            for trow in sorted(rows):
                formula = ws_f[f"{col}{trow}"].value
                m = _SUM_RANGE.match(formula) if isinstance(formula, str) else None
                if m and m.group(1) == m.group(3) == col:
                    r1, r2 = int(m.group(2)), int(m.group(4))
                    outside = [f"{col}{rr}={a}" for rr, a in rows_of[(t, col)] if not r1 <= rr <= r2]
                    if outside:
                        result.issue("value_outside_total", "check",
                                     f"{', '.join(outside)} ({period}) not included in the total {col}{trow} ({formula}).",
                                     tab=ws_f.title, cell=outside[0].split("=")[0])
                elif rows_of[(t, col)]:
                    result.issue("month_without_total", "check",
                                 f"The {period} column has values but {col}{trow} holds no total for it.",
                                 tab=ws_f.title, cell=f"{col}{trow}")


# ── Entry point ─────────────────────────────────────────────────────────────
def import_tracker(path: str | Path, include_sensitive: bool = False) -> TrackerImport:
    path = Path(path)
    wb_v = openpyxl.load_workbook(path, data_only=True)
    wb_f = openpyxl.load_workbook(path, data_only=False)
    palette = theme_palette(wb_v)
    result = TrackerImport(source=path.name)
    if not palette:
        result.issue("no_theme", "info", "Workbook has no theme, so theme colours cannot be resolved.")
    bands = sub_account_bands(wb_f, result)

    for ws in wb_v.worksheets:
        t = norm(ws.title)
        if t in LIVE_TABS:
            prefix, segment, default_account = LIVE_TABS[t]
            _read_project_tab(ws, wb_f[ws.title], prefix, segment, default_account, bands, palette, result)
        elif t == BRANDS_TAB:
            _read_brands(ws, result, include_sensitive)
        elif t in ARCHIVE_TABS:
            result.skipped_tabs[ws.title] = ARCHIVE_TABS[t]
        elif t != TOTALS_TAB:
            result.skipped_tabs[ws.title] = "not a recognised tracker tab"
            result.issue("unknown_tab", "check", "Tab not recognised, so it was not imported.", tab=ws.title)

    accounts = {}
    for p in result.projects:
        parent = BOOTS_GROUP if p.account in SUB_ACCOUNT_LABELS.values() else None
        accounts.setdefault(p.account, {"name": p.account, "parent": parent, "segment": p.segment})
    if any(a["parent"] == BOOTS_GROUP for a in accounts.values()):
        accounts[BOOTS_GROUP] = {"name": BOOTS_GROUP, "parent": None, "segment": "Boots"}
    result.accounts = sorted(accounts.values(), key=lambda a: (a["parent"] or "", a["name"]))

    _collect_people(result)
    reconcile(wb_v, wb_f, result)
    return result


def summarise(result: TrackerImport) -> dict:
    lines = result.forecast_lines
    by_status = defaultdict(Decimal)
    for line in lines:
        if line.amount is not None:
            by_status[line.status or "Unclassified"] += Decimal(line.amount)
    return {
        "source": result.source,
        "projects": len(result.projects),
        "projects_hidden": sum(p.hidden for p in result.projects),
        "projects_by_tab": dict(Counter(p.tab.strip() for p in result.projects)),
        "projects_by_account": dict(Counter(p.account for p in result.projects)),
        "forecast_cells": len(lines),
        "forecast_cells_classified": sum(1 for x in lines if x.status),
        "forecast_cells_undated": sum(1 for x in lines if not x.period),
        "forecast_by_status": {k: str(v) for k, v in sorted(by_status.items())},
        "brands": len(result.brands),
        "people_named": len(result.people),
        "issues_by_code": dict(Counter(i.code for i in result.issues)),
        "skipped_tabs": result.skipped_tabs,
    }


def write_outputs(result: TrackerImport, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    summary = summarise(result)
    payload = {
        "summary": summary,
        "accounts": result.accounts,
        "people": result.people,
        "projects": [asdict(p) for p in result.projects],
        "forecast_lines": [asdict(x) for x in result.forecast_lines],
        "brands": result.brands,
        "reconciliation": result.reconciliation,
        "issues": [asdict(i) for i in result.issues],
    }
    (out / "m2f_tracker_import.json").write_text(json.dumps(payload, indent=2, default=_jsonable), encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import the account tracker into Monday2Friday records.")
    ap.add_argument("workbook")
    ap.add_argument("--out", default="output/m2f")
    ap.add_argument("--include-sensitive", action="store_true", help="also export credit limits")
    args = ap.parse_args(argv)
    result = import_tracker(args.workbook, include_sensitive=args.include_sensitive)
    summary = write_outputs(result, Path(args.out))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
