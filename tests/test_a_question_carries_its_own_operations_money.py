"""A question about an operation carries that operation's money, and a ruled-off coat is not
said to be charged (D-698).

12693-01-GA, 22:06 book, 5 Nov. Two lines in the covering email and the report said what the
sheet did not:

1. The weld-rate question on 12693-01-01M ("give the TIG rate, or the minutes at the Weld (CO2)
   rate") was printed with "£59.17 rides on it". £59.17 is 01M's tube material. Its weld row
   is £24.15. A question about an operation is worth that operation's rows on the part, or no
   figure; never the part's material line.
2. The wires 05M and 06M were flagged "P.COAT CHARGED WITH NO COATED AREA: booth time is
   charged on this part", while the route had ruled their powder coat not applicable (welded
   into the plated weldment and finished with it) and no P.Coat row named them. The flag is
   written before the route decides; a ruling withdraws it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import costed_facts as cf  # noqa: E402
import estimator as est  # noqa: E402
import weld_symbols as ws  # noqa: E402


# ---------------------------------------------------------------- 1. the weld-rate question

def _tube_part():
    return {"part_number": "T-01M", "description": "TUBE FRAME",
            "weld_process": "TIG", "_weld_rate_row": "Weld (CO2)"}


def _ask_the_rate(part):
    q = {"issue": "Weld rate: TIG welding is stated, and the rate card has no TIG rate",
         "assumption": "charged at the Weld (CO2) rate, as a placeholder",
         "action": "give the TIG rate, or the minutes at the Weld (CO2) rate",
         "source": "weld_symbols.weld_rate_gap_question", "operations": ["welding"]}
    part.setdefault("manufacturing_questions", []).append(q)
    return q


def _src(part, rows, material_gbp=59.17):
    """rows: (sheet row, department, £, engine operation, parts)."""
    return {"estimate_summary": {
        "part_estimates": [{"part_number": part["part_number"], "quantity": 1,
                            "material_estimate": {"extended_material_cost_gbp": material_gbp},
                            "line_total_gbp": material_gbp}],
        "canonical_route_shadow": {"decisions": []},
        "final_estimate": {"labour_rows": [
            {"operation": d, "total_value_gbp": v, "workbook_row": n} for n, d, v, _, _ in rows]},
        "workbook_labour": {"rows": [
            {"workbook_row": n, "engine_operations": [e], "part_numbers": list(pns)}
            for n, _, _, e, pns in rows]}},
        "manufacturing_writeup": {"parts": [part]}}


def _rate_rows(src):
    return [d for d in cf.costed_job(src)["decisions_required"]
            if d.get("part") == "T-01M" and "Weld rate" in str(d.get("issue"))]


def test_the_weld_rate_question_is_worth_the_weld_row_not_the_tube():
    part = _tube_part()
    _ask_the_rate(part)
    src = _src(part, [(164, "Weld (CO2)", 24.15, "welding", ["T-01M"]),
                      (165, "Dress Welds", 11.20, "dress_welds", ["T-01M"]),
                      (166, "Weld (CO2)", 40.00, "welding", ["T-999"])])
    rows = _rate_rows(src)
    assert len(rows) == 1
    assert rows[0]["gbp_at_stake"] == 24.15
    assert rows[0]["operations"] == ["welding"]


def test_with_no_weld_row_the_question_carries_no_figure():
    part = _tube_part()
    _ask_the_rate(part)
    rows = _rate_rows(_src(part, []))
    assert len(rows) == 1
    assert rows[0]["gbp_at_stake"] is None


def test_one_question_for_the_job_carries_every_weld_row_of_the_parts_it_covers():
    """Asked once for every TIG part (its words name no part): the TIG rate moves every weld
    row on those parts, each row once, and the assumption names the rows."""
    part = _tube_part()
    _ask_the_rate(part)
    weldment = {"part_number": "T-104", "description": "WELDMENT"}
    _ask_the_rate(weldment)
    src = _src(part, [(164, "Weld (CO2)", 24.15, "welding", ["T-01M"]),
                      (170, "Weld (CO2)", 83.54, "welding", ["T-104", "T-01M"]),
                      (171, "Dress Welds", 47.81, "dress_welds", ["T-104"]),
                      (172, "Weld (CO2)", 9.99, "welding", ["T-999"])])
    src["manufacturing_writeup"]["parts"].append(weldment)
    rows = [d for d in cf.costed_job(src)["decisions_required"]
            if "Weld rate" in str(d.get("issue"))]
    assert len(rows) == 1, "asked once for the job"
    assert rows[0]["gbp_at_stake"] == 107.69
    assert "Estimate rows 164, 170" in rows[0]["assumption"]


def _stated(process="TIG"):
    return {"part_number": "T-01M", "weld_process_stated": {"process": process}}


def test_the_reader_names_the_operation_it_asks_about():
    rec = _stated()
    assert ws.weld_rate_gap_question(rec)
    q = next(x for x in rec["manufacturing_questions"] if "Weld rate" in x["issue"])
    assert q["operations"] == ["welding"]


def test_the_rate_question_does_not_stand_in_for_is_it_welded():
    """subject "welding" would put the part in the asked-about-its-weld set and drop the
    route's own weld questions on it; a rate question names the operation only."""
    rec = _stated()
    ws.weld_rate_gap_question(rec)
    assert all(q.get("subject") != "welding" for q in rec["manufacturing_questions"])


