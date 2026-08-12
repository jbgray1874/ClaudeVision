r"""
test_a_pricing_source_that_is_off_says_so.py

bay_rollup holds two UDEF lookups -- one for bought-in lines, one for tube stock -- and both
are on the live path through file_scan. Both opened with

    cs = _cfg.SQL_CONNECTION_STRING

against a config that has never defined that name, so the FIRST statement inside each `try`
raised AttributeError, `except Exception: pass` swallowed it, and both returned None.

None is the same answer these functions give when UDEF is reachable and simply holds no match.
So from the caller, and from the estimate, and from the console, a pricing source that was
never switched on was indistinguishable from one that was asked and had nothing to say. Every
bought-in and every tube routed through bay_rollup went unpriced on every job, for as long as
the code has existed, and nothing anywhere said a word about it.

That is the shape to test, not the typo. The typo is fixed by a name; the class is fixed by
refusing to let a source fail quietly. These two facts:

    1. the lookups reach UDEF through config.get_connection(), the one connector
    2. when that fails, it is SAID -- once, not per line -- and the line is left unpriced
       rather than priced at zero
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bay_rollup  # noqa: E402
import config      # noqa: E402


@pytest.fixture(autouse=True)
def _forget_what_was_said():
    """The "say it once" memo is module state and would hide the message from the next test."""
    bay_rollup._UDEF_SAID.clear()
    yield
    bay_rollup._UDEF_SAID.clear()


def _udef_is_down(monkeypatch, exc=RuntimeError("no route to host")):
    def _boom(*_a, **_k):
        raise exc
    monkeypatch.setattr(config, "get_connection", _boom)


@pytest.mark.parametrize("call", [
    lambda: bay_rollup._udef_fuzzy_lookup("2 OFF 50CM LOOM", "ELECTRICS"),
    lambda: bay_rollup._lookup_tube_udef(60.0, 30.0, 1.5, 1200),
])
def test_a_lookup_that_cannot_reach_udef_says_so_and_returns_no_price(call, monkeypatch, capsys):
    _udef_is_down(monkeypatch)
    assert call() is None, "an unreachable source must not invent a match"
    said = capsys.readouterr().out
    assert "UDEF" in said and "unavailable" in said, (
        "the lookup failed silently. A source that is switched off must never read the same "
        "as a source that was asked and had no answer -- that is what hid this for the whole "
        "life of the module.")
    assert "no route to host" in said, "say WHAT failed, or the message cannot be acted on"


def test_it_is_said_once_not_once_per_line(monkeypatch, capsys):
    """A folder job runs this per bought-in line. Per-line would print thousands of times and
    the message would be scrolled past, which is the same as not printing it."""
    _udef_is_down(monkeypatch)
    for _ in range(20):
        bay_rollup._udef_fuzzy_lookup("2 OFF 50CM LOOM", "ELECTRICS")
    assert capsys.readouterr().out.count("unavailable") == 1


def test_both_lookups_get_their_own_line(monkeypatch, capsys):
    """Bought-ins and tube are different gaps in the estimate and are worth naming apart."""
    _udef_is_down(monkeypatch)
    bay_rollup._udef_fuzzy_lookup("2 OFF 50CM LOOM", "ELECTRICS")
    bay_rollup._lookup_tube_udef(60.0, 30.0, 1.5, 1200)
    out = capsys.readouterr().out
    assert "bought-in lookup" in out and "tube lookup" in out


def test_a_working_lookup_says_nothing(monkeypatch, capsys):
    """The message must be earned. If it prints on a healthy run it stops being read, and the
    next real outage goes past on a console nobody trusts."""
    class _Cur:
        def execute(self, *_a, **_k): return self
        def fetchone(self): return None
    class _Cn:
        def cursor(self): return _Cur()
        def close(self): pass
    monkeypatch.setattr(config, "get_connection", lambda *_a, **_k: _Cn())
    assert bay_rollup._udef_fuzzy_lookup("2 OFF 50CM LOOM", "ELECTRICS") is None
    assert "unavailable" not in capsys.readouterr().out


def test_the_connection_is_closed_even_when_the_query_raises(monkeypatch):
    """pyodbc's own `with` manages the TRANSACTION and leaves the connection open, which is
    what the previous code used. On a folder job that is one live SQL connection per
    bought-in line, held until garbage collection."""
    closed = []

    class _Cn:
        def cursor(self): raise RuntimeError("query blew up")
        def close(self): closed.append(True)

    monkeypatch.setattr(config, "get_connection", lambda *_a, **_k: _Cn())
    assert bay_rollup._udef_fuzzy_lookup("x", "y") is None
    assert closed == [True], "the connection was left open when the query raised"


def test_the_lookups_do_not_assemble_their_own_connection_string():
    """Both must go through the one connector. A second way to reach the database is a second
    place for a credential to live and a second thing to fix when the login rotates."""
    import ast
    tree = ast.parse((ROOT / "src" / "bay_rollup.py").read_text(encoding="utf-8"))
    body = ast.unparse(tree)          # AST-parsed: the comments explaining this are not code
    assert "PWD=" not in body, "bay_rollup is assembling its own connection string again"
    assert "get_connection" in body, "bay_rollup no longer reaches UDEF through config"
