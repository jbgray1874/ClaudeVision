"""A ruling is a ruling at whatever severity the check gives it, and it is asked once.

12173-02 Card Spinner (M&S), 1 Oct 2026. Two reviews of the same section 13 fixed the same
twenty "could not be run" rows two ways:

  * the checks-and-finish review made operation_charged_on_a_parent_and_its_child a WARNING
    whose overlap is asked under Decisions required (costed_facts.parent_child_overlaps, the
    joining question on the member, the powder-scope question on the assembly);
  * the report review kept it UNVERIFIED, marked it needs_ruling, counted rulings apart from
    checks that could not run, and netted each ruling onto the manufacturing decision that
    asks the same part and operation, by fields.

Merged, both stand: the finding is a WARNING that carries needs_ruling, it is counted as a
ruling (not "could not be run", not a bare advisory), and it nets onto the decision that asks
it — on the assembly, or on the member for a joint — so the tally holds one row per question.

Synthetic inputs only; the job's facts are in the docstrings.
"""
from __future__ import annotations

import html
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import client_quote_html as CQ                                            # noqa: E402
import costed_facts as cf                                                 # noqa: E402
import invariants as inv                                                  # noqa: E402
import job_report_html as J                                               # noqa: E402

_CODE = "operation_charged_on_a_parent_and_its_child"


def _shadow_job(decs, issues=()):
    parts = [{"part_number": "P", "assembly_children": ["C"]},
             {"part_number": "C", "assembly_children": ["L1", "L2"]}]
    return {"manufacturing_writeup": {"parts": parts},
            "canonical_route_shadow": {
                "decisions": list(decs), "issues": list(issues),
                "priced_route_rows": [{"decision_id": d["decision_id"]} for d in decs]}}


def _coat_overlap():
    return _shadow_job([
        {"decision_id": "d1", "operation": "powder_coating", "status": "required",
         "target_id": "C", "participants": ["C"]},
        {"decision_id": "d2", "operation": "powder_coating", "status": "required",
         "target_id": "L1", "participants": ["L1"]}])


def _joint_overlap():
    return _shadow_job([
        {"decision_id": "w1", "operation": "welding", "status": "required",
         "target_id": "C", "participants": ["C", "L1"]},
        {"decision_id": "w2", "operation": "welding", "status": "required",
         "target_id": "L1", "participants": ["L1"]}],
        issues=[{"code": "joining_charged_on_assembly_and_member", "assembly": "C",
                 "member": "L1", "operation": "welding"}])


# ── the check: a WARNING that needs a ruling ─────────────────────────────────────────────

def test_the_overlap_is_a_warning_that_needs_a_ruling():
    v = inv.check_an_operation_is_not_charged_on_a_parent_and_its_child(_coat_overlap())
    assert len(v) == 1 and v[0]["severity"] == inv.WARNING
    assert v[0]["detail"]["needs_ruling"] is True
    assert v[0]["detail"]["decision_ids"] == ["d1", "d2"]


def test_a_warning_ruling_is_counted_as_a_ruling_not_as_could_not_be_run():
    r = inv.check_job(_coat_overlap(), write_back=False)
    mine = [v for v in r["violations"] if v["code"] == _CODE]
    assert mine and r["rulings"] >= len(mine)
    assert all(v["check"] not in r["checks_not_run"] for v in mine)
    # `not_run` and the UNVERIFIED rulings together are the UNVERIFIED count.
    unv_rulings = sum(1 for v in r["violations"] if v["severity"] == inv.UNVERIFIED
                      and (v.get("detail") or {}).get("needs_ruling"))
    assert r["not_run"] + unv_rulings == r["unverified"]


def test_a_blocking_finding_is_never_a_ruling():
    s = _coat_overlap()
    r = inv.check_job(s, write_back=False)
    bl = inv._violation("x_failed", inv.BLOCKING, "m.", needs_ruling=True)
    r2 = dict(r, violations=r["violations"] + [bl])
    s["invariants"] = r2
    job = cf.costed_job(s)
    assert not any(d["kind"] == "ruling" and d.get("check_code") == "x_failed"
                   for d in job["decisions_required"])


# ── the record: one row per question ─────────────────────────────────────────────────────

