"""A labour block the grower refuses still writes the book, and says why (26 Nov 2026).

workbook_labour_capacity refuses an unrecognised template or a short department-hours scan
before touching anything. Raised straight out of populate_workbook, that refusal would cost
the job its whole workbook; the old behaviour (overflow reported as labour not on the sheet)
is kept instead, with the reason stated.
"""
import wb_populate


def test_a_refused_growth_is_a_stated_flag_not_a_crash(monkeypatch):
    import workbook_labour_capacity as wlc

    def refuse(*a, **k):
        raise ValueError("Cannot expand an unrecognised labour block; no costs were dropped.")
    monkeypatch.setattr(wlc, "ensure_labour_capacity", refuse)
    flags = []
    assert wb_populate.grow_labour_block(object(), {}, 98, flags) == 0
    assert any("labour block not grown to 98 rows" in f and "unrecognised" in f for f in flags)


def test_growth_that_works_is_passed_through(monkeypatch):
    import workbook_labour_capacity as wlc
    monkeypatch.setattr(wlc, "ensure_labour_capacity", lambda *a, **k: 26)
    flags = []
    assert wb_populate.grow_labour_block(object(), {}, 98, flags) == 26 and flags == []
