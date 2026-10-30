"""One letter between an operation and its rate, and the tube-bender worked for nothing.

7332-01's sheet books Tubebend at 30/hr. That is not a calculation — it is
wb_populate._THROUGHPUT_DEFAULTS["Tubebend"], the department default, and our own table
flags it UNMEASURED. The engine had computed the time and then thrown it away:

    the operation the estimator emits      "tube_bending"
    the key in config.HOURLY_RATES_GBP     "tube_bend"

`rate is None` sends the op to missing_rate_operations and `continue`s — so no batch_hours
and no run_hours_per_unit are written for it at all. wb_populate then has nothing to derive
from and falls back to the corpus median. The template has priced Tubebend at £32.84/hr with
a 45-minute set-up (TBEN) since it was written; nothing was missing but the spelling.

THE FAILURE MODE IS THE POINT. This does not produce a blank, an error, or a zero — it
produces a plausible number from a different source, on a row that looks finished. Every
book 7332-01 has ever produced carried it. A rate table keyed one letter off an operation
name must not be shippable, so the check is mechanical rather than a matter of noticing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                            # noqa: E402

SRC = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")


def _timed_operations():
    """Every operation the estimator writes a run time for, read from the source.

    These are exactly the ops that can generate hours, so they are exactly the ops that can
    LOSE them. Dynamic keys (_bb_op and friends) resolve to names already in this set or to
    a config-declared operation, which the dedicated tests below cover."""
    return sorted(set(re.findall(r'run_times_min\[["\'](\w+)["\']\]', SRC)))


def test_every_operation_the_estimator_times_has_a_rate():
    missing = [op for op in _timed_operations() if op not in config.HOURLY_RATES_GBP]
    assert not missing, (
        f"these operations generate hours and have NO hourly rate, so their time is "
        f"silently dropped and the workbook substitutes a department median: {missing}")


def test_the_tube_bend_spelling_that_cost_the_money():
    """Both spellings resolve now. The engine emits the first; the second is referenced
    elsewhere and removing it would be the same defect in the other direction."""
    assert config.HOURLY_RATES_GBP["tube_bending"] == 32.84
    assert config.HOURLY_RATES_GBP["tube_bend"] == 32.84


def test_the_rate_matches_what_the_template_charges():
    """£32.84/hr, TBEN — the figure on the Estimate sheet's own rate list, which is where
    this should have been read from all along."""
    assert config.HOURLY_RATES_GBP["tube_bending"] == 32.84


def test_the_config_says_why_both_keys_exist():
    cfg = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
    assert "TWO SPELLINGS, ONE LETTER" in cfg
    assert "the name the engine actually emits" in cfg


# ── the operations config itself names ───────────────────────────────────────────────────

def test_the_brushing_operation_has_a_rate():
    """config.BRUSH_BEFORE_PLATE names the operation it books. If that name ever drifts from
    the rate table the forty minutes vanish exactly as the tube bend did."""
    op = config.BRUSH_BEFORE_PLATE["operation"]
    assert op in config.HOURLY_RATES_GBP, op


def test_every_labour_rule_operation_has_a_rate():
    """LABOUR_RULES is the other place an operation name is declared."""
    missing = [op for op in (getattr(config, "LABOUR_RULES", {}) or {})
               if op not in config.HOURLY_RATES_GBP]
    assert not missing, (
        f"operations with a timing rule but no rate: {missing}")


# ── and the table does not quietly hold two answers for one operation ────────────────────

def test_no_operation_is_listed_twice_with_different_rates():
    """A duplicate key in a literal silently keeps the last one. If the two ever differ, the
    rate an estimate uses depends on line order in a config file."""
    cfg = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
    block = cfg.split("HOURLY_RATES_GBP = {")[1].split("\n}")[0]
    pairs = re.findall(r'"([a-z_]+)":\s*([0-9.]+)', block)
    seen = {}
    for key, val in pairs:
        if key in seen:
            assert seen[key] == val, (
                f"'{key}' is listed twice with different rates ({seen[key]} and {val}) — "
                f"the later line silently wins")
        seen[key] = val
