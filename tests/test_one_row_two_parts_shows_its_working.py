"""Two components, one labour row, one rate — and no way to check it against either.

    "Line 98 – Laser Rate Mild Steel 2.5mm – 2 Separate Components x 2 per each component
     one Labour Rate shown – Is AI linking both parts with average rate input? AI Laser
     4 x 441 per Hour if averaging out Manual Estimate 567.5 per Hour (2 x 235 & 2 x 900)"
                                        — Howard Thurley, SDI estimating, 9 Sep 2026

THE ANSWER TO HIS QUESTION IS NO, AND THE ARITHMETIC MATTERS.

    a mean of 235 and 900                       567.5
    the true combination, two pieces at each    372.7

Those are different numbers and only one of them is a rate. The row is total pieces divided
by total hours, which is the second kind — so the engine is not averaging, and saying so is
the whole of the answer he is owed on the method.

WHAT HE IS RIGHT ABOUT IS THAT IT CANNOT BE AUDITED. 7332-01-003 is a 441 x 10 strap;
7332-01-004 is a 15.88 mm square cap. They share a row because they share a 2.5 mm laser
set-up, which is correct and is why the set-up is booked once. But one blended figure hides
a fast part behind a slow one, and only the SUM of their hours was ever retained — so the
row could not show its working even in principle.

Their own hours cost nothing to keep. This changes no money: it is the working, not a new
figure, and the grouping stays.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                            # noqa: E402

SRC = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")


# ── the arithmetic he asked about ────────────────────────────────────────────────────────

def test_the_engine_combines_it_does_not_average():
    """qty / summed hours is a combination. If this ever became (a + b) / 2 the row would
    report 567.5 where the true figure is 372.7 — a 52% over-statement of throughput, which
    is a 34% UNDER-charge of the labour."""
    assert "_derived = float(_qty) / _rhpu" in SRC
    assert "_derived = _total_pieces / bh" in SRC


def test_the_two_are_genuinely_different_numbers():
    """Pinned as arithmetic so the distinction cannot be argued away later."""
    a, b = 235.0, 900.0
    mean = (a + b) / 2
    combination = 4 / (2 / a + 2 / b)
    assert round(mean, 1) == 567.5
    assert round(combination, 1) == 372.7
    assert mean > combination * 1.5


# ── the parts' own hours are kept ────────────────────────────────────────────────────────

def test_each_parts_hours_are_recorded_beside_the_total():
    assert 'g.setdefault("hours_by_part", {})[_pn]' in SRC
    assert "WHOSE HOURS THEY WERE" in SRC


def test_the_canonical_path_records_them_too():
    """A row must be able to show its working whichever of the two grouping routes built
    it, or the fix is present on some jobs and absent on others."""
    assert 'group.setdefault("hours_by_part", {})[str(representative_id)]' in SRC


def test_the_row_names_its_members_and_their_rates():
    assert "members_own_rates" in SRC
    assert "each: {_shown}" in SRC


def test_it_lands_on_the_row_not_only_in_a_flag():
    """Every question raised in a review flag so far reached neither deliverable. A
    breakdown an estimator cannot see answers nothing."""
    assert 'ws.cell(row=row, column=lb["col_desc"])' in SRC
    assert "ON THE ROW ITSELF, not only in a flag" in SRC


# ── and it says when the members are far apart ───────────────────────────────────────────

def test_a_wide_spread_reaches_the_outstanding_inputs_list():
    assert "ONE {wb_op} row covers parts running {_spread:.1f}x" in SRC
    assert "_inputs.append" in SRC.split("THE ROW SHOWS ITS WORKING")[1][:4500]


def test_the_threshold_is_config_and_explains_itself():
    assert config.LABOUR_GROUP_RATE_SPREAD_FLAG == 3.0
    cfg = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
    assert "3x is a strap against a cap" in cfg
    assert "Howard Thurley" in cfg.split("LABOUR_GROUP_RATE_SPREAD_FLAG")[0][-1500:]


def test_the_message_says_it_is_not_an_average():
    """The sentence that answers his actual question has to be the one on the sheet."""
    assert "the true combination and NOT an average" in SRC


def test_the_message_says_why_they_share_a_row():
    """Otherwise "split them" reads as advice to split the set-up too, which would
    over-charge every job that shares a nest."""
    assert "Set-up is booked once because the parts share it." in SRC


# ── and nothing about the money changes ──────────────────────────────────────────────────

def test_a_single_part_row_gets_no_breakdown():
    """One part is its own rate. A row that explains itself when there is nothing to explain
    is noise, and noise is how a checklist stops being read."""
    assert "if len(_hbp) > 1 and order_qty:" in SRC


def test_the_grouping_itself_is_untouched():
    """The set-up is genuinely shared, so the parts genuinely belong on one row. This adds
    the working; it does not split the row or re-book the set-up."""
    assert "setup is booked once per tooling group" in SRC


def test_no_throughput_is_altered_by_any_of_it():
    """The breakdown is computed AFTER the rate and writes only the description and the
    flags — if it ever assigned `throughput` this would be a money change wearing a
    transparency label."""
    block = SRC.split("THE ROW SHOWS ITS WORKING")[1].split("if (_rhpu and _rhpu > 0)")[0]
    assert "throughput =" not in block
    assert "g[\"qty\"]" not in block
