"""11650-06, 25 Sep: the run filed no BOMs and Routes. The extract was written inside the
source-drawing-data audit's try block, so any failure in the audit skipped it and the log
named only the audit. It now has its own try, after the audit's."""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text(encoding="utf-8")


def test_the_extract_is_written_after_the_audit_has_finished_or_failed():
    audit_fail = SRC.index('print(f"   -> Source drawing data not written: "')
    extract = SRC.index("from bom_and_route_extract import write_both as _write_extracts")
    assert extract > audit_fail


def test_the_extract_says_so_when_it_is_not_written():
    assert 'print(f"   -> BOMs and routes not written: "' in SRC
