"""Task #8, from 11650 (23 Sep): a bare "FIXING" line — the M4 PEM stud — ended up inside
FIXING632, the M6 PEM stud. D-214 taught the estimator's bought-in matcher that two threads
are two items. The route compiler's alias pass still read "PEM STUD M6" and "M4 PEM STUD" as
the same two words, because its tokeniser drops every M-number. Every matcher now asks one
reading of the thread, and every stem or alias path refuses a different thread.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drawing_job_merge as djm  # noqa: E402
import file_scan as fs  # noqa: E402
import part_identity as pi  # noqa: E402
import route_compiler as rc  # noqa: E402

M4 = "M4x12mm THREADED PEM STUD"
M6 = "PEM STUD M6 x 12mm"


def test_one_reading_of_a_thread():
    assert pi.thread_sizes(M4) == {"4"} and pi.thread_sizes(M6) == {"6"}
    assert pi.thread_sizes("M5-2 CLINCH NUT") == {"5"}
    assert pi.thread_sizes("SCREW M4.") == {"4"}
    assert pi.thread_sizes("M4.5 SCREW") == {"4.5"}
    assert pi.thread_sizes("CM6 BOARD") == frozenset() and pi.thread_sizes("18MM MDF") == frozenset()
    assert pi.threads_differ(M4, M6)
    assert not pi.threads_differ("PEM STUD M6x12", "M6 x 12 PEM STUD")
    assert not pi.threads_differ("PEM STUD", M6)          # an unstated thread is silence


def test_the_alias_pass_never_makes_an_m4_an_m6():
    # Both reduce to {PEM, STUD} once the tokeniser drops the M-numbers.
    raw = {"BI-PEMSTUD": {"description": "M4 PEM STUD", "is_bought_in": True}}
    extracted = {"FIXING632": {"description": "PEM STUD M6", "is_bought_in": True}}
    assert rc._raw_identity_aliases(raw, extracted) == {}


def test_the_alias_pass_still_joins_the_same_thread():
    raw = {"BI-PEMSTUD": {"description": "M6 PEM STUD", "is_bought_in": True}}
    extracted = {"FIXING632": {"description": M6, "is_bought_in": True}}
    assert rc._raw_identity_aliases(raw, extracted) == {"BI-PEMSTUD": "FIXING632"}


def test_the_bare_stem_stays_its_own_line_on_the_part_records():
    parts = [{"part_number": "FIXING", "description": M4, "quantity": 18},
             {"part_number": "FIXING632", "description": M6, "quantity": 30}]
    assert djm.merge_truncated_part_codes(parts) == []
    assert [p["part_number"] for p in parts] == ["FIXING", "FIXING632"]


def test_the_bare_stem_stays_its_own_line_on_the_bom_rows():
    rows = [{"part_number": "FIXING", "description": M4, "quantity": 18},
            {"part_number": "FIXING632", "description": M6, "quantity": 30}]
    out = fs._merge_truncated_bom_codes(rows)
    assert [r["part_number"] for r in out] == ["FIXING", "FIXING632"]
    assert out[1]["quantity"] == 30
