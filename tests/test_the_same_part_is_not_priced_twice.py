"""One part, one lookup — not two, at three and a half seconds each.

WHAT THE RUN LOG SHOWED. Costing 10575-02 at 1 off, every one of the 25 parts:

    get_part_system_cost part_code=10575-01-001 desc_len=21
    code-seek miss part_code=10575-01-001 -> description scan skipped
    done get_part_system_cost rows=0 elapsed=3.4s
    get_part_system_cost part_code=10575-01-001 desc_len=21
    code-seek miss part_code=10575-01-001 -> description scan skipped
    done get_part_system_cost rows=0 elapsed=3.41s

Identical code, identical description, identical empty answer, twice. Each part took about
fifteen seconds end to end and roughly seven of those were this. Twenty-five parts is close to
three minutes of a ten-minute run spent asking a question already answered — on a job where the
material and labour lookups beside it return in 0.05s.

THE MISS IS THE EXPENSIVE CASE, WHICH IS WHY MISSES ARE CACHED TOO. A fabricated part is not in
the purchased-parts catalogue and never will be, so it scans and returns nothing every time. A
cache that stored only hits would leave the entire cost exactly where it is.

THE UNDERLYING QUERY IS ALSO NOT SARGABLE and that is NOT fixed here — config.py wraps the
COLUMN in LTRIM(RTRIM(... COLLATE ...)), which no index can be used against, so each call scans
91k rows. The comment above it claims "sargable, ~ms". Changing a query that runs against
SDILive is not something to do from a guess, so it stays for now and this halves the cost
without touching it. If the predicate is later fixed, this cache becomes cheap insurance
instead of the load-bearing fix, and nothing here needs to change.

PER INSTANCE, NOT PER PROCESS. The connector is built for a run; prices move, and a cache that
outlived a run would be a quiet way to quote yesterday's.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sqlserver_prices as sp                                            # noqa: E402


class _Cursor:
    description = [("part_code",), ("price",)]

    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cursor(self._rows)


def _connector(rows=()):
    """A connector that answers from a list instead of SDILive, counting every execution."""
    # BOTH QUERIES. get_part_system_cost returns [] up front unless part_system_cost_query is
    # set — the by-code seek is the fast path INSIDE it, not a replacement for it — so a
    # fixture with only the by-code query exercises nothing at all and every assertion here
    # passes on a function that returned before it started.
    c = sp.SqlServerPriceConnector("s", "d", "u", "p",
                                   part_system_cost_query="SELECT ? ? ? ? ?",
                                   part_system_cost_query_by_code="SELECT ? ? ?")
    c.is_available = lambda: True                                        # type: ignore
    c._connect = lambda: _Conn(rows)                                     # type: ignore
    c.executed = []
    real = c._execute_query

    def spy(cursor, query, params):
        c.executed.append(list(params))

    c._execute_query = spy                                               # type: ignore
    c._rows_to_dicts = lambda cursor: [dict(r) for r in rows]            # type: ignore
    return c


def test_the_second_ask_for_the_same_part_does_not_reach_the_database():
    c = _connector()
    c.get_part_system_cost("10575-01-001", "V1 - BACK - REAR TRAY")
    c.get_part_system_cost("10575-01-001", "V1 - BACK - REAR TRAY")
    assert len(c.executed) == 1, (
        "the same part was queried twice — three and a half seconds a time, twenty-five times "
        "a job")


def test_a_miss_is_cached_because_the_miss_is_what_costs():
    """Every fabricated part misses. Caching only hits would save nothing at all."""
    c = _connector(rows=())
    assert c.get_part_system_cost("10575-01-002", "BASE BRACKET") == []
    assert c.get_part_system_cost("10575-01-002", "BASE BRACKET") == []
    assert len(c.executed) == 1


def test_a_different_part_is_still_asked():
    c = _connector()
    c.get_part_system_cost("10575-01-001", "REAR TRAY")
    c.get_part_system_cost("10575-01-002", "BASE BRACKET")
    assert len(c.executed) == 2, "the cache is answering for a part it was never asked about"


def test_the_key_is_what_the_query_uses_not_what_the_caller_typed():
    """Both callers ask the database the identical question; they must not miss each other in
    here over whitespace or case that the query normalises away anyway."""
    c = _connector()
    c.get_part_system_cost("10575-01-001", "REAR TRAY")
    c.get_part_system_cost("  10575-01-001  ", "REAR TRAY")
    assert len(c.executed) == 1, "normalised-identical lookups are missing each other"


def test_a_failure_is_not_remembered_as_an_answer():
    """A dropped connection is not "this part is not in the catalogue" — it is no answer at
    all. Cached, one blip would price the rest of the run as though the part had been looked up
    and found missing, which looks identical in the output to a part that genuinely is not
    there."""
    c = _connector()

    def boom():
        raise RuntimeError("connection reset")

    c._connect = boom                                                    # type: ignore
    assert c.get_part_system_cost("10575-01-001", "REAR TRAY") == []
    # now the database comes back
    c._connect = lambda: _Conn(())                                       # type: ignore
    c.get_part_system_cost("10575-01-001", "REAR TRAY")
    assert len(c.executed) == 1, "the failure was cached and the part is never looked up again"


def test_the_caller_cannot_edit_what_the_next_caller_receives():
    """The answer is a list of dicts the caller may well annotate — a source name, a
    confidence, a note. Handing out the cached objects themselves would let the first caller's
    edits turn up in the second's answer, which is a bug that only appears on the second part
    with the same code and is unreadable when it does."""
    c = _connector(rows=({"part_code": "X", "price": 1.5},))
    first = c.get_part_system_cost("X", "d")
    first[0]["price"] = 999
    first[0]["injected"] = True
    second = c.get_part_system_cost("X", "d")
    assert second[0]["price"] == 1.5
    assert "injected" not in second[0]


def test_the_cache_does_not_outlive_the_run():
    """Two connectors, two runs. Prices move; a cache shared across them is a quiet way to
    quote yesterday's."""
    a, b = _connector(), _connector()
    a.get_part_system_cost("10575-01-001", "REAR TRAY")
    b.get_part_system_cost("10575-01-001", "REAR TRAY")
    assert len(a.executed) == 1 and len(b.executed) == 1, (
        "the cache is shared between connectors, so a second run would reuse the first's "
        "prices")
