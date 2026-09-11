"""The two questions that come before a price: what parts, and what work.

The estimate answers "what does it cost". Before anybody can trust that, these have to be
answerable on their own — and they were not reachable without opening a costed workbook.

THE DEFECT FOUND WHILE BUILDING THIS. source_drawing_data.operation_rows read the route from
`estimate_summary.canonical_route` only. Every real run writes it to `canonical_route_shadow` —
v0013 of 7332-01 carries 27 decisions there — so the Operations sheet of the extraction audit
came back EMPTY on every real job and read as "this pack states no operations". That is the worst
way for a route to be missing: indistinguishable from a pack that genuinely has none.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bom_and_route_extract as bre                                      # noqa: E402
import source_drawing_data as sdd                                        # noqa: E402


def _record(route_key: str = "canonical_route_shadow", nested: bool = True) -> dict:
    decisions = [
        {"decision_id": "d1", "target_id": "7332-01-002", "operation": "tubebend",
         "status": "required", "scope": "part", "participants": ["7332-01-002"],
         "reason": "the leg is bent from tube"},
        {"decision_id": "d2", "target_id": "7332-01-002", "operation": "folding",
         "status": "not_applicable", "scope": "part", "participants": ["7332-01-002"],
         "reason": "not possible on stock form 'tube'"},
        {"decision_id": "d3", "target_id": "7332-01", "operation": "welding",
         "status": "required", "scope": "assembly",
         "participants": ["7332-01-002", "7332-01-007"], "reason": "a welded frame"},
    ]
    route = {route_key: {"decisions": decisions}}
    record = {
        "job_number": "7332-01",
        "document_analysis": {"bom_rows": [
            {"part_number": "7332-01-002", "description": "Leg, tube", "quantity": 2,
             "material_text": "Steel, Mild Tube 25x25x2", "source_page": 3,
             "source": "bom_table"},
            {"part_number": "7332-01-002", "description": "Leg, tube", "quantity": 2,
             "material_text": "MS TUBE", "source_page": 7, "source": "vision"},
            {"part_number": "7332-01-007", "description": "Lens", "quantity": 1,
             "material_text": "Acrylic 3mm", "source_page": 4, "source": "solidworks_api"}]},
    }
    if nested:
        record["estimate_summary"] = dict(route)
    else:
        record.update(route)
    return record


# ── the route is found wherever it is written ──────────────────────────────────────────


@pytest.mark.parametrize("key", ["canonical_route_shadow", "canonical_route"])
@pytest.mark.parametrize("nested", [True, False])
def test_the_route_is_read_under_either_spelling_and_either_nesting(key, nested):
    """Reading one was a silent hole: the audit's Operations sheet was empty on every real job."""
    rows = bre.route_sheet(_record(key, nested))
    assert len(rows) == 3, f"{key} nested={nested}"


def test_the_audit_operations_sheet_is_no_longer_empty_on_a_real_shaped_record():
    """THE REGRESSION THIS CLOSES, asserted on the audit itself and not only on the new module."""
    assert len(sdd.operation_rows(_record("canonical_route_shadow"))) == 3


def test_one_decision_found_under_both_spellings_is_not_duplicated():
    record = _record("canonical_route_shadow")
    record["canonical_route"] = record["estimate_summary"]["canonical_route_shadow"]
    assert len(bre.route_sheet(record)) == 3


def test_an_absent_route_gives_no_rows_rather_than_raising():
    assert bre.route_sheet({"job_number": "x"}) == []
    assert bre.bom_sheet({"job_number": "x"}) == []


# ── what the sheets say, and what they refuse to say ──────────────────────────────────


def test_only_a_required_decision_is_marked_charged():
    rows = {(r["part_or_assembly"], r["operation"]): r for r in bre.route_sheet(_record())}
    assert rows[("7332-01-002", "tubebend")]["charged"] == "yes"
    assert rows[("7332-01-002", "folding")]["charged"] == "no"
    assert "not possible on stock form" in rows[("7332-01-002", "folding")]["why"]


