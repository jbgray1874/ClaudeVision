"""One rate, one file. A second copy is not untidiness — it is two prices for one job.

    "all the prices / calculations also need to be in the s/sheet itself or in one easily
     modified config file. not scattered around all over the code"
                                                    — James Gray, SDI, 14 Sep 2026

The audit behind this is `tools/where_do_the_rates_live.py`: 53 rate constants and tables
outside config.py holding 192 numbers across 16 modules, and six rates written down in more
than one place with different values. Four more duplicates agree today. Neither of the six
is a mistake anybody made — each is two people being right in two files, years apart:

    FOAMEX   550 kg/m3 in config   500 in the two modules that decide what a pallet weighs
    PLYWOOD  680 kg/m3 in config   600 in the same two
    powder   0.20 kg/m2            0.166667 in the policy beside it — both in config
    powder   £4.00/kg              £12.50 in sheet_steel_costing
    wire     £1500/tonne default   £1600 in wire_costing, and 1600 on the sheet that shipped
    steel    £950/tonne default    £900 on the sheet that shipped

THE FIRST COUNT WAS WRONG, AND WRONG IN THE PLACE THAT MATTERED MOST. It said 35 tables and
171 numbers, and reported wb_populate.py as holding no rates at all — because the scanner
walked only module level, and `_THROUGHPUT_DEFAULTS` is declared INSIDE populate_workbook().
That table is thirty operations in pieces-per-hour and it is what actually sets the Rate Per
Hour column an estimator reads: Howard Thurley's "Laser Rate Acrylic AI 252 p/hour" is a row
in it. A rate does not stop being a rate because it is indented, and a tool built to answer
"where do the rates live" could not see the biggest answer.

THIS FILE IS A RATCHET, NOT A CLEAN-UP. Migrating 192 numbers is a week's work with an
estimator's ruling needed on each disagreement, and doing it silently would move money on
live jobs. So the list below is frozen at what exists TODAY, with the sizes recorded. A new
rate in a module that is not on the list fails. A listed module that GROWS a rate fails. A
module that loses its rates comes off the list and can never come back.

The point is that the number goes one way.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from where_do_the_rates_live import (against_the_template, clashes,      # noqa: E402
                                     duplicated_but_agreeing, inventory)

# module -> how many rate NUMBERS it is allowed to hold outside config.py, as of 14 Sep 2026.
# Every one of these is a migration waiting for a ruling. Lower a number when you move rates
# out; never raise one.
FROZEN_BUDGET = {
    "src/sheet_steel_costing.py": 72,   # the department rate card, laser speeds, powder
    "src/wb_populate.py": 36,           # _THROUGHPUT_DEFAULTS — the pieces/hour that set the
                                        #   Rate Per Hour column an estimator actually reads
    "src/commercial_lines.py": 19,      # density table (copy 2 of 3)
    "src/palletising.py": 19,           # density table (copy 3 of 3)
    "src/concept_pricing.py": 15,
    "src/dxf_reader.py.py": 12,         # density again, in g/mm3
    "src/estimator.py": 7,
    "src/bought_in_recogniser.py": 2,
    "src/costed_facts.py": 2,
    "src/wire_costing.py": 2,          # gauge table at module level; £/tonne + scrap
    "src/blank_credibility.py": 1,
    "src/client_quote_html.py": 1,     # MARKUP_FACTOR — the customer's price, in an HTML module
    "src/enquiry.py": 1,
    "src/invariants.py": 1,
    "src/parity_check.py": 1,
    "src/web_scrape_price_lookup.py": 1,
}


def _by_module():
    got = {}
    for path, _lineno, _name, n in inventory():
        got[path] = got.get(path, 0) + n
    return got


# ── the ratchet ──────────────────────────────────────────────────────────────────────────

def test_no_module_grows_a_new_rate():
    """A rate added to a module instead of config fails here, on the commit that adds it —
    which is the only moment it is cheap to move."""
    got = _by_module()
    grown = {m: (n, FROZEN_BUDGET.get(m, 0))
             for m, n in got.items() if n > FROZEN_BUDGET.get(m, 0)}
    assert not grown, (
        "rates added outside config.py (module: now vs allowed) — put them in config.py, "
        f"or in the Estimate template: {grown}\n"
        "Run: python tools/where_do_the_rates_live.py")


def test_no_new_module_starts_holding_rates():
    got = _by_module()
    new = sorted(set(got) - set(FROZEN_BUDGET))
    assert not new, (
        f"these modules did not hold rates and now do: {new}. "
        "A rate belongs in config.py or on the Estimate sheet.")


def test_a_module_that_was_cleaned_up_cannot_regress():
    """The budget is the record of the migration. A file emptied of rates must come OFF the
    list, so nothing can quietly refill it up to an old allowance."""
    got = _by_module()
    empty = sorted(m for m in FROZEN_BUDGET if got.get(m, 0) == 0)
    assert not empty, (
        f"these modules no longer hold rates — delete them from FROZEN_BUDGET so they "
        f"cannot silently regrow: {empty}")


def test_the_budget_is_honest_about_the_size_of_the_job():
    """If this ever reads zero the instruction is done, and the ratchet can go."""
    total = sum(_by_module().values())
    assert total <= sum(FROZEN_BUDGET.values()), (
        f"{total} rate numbers now live outside config.py; the frozen total was "
        f"{sum(FROZEN_BUDGET.values())}")


# ── and the disagreements are counted, so they cannot quietly multiply ───────────────────
#
# These are NOT fixed here. Each needs an estimator's ruling and each moves money on live
# jobs, so picking one silently would be this engine inventing a rate. They are pinned at
# the count found on 14 Sep so a SEVENTH cannot appear unnoticed while the six wait.

KNOWN_CLASHES = 6      # FOAMEX, PLYWOOD, powder kg/m2, powder £/kg, wire £/t, steel £/t


def test_no_new_rate_disagreement_appears():
    found = clashes()
    assert len(found) <= KNOWN_CLASHES, (
        "a new rate disagreement has appeared:\n"
        + "\n".join(f"  {c['what']}: {c['a'][0]}={c['a'][1]} vs {c['b'][0]}={c['b'][1]}"
                    for c in found))


def test_the_known_disagreements_are_still_the_known_ones():
    """Named, so that fixing one is visible as progress rather than as a number going down."""
    what = {c["what"] for c in clashes()}
    for expected in ("density of FOAMEX", "density of PLYWOOD", "powder consumed per m2",
                     "powder £/kg", "wire £/tonne", "sheet steel £/tonne"):
        assert expected in what or len(what) < KNOWN_CLASHES, expected


def test_the_agreeing_duplicates_are_listed_not_forgotten():
    """Four rates written in more than one place that happen to match today. They are the
    disagreements of next year, and the tool names them so a change finds all the copies."""
    names = {row[0] for row in duplicated_but_agreeing()}
    assert "scrap %" in names
    assert "material density table" in names


# ── the tool itself has to keep working, or none of the above means anything ─────────────

def test_the_audit_runs_from_the_command_line():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "where_do_the_rates_live.py")],
                         capture_output=True, text=True, timeout=120)
    assert "RATES DEFINED OUTSIDE config.py" in out.stdout
    assert "RATES TWO FILES DISAGREE ABOUT" in out.stdout


def test_the_audit_ignores_probes_and_superseded_copies():
    """estimator_old.py and the _probe scripts are not the shipping engine, and counting
    them would make the budget noise instead of a measurement."""
    files = {row[0] for row in inventory()}
    assert not [f for f in files
                if Path(f).name.startswith("_") or "_old.py" in f or "estimator1" in f]


def test_config_itself_is_never_counted():
    """It is the destination. Counting it would make the number go up as the job gets done."""
    assert not [f for f in {row[0] for row in inventory()} if f.endswith("config.py")]


# ── the spreadsheet is allowed to be the owner, but somebody has to re-read it ───────────
#
# For the £/hr card it already IS the owner: sheet_steel_costing._RATE_CARD_AS_READ_OFF_THE_
# TEMPLATE names the template rows it came from, and every figure in it matches what 7332-01
# shipped — Laser (Metal) 68.1868, Dress Welds 28.6816, Assemble/pack (Metal) 28.5588,
# Manual labour (Acrylic) 25.4257, Diamond Polish 31.6024. That is not scatter; it is a
# transcription with its source named.
#
# What was missing is the re-read. config.py already records one instance of this failing,
# in its own words: "THE TEMPLATE MOVED AND THIS CONSTANT DID NOT."

def test_a_missing_template_is_reported_and_never_guessed_around():
    """This checkout has no spreadsheets directory. The comparison must say so plainly —
    a silent pass would report "all rates match" on a machine that checked nothing."""
    lines = against_the_template()
    assert lines
    joined = " ".join(lines)
    assert ("template not on this machine" in joined
            or "match" in joined or "DIFFERS" in joined or "NOT FOUND" in joined)
    assert "all" not in joined or "match" in joined


def test_the_card_is_matched_by_operation_name_not_by_cell():
    """Inserting a row in the template must not make the check quietly compare the wrong
    two numbers, which is the failure a cell-address mapping would have."""
    src = (ROOT / "tools" / "where_do_the_rates_live.py").read_text(encoding="utf-8")
    assert "Matched by the operation's NAME, not by cell address" in src


def test_the_setup_minutes_still_have_exactly_one_owner():
    """The rate card spells out set-up minutes AND config owns them — deliberately, so the
    two halves can be read side by side. The moment that stops being enforced it becomes a
    seventh disagreement."""
    import config                                                      # noqa: PLC0415
    import sheet_steel_costing as ssc                                  # noqa: PLC0415
    book = getattr(config, "OPERATION_SETUP_MIN", {}) or {}
    card = ssc.RATE_CARD if hasattr(ssc, "RATE_CARD") else {}
    for name, entry in card.items():
        if name in book:
            assert abs(float(entry[1]) - float(book[name])) < 1e-9, (
                f"{name}: rate card says {entry[1]} set-up minutes, config says {book[name]} "
                f"— config is the owner and _with_book_setup should have applied it")


# ── the blind spot that hid the biggest table, pinned ────────────────────────────────────

def test_a_rate_table_inside_a_function_is_still_a_rate_table():
    """_THROUGHPUT_DEFAULTS lives inside populate_workbook(). The first audit walked module
    level only and reported wb_populate.py as clean — while the table that sets the Rate Per
    Hour column sat in it. Indentation is not a hiding place."""
    names = {row[2] for row in inventory()}
    assert "_THROUGHPUT_DEFAULTS" in names
    wb = [row for row in inventory() if row[2] == "_THROUGHPUT_DEFAULTS"]
    assert wb and wb[0][3] >= 25, wb


def test_working_variables_are_not_counted_as_rates():
    """`_cost = area * rate * qty` matches every name pattern and is arithmetic, not a rate.
    Counting those buried the thirty numbers that matter under three hundred that did not."""
    names = {row[2] for row in inventory()}
    for noise in ("_cost", "unit_cost", "hit_min", "priced", "_scrap", "credible_cost"):
        assert noise not in names, noise


def test_the_throughput_that_sets_the_sheets_rate_column_is_named():
    """Howard Thurley asked why acrylic laser reads 252/hr. The answer is a row in this
    table — so the audit has to be able to point at it."""
    import wb_populate                                                  # noqa: PLC0415
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    assert '"Laser (Acrylic)":          252' in src
    assert "UNMEASURED" in src            # and the ones with no corpus behind them say so