def test_a_co2_weld_is_not_asked():
    assert not ws.weld_rate_gap_question(_stated("CO2"))


# ---------------------------------------------------------- 2. a coat the route rules off

def _wire(pn):
    return {"part_number": pn, "review_flags": [est._ZERO_COAT_PART_FLAG, "OTHER"],
            "risk_flags": ["powder_charged_zero_coated_area", "missing_material_price"]}


def _graph(*decisions):
    return {"decisions": [{"operation": o, "target_id": t, "status": s}
                          for o, t, s in decisions]}


def test_a_ruled_off_coat_withdraws_the_flag_from_the_part_and_the_job():
    parts = [_wire("W-05M"), _wire("W-06M"), _wire("F-101")]
    ests = [_wire("W-05M"), _wire("W-06M"), _wire("F-101")]
    powder = {"charged_with_zero_coated_area": ["W-05M", "W-06M", "F-101"]}
    summary = {"review_flags": ["KEEP ME", est._zero_coat_job_flag(["W-05M", "W-06M", "F-101"])]}
    graph = _graph(("powder_coating", "W-05M", "not_applicable"),
                   ("powder_coating", "W-06M", "ruled_out"),
                   ("powder_coating", "F-101", "required"))
    out = est._withdraw_coats_the_route_rules_off(graph, summary, powder, parts, ests)
    assert out == ["W-05M", "W-06M"]
    for lst in (parts, ests):
        for p in lst[:2]:
            assert est._ZERO_COAT_PART_FLAG not in p["review_flags"]
            assert "OTHER" in p["review_flags"]
            assert "powder_charged_zero_coated_area" not in p["risk_flags"]
            assert "missing_material_price" in p["risk_flags"]
        assert est._ZERO_COAT_PART_FLAG in lst[2]["review_flags"]
    assert powder["charged_with_zero_coated_area"] == ["F-101"]
    job = [f for f in summary["review_flags"] if f.startswith("P.COAT CHARGED")]
    assert job == [est._zero_coat_job_flag(["F-101"])]
    assert "KEEP ME" in summary["review_flags"]


def test_when_every_coat_is_ruled_off_the_job_line_goes():
    parts = [_wire("W-05M")]
    powder = {"charged_with_zero_coated_area": ["W-05M"]}
    summary = {"review_flags": [est._zero_coat_job_flag(["W-05M"])]}
    est._withdraw_coats_the_route_rules_off(
        _graph(("powder_coating", "W-05M", "not_applicable")), summary, powder, parts)
    assert summary["review_flags"] == []
    assert powder["charged_with_zero_coated_area"] == []


def test_an_unverified_or_still_required_coat_withdraws_nothing():
    parts = [_wire("W-05M"), _wire("W-06M")]
    graph = _graph(("powder_coating", "W-05M", "unverified"),
                   ("powder_coating", "W-06M", "not_applicable"),
                   ("powder_coating", "W-06M", "required"))
    assert est._withdraw_coats_the_route_rules_off(graph, {}, {}, parts) == []
    assert all(est._ZERO_COAT_PART_FLAG in p["review_flags"] for p in parts)


def test_a_ruling_on_another_operation_withdraws_nothing():
    parts = [_wire("W-05M")]
    graph = _graph(("folding", "W-05M", "not_applicable"))
    assert est._withdraw_coats_the_route_rules_off(graph, {}, {}, parts) == []
