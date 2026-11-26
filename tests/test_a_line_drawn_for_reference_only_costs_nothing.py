"""A line its own words put outside SDI's supply is listed at £0 (Hotel Chocolat, 26 Nov 2026).

The 3 m cash desk's bill lists "CASH DRAWER FOR REFERENCE ONLY" x3. It went down the ordinary
bought-in chain to a web guess of £45 each: £140.40 of a £180.31 unit. The engine's supply-
exclusion vocabulary already knew the phrase, but was never asked about a bill line.
"""
from third_party_supply import mark_third_party_supplied


def _mark(*descriptions):
    parts = [{"part_number": f"P{i}", "description": d} for i, d in enumerate(descriptions)]
    mark_third_party_supplied(parts, {"pages": []})
    return parts


def test_reference_only_and_by_others_lines_are_zero_and_say_why():
    drawer, graphic, free = _mark("CASH DRAWER FOR REFERENCE ONLY", "FABRIC GRAPHIC BY OTHERS",
                                  "MONITOR - CUSTOMER FREE ISSUE")
    for p in (drawer, graphic, free):
        assert p["supplied_by_third_party"] == "OTHERS"
        assert "customer_supplied_zero_cost" in p["risk_flags"]
    assert "CASH DRAWER FOR REFERENCE ONLY" in drawer["review_flags"][0]


def test_ordinary_lines_are_untouched():
    for p in _mark("3MTR CASH DESK COUNTER CARCASE ASM", "SHELF PUSHER", "REFERENCE PLATE"):
        assert "supplied_by_third_party" not in p