def test_the_ruling_nets_onto_the_overlap_decision_on_the_assembly():
    s = _coat_overlap()
    inv.check_job(s)
    ds = cf.costed_job(s)["decisions_required"]
    assert not any(d["kind"] == "ruling" for d in ds)
    asked = [d for d in ds if d["kind"] == "manufacturing_decision" and d["part"] == "C"]
    assert len(asked) == 1
    assert asked[0]["operation"] == "powder_coating"
    assert asked[0]["also_ruled_by_check"] == _CODE
    words = cf.failing_checks_summary(s)
    assert words["rulings"] == 1 and words["rulings_added"] == 0
    assert "1 finding(s) need a ruling (1 already listed as a manufacturing decision" \
        in words["sentence"]


def test_a_joint_ruling_nets_onto_the_question_on_the_member():
    s = _joint_overlap()
    inv.check_job(s)
    ds = cf.costed_job(s)["decisions_required"]
    assert not any(d["kind"] == "ruling" for d in ds)
    joint = [d for d in ds if d["kind"] == "manufacturing_decision" and d["part"] == "L1"]
    assert len(joint) == 1
    assert joint[0]["assembly"] == "C" and "welding" in joint[0]["operations"]
    assert joint[0]["also_ruled_by_check"] == _CODE


def _ruled(assembly="C", member="L1", op="welding"):
    ruling = inv._violation(_CODE, inv.WARNING, f"{op} is charged on {assembly}. y.",
                            operation=op, assembly=assembly, descendants=[member],
                            needs_ruling=True)
    return {"violations": [ruling], "blocking": 0, "unverified": 0,
            "may_quote_firm": True, "checks_run": ["a"]}


def test_the_members_own_question_on_the_operation_takes_the_ruling():
    # The member's own weld question (or its inferred-weld decision) stands in for the joint
    # question, as costed_job already decides when it skips the joining row for it.
    s = {"estimate_summary": {"part_estimates": [{
        "part_number": "L1", "quantity": 1, "manufacturing_questions": [
            {"issue": "Is L1 welded itself?", "assumption": "a", "action": "b",
             "operations": ["welding", "dress_welds"]}]}], "canonical_route_shadow": {}},
         "invariants": _ruled()}
    ds = cf.costed_job(s)["decisions_required"]
    assert not any(d["kind"] == "ruling" for d in ds)
    q = next(d for d in ds if d["issue"] == "Is L1 welded itself?")
    assert q["also_ruled_by_check"] == _CODE


def test_a_joint_row_for_another_assembly_does_not_take_the_ruling():
    s = {"estimate_summary": {"part_estimates": [], "canonical_route_shadow": {
        "issues": [{"code": "joining_charged_on_assembly_and_member", "assembly": "Q",
                    "member": "L1", "operation": "welding"}]}},
         "invariants": _ruled(assembly="C")}
    ds = cf.costed_job(s)["decisions_required"]
    row = next(d for d in ds if d["kind"] == "manufacturing_decision" and d["part"] == "L1")
    assert row["assembly"] == "Q" and not row.get("also_ruled_by_check")
    assert [d["kind"] for d in ds].count("ruling") == 1


def test_a_readers_question_priced_by_its_charged_operations_carries_them():
    s = {"estimate_summary": {
        "part_estimates": [{"part_number": "C", "quantity": 1, "manufacturing_questions": [
            {"issue": "Is C welded itself?", "assumption": "stands", "action": "read it",
             "subject": "welding", "charged_operations": ["welding", "dress_welds"]}]}],
        "workbook_labour": {"rows": [
            {"workbook_row": 40, "engine_operations": ["welding"], "part_numbers": ["C"],
             "total_value_gbp": 3.5}]},
        "canonical_route_shadow": {}}}
    ds = cf.costed_job(s)["decisions_required"]
    q = next(d for d in ds if d["issue"] == "Is C welded itself?")
    assert q["operations"] == ["dress_welds", "welding"]
    assert q["gbp_at_stake"] == 3.5


# ── the page: the same marker, the same label ────────────────────────────────────────────

def test_section_13_labels_a_warning_ruling_as_a_ruling():
    s = _coat_overlap()
    inv.check_job(s)
    page = J.build_report_html(s)
    i = page.find(f"<code>{_CODE}</code>")
    assert i > 0
    assert "Needs a ruling" in page[max(0, i - 200):i]


def test_the_quote_banner_counts_a_warning_ruling():
    s = _coat_overlap()
    inv.check_job(s)
    s["invariants"]["may_quote_firm"] = False
    banner = html.unescape(CQ._invariant_banner(s))
    assert "1 finding(s) need an estimator's ruling" in banner
