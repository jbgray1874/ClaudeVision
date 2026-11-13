"""A COUNT NOBODY READ IS NOT REPLACED BY ONE (6364-01 18:24, 12 Nov 2026).

The bill tree produced 52 hank bushes where the drawing calls for 4. The quantity cap "reset
to 1" with a warning and one bush was priced as the answer. Reviewer: "no ... hard-coded
quantities or prices, silent exclusions".
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator as E  # noqa: E402


def test_an_uncounted_quantity_over_the_limit_is_marked_unresolved():
    part = {"part_number": "FIXING-BUSH", "quantity": 52}
    assert E._sanitise_part_quantity(part) == 1
    held = part["quantity_unresolved"]
    assert held["computed"] == 52 and held["carried_at"] == 1 and "NOT a price" in held["note"]
    flag = [f for f in part["review_flags"] if isinstance(f, dict) and f.get("flag") == "quantity_capped"][0]
    assert flag["severity"] == "blocking" and "NOT ESTABLISHED" in flag["detail"]


def test_a_quantity_under_the_limit_is_kept_and_not_marked():
    part = {"part_number": "FIXING-SCREW", "quantity": 40}
    assert E._sanitise_part_quantity(part) == 40 and "quantity_unresolved" not in part


def test_a_counted_quantity_over_the_limit_is_kept_and_not_marked():
    part = {"part_number": "FIXING-SCREW", "quantity": 120, "quantity_counted": {"basis": "12 per panel x 10 panels"}}
    assert E._sanitise_part_quantity(part) == 120 and "quantity_unresolved" not in part


def test_the_unresolved_line_is_never_passed_as_a_credible_figure():
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    at = src.index('if mfg.get("quantity_unresolved"):')
    assert 'reasons.append("quantity_not_established")' in src[at:at + 120]
