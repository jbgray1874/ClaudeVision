r"""
test_one_powder_rate_not_two.py

The engine held TWO powder rates and they disagreed by 2.4x. The estimator costed powder at
£4.00/kg from POWDER_COSTING_POLICY; the workbook charged £9.73/kg from POWDER_COST_PER_KG,
for the same powder on the same part.

The evidence is all on one side. The policy's note says "£4/kg standard powder, confirmed by
estimating (Tim, POWDER5 on job 1282)". POWDER_COST_PER_KG's own note said it was "reconciled
to ~£4/kg" while holding 9.73 — a comment contradicting the value beneath it. Tim's 12349-02
sheet buys POWDER40 at £3.48/kg. Nothing anywhere evidences 9.73.

WHAT IT COST: 12349-02's powder came out at £2.14 against Tim's £0.72. At the policy rate the
same calculation gives £0.88, and the rest of that gap is the quantity and the area, both
fixed separately. Every powder-coated job carried the same 2.4x.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                        # noqa: E402

SRC = (ROOT / "src" / "config.py").read_text(encoding="utf-8")


def test_the_two_rates_are_now_one():
    """THE FAULT ITSELF. A part cannot be costed at one rate and charged at another."""
    assert config.POWDER_COST_PER_KG == \
        config.POWDER_COSTING_POLICY["powder_material_gbp_per_kg"]


def test_the_charged_rate_is_derived_not_typed():
    """A second literal is a second rate the moment somebody edits one of them."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and node.targets
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "POWDER_COST_PER_KG"):
            assert not isinstance(node.value, ast.Constant), (
                "POWDER_COST_PER_KG is a literal again — it must come from the policy")
            return
    raise AssertionError("POWDER_COST_PER_KG is not assigned in config")


def test_the_rate_it_settles_on_is_the_evidenced_one():
    """£4.00 has a name against it — estimating, Tim, POWDER5, job 1282. 9.73 never did."""
    assert config.POWDER_COST_PER_KG == pytest.approx(4.0)


def test_it_lands_nearer_the_estimators_own_sheet():
    """Tim buys POWDER40 at £3.48/kg. The old rate was 2.8x that; this is within 15%."""
    tim = 3.48
    assert abs(config.POWDER_COST_PER_KG - tim) / tim < 0.20
    assert abs(9.73 - tim) / tim > 1.5, "the measurement this replaces"


def test_a_special_finish_still_has_its_own_rate():
    """Metallic, textured and wrinkle powders genuinely cost more. Unifying the standard rate
    must not flatten that."""
    assert config.POWDER_COSTING_POLICY["powder_material_gbp_per_kg_special"] > \
        config.POWDER_COST_PER_KG


def test_the_environment_can_still_override_it():
    """One number to change, and it is still changeable without a code edit."""
    assert "POWDER_MATERIAL_GBP_PER_KG" in SRC


def test_the_history_is_written_down_where_the_number_is():
    """The next person to see 4.00 and think it looks low needs the reason in front of them,
    not in a commit message."""
    i = SRC.index("POWDER_COST_PER_KG = float(")
    block = SRC[max(0, i - 1600):i]
    assert "9.73" in block and "2.4x" in block
    assert "POWDER40" in block and "3.48" in block
