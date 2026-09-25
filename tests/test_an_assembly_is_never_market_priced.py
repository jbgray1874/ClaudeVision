"""11650-06 (25 Sep): "MIRROR11650-03-GA", the SolidWorks mirror of the arm assembly, came back
from the researched-price rung as "£85.00, one complete mirror unit". Not charged, but a false
£85 decision on the review list, as 12633-00-GA's "Bottle Support" £3.25 was. The web/AI rung
refused assemblies; the researched rung after it never asked. Both now ask one test.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator  # noqa: E402
import pricing_service as ps  # noqa: E402


class _Spy:
    def __init__(self):
        self.briefs = []

    def __call__(self, brief):
        self.briefs.append(brief)
        return {}


def _asked(monkeypatch, part):
    spy = _Spy()
    monkeypatch.setattr(estimator, "_rung4_researcher", spy)
    estimator._resolve_part_system_cost(dict(part))
    return spy.briefs


def test_a_mirror_assembly_is_not_sent_for_a_market_price(monkeypatch):
    part = {"part_number": "MIRROR11650-03-GA",
            "description": "assembly (from the SolidWorks model's own tree)", "quantity": 3}
    assert _asked(monkeypatch, part) == []


def test_a_record_with_children_is_not_sent_either(monkeypatch):
    part = {"part_number": "X-100", "description": "ARM", "assembly_children": ["X-101"]}
    assert _asked(monkeypatch, part) == []


def test_a_bought_in_still_reaches_the_last_rung(monkeypatch):
    part = {"part_number": "BI-PEMSTUD", "description": "M4x12mm THREADED PEM STUD",
            "quantity": 18, "is_bought_in": True}
    assert len(_asked(monkeypatch, part)) == 1


def test_one_test_for_both_rungs():
    assert not ps.is_something_you_can_buy({"part_number": "11650-03-GA"})
    assert not ps.is_something_you_can_buy({"part_number": "A", "is_assembly_parent": True})
    assert ps.is_something_you_can_buy({"part_number": "YIREE KEY", "description": "YIREE KEY"})
