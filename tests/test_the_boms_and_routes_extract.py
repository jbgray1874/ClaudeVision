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


def _record(route_key: str = "canonical_route_shadow", nested: bool = True,
            costed: bool = True) -> dict:
    """A 7332-01-shaped record. COSTED BY DEFAULT, because the real one was: a full estimate
    ran, the workbook was read back, and the route was projected onto priced rows. The tests
    below that talk about a `charged` column are testing that case, and it only exists when a
    price does. Pass costed=False for the pack-read case the new buttons produce."""
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
    if costed:
        _es = record.setdefault("estimate_summary", {})
        _es["final_estimate"] = {"totals": {"unit_gbp": 80.34, "material_gbp": 40.89,
                                            "labour_gbp": 33.83}}
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


# ── which read produced this, and the column that must not lie about it ───────────────
#
# THE ASK THAT MADE THIS NECESSARY. The estimating team want BOMs and routes out of a pack
# WITHOUT a costed run, so the same extract now has three possible sources: a costed run's
# saved record, a full read of the drawings with no pricing, and a vision-model-only first
# look. They produce the same shaped tables and they are not interchangeable, and the trap is
# one column: "charged". On a pack nobody priced, a column of "charged: no" against every row
# reads as "this pack needs no work" — the opposite of what the route actually decided.


def test_a_costed_record_says_so_and_its_charged_column_means_money():
    d = bre.source_declaration(_record())
    assert d["source"] == "costed_run"
    assert d["charged_is_meaningful"] is True
    assert d["operation_column"] == "charged"
    row = [r for r in bre.route_sheet(_record()) if r["operation"] == "tubebend"][0]
    assert row["charged"] == "yes"


def test_an_uncosted_pack_read_never_offers_a_charged_column():
    """The column is RENAMED, not blanked. A blank would be a missing fact; the fact is real
    and is about the route, not about money."""
    record = _record(costed=False)
    d = bre.source_declaration(record)
    assert d["source"] == "pack_read"
    assert d["charged_is_meaningful"] is False
    assert d["operation_column"] == "required by the route"
    row = [r for r in bre.route_sheet(record) if r["operation"] == "tubebend"][0]
    assert "charged" not in row, "the word must not appear as a column on an uncosted read"
    assert row["required by the route"] == "yes"
    assert "Nothing here is charged" in row["what_that_status_means"]
    assert "was not costed" in row["what_that_status_means"]


def test_a_vision_only_read_is_its_own_source_and_says_it_is_uncorroborated():
    record = _record(costed=False)
    record["llm_only"] = True
    d = bre.source_declaration(record)
    assert d["source"] == "fast_read"
    assert d["charged_is_meaningful"] is False
    assert "VISION MODEL ALONE" in d["meaning"]
    assert "not a basis for quoting" in d["meaning"]


def test_llm_only_beats_costed_because_the_weaker_read_is_the_honest_one():
    """A record can carry both marks — an --llm-only run still writes totals. The reader has
    to be told the BOM came from one source, which is the fact that limits everything else."""
    record = _record(costed=True)
    record["llm_only"] = True
    assert bre.source_declaration(record)["source"] == "fast_read"


def test_the_source_is_derived_from_the_record_not_passed_in():
    """A caller that labels its own output can label it wrongly, and 'this was costed' is the
    mislabel a hurried caller reaches for."""
    import inspect
    sig = inspect.signature(bre.source_declaration)
    assert list(sig.parameters) == ["summary"], "no source parameter to get wrong"


def test_an_archived_record_with_totals_but_no_money_provenance_is_still_costed():
    """money_provenance is newer than the archive. Absence of the block is not evidence the
    run was never costed, and downgrading those records would misreport twenty-three of them."""
    record = _record(costed=True)
    record.pop("money_provenance", None)
    assert bre.source_declaration(record)["source"] == "costed_run"


def test_the_yes_no_column_keeps_its_colour_under_either_name(tmp_path):
    """Styling was keyed on the literal string "charged", so the colour vanished on exactly
    the outputs the new buttons produce — where telling a required operation from a ruled-out
    one at a glance is the point of the sheet."""
    path = bre.write_html(_record(costed=False), tmp_path, "7332-01", "routes")
    text = path.read_text(encoding="utf-8")
    assert "class='yes'>yes" in text
    assert "class='no'>no" in text


