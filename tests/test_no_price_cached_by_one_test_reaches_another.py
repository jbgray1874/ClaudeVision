"""NO PRICE CACHED BY ONE TEST REACHES ANOTHER (reviewer, 12 Nov 2026).

"Please also investigate the intermittent board-pricing tests. An unchanged test file and a
successful second run do not establish that the failure is harmless."

The cause: the estimator's price caches live for the process, the suite is one process, and
its order is shuffled. These two tests are written to fail in either order without the guard
in conftest.py: each plants a rate for the board the other prices.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as E  # noqa: E402

CACHES = ("_SHEET_RATE_CACHE", "_SHEET_RATE_ROWS", "_SHEET_RATE_META",
          "_RESEARCHED_BOARD_RATE_CACHE", "_MARKET_INDICATION_CACHE", "_SECTION_ROWS_CACHE")


def _plant():
    E._SHEET_RATE_CACHE[("MFC", 18.0)] = 7.18
    E._SHEET_RATE_CACHE[("PETG", 2.2)] = 19.5
    E._RESEARCHED_BOARD_RATE_CACHE[("MFC", 18.0, "")] = {"price_gbp": 10.0}
    E._MARKET_INDICATION_CACHE[("X", 1)] = 5.0


def _all_empty():
    return all(not getattr(E, n) for n in CACHES)


def test_a_test_starts_with_every_price_cache_empty_then_plants_rates():
    assert _all_empty(), {n: len(getattr(E, n)) for n in CACHES}
    _plant()


def test_another_test_also_starts_empty_whichever_ran_first():
    assert _all_empty(), {n: len(getattr(E, n)) for n in CACHES}
    _plant()


def test_every_cache_the_estimator_keeps_for_a_run_is_cleared(monkeypatch):
    import re
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    kept = set(re.findall(r"^(_[A-Z_]*(?:CACHE|_ROWS|_META)[A-Z_]*)\s*:\s*Dict", src, re.M))
    conf = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    missing = sorted(n for n in kept if f'"{n}"' not in conf)
    assert not missing, f"a module-level price cache the test guard does not clear: {missing}"
