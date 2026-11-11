"""SCRUM-194 requirement 1 in the regression gate: each acceptance pack's drawing, read by the
deterministic reader alone, against its reviewed expected facts.

A DRAWING THAT IS NOT HERE IS NOT TESTED, AND SAYS SO. The drawings are customer data and are
never committed; they sit beside the facts file on the laptop, or under $SDI_ACCEPTANCE_PACKS.
As with tests/replay, a missing drawing FAILS unless SDI_REPLAY_ALLOW_MISSING=1, which GitHub CI
sets and the laptop's acceptance run never does; the skip names the pack so four skips can never
read as four passes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "acceptance"))

import deterministic_pack_check as dpc  # noqa: E402

PACKS = sorted(p.name for p in dpc.PACKS.iterdir() if (p / "expected_facts.json").is_file()) \
    if dpc.PACKS.is_dir() else []


@pytest.mark.parametrize("pack", PACKS or ["(no packs)"])
@pytest.mark.parametrize("mode", ["deterministic"])
def test_the_drawing_reads_as_the_reviewer_expects(pack, mode):
    if pack == "(no packs)":
        pytest.skip("NOT TESTED: no acceptance packs under tests/acceptance/packs")
    code, text = dpc.check_pack(pack, mode)
    if code == dpc.NOT_TESTED:
        if os.getenv("SDI_REPLAY_ALLOW_MISSING", "").strip() == "1":
            pytest.skip(text)
        pytest.fail(text + "\n(set SDI_REPLAY_ALLOW_MISSING=1 to downgrade to a named skip)")
    assert code == dpc.PASS, text
