"""A written-down price chain that has drifted from the code is worse than none.

WHAT PROMPTED IT. Asked where SDI Estimating gets its prices and in what order, the answer came
back as a seven-step table. The next question was the right one: "do we genuinely do all these
lookups, and do we specifically ever find anything from bought_in_parts, the supplier catalogue,
or the historical RAG?"

Both halves of that are worth separating, because they fail differently.

IS IT WIRED? Readable in `_select_anchor_price_source` — it walks the steps in order and the first
hit wins. That is what this file pins: the order described in pricing_sources_audit.SOURCES is the
order the code actually calls. A documented chain that has quietly reordered is a worse artefact
than no documentation, because somebody will reason from it about why a price came out wrong and
reach a confident wrong conclusion.

DOES IT EVER FIRE? Not answerable from source at all, which is the point of the audit tool and not
of this test. A table with no rows can never fire however carefully it is queried, and a step
below UDEF only ever sees parts UDEF could not price — so a healthy UDEF legitimately starves the
ones beneath it. Those are data questions and they need the database.

THE ONE THING TO KEEP STRAIGHT: step 6 has no call site of its own. `_standard_commodity_price` is
consulted INSIDE `_get_web_ai_fallback`, before the model is asked, so the chain reads as six
calls and seven steps. That is deliberate — a real catalogue rate must still beat a config
provisional — and it is the kind of detail a hand-written table gets wrong first.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import pricing_sources_audit as psa  # noqa: E402

_SERVICE = (_ROOT / "src" / "pricing_service.py").read_text(encoding="utf-8")
_CHAIN = _SERVICE[_SERVICE.index("def _select_anchor_price_source"):
                  _SERVICE.index("def _web_ai_fallback_allowed")]

# The method each declared step corresponds to, in order.
_EXPECTED_CALLS = [
    "_get_udef_anchor",
    "_get_pma_purchased",
    "_get_bought_in_part",
    "_get_historical_rag",
    "_get_supplier_catalog",
    "_get_web_ai_fallback",          # step 6 lives inside this one — see the docstring
]


def _call_order():
    return re.findall(r"self\.(_get_\w+|_standard_commodity_price)\(", _CHAIN)


def test_the_chain_calls_the_sources_in_the_order_we_say_it_does():
    """THE ASSERTION THIS FILE EXISTS FOR."""
    assert _call_order() == _EXPECTED_CALLS, (
        "the pricing chain has been reordered and pricing_sources_audit.SOURCES now describes "
        f"something the code does not do:\n  code says {_call_order()}\n  we say  {_EXPECTED_CALLS}")


def test_every_step_we_describe_has_a_number_and_they_run_one_to_seven():
    steps = [s["step"] for s in psa.SOURCES]
    assert steps == list(range(1, len(steps) + 1))


def test_the_declared_steps_and_the_call_sites_line_up():
    """Seven steps, six calls, and the reason is the commodity provisional living inside the
    fallback. If that ever stops being true this arithmetic breaks and somebody looks."""
    assert len(psa.SOURCES) == 7
    assert len(_EXPECTED_CALLS) == 6


def test_the_commodity_provisional_is_still_consulted_before_the_model():
    """It exists because generically-named standards reached the LLM and got a different number
    every run — a castor moved £4.54 to £8.54 between two runs of one job. If it ever moves
    AFTER the model call, it stops doing the job it was added for."""
    body = _SERVICE[_SERVICE.index("def _get_web_ai_fallback"):]
    body = body[:body.index("def _get_labour_rate_from_db")]
    assert "_standard_commodity_price" in body
    assert body.index("_standard_commodity_price") < body.index("lookup_web_ai_price"), \
        "the model is asked before the reproducible provisional is tried"


def test_first_hit_wins_rather_than_a_score_across_sources():
    """The chain is precedence, not competition. If it ever collects candidates and picks a
    winner, every confidence number in the description means something different."""
    assert _CHAIN.count("return ") >= len(_EXPECTED_CALLS), \
        "a step no longer returns immediately — this may have become a scoring contest"
    assert "max(" not in _CHAIN and "sorted(" not in _CHAIN


# ── the table names have to be the real ones ───────────────────────────────────

def test_each_described_table_is_one_the_service_actually_queries():
    """A wrong table name in the description sends somebody to count rows in the wrong place and
    conclude a working source is empty."""
    for s in psa.SOURCES:
        if not s["table"]:
            continue
        bare = s["table"].split(".")[-1]
        assert bare in _SERVICE, f"{s['name']} names {s['table']}, which pricing_service never reads"


def test_the_source_keys_match_what_the_engine_stamps_on_a_price():
    """The audit counts wins by the `source` string the engine writes. A key that never matches
    reports every source as never having fired — a silent, total false negative."""
    for s in psa.SOURCES:
        if s["source_key"] in ("udef_parts_table_for_estimating", "web_ai"):
            continue                     # set elsewhere / composed; checked by the audit's own output
        assert f'"{s["source_key"]}"' in _SERVICE, (
            f"{s['name']} counts wins under {s['source_key']!r}, a string the engine never writes")


# ── what the audit must not claim ──────────────────────────────────────────────

def test_a_source_that_never_won_is_not_called_broken():
    """A step below UDEF only sees parts UDEF could not price. Reporting 'never fired' as a fault
    would send somebody debugging a lookup that is working exactly as designed."""
    src = (_ROOT / "src" / "pricing_sources_audit.py").read_text(encoding="utf-8")
    assert "NOT AUTOMATICALLY A FAULT" in src.upper()
    assert "starves" in src


def test_it_separates_can_it_fire_from_did_it_fire():
    """The two questions have different answers and different fixes: no priced rows is a data
    problem, plenty of rows and no wins is a matching problem."""
    src = (_ROOT / "src" / "pricing_sources_audit.py").read_text(encoding="utf-8")
    assert "def supply(" in src and "def demand(" in src


def _sql_literals(path: Path):
    """Only the strings that ARE SQL.

    The first version of this grepped the whole source for INSERT/UPDATE/DELETE and failed on a
    COMMENT saying "nothing in the codebase writes to it -- there is no INSERT anywhere". That is
    the same trap already recorded against the credential detector in
    test_a_setting_we_read_is_a_setting_that_exists: a guard that reads source as text cannot tell
    a statement from prose about a statement. Parse it, keep the string constants that look like
    queries, and check those.
    """
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.upper()
            if "SELECT " in text and "FROM " in text:
                yield node.value


def test_the_audit_only_reads():
    queries = list(_sql_literals(_ROOT / "src" / "pricing_sources_audit.py"))
    assert queries, "no SQL found at all — has the audit stopped querying?"
    for q in queries:
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE ", "MERGE "):
            assert verb not in q.upper(), f"{verb.strip()} in a read-only audit:\n{q[:200]}"


def test_an_unreachable_database_is_said_rather_than_reported_as_all_zeros():
    """All-zero counts and a dead connection look identical in a table, and one of them would be
    read as 'none of our price sources hold anything'."""
    out = psa.report({"connected": False, "error": "ModuleNotFoundError: pyodbc"})
    assert "Could not reach" in out and "nothing was measured" in out
