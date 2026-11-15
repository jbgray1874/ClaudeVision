"""The estimate states the drawings it used and the ones believed missing (JG, 15 Nov 2026).

"yes, we identify the drawings used in the estimate and we make a statement about what we
think are drawings that are missing and would have helped the estimate." ... "both runners also
need to display the drawings used and a list of drawings that ideally we have that are missing
also in the email. html and the e-mail that is produced."

One statement, built from the run's saved record (src/drawings_statement.py), shown on the
report page and in the covering e-mail. A part bound only to a parts list page has no drawing
of its own; a bought-in item needs none; a file in the pack that nothing read is named as not
read, not as missing; and when nothing is missing the statement says so in words.
"""
import html as _html
import importlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawings_statement as ds  # noqa: E402


def _record(**over):
    parts = [
        {"part_number": "5000-01-01", "description": "SIDE PANEL", "pages": [3], "page_roles": ["detail"]},
        {"part_number": "5000-01-02", "description": "SHELF EDGING", "pages": [2], "page_roles": ["detail"],
         "bound_to_parts_list_page": 2, "solidworks_native": {"found": True}},
        {"part_number": "5000-01-03", "description": "BRACKET", "pages": [],
         "dxf_source_file": "5000-01-03_2mm.DXF"},
        {"part_number": "M6 BOLT", "description": "M6 BOLT", "pages": [2], "page_roles": ["bought_in"],
         "bound_to_parts_list_page": 2},
        {"part_number": "5000-01-00", "description": "TOP ASSEMBLY", "pages": None,
         "is_assembly_parent": True, "canonical_kind": "assembly"},
    ]
    rec = {"job_source_pdfs": [{"name": "5000-01-GA_Unit.PDF", "page_count": 6}],
           "cad_inputs": {"unread": ["5000-01-GA_Unit.DWG"]},
           "parts": parts,
           "estimate_summary": {"part_estimates": [{"part_number": p["part_number"]} for p in parts]}}
    rec.update(over)
    return rec


def _text(html):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def test_a_part_named_only_by_a_parts_list_page_is_believed_missing():
    st = ds.statement(_record())
    assert [u["name"] for u in st["used"]] == ["5000-01-GA_Unit.PDF"]
    assert [m["part_number"] for m in st["missing"]] == ["5000-01-02"]
    why = st["missing"][0]["why"]
    assert "parts list on page 2" in why and "the model's" in why
    # a file nothing read is named as not read: it was supplied, so it is not called missing
    assert [u["name"] for u in st["not_read"]] == ["5000-01-GA_Unit.DWG"]


def test_the_contrasts_a_bound_sheet_a_flat_a_bought_in_and_a_model_tree_assembly_are_not_missing():
    rec = _record()
    rec["parts"][1].pop("bound_to_parts_list_page")           # now bound to a detail sheet
    st = ds.statement(rec)
    assert st["missing"] == []
    t = _text(ds.html(st))
    assert "Drawings we believe are missing and would have helped" in t
    assert ds.NONE_MISSING in t, "nothing missing is said in words, never an empty heading"
    assert "<ul></ul>" not in ds.html(st)


def test_a_line_the_parts_list_names_with_no_drawing_in_the_pack_is_listed():
    rec = _record(invariants={"violations": [{
        "code": "bom_names_a_drawing_the_pack_does_not_contain",
        "detail": {"missing": [{"part_number": "5000-02-GA", "description": "WELDED FRAME"}]}}]})
    missing = {m["part_number"]: m for m in ds.statement(rec)["missing"]}
    assert missing["5000-02-GA"]["kind"] == "named_not_supplied"
    assert "nothing is charged for it" in missing["5000-02-GA"]["why"]


def test_a_record_that_named_no_files_says_so():
    st = ds.statement({"parts": []})
    assert st["recorded"] is False
    assert ds.NOT_RECORDED in _text(ds.html(st)) and ds.NOT_RECORDED in ds.text(st)
    assert ds.statement(None)["missing"] == []


def test_the_report_page_and_the_email_carry_the_same_statement(tmp_path):
    import estimate_explained as ee
    import job_report_html as jr
    sys.path.insert(0, str(ROOT / "tests"))
    sib = importlib.import_module("test_the_covering_note_says_what_the_estimate_costs")
    scan = sib._scan(tmp_path / "j.json")
    doc = json.loads(scan.read_text(encoding="utf-8"))
    extra = _record()
    doc["job_source_pdfs"] = extra["job_source_pdfs"]
    doc["cad_inputs"] = extra["cad_inputs"]
    doc["parts"] = list(doc.get("parts") or []) + extra["parts"]
    doc.setdefault("estimate_summary", {}).setdefault("part_estimates", []).extend(
        extra["estimate_summary"]["part_estimates"])
    scan.write_text(json.dumps(doc), encoding="utf-8")
    st = ds.statement(doc)
    assert "5000-01-02" in [m["part_number"] for m in st["missing"]]

    page = _text(jr._files_read_section(doc))
    note = ee.covering_email(sib._workbook(tmp_path / "j.xlsx"), scan, client="x")
    mail = _text(note["html"])
    assert "Drawings used, and drawings believed missing" in mail
    for m in st["missing"]:
        line = f"{m['part_number']} {m['description']}: {m['why']}."
        assert line in page and line in mail, "one statement, two places"
    for u in st["used"]:
        assert u["name"] in page and u["name"] in mail
    assert "5000-01-GA_Unit.DWG" in page and "In the pack and not read" in mail
    # THE DRAWING PACK SECTION SAYS HOW MANY FILES WERE READ AND WHERE THE FULL LIST IS (JG,
    # 15 Nov 2026: "why are the html report e-mails missing loads of drawings?"): its own
    # table is one row per costed part with a sheet, and read as the pack with most missing.
    count = ds.count_line(st)
    assert count and str(len(st["used"])) in count
    section = mail[mail.index("7. The drawing pack"):]
    assert section.index(count) < section.index("Drawings used, and drawings believed missing")
    assert "one row for each costed part" in section
    assert mail.count(count) == 2, "the count opens the pack section and heads the full list"
    # the statement sits above the calculator section, which stays at the bottom
    assert mail.index("Drawings used, and drawings believed missing") < mail.index("Produced by SDI")


def test_the_count_names_each_kind_of_file_and_is_silent_when_nothing_was_recorded():
    st = {"used": [{"name": "a.pdf", "kind": "PDF"}, {"name": "b.dxf", "kind": "DXF"},
                   {"name": "c.dxf", "kind": "DXF"}]}
    assert ds.count_line(st) == "3 files were read for this estimate: 1 PDF, 2 DXF."
    assert ds.count_line({"used": [{"name": "a.pdf", "kind": "PDF"}]}).startswith("1 file was read")
    assert ds.count_line({"used": []}) == "" and ds.count_line(ds.statement({"parts": []})) == ""
