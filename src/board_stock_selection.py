"""Choose a stocked board that the workbook can actually nest, without changing its rule.

A full-sheet quote is tied to its dimensions. Only the existing kg-rate fallback
can be moved to a larger sheet here; its price is then rebuilt for that sheet.
"""
from costed_facts import other_sheet_parts_per_sheet


def stock_for_board_row(length, width, current, sizes, *, sheet_price_bound=False):
    try:
        length, width = float(length), float(width)
        sl, sw = map(float, current[:2])
    except (TypeError, ValueError, IndexError):
        return current, ''
    if min(length, width, sl, sw) <= 0:
        return current, ''
    if other_sheet_parts_per_sheet(length, width, sl, sw):
        return current, ''
    candidates = []
    for size in sizes or ():
        try:
            a, b = map(float, size[:2])
        except (TypeError, ValueError, IndexError):
            continue
        if a > 0 and b > 0 and other_sheet_parts_per_sheet(length, width, a, b):
            candidates.append((a * b, a, b))
    if sheet_price_bound:
        return current, ('NO NEST: the priced sheet does not fit the blank with the workbook\'s '
                         'cutting clearances. Obtain a price for a suitable sheet; the existing '
                         'sheet quote has not been scaled or reused.')
    if not candidates:
        return current, ('NO NEST: no configured stock sheet fits the blank with the workbook\'s '
                         'cutting clearances. Confirm stock size and cutting method; do not '
                         'treat the blank material charge as zero cost.')
    _, a, b = min(candidates)
    return [a, b], (f'STOCK SIZE CHANGED: {sl:g} x {sw:g} has zero yield for '
                   f'{length:g} x {width:g} under the workbook\'s cutting clearances; '
                   f'using configured {a:g} x {b:g} stock. Price is recalculated from the '
                   'material kg rate, not copied from the smaller sheet. Confirm stock '
                   'availability and whether a smaller sheet can be trimmed instead.')