def test_every_status_carries_its_meaning_in_words():
    """"unverified" is neither charged nor ruled out, and a sheet that prints the bare word
    leaves the reader to guess which."""
    for row in bre.route_sheet(_record()):
        assert row["what_that_status_means"], row
    assert "a person should rule on it" in bre.STATUS_MEANING["unverified"]
    assert "NOT charged" in bre.STATUS_MEANING["unverified"]


def test_an_unrecognised_status_is_not_silently_treated_as_charged():
    record = _record()
    record["estimate_summary"]["canonical_route_shadow"]["decisions"][0]["status"] = "peculiar"
    # route_sheet SORTS, so index 0 is not the row just edited — find it by identity.
    row = [r for r in bre.route_sheet(record) if r["operation"] == "tubebend"][0]
    assert row["status"] == "peculiar"
    assert row["charged"] == "no", "only `required` is charged; anything else is not"
    assert "not recognised" in row["what_that_status_means"]


def test_an_assembly_decision_names_every_part_it_covers():
    """A weld is not three welds because three parts meet. Dividing a setup between its
    participants is what makes one setup look like three."""
    row = [r for r in bre.route_sheet(_record()) if r["operation"] == "welding"][0]
    assert row["scope"] == "assembly"
    assert "7332-01-002" in row["covers_parts"] and "7332-01-007" in row["covers_parts"]


def test_a_duplicated_part_number_is_flagged_and_never_merged():
    """Most SDI parts appear on several sheets of one pack. Merging here would hide the very
    question an estimator has to rule on, and adding the quantities would be worse."""
    rows = bre.bom_sheet(_record())
    legs = [r for r in rows if r["part_number"] == "7332-01-002"]
    assert len(legs) == 2, "both rows survive"
    assert all(r["appears_on_n_rows"] == 2 for r in legs)
    assert "NOT a quantity to add up" in legs[0]["duplicate_note"]
    single = [r for r in rows if r["part_number"] == "7332-01-007"][0]
    assert single["duplicate_note"] == ""


def test_each_bom_row_says_which_reader_produced_it_and_what_that_means():
    rows = {r["read_by"]: r for r in bre.bom_sheet(_record())}
    assert "table parser" in rows["bom_table"]["what_that_reader_is"]
    assert "IMAGE" in rows["vision"]["what_that_reader_is"]
    assert "designer's structure" in rows["solidworks_api"]["what_that_reader_is"]


def test_an_unknown_reader_is_reported_as_itself_not_mapped_to_a_guess():
    record = _record()
    record["document_analysis"]["bom_rows"][0]["source"] = "some_new_reader"
    row = bre.bom_sheet(record)[0]
    assert "some_new_reader" in row["what_that_reader_is"]


def test_the_material_is_carried_as_printed_never_normalised():
    rows = bre.bom_sheet(_record())
    assert rows[0]["material_as_printed"] == "Steel, Mild Tube 25x25x2"
    assert rows[1]["material_as_printed"] == "MS TUBE", "the second reader's wording is kept too"


# ── the derivation sheet ──────────────────────────────────────────────────────────────


def test_every_derivation_row_says_what_the_value_does_NOT_mean():
    """The column that earns its place. Every figure on a sheet like this gets quoted eventually,
    and the quickest way to be misquoted is to publish a number with no statement of its limits."""
    rows = bre.derivation_sheet(_record())
    assert rows
    for row in rows:
        assert row["what_it_does_not_mean"], row
        assert row["derived_from"], row


def test_the_quantity_derivation_warns_it_is_not_rolled_through_the_assembly():
    row = [r for r in bre.derivation_sheet(_record()) if r["column"] == "quantity"][0]
    assert "NOT the job quantity" in row["what_it_does_not_mean"]
    assert "12 parts" in row["what_it_does_not_mean"], "with the arithmetic spelled out"


