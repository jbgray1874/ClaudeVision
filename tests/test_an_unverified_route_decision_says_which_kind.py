r"""
test_an_unverified_route_decision_says_which_kind.py

THE MESSAGE ASSERTED A CAUSE IT NEVER CHECKED.

Six of 11650's eleven blocking findings read:

    canonical_route_decision_unverified: Route decision decision:06ff61895b1c for
    powder_coating on 11650-02-SA01 contains conflicts and cannot be priced automatically.

The predicate that produces them is `decision.get("status") == "unverified"` and nothing
else. The word "conflicts" was unconditional prose chosen by cutover-vs-shadow mode, and the
conflicts list -- attached as detail -- is empty on all six.

route_compiler sets UNVERIFIED in two places that involve no conflict at all: a leaf whose
finish says SEE ASSEMBLY and no extracted route owns it (~2063), and an unattributed
operation stranded on an assembly record (~2073). Both comments say the same thing -- pricing
it would be a guess about who performs the work, and could charge it twice.

The two need OPPOSITE actions. A conflict is a tie between competing readings and somebody
picks one. UNOWNED means there is no second reading: the drawing names the work and no route
claims it, and the answer comes from the drawing office. An estimator told "conflicts" goes
looking for two claims to choose between and finds none, on six lines at once.

MONEY: build_workbook_labour skips any decision whose status is not exactly "required"
(wb_populate.py:1710), so an unverified powder decision never becomes a P.Coat group. On this
job 11650-01-SA01 and 11650-01-SA02 ARE on the P.Coat line and 02-SA01, 02-SA02 and 03-SA01
are not, while the run's own observations report POWDER COATED - MATT - EPOXY BASED POWDER
detected on all of them. That gap is real and is reported honestly; whether to price an
unowned operation is a policy question this file does not answer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import invariants as inv  # noqa: E402


def _job(decision, mode="cutover"):
    return {"canonical_route_shadow": {"mode": mode, "decisions": [decision]}}


def _decision(**kw):
    d = {"decision_id": "decision:06ff61895b1c", "operation": "powder_coating",
         "target_id": "11650-02-SA01", "status": "unverified"}
    d.update(kw)
    return d


def _message(job):
    for v in inv.check_canonical_route_shadow(job):
        if "unverified" in str(v.get("code") or v.get("name") or ""):
            return v["message"]
    return ""


def test_an_unowned_decision_is_not_called_a_conflict():
    """The exact 11650 case: status unverified, conflicts empty."""
    msg = _message(_job(_decision()))
    assert "UNOWNED" in msg
    assert "contains conflicts" not in msg, (
        "the message still asserts conflicts on a decision that records none -- an estimator "
        "goes looking for two claims to choose between and finds nothing")
    assert "ASK WHO PERFORMS THIS" in msg, "say what would resolve it"


def test_a_real_conflict_is_still_called_a_conflict():
    """The fix must not go the other way. Where competing claims exist, that IS the fact and
    it needs a different action -- somebody picks one."""
    msg = _message(_job(_decision(conflicts=[{"a": 1}, {"b": 2}])))
    assert "2 conflicting claim(s)" in msg
    assert "UNOWNED" not in msg


def test_the_count_is_the_real_count():
    """"Conflicts" without a number is not actionable; a wrong number is worse than none."""
    assert "3 conflicting claim(s)" in _message(_job(_decision(conflicts=[1, 2, 3])))


@pytest.mark.parametrize("mode", ["cutover", "shadow"])
def test_both_modes_distinguish_the_two_kinds(mode):
    """Shadow mode says the same thing in a quieter voice. It carried the same false 'metadata
    conflicts' wording, so an unowned decision was misdescribed there too."""
    unowned = _message(_job(_decision(), mode=mode))
    conflicted = _message(_job(_decision(conflicts=[{"x": 1}]), mode=mode))
    assert "UNOWNED" in unowned and "UNOWNED" not in conflicted
    assert "conflict" in conflicted.lower()


def test_the_decision_id_and_target_survive_either_way():
    """Whatever the reason, the line has to name which decision and which part, or nobody can
    act on it."""
    for d in (_decision(), _decision(conflicts=[{"a": 1}])):
        msg = _message(_job(d))
        assert "decision:06ff61895b1c" in msg and "11650-02-SA01" in msg
        assert "powder_coating" in msg


def test_a_verified_decision_raises_nothing():
    assert _message(_job(_decision(status="required"))) == ""


def test_the_gate_is_still_status_alone():
    """Pinning what the check actually keys on, since the message spent this long claiming
    something else. If the predicate ever becomes 'has conflicts', decisions that are unowned
    -- the majority on this job -- stop being reported at all."""
    import ast
    body = ast.unparse(ast.parse((ROOT / "src" / "invariants.py").read_text(encoding="utf-8")))
    assert "decision.get('status') == 'unverified'" in body
