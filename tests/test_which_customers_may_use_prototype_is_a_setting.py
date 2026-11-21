"""Who may supplement Design from Prototype is a setting, not a customer written into the
engine (JG, 21 Nov 2026: "the design folder should contain everything. we only pull in from
prototype for tti and other bespoke prototype jobs going fwd"). Made-up names only."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pack_resolver as pr


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SDI_PACK_PROTOTYPE_CUSTOMERS", raising=False)
    monkeypatch.delenv("SDI_PACK_PROTOTYPE_JOBS", raising=False)


def test_with_nothing_set_the_default_customer_may_and_another_may_not():
    assert pr.prototype_allowed("TTI", "50042-01-GA") is True
    assert pr.prototype_allowed("Acme Displays", "50042-01-GA") is False


def test_the_list_can_name_other_customers(monkeypatch):
    monkeypatch.setenv("SDI_PACK_PROTOTYPE_CUSTOMERS", "Acme Displays; Borealis")
    assert pr.prototype_allowed("acme displays", "50042-01-GA") is True
    assert pr.prototype_allowed("Borealis", "50042-01-GA") is True
    assert pr.prototype_allowed("TTI", "50042-01-GA") is False, "the list is the whole answer"
    assert pr.prototype_allowed("Acme", "50042-01-GA") is False, "an exact name, never a part of one"


def test_an_empty_list_makes_every_customer_design_only(monkeypatch):
    monkeypatch.setenv("SDI_PACK_PROTOTYPE_CUSTOMERS", "")
    assert pr.prototype_allowed("TTI", "50042-01-GA") is False
    monkeypatch.setenv("SDI_PACK_PROTOTYPE_JOBS", "50042")
    assert pr.prototype_allowed("TTI", "50042-01-GA") is True, "a named job is still its own opt-in"


def test_the_shared_route_follows_the_list(monkeypatch):
    seen = []
    monkeypatch.setattr(pr, "folders_now", lambda drawing, design_only: (seen.append(design_only) or ([], "test", None)))
    pr.folders_for_customer_now("50042-01-GA", "TTI")
    pr.folders_for_customer_now("50042-01-GA", "Acme Displays")
    assert seen == [False, True]
