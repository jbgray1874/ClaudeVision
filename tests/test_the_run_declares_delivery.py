"""The Run form's delivery declaration (D-524).

Tim, 14 Oct, on 12665-01-GA: "There is £125 delivery when there is no delivery requested."
Whether an order is delivered, and where to, is the enquiry's fact — no drawing can say it —
so the portal asks it (a checkbox and a postcode), files DELIVERY_DECLARED.json beside the
staged drawings, file_scan carries it onto summary["delivery_declared"], and the DELIVERY
line follows it. The postcode is the input the per-mile delivery calculator (cost per mile,
by the number and size of boxes) will price from when it lands."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import estimator as E  # noqa: E402
from commercial_lines import find_delivery_declaration  # noqa: E402


def _shippable_parts():
    return [{"part_number": "12399-77J", "description": "KD V2 SHELF", "quantity": 1,
             "normalized_material": "MFC", "normalized_thickness_mm": 18.0,
             "blank_length_mm": 1198.0, "blank_width_mm": 398.0,
             "textual_operations": ["cnc_routing"],
             "normalized_geometry": {"blank_length_mm": 1198.0, "blank_width_mm": 398.0},
             "pages": [1], "page_roles": ["detail"]}]


def _summary(parts, declared=None):
    s = {"declared_product": "12399-77J", "drawing_number": "12399-77J",
         "manufacturing_writeup": {"parts": parts},
         "document_analysis": {"bom_rows": []}, "llm_full_extract": {}, "pages": []}
    if declared is not None:
        s["delivery_declared"] = declared
    return s


def _line_of(parts, code):
    return next((p for p in parts if str(p.get("part_number")) == code), None)


def test_declared_not_required_is_a_deliberate_zero_that_says_so():
    parts = _shippable_parts()
    E.estimate_document(parts, summary=_summary(parts, {"requested": False, "postcode": ""}))
    d = _line_of(parts, "DELIVERY")
    assert d is not None, "the line stays ON the sheet — absence would read as forgotten"
    assert d.get("_commercial_excluded") and d.get("unit_cost_gbp") == 0.0
    assert "declared on the Run" in str(d.get("description"))
    p = _line_of(parts, "PACKAGING")
    assert p is not None and not p.get("_commercial_excluded"), \
        "the declaration is delivery's alone — packaging is untouched"


def test_declared_with_a_postcode_rides_the_line_for_the_calculator():
    parts = _shippable_parts()
    E.estimate_document(parts, summary=_summary(
        parts, {"requested": True, "postcode": "LE19 1WZ"}))
    d = _line_of(parts, "DELIVERY")
    cl = (d or {}).get("commercial_line") or {}
    assert cl.get("delivery_postcode") == "LE19 1WZ"
    assert "per mile" in str(cl.get("note") or ""), \
        "the line says the distance basis awaits the calculator"


def test_a_postcode_that_does_not_read_as_one_is_flagged_not_refused():
    parts = _shippable_parts()
    E.estimate_document(parts, summary=_summary(
        parts, {"requested": True, "postcode": "NOT A PC"}))
    cl = (_line_of(parts, "DELIVERY") or {}).get("commercial_line") or {}
    assert any("does not read as a UK postcode" in str(f)
               for f in (cl.get("review_flags") or [])), cl.get("review_flags")


def test_undeclared_runs_cost_exactly_as_before():
    parts = _shippable_parts()
    E.estimate_document(parts, summary=_summary(parts))
    d = _line_of(parts, "DELIVERY")
    assert d is not None and not d.get("_commercial_excluded")
    cl = d.get("commercial_line") or {}
    assert "delivery_postcode" not in cl and not cl.get("delivery_declared")


def test_the_declaration_file_reads_off_the_staged_folder(tmp_path):
    (tmp_path / "DELIVERY_DECLARED.json").write_text(
        json.dumps({"requested": True, "postcode": "le19 1wz", "declared_on": "run_form"}),
        encoding="utf-8")
    got = find_delivery_declaration([tmp_path])
    assert got == {"requested": True, "postcode": "LE19 1WZ",
                   "file": str(tmp_path / "DELIVERY_DECLARED.json")}
    assert find_delivery_declaration([tmp_path / "nowhere"]) is None
    (tmp_path / "DELIVERY_DECLARED.json").write_text("{broken", encoding="utf-8")
    assert find_delivery_declaration([tmp_path]) is None, \
        "a malformed declaration must not stop a costing run"