def test_the_derivation_names_where_the_route_was_actually_found():
    row = [r for r in bre.derivation_sheet(_record()) if r["column"] == "operation"][0]
    assert "canonical_route_shadow" in row["derived_from"]


# ── the three buttons, one builder ────────────────────────────────────────────────────


@pytest.mark.parametrize("want,expect", [
    ("boms", {"BOMs"}), ("routes", {"Routes"}), ("both", {"BOMs", "Routes"})])
def test_each_button_builds_only_its_own_subject(want, expect):
    tables = bre.build_tables(_record(), want)
    assert expect <= set(tables)
    assert "How these were derived" in tables, "every extract explains itself"
    assert (set(tables) - {"How these were derived"}) == expect


def test_the_derivation_sheet_is_filtered_to_the_subject_asked_for():
    boms = bre.build_tables(_record(), "boms")["How these were derived"]
    assert {r["sheet"] for r in boms} == {"BOMs"}


# ── the files ─────────────────────────────────────────────────────────────────────────


def test_both_outputs_are_written_from_one_snapshot(tmp_path):
    """So the sheet estimating works from and the page everyone else reads cannot disagree."""
    result = bre.write_both(_record(), tmp_path, "7332-01", "both")
    assert result["xlsx"] and Path(result["xlsx"]).is_file()
    assert result["html"] and Path(result["html"]).is_file()
    assert result["boms"] == 3 and result["routes"] == 3


def test_the_workbook_has_one_sheet_per_subject(tmp_path):
    import openpyxl
    path = bre.write_workbook(_record(), tmp_path, "7332-01", "both")
    book = openpyxl.load_workbook(path)
    assert book.sheetnames == ["BOMs", "Routes", "How these were derived"]
    assert book["Routes"].freeze_panes == "A2", "headers stay visible while scrolling"


def test_the_filename_says_which_extract_it_is(tmp_path):
    for want, suffix in (("boms", "_boms"), ("routes", "_routes"),
                         ("both", "_boms_and_routes")):
        path = bre.write_workbook(_record(), tmp_path, "7332-01", want)
        assert path.name == f"7332-01{suffix}.xlsx"


def test_the_page_escapes_everything_it_prints(tmp_path):
    """Every value here came out of a drawing. A description containing markup must render as
    text, whether or not today's packs happen to contain any."""
    record = _record()
    record["document_analysis"]["bom_rows"][0]["description"] = "<script>alert(1)</script>"
    path = bre.write_html(record, tmp_path, "7332-01", "boms")
    text = path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_the_page_marks_charged_and_uncharged_differently(tmp_path):
    path = bre.write_html(_record(), tmp_path, "7332-01", "routes")
    text = path.read_text(encoding="utf-8")
    assert "class='yes'>yes" in text
    assert "class='no'>no" in text


def test_an_empty_record_still_produces_both_files_saying_so(tmp_path):
    """An extract that writes nothing when a pack yielded nothing is indistinguishable from an
    extract that failed."""
    result = bre.write_both({"job_number": "empty"}, tmp_path, "empty", "both")
    assert result["xlsx"] and result["html"]
    text = Path(result["html"]).read_text(encoding="utf-8")
    assert "Nothing in this record" in text
    assert "a fact about the record, not about the pack" in text


@pytest.mark.parametrize("broken", [None, [], "not a record", 7, {"pages": "wrong type"}])
def test_a_malformed_record_never_raises_into_the_page(broken, tmp_path):
    """It is launched from the estimating page; it must never be the reason that page errors."""
    try:
        bre.write_both(broken if isinstance(broken, dict) else {}, tmp_path, "x", "both")
    except Exception as err:                                             # noqa: BLE001
        pytest.fail(f"raised into the caller: {type(err).__name__}: {err}")


def test_the_page_states_that_it_prices_nothing(tmp_path):
    """So a figure from it is never quoted as a cost."""
    path = bre.write_html(_record(), tmp_path, "7332-01", "both")
    text = path.read_text(encoding="utf-8")
    assert "prices nothing" in text
    assert "no figure on this page is a cost" in text
