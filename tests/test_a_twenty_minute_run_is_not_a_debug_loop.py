"""Four job runs were spent answering a question about one cell.

    "if I re run now, nothing will change, so what do we do from here?"
                                                    — James Gray, SDI, 15 Sep 2026

Fair, and the answer is not "trust me this time". Four fixes were predicted to move a number
on 7332-01 and two of them did. Each verdict arrived as a whole job run — extraction,
costing, Excel, twenty minutes — to settle which branch decides one throughput.

THE WELD TIME HAD THREE RULES STACKED IN FRONT OF IT, each individually defensible:

    assembly scope skips the grouping        no hours reach the group
    the floor guard replaces outliers        a stated time looks like garbage
    one-row-per-job ops take the default     the derived value is never read

Any loop that showed all three at once would have found them in a sitting. The loop in use
showed one per run, so it took four.

tools/what_will_the_sheet_say.py runs the grouping and the throughput decision only, against
the record the last run already saved, and prints WHICH RULE decides each row. Seconds. It
is not a substitute for the run — the workbook's formulas turn a throughput into money and
nothing here does that — it just stops a run being the only way to ask.

AND IT READS THE REAL SET. _ONE_ROW_PER_JOB is parsed out of wb_populate rather than copied,
because a second copy of that set is precisely the defect this whole session has been about:
two readers of one fact, agreeing until the day they do not.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import what_will_the_sheet_say as dry                                   # noqa: E402


def test_the_one_row_per_job_set_is_read_from_the_engine_not_copied():
    got = dry.wb_one_row_per_job()
    assert {"Weld (CO2)", "Dress Welds", "Assemble/pack (Metal)"} <= got
    # And it really is parsed, not a literal in the tool.
    src = (ROOT / "tools" / "what_will_the_sheet_say.py").read_text(encoding="utf-8")
    assert 'src.split("_ONE_ROW_PER_JOB = {")' in src
    assert '"Weld (CO2)"' not in src.split("def wb_one_row_per_job")[0]


def test_the_three_ops_that_failed_together_are_all_in_it():
    """They failed together because they share one branch. A tool that cannot show that is
    no better than the run it replaces."""
    got = dry.wb_one_row_per_job()
    for op in ("Weld (CO2)", "Dress Welds", "Assemble/pack (Metal)"):
        assert op in got, op


def test_a_missing_file_is_reported_not_traced():
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "what_will_the_sheet_say.py"),
                          "definitely-not-a-job.json"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 2
    assert "no such file" in out.stdout


def test_it_names_the_rule_rather_than_only_the_number():
    """"1.20/hr" is not an answer to "why did my fix not land". "DEPARTMENT DEFAULT
    (one-row-per-job) — a derived time is not read" is."""
    src = (ROOT / "tools" / "what_will_the_sheet_say.py").read_text(encoding="utf-8")
    assert "DEPARTMENT DEFAULT (one-row-per-job)" in src
    assert "STATED SHOP TIME" in src
    assert "template_calculated" in src


def test_it_says_what_it_cannot_tell_you():
    """It prints throughputs and buckets, not money — the workbook's own formulas do that.
    A tool that implied otherwise would be a third opinion about the price."""
    src = (ROOT / "tools" / "what_will_the_sheet_say.py").read_text(encoding="utf-8")
    assert "It is not a substitute for the run" in src


def test_the_prices_mode_exists_because_that_fix_failed_silently_too():
    """The freight relabel did not land either, and nothing said so until the report was
    read by eye. The same question needs the same cheap answer."""
    src = (ROOT / "tools" / "what_will_the_sheet_say.py").read_text(encoding="utf-8")
    assert "--prices" in src
    assert "price-origin" in src.lower()
