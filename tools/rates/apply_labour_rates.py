"""Copy new department labour rates from an estimators' blank into the AI workbook template.

    python tools/rates/apply_labour_rates.py --source "<estimators' blank, .xls or .xlsx>"
                                              --template "<AI template .xlsx>" [--dry-run]

WHY THIS EXISTS (D-704). James Ryan, 3 Nov 2026: "Blank estimate sheet attached with updated
labour rates to start using with immediate effect ... factor these new rates (see I115 to
I146) into the AI system." The estimators' blank and the AI template are different files: the
AI template has a wider parts block, so its Labour / Rate / Dept / Set Up block sits lower
(rows 235-266 against 115-146). Copying the file across would lose the AI template's own
layout; retyping 32 rates by hand is how one of them ends up a row out.

WHAT IT DOES, AND WHAT IT REFUSES TO DO
  * Finds the Labour / Rate / Dept header in each workbook's Estimate sheet, wherever it sits.
  * Matches every department by its label AND its code, never by row.
  * Copies the RATE only. A set-up minute that differs is reported, not copied: the email was
    about rates, and nothing else is changed on its say-so.
  * Refuses, changing nothing, if any department in the template is missing from the source,
    if a code disagrees, or if a rate is outside the plausible range.
  * Saves a dated backup of the template beside it before writing, then writes the rates in
    place, so every path that names the template keeps working.
  * Reads the written file back and checks every rate landed.

ENGINES. On Windows with Excel it uses Excel itself (`--engine excel`, the default there): it
opens the .xls James sends, and it saves the template exactly as Excel would, with every
formula's cached value intact. Elsewhere (`--engine openpyxl`, used by the tests) it needs an
.xlsx source. ASCII only in what it prints.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

PLAUSIBLE_GBP_PER_HOUR = (1.0, 2000.0)     # the same bounds the engine's rate card uses
_HEADER = ("labour", "rate", "dept")
_COL_LABEL, _COL_RATE, _COL_DEPT, _COL_SETUP = 8, 9, 10, 11     # H, I, J, K
_SCAN_ROWS = 600


@dataclass
class Dept:
    label: str
    rate: float
    code: str
    setup: Optional[float]
    row: int


class RateError(RuntimeError):
    pass


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def read_block(cell: Callable[[int, int], object], max_rows: int = _SCAN_ROWS) -> List[Dept]:
    """The Labour / Rate / Dept block of an Estimate sheet, through `cell(row, col)` (1-based).

    The header is located, not assumed. The block ends at the first row whose code is empty or
    does not start with a letter: below it sits the wire gauge table, whose J is a number."""
    header = None
    for r in range(1, max_rows + 1):
        if (_norm(cell(r, _COL_LABEL)), _norm(cell(r, _COL_RATE)),
                _norm(cell(r, _COL_DEPT))) == _HEADER:
            header = r
            break
    if header is None:
        raise RateError("no 'Labour / Rate / Dept' header found on the Estimate sheet")
    out: List[Dept] = []
    for r in range(header + 1, header + 200):
        code = str(cell(r, _COL_DEPT) or "").strip()
        if not code or not code[0].isalpha():
            break
        rate = cell(r, _COL_RATE)
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            raise RateError(f"row {r} ({cell(r, _COL_LABEL)}): rate {rate!r} is not a number")
        setup = cell(r, _COL_SETUP)
        try:
            setup_f: Optional[float] = float(setup)
        except (TypeError, ValueError):
            setup_f = None
        out.append(Dept(str(cell(r, _COL_LABEL) or "").strip(), rate_f, code, setup_f, r))
    if not out:
        raise RateError(f"the header at row {header} has no department rows under it")
    return out


@dataclass
class Change:
    label: str
    code: str
    row: int
    old: float
    new: float


def plan(source: Sequence[Dept], template: Sequence[Dept]) -> Tuple[List[Change], List[str]]:
    """The rate changes to make, and notes. Raises RateError on anything that would make the
    template a mixture of two cards."""
    by_label = {_norm(d.label): d for d in source}
    errors: List[str] = []
    changes: List[Change] = []
    notes: List[str] = []
    lo, hi = PLAUSIBLE_GBP_PER_HOUR
    for t in template:
        s = by_label.get(_norm(t.label))
        if s is None:
            errors.append(f"{t.label} ({t.code}) is in the template and not in the source")
            continue
        if s.code.strip().upper() != t.code.strip().upper():
            errors.append(f"{t.label}: code {t.code} in the template, {s.code} in the source")
            continue
        if not lo <= s.rate <= hi:
            errors.append(f"{t.label}: source rate {s.rate} is outside {lo}-{hi} per hour")
            continue
        if s.setup is not None and t.setup is not None and abs(s.setup - t.setup) > 1e-9:
            notes.append(f"{t.label}: set-up {t.setup:g} min in the template, {s.setup:g} in "
                         f"the source - NOT copied (rates only)")
        if abs(s.rate - t.rate) > 1e-9:
            changes.append(Change(t.label, t.code, t.row, t.rate, s.rate))
    extra = sorted(set(by_label) - {_norm(t.label) for t in template})
    for name in extra:
        notes.append(f"{by_label[name].label} ({by_label[name].code}) is in the source and not "
                     f"in the template - NOT added")
    if errors:
        raise RateError("nothing changed:\n  " + "\n  ".join(errors))
    return changes, notes


def backup_path(template: Path, stamp: str) -> Path:
    return template.with_name(f"{template.stem} (before labour rates {stamp}){template.suffix}")


# -- openpyxl engine (any platform; .xlsx only) -------------------------------------------
def _openpyxl_cells(path: Path):
    if path.suffix.lower() == ".xls":
        try:
            import xlrd                                              # noqa: PLC0415
        except Exception as exc:                                     # noqa: BLE001
            raise RateError(f"{path.name} is .xls: use --engine excel on the laptop, or save "
                            f"it as .xlsx ({exc.__class__.__name__})")
        sh = xlrd.open_workbook(str(path)).sheet_by_name("Estimate")

        def cell(r, c):
            if r - 1 >= sh.nrows or c - 1 >= sh.ncols:
                return None
            return sh.cell_value(r - 1, c - 1)
        return cell, None
    import openpyxl                                                  # noqa: PLC0415
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    ws = wb["Estimate"] if "Estimate" in wb.sheetnames else wb.worksheets[0]
    grid = {}
    for row in ws.iter_rows(min_row=1, max_row=_SCAN_ROWS, min_col=_COL_LABEL,
                            max_col=_COL_SETUP):
        for c in row:
            if c.value is not None:
                grid[(c.row, c.column)] = c.value
    wb.close()
    return (lambda r, c: grid.get((r, c))), None


def _openpyxl_write(template: Path, changes: Sequence[Change]) -> None:
    import openpyxl                                                  # noqa: PLC0415
    wb = openpyxl.load_workbook(str(template))
    ws = wb["Estimate"] if "Estimate" in wb.sheetnames else wb.worksheets[0]
    for ch in changes:
        ws.cell(ch.row, _COL_RATE).value = ch.new
    wb.save(str(template))


# -- Excel engine (Windows with Excel) ------------------------------------------------------
def _excel():
    import win32com.client                                           # noqa: PLC0415
    app = win32com.client.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    return app


def _excel_cells(app, path: Path):
    wb = app.Workbooks.Open(str(path.resolve()), 0, True)            # read-only
    ws = wb.Worksheets("Estimate")
    grid = {}
    rng = ws.Range(ws.Cells(1, _COL_LABEL), ws.Cells(_SCAN_ROWS, _COL_SETUP)).Value
    for i, row in enumerate(rng or ()):
        for j, v in enumerate(row or ()):
            if v is not None:
                grid[(i + 1, _COL_LABEL + j)] = v
    wb.Close(False)
    return lambda r, c: grid.get((r, c))


def _excel_write(app, template: Path, changes: Sequence[Change]) -> None:
    wb = app.Workbooks.Open(str(template.resolve()), 0, False)
    try:
        ws = wb.Worksheets("Estimate")
        for ch in changes:
            ws.Cells(ch.row, _COL_RATE).Value = ch.new
        wb.Save()
    finally:
        wb.Close(False)


# -- the run --------------------------------------------------------------------------------
def run(source: Path, template: Path, engine: str, dry_run: bool,
        say: Callable[[str], None] = print, stamp: Optional[str] = None) -> List[Change]:
    if not source.is_file():
        raise RateError(f"source not found: {source}")
    if not template.is_file():
        raise RateError(f"template not found: {template}")
    if template.suffix.lower() != ".xlsx":
        raise RateError(f"the template must be the AI .xlsx, not {template.name}")
    app = _excel() if engine == "excel" else None
    try:
        if app is not None:
            src_cell, tpl_cell = _excel_cells(app, source), _excel_cells(app, template)
        else:
            src_cell, _ = _openpyxl_cells(source)
            tpl_cell, _ = _openpyxl_cells(template)
        src, tpl = read_block(src_cell), read_block(tpl_cell)
        say(f"source:   {source.name}  rows {src[0].row}-{src[-1].row}, {len(src)} departments")
        say(f"template: {template.name}  rows {tpl[0].row}-{tpl[-1].row}, "
            f"{len(tpl)} departments")
        changes, notes = plan(src, tpl)
        say("")
        say(f"  {'Department':26} {'code':5} {'row':>4} {'now':>9} {'new':>9} {'change':>8}")
        for ch in changes:
            pct = (ch.new / ch.old - 1) * 100 if ch.old else 0.0
            say(f"  {ch.label[:26]:26} {ch.code:5} {ch.row:>4} {ch.old:>9.2f} {ch.new:>9.2f} "
                f"{pct:>+7.1f}%")
        for n in notes:
            say(f"  note: {n}")
        if not changes:
            say("  nothing to change: the template already has these rates")
            return []
        if dry_run:
            say(f"\n  dry run: {len(changes)} rate(s) would change; nothing written")
            return changes
        stamp = stamp or time.strftime("%Y-%m-%d %H%M")
        backup = backup_path(template, stamp)
        shutil.copy2(template, backup)
        say(f"\n  backup:   {backup.name}")
        if app is not None:
            _excel_write(app, template, changes)
            check = _excel_cells(app, template)
        else:
            _openpyxl_write(template, changes)
            check, _ = _openpyxl_cells(template)
        wrong = [ch for ch in changes if abs(float(check(ch.row, _COL_RATE) or 0) - ch.new) > 1e-6]
        if wrong:
            shutil.copy2(backup, template)
            raise RateError("read-back did not match; the template was restored from the "
                            "backup: " + ", ".join(ch.label for ch in wrong))
        say(f"  written:  {len(changes)} rate(s), read back and checked")
        return changes
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:                                        # noqa: BLE001
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, help="the estimators' blank with the new rates")
    ap.add_argument("--template", required=True, help="the AI workbook template (.xlsx)")
    ap.add_argument("--engine", choices=("excel", "openpyxl"),
                    default="excel" if sys.platform == "win32" else "openpyxl")
    ap.add_argument("--dry-run", action="store_true", help="show the changes, write nothing")
    a = ap.parse_args(argv)
    try:
        run(Path(a.source), Path(a.template), a.engine, a.dry_run)
    except RateError as exc:
        print(f"STOP: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
