"""A map that drifts from the territory is worse than no map — it gets believed.

    "these files need to be in the SDI Estimating Intelligence architecture page so that
     data / knowledge is not lost"                        — James Gray, SDI, 15 Sep 2026

docs/KNOWLEDGE_SOURCES.md is the one page answering "where does SDI's build-and-price
knowledge live". This holds it in step with the code: every register the engine actually
reads is named on the page, and the page names no register that has ceased to exist.

Deliberately shallow — it checks NAMES appear, not prose. Prose ages honestly; a register
the map has never heard of is the failure worth stopping.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

MAP = open(os.path.join(os.path.dirname(__file__), "..", "docs", "KNOWLEDGE_SOURCES.md"),
           encoding="utf-8").read()

# The registers an estimator would go looking for. A new one is added HERE and to the map
# in the same commit — that is the whole contract.
REGISTERS = (
    "SHOP_STATED", "ESTIMATOR_STATED_PRICES", "ROLL_GOODS_CATALOGUE",
    "PER_ORDER_UNIT_COUNTS", "ACRYLIC_PRICE_GBP_PER_M2", "BOARD_SHEET_PRICE_GBP",
    "MATERIAL_PRICE_GBP_PER_KG", "DIRECTIONAL_FINISH_TOKENS", "MATERIAL_PRICE_BREAK",
    "PRICE_SOURCE_CONFIG", "WELD_TIME_MODEL", "ACRYLIC_OP_DRIVERS",
)


def test_every_register_the_engine_reads_is_on_the_map():
    import config
    for name in REGISTERS:
        assert hasattr(config, name), f"{name} has left config — take it off the map " \
                                      f"or say where it went"
        assert name in MAP, f"{name} exists and the map does not name it"


def test_the_data_overlays_are_on_the_map():
    for name in ("rate_card.json", "batch_ingest_historical", "BoughtInCatalogue",
                 "JobBoughtInMaterials", "UDEF_PARTS_TABLE_FOR_ESTIMATING",
                 "_THROUGHPUT_DEFAULTS"):
        assert name in MAP, name


def test_the_registers_that_live_outside_config_are_mapped_where_they_live():
    """CELL_MAP and the throughput table are wb_populate's — the map must name them, and
    this must not pretend they are config's."""
    import wb_populate
    assert hasattr(wb_populate, "CELL_MAP")
    assert "CELL_MAP" in MAP


def test_the_map_states_the_two_rules_that_matter():
    assert "asked first" in MAP, "the system outranks a stated figure"
    assert "can't hard code prices" in MAP, "James's rule, quoted, dated"


def test_the_map_does_not_promise_a_live_spreadsheet_connector():
    """It points at the blank template and contributes nothing; the map must say so
    rather than list it as a working source — a listed source that answers nothing is
    exactly how knowledge gets lost while everyone believes it is held."""
    assert "blank" in MAP and "contributes nothing" in MAP
