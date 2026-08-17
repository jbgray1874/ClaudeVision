"""The SECOND drawing_deterministic gauge apply path also refuses a tolerance table.

A drawing's gauge is written in TWO places on the way to a part: the title block's own reading
(extractor_patterns._primary_thickness_mm) and, when that leaves the thickness open, a fallback
over the raw thickness run (document_builder._first_numeric_thickness, called at
part_index.py:204). The title-block fix stripped 8352's tolerance table (0.5/1.0/1.5/2.0), but the
fallback still returned 1.5 for the very same band — so a false 1.5mm drawing_deterministic gauge
was stamped on parts the model then had to overrule, every overrule a noise flag.

The fallback now decides exactly as the title-block picker does — it delegates to the same
_primary_thickness_mm — so the two apply paths cannot disagree on one drawing, and a pure
tolerance table yields no gauge at either.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import document_builder as db  # noqa: E402
import extractor_patterns as ep  # noqa: E402


def test_a_full_tolerance_table_yields_no_gauge_at_the_fallback():
    """THE 8352 CASE at the second apply path. The whole band alone -> None, not 1.5."""
    assert db._first_numeric_thickness(["0.5", "1.0", "1.5", "2.0"]) is None


def test_a_real_gauge_beside_the_band_survives_the_fallback():
    assert db._first_numeric_thickness(["0.5", "1.0", "1.5", "2.0", "3.0"]) == 3.0


def test_a_lone_band_value_is_kept_by_the_fallback():
    assert db._first_numeric_thickness(["2.0"]) == 2.0
    assert db._first_numeric_thickness(["1.5"]) == 1.5


def test_sub_floor_noise_is_not_a_gauge_at_the_fallback():
    assert db._first_numeric_thickness(["0.5"]) is None


def test_no_thicknesses_is_none_at_the_fallback():
    assert db._first_numeric_thickness([]) is None
    assert db._first_numeric_thickness(None) is None


def test_the_two_apply_paths_agree_on_every_input():
    """The guard against drift: the fallback and the title-block picker return the same gauge for
    every kind of input, because the fallback IS the picker."""
    for values in (
        ["0.5", "1.0", "1.5", "2.0"],
        ["0.5", "1.0", "1.5", "2.0", "3.0"],
        ["2.0"],
        ["1.5"],
        ["0.5"],
        ["3.0", "6.0"],
        [],
    ):
        assert db._first_numeric_thickness(values) == ep._primary_thickness_mm(values)


def test_the_fallback_delegates_to_the_shared_picker():
    """Wired, not merely aligned: document_builder imports the extractor's picker and calls it, so
    there is a single band and a single algorithm."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "document_builder.py"),
               encoding="utf-8").read()
    assert "from extractor_patterns import _primary_thickness_mm as _primary_thickness_mm" in src
    assert "return _primary_thickness_mm(values)" in src
