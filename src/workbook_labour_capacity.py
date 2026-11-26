"""Grow only the generated book's labelled labour block; never edit its template.

Keep every route group and its individual setup. Moving the total without moving
references would corrupt the price, so references, merges and row formulas move
together. No Excel, CAD, file access or recalculation is performed here.
"""
from copy import copy, deepcopy
from collections import OrderedDict
import re

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.formula.translate import Translator
from openpyxl.cell.cell import MergedCell
from openpyxl.worksheet.cell_range import CellRange

_CELL = re.compile(r'^(\$?[A-Z]{1,3})(\$?)([1-9]\d*)$')


def _sheet_name(value):
    return value.strip("'").replace("''", "'")


def shifted_range(value, owner, target, at, count, first):
    """Adjust an A1 operand for inserted rows, including absolute references.

    A range ending at the old labour last row expands only when it covers the
    whole block. Text, structured names, other sheets and external books stay put.
    """
    prefix, bang, addr = value.rpartition('!')
    sheet = _sheet_name(prefix) if bang else owner
    if sheet != target or '[' in prefix:
        return value
    ends = addr.split(':') if bang else value.split(':')
    if len(ends) not in (1, 2):
        return value
    matches = [_CELL.fullmatch(x) for x in ends]
    if not all(matches):
        return value
    old = [int(x.group(3)) for x in matches]
    rows = [r + count if r >= at else r for r in old]
    if len(rows) == 2 and old[0] <= first and old[1] == at - 1:
        rows[1] += count
    result = ':'.join(f'{m.group(1)}{m.group(2)}{r}' for m, r in zip(matches, rows))
    return (prefix + '!' if bang else '') + result


def shifted_formula(formula, owner, target, at, count, first):
    tokens = Tokenizer(formula)
    for token in tokens.items:
        if token.type == 'OPERAND' and token.subtype == 'RANGE':
            token.value = shifted_range(token.value, owner, target, at, count, first)
    return tokens.render()


def ensure_labour_capacity(wb, cm, required, flags=None):
    """Add exactly the missing rows in a recognised template, retaining formulas.

    Department arrays are an independent template capacity. Refuse an untested
    expansion beyond that capacity before touching anything, rather than emit
    an apparently complete price with hours missing from the department totals.
    """
    lab = cm['labour']
    first, last = int(lab['first_row']), int(lab['last_row'])
    extra = max(0, int(required) - (last - first + 1))
    if not extra:
        return 0
    ws = wb[cm.get('estimate_sheet', 'Estimate')]
    col = int(lab.get('col_operation', 3))
    if (str(ws.cell(first - 1, col).value or '').strip().lower() != 'operation'
            or not str(ws.cell(last + 1, col).value or '').strip().lower().startswith('total labour cost')):
        raise ValueError('Cannot expand an unrecognised labour block; no costs were dropped.')
    # Reuse the writer's own template inspection, not a guessed 100-row limit.
    from wb_populate import labour_sheet_coverage
    coverage = labour_sheet_coverage(wb, cm)
    if coverage and coverage.get('capacity', required) < required:
        raise ValueError(f"The department-hours template scans {coverage['capacity']} rows; "
                         f"{required} are required. Widen its scan before pricing; no costs were dropped.")

    at = last + 1
    # Prepare every formula first: unsupported syntax fails before any mutation.
    formulas = []
    for sh in wb.worksheets:
        for row in sh:
            for cell in row:
                val = cell.value
                if isinstance(val, str) and val.startswith('='):
                    formulas.append((cell, shifted_formula(val, sh.title, ws.title, at, extra, first)))
                elif getattr(val, 'text', None):
                    new = copy(val)
                    new.text = shifted_formula(val.text, sh.title, ws.title, at, extra, first)
                    if sh == ws and getattr(new, 'ref', None):
                        new.ref = shifted_range(new.ref, ws.title, ws.title, at, extra, first)
                    formulas.append((cell, new))
    names = []
    for holder, owner in [(wb.defined_names, '')] + [(s.defined_names, s.title) for s in wb]:
        for name in holder.values():
            text = name.attr_text
            if text:
                new = shifted_formula('=' + text, owner, ws.title, at, extra, first)[1:]
                names.append((name, new))

    merges = [CellRange(str(m)) for m in ws.merged_cells.ranges]
    source_merges = [m for m in merges if m.min_row == m.max_row == last]
    source = [(c.column, c.value, copy(c._style), copy(c.alignment), copy(c.protection))
              for c in ws[last] if not isinstance(c, MergedCell)]
    dimensions = {r: copy(d) for r, d in ws.row_dimensions.items() if r >= at}
    source_dim = copy(ws.row_dimensions[last])
    areas = [a.rpartition('!')[2] for a in str(ws.print_area).split(',')] if ws.print_area else []
    for m in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(m))
    # The cell objects retain their formulas as they move. Assign prepared texts
    # before insertion, then let openpyxl move their coordinates without translating twice.
    for cell, value in formulas:
        cell.value = value
    for name, value in names:
        name.attr_text = value
    ws.insert_rows(at, extra)
    for r in dimensions:
        del ws.row_dimensions[r]
    for r, dim in dimensions.items():
        dim.index = r + extra
        ws.row_dimensions[r + extra] = dim
    for r in range(at, at + extra):
        dim = copy(source_dim)
        dim.index = r
        ws.row_dimensions[r] = dim
        for c, value, style, alignment, protection in source:
            cell = ws.cell(r, c)
            cell._style, cell.alignment, cell.protection = copy(style), copy(alignment), copy(protection)
            # Only the template formulas repeat, never a previous part or its charge.
            if isinstance(value, str) and value.startswith('='):
                moved = shifted_formula(value, ws.title, ws.title, at, extra, first)
                cell.value = Translator(moved, origin=f'{cell.column_letter}{last}').translate_formula(cell.coordinate)
    for m in merges:
        if m.min_row >= at:
            m.shift(row_shift=extra)
        elif m.max_row >= at:
            m.max_row += extra
        ws.merge_cells(str(m))
    for r in range(at, at + extra):
        for m in source_merges:
            new = CellRange(str(m))
            new.shift(row_shift=r - last)
            ws.merge_cells(str(new))
    for validation in ws.data_validations.dataValidation:
        validation.sqref = ' '.join(shifted_range(str(r), ws.title, ws.title, at, extra, first)
                                  for r in validation.sqref.ranges)
        for key in ('formula1', 'formula2'):
            value = getattr(validation, key)
            if isinstance(value, str) and not value.startswith('"'):
                moved = shifted_formula('=' + value.lstrip('='), ws.title, ws.title, at, extra, first)
                setattr(validation, key, moved if value.startswith('=') else moved[1:])
    conditions = OrderedDict()
    for cf, rules in ws.conditional_formatting._cf_rules.items():
        moved = copy(cf)
        moved.sqref = ' '.join(shifted_range(str(r), ws.title, ws.title, at, extra, first)
                              for r in cf.sqref.ranges)
        rewritten = deepcopy(rules)
        for rule in rewritten:
            rule.formula = [shifted_formula('=' + f.lstrip('='), ws.title, ws.title,
                                            at, extra, first)[1:] for f in rule.formula]
        conditions[moved] = rewritten
    ws.conditional_formatting._cf_rules = conditions
    if areas:
        ws.print_area = [shifted_range(str(a), ws.title, ws.title, at, extra, first) for a in areas]
    lab['last_row'] = last + extra
    if isinstance(flags, list):
        flags.append(f'Labour block expanded in this generated book: {last-first+1} -> '
                     f'{required} rows; individual routes, setups and quantities retained. Template unchanged.')
    return extra
