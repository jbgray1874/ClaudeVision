"""Presentation-only identity: old runs work without touching files, prices or timing."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("visual_wall", ROOT / "sdi-intelligence-backend/estimate_wall.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)


def test_reference_is_never_replaced_by_a_title():
    r = dict(run_id="r", drawing_number="12133-00-GA", job_title="Product display", units=6)
    got = W._summary(r)
    assert got["drawing_number"] == "12133-00-GA"
    assert got["description"] == "Product display" and got["units"] == 6
    assert got["source_row"] is None


def test_old_tti_service_log_supplies_row_and_explicit_dropoff_title():
    r = dict(source="tti", drawing_number="TTI-C-abc123", units=2, log=[
        "  | Workbook worksheet Milwaukee, source row 47. Quantity: 2.",
        "Drop-off  Review copy of this pack (1 file(s), new): C:\\pack\\TTI-C-abc123 - METAL CLAMP. NOT SHOWN COMPLETE: source pack: no manifest",
    ])
    assert W.display_identity(r) == dict(description="METAL CLAMP", source_row=47, units=2)


@pytest.mark.parametrize("source,line", [
    ("page", "  | Workbook worksheet Milwaukee, source row 47. Quantity: 2."),
    ("tti", "A person mentioned source row 47."),
    ("tti", "  | Workbook worksheet Milwaukee, source row -5. Quantity: 2."),
])
def test_no_guessed_rows(source, line):
    assert W.display_identity(dict(source=source, log=[line]))["source_row"] is None


def test_missing_metadata_does_not_read_the_disk_or_invent_a_title(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("wall identity must never access a file")
    monkeypatch.setattr(Path, "read_text", forbidden)
    r = dict(source="tti", drawing_number="TTI-C-abcdef", log=[])
    assert W.display_identity(r) == dict(description="", source_row=None, units=None)


def test_title_cannot_be_taken_from_another_reference_or_generic_log():
    r = dict(drawing_number="12133-GA", log=[
        "Drop-off  Review copy of this pack: C:\\pack\\99999-GA - WRONG",
        "Somebody said 12133-GA - ALSO WRONG",
    ])
    assert not W.display_identity(r)["description"]


def test_existing_explicit_title_wins_and_is_bounded():
    r = dict(job_title="A" * 300, log=["anything"])
    assert W.display_identity(r)["description"] == "A" * 240


def test_presentation_does_not_mutate_run_or_timing():
    r = dict(run_id="r", drawing_number="D-1", status="done", source="tti", units=1,
             engine_price_gbp=100.0, started_at=100, finished_at=200, log=[])
    before = dict(r)
    got = W._summary(r)
    assert r == before and got["seconds"] == 100 and got["engine_price_gbp"] == 100


def test_page_retains_brand_and_discloses_limits():
    page = (ROOT / "sdi-intelligence-backend/sdi-estimating-wall.html").read_text(encoding="utf-8")
    assert 'aria-label="we.are.sdi"' in page and 'class="sdi-dots"' in page
    assert "batch rows not yet submitted are not counted" in page
    assert "not the full batch backlog" in page and "No automatic retry" in page
    assert "No operational alerts reported. Estimate review status is shown separately." in page
    assert "No open items reported" in page and "quotation approval" in page