def test_a_workbook_labour_row_is_proof_the_pack_was_costed():
    """SHIPPED WRONG, AND CAUGHT ON THE OUTPUT. 7332-01's 14:17 run priced at GBP 80.34 a unit,
    and its BOMs & Routes tab said of every operation: "Nothing here is charged — this pack was
    not costed."

    A TIMING BOUNDARY, not a logic error. wb_populate writes that tab WHILE it builds the
    estimate workbook. final_estimate.totals is written back afterwards, once Excel has
    calculated — so at the moment the tab is written the totals do not exist yet, and asking for
    them can only ever answer no.

    workbook_labour.rows DOES exist at that moment: the same tab reads it to fill the "sheet
    row" column, and on that run it resolved decisions to rows 96 to 107. A workbook labour row
    is not a hint that costing might happen — it is a line the workbook charges, carrying its
    own row number.
    """
    mid_run = {
        "job_number": "7332-01",
        "workbook_labour": {"rows": [{"workbook_row": 103, "part_numbers": ["7332-01-002"],
                                      "decision_ids": ["dC"], "wb_operation": "Tubebend"}]},
        "estimate_summary": {"canonical_route_shadow": {"decisions": [
            {"decision_id": "dC", "target_id": "7332-01-002", "operation": "tubebend",
             "status": "required", "scope": "part", "participants": ["7332-01-002"]}]}},
    }
    assert "final_estimate" not in mid_run["estimate_summary"], \
        "the point of this fixture is that the read-back has NOT happened yet"
    declared = bre.source_declaration(mid_run)
    assert declared["source"] == "costed_run"
    assert declared["operation_column"] == "charged"
    row = bre.route_sheet(mid_run)[0]
    assert row["charged"] == "yes"
    assert "not costed" not in row["what_that_status_means"], \
        "the sentence that shipped on a costed pack"


def test_a_pack_with_no_workbook_rows_is_still_a_pack_read():
    """The guard on the guard. If any record at all counted as costed, the distinction the
    whole source declaration exists for would be gone."""
    pack = {"estimate_summary": {"canonical_route_shadow": {"decisions": [
        {"decision_id": "d1", "target_id": "X", "operation": "folding", "status": "required"}]}}}
    assert bre.source_declaration(pack)["source"] == "pack_read"
    for empty in ({}, {"rows": []}, {"rows": None}):
        assert bre.source_declaration(dict(pack, workbook_labour=empty))["source"] == "pack_read"


# ── nothing is lost between the read and the sheet ────────────────────────────────────
#
# "we should retain the data in the required list that is kept in memory. we shouldn't be losing
#  key data at any point ... we need to retain all the information that is needed start to finish
#  to eliminate errors."


def _merged(second: dict) -> dict:
    """One line read by the table parser, then read again by another reader."""
    import file_scan as fs
    from extractor_patterns import extract_bom_rows
    table = extract_bom_rows("1 7332-01-002 LEG 2\n", source_page=3)[0]
    other = dict(table)
    other.update(second)
    winner = dict(table)
    fs._merge_bom_rows(winner, other)
    return winner


def test_every_reading_survives_the_merge_whole():
    """Not the winner plus a note. The generic record merge keeps the winner's value and turns
    the loser's into prose, so a row read twice came out looking read once and a contradicted
    quantity survived only as a sentence nothing could act on."""
    row = _merged({"source": "vision", "source_page": 7, "quantity": 4})
    readings = row["readings"]
    assert len(readings) == 2
    assert {r["source"] for r in readings} == {"bom_table", "vision"}
    assert sorted(r["quantity"] for r in readings) == [2, 4], "both values are still there"
    assert {r["source_page"] for r in readings} == {3, 7}


def test_the_arbitrated_value_still_stands_on_the_row():
    """Precedence is unchanged — every existing consumer reads the row, not the readings. The
    readings are additional evidence, not a replacement for the decision."""
    row = _merged({"source": "vision", "source_page": 7, "quantity": 4})
    assert row["quantity"] == 2, "the winner's reading is still the row's value"
    assert row["source"] == "bom_table"


def test_a_disagreement_is_reported_reader_by_reader():
    """The most valuable fact the pipeline produces: if the table read 2 and vision read 4, one
    is wrong and an estimator settles it in seconds FROM THE DRAWING — but only if told."""
    row = _merged({"source": "vision", "source_page": 7, "quantity": 4})
    said = bre.bom_sheet({"document_analysis": {"bom_rows": [row]}})[0]
    assert "quantity" in said["readers_disagree_on"]
    assert "bom_table read '2'" in said["readers_disagree_on"]
    assert "vision read '4'" in said["readers_disagree_on"]
    assert said["times_read"] == 2


def test_agreement_says_nothing():
    """A column that speaks on every row is one nobody reads."""
    row = _merged({"source": "vision", "source_page": 7})
    said = bre.bom_sheet({"document_analysis": {"bom_rows": [row]}})[0]
    assert said["readers_disagree_on"] == ""
    assert said["times_read"] == 2, "still corroborated, just not contested"


def test_a_third_reader_joins_the_same_list_rather_than_replacing_it():
    """Readings accumulate across successive merges — a line on three sheets is three readings,
    not the last two."""
    import file_scan as fs
    row = _merged({"source": "vision", "source_page": 7, "quantity": 4})
    fs._merge_bom_rows(row, {"part_number": "7332-01-002", "description": "LEG",
                             "quantity": 2, "source": "solidworks_api", "source_page": 11})
    assert len(row["readings"]) == 3
    assert {r["source"] for r in row["readings"]} == {"bom_table", "vision", "solidworks_api"}


def test_a_reading_never_contains_the_merge_s_own_bookkeeping():
    """Otherwise one reader's audit trail is reported as another's, and readings nest inside
    readings the next time the row is merged."""
    row = _merged({"source": "vision", "source_page": 7, "quantity": 4})
    for reading in row["readings"]:
        for own in ("readings", "also_read_by", "also_on_pages", "merge_notes"):
            assert own not in reading
