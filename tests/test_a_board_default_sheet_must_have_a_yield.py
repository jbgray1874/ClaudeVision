import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from board_stock_selection import stock_for_board_row
from costed_facts import other_sheet_parts_per_sheet


def test_near_full_sheet_board_uses_larger_configured_stock():
    size, reason = stock_for_board_row(2430, 1210, [2440, 1220],
                                       [(2440, 1220), (3050, 1525)])
    assert size == [3050, 1525]
    assert other_sheet_parts_per_sheet(2430, 1210, *size) == 1
    assert 'kg rate' in reason and 'trimmed' in reason


def test_existing_quoted_sheet_price_is_not_scaled():
    size, reason = stock_for_board_row(2430, 1210, [2440, 1220],
                                       [(3050, 1525)], sheet_price_bound=True)
    assert size == [2440, 1220] and reason.startswith('NO NEST')


def test_no_stock_never_claims_one_part_fits():
    size, reason = stock_for_board_row(4000, 2000, [2440, 1220], [(3050, 1525)])
    assert size == [2440, 1220] and 'no configured stock' in reason
    assert not other_sheet_parts_per_sheet(4000, 2000, *size)


def test_a_working_sheet_and_orientation_stay_unchanged():
    size, reason = stock_for_board_row(200, 300, [2440, 1220], [(3050, 1525)])
    assert size == [2440, 1220] and not reason


def test_rotation_is_not_invented_for_grained_board():
    size, reason = stock_for_board_row(2400, 1500, [2440, 1220], [(1600, 2500)])
    assert size == [2440, 1220] and 'NO NEST' in reason
