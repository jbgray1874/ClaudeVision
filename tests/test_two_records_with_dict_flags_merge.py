"""Two records for one part merge even when their review flags are dicts.

12645, 29 Sep 2026 10:43 run on dcbc2be: no workbook was written at all. Replaying the
workbook stage from the run's JSON gave

    File "wb_populate.py", line 2207, in merge_canonical_estimate_records
    TypeError: unhashable type: 'dict'

The flag merge deduplicated with dict.fromkeys, and a review flag may be a dict
({"severity", "field", "reason"}). No job had merged two records that both carried one until
D-322 joined the model's "12645-01GA V2" and the sheet's "12645-01GA" into one node (D-326).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import wb_populate as wp  # noqa: E402

_DICT_FLAG = {"severity": "warning", "field": "material",
              "reason": "No material extracted from title block."}


def _rec(pn, flags):
    return {"part_number": pn, "description": "BODY FRAME", "quantity": 1,
            "review_flags": flags}


def test_dict_flags_on_both_records_merge_without_raising():
    merged = wp.merge_canonical_estimate_records(
        _rec("12645-01GA", [_DICT_FLAG, "text flag"]),
        _rec("12645-01GA V2", [dict(_DICT_FLAG), "text flag", "another"]),
        "assembly")
    flags = merged["review_flags"]
    assert flags.count(_DICT_FLAG) == 1, "the same dict flag is kept once"
    assert flags.count("text flag") == 1
    assert "another" in flags


def test_order_is_kept_first_seen_first():
    merged = wp.merge_canonical_estimate_records(
        _rec("A", ["one", _DICT_FLAG]), _rec("A V2", ["two", "one"]), "leaf")
    assert merged["review_flags"] == ["one", _DICT_FLAG, "two"]


def test_reliability_flags_take_the_same_path():
    a = dict(_rec("A", []), reliability_flags=[{"k": 1}])
    b = dict(_rec("A V2", []), reliability_flags=[{"k": 1}, {"k": 2}])
    assert wp.merge_canonical_estimate_records(a, b, "leaf")["reliability_flags"] == \
        [{"k": 1}, {"k": 2}]
