"""A PART IS NAMED BY ITS CODE, NOT BY ITS MODEL FILE (12773-01-GA 17:07, 12 Nov 2026).

The bill printed "12773-03-203.SLDPRT1". The hierarchy already treats that as 12773-03-203,
but the costed record, and so the workbook row, kept the file name. Reviewer: "normalise
filename aliases without merging distinct pieces or losing repeated BOM occurrences."
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from route_compiler import name_parts_by_their_code  # noqa: E402


def test_the_extension_and_copy_number_come_off_the_parts_number():
    parts = [{"part_number": "X-03-203.SLDPRT1", "quantity": 5}, {"part_number": "X-03-204", "quantity": 2}]
    said = name_parts_by_their_code(parts)
    assert parts[0]["part_number"] == "X-03-203" and parts[0]["part_number_as_printed"] == "X-03-203.SLDPRT1"
    assert parts[0]["quantity"] == 5 and parts[1] == {"part_number": "X-03-204", "quantity": 2}
    assert said == [{"printed": "X-03-203.SLDPRT1", "code": "X-03-203", "renamed": "yes"}]


def test_two_parts_are_never_made_one():
    parts = [{"part_number": "X-03-203", "quantity": 2}, {"part_number": "X-03-203.SLDPRT1", "quantity": 4}]
    said = name_parts_by_their_code(parts)
    assert [p["part_number"] for p in parts] == ["X-03-203", "X-03-203.SLDPRT1"]
    assert [p["quantity"] for p in parts] == [2, 4] and said[0]["renamed"].startswith("no")


def test_an_assembly_file_name_and_lower_case_are_handled_and_plain_codes_are_left():
    parts = [{"part_number": "x-01-101sa.sldasm"}, {"part_number": "BOLT M6.5"}, {"part_number": ""}]
    name_parts_by_their_code(parts)
    assert [p["part_number"] for p in parts] == ["X-01-101SA", "BOLT M6.5", ""]


def test_the_scan_names_parts_before_it_sizes_or_prices_them():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert src.index("name_parts_by_their_code(") < src.index("_inf = infer_missing_geometry(")
