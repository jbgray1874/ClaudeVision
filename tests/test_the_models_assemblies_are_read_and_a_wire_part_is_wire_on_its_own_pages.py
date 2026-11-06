"""12173-02 Card Spinner, 4 Oct 19:37 book on 7c9cd2a (D-390): the first book with the weld,
coat, hand and ruling rules in force — 150 brief facts held, 5 failed, and the report showed
four faults of the engine's own:

* 12173-07-1-GA and 07-2-GA carried no coat: the SolidWorks tree mints them AFTER the sheet
  readers ran, so their own title blocks (POWDER COATED) were never read.
* "welding on this wire part is the wire route's assumption" sat on the MDF spinner plate, the
  MFC back and the screws: the wire test read the WHOLE pack's text, so one hook arm's "MILD
  STEEL WIRE" made every part wire — and gave the sheet bases the flag the Robomac guard
  mistook for evidence (D-388).
* The frames, priced at config.SECTION_STOCK_PRICE_GBP_PER_KG, read "SDI Live" in the BOM
  row's source column — the stamp of the £/kg lookup the branch asked and did not use.
* The source-drawing-data sheet was not written: a mirrored hand's envelope dict reached a cell.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import source_drawing_data as sdd                                     # noqa: E402
import wb_populate as wb                                              # noqa: E402


def test_the_sheet_readers_run_again_over_the_assemblies_the_model_mints():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    first = src.index("_ws_by_part = _ws_read(_ws_pdfs)")
    hier = src.index("[hierarchy] applied to")
    late = src.index("apply_finish_coats as _ws_coats_late")
    assert first < hier < late, "the late read must follow the model's hierarchy"
    # Only the records the first pass did not see, so nothing is read twice.
    assert "not in _ws_seen_pns" in src
    assert "_ws_seen_pns |= " in src


def test_a_part_is_wire_on_its_own_pages_not_the_packs():
    src = (ROOT / "src" / "document_builder.py").read_text(encoding="utf-8")
    assert '"MILD STEEL WIRE" in doc_page_text_upper' not in src
    assert '"MILD STEEL WIRE" in _own_text_upper' in src
    assert '("WIRE" in _own_text_upper and "LOOP" in _own_text_upper)' in src


def test_a_section_on_the_config_hold_does_not_wear_sdi_live():
    pe = {"part_number": "F-04M",
          "material_estimate": {"cost_method": "section_stock_config_rate",
                                "unit_material_cost_gbp": 49.38,
                                "price_source": {"source_name": "sqlserver", "applied": False}}}
    label, guess = wb._price_origin(pe)
    assert label == "SDI config section rate - verify" and guess is False
    pe["material_estimate"]["cost_method"] = "section_stock_flat_rate"
    assert wb._price_origin(pe)[0].startswith("flat-product rate")


def test_a_dict_or_list_in_a_source_data_row_becomes_text(tmp_path):
    assert sdd._cell_value({"length": None, "width": None, "height": 2.0}) == "height: 2.0"
    assert sdd._cell_value([1, None, "a"]) == "1, a"
    assert sdd._cell_value({}) is None and sdd._cell_value(3.5) == 3.5
    tables = {name: [] for name in sdd.SHEETS}
    tables[sdd.SHEETS[0]] = [{"part": "X-02M-H", "envelope": {"length": None, "height": 2.0}}]
    path = sdd.write_source_drawing_data({}, tmp_path, job="X", tables=tables)
    assert path is not None and path.is_file()
