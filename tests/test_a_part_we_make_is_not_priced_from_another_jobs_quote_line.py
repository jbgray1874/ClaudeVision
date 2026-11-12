"""A weak historical match is not an authoritative price for something SDI makes (12 Nov 2026).

6364-02's bin took £569.92 from a 50% word match to a different drawing's "BIN SLOPE", with the
bin's own components and labour charged beside it. 12674-01-GA's panels took £1,009 and £1,890
from other jobs' quote lines. The historical lookup matches words; it stays for what SDI buys."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pricing_service as ps  # noqa: E402


class _Svc:
    """The price chain with every arm stubbed: only the order and the gate are under test."""
    _select_anchor_price_source = ps.PricingService._select_anchor_price_source

    def __init__(self):
        self.asked = []
        self._web_ai_calls = 0

    def _get_udef_anchor(self, part): return None
    def _is_sighted_line(self, part): return False
    def _get_pma_purchased(self, part): return None
    def _get_bought_in_part(self, part): return None
    def _get_supplier_catalog(self, part): return None
    def _is_bought_in_heuristic(self, part): return False
    def _web_ai_fallback_allowed(self, part, policy): return False

    def _get_historical_rag(self, part):
        self.asked.append(part.get("part_number"))
        return {"source": "historical_quote_material_line", "unit_price_gbp": 569.92,
                "token_overlap_score": 0.5}


def test_a_drawn_part_of_the_job_takes_no_historical_quote_price(capsys):
    got = _Svc()._select_anchor_price_source({"part_number": "6364-02-011", "description": "BIN"})
    assert got["source"] != "historical_quote_material_line" and not got["unit_price_gbp"]
    assert "NOT used" in capsys.readouterr().out


def test_a_cut_part_and_an_assembly_take_none_either():
    for part in ({"part_number": "11896-04-01-01M", "description": "BACK PANEL"},
                 {"part_number": "12674-01-01J", "description": "TOP PANEL"},
                 {"part_number": "X", "description": "FRAME", "assembly_children": ["A", "B"]},
                 {"part_number": "X2", "description": "PLATE", "native_flat_pattern": True}):
        assert _Svc()._select_anchor_price_source(part)["source"] != "historical_quote_material_line", part


def test_something_we_buy_still_takes_its_historical_price():
    for part in ({"part_number": "HAFELE: 637.30.941", "description": "ADJUSTABLE FOOT"},
                 {"part_number": "GGC-10-401", "description": "CORNER GUARD"},
                 {"part_number": "FIXING308", "description": "M6 CONNECTOR BOLT"},
                 {"part_number": "12736-01-04X", "description": "EU INTERNAL DOOR"},
                 {"part_number": "6364-02-011", "description": "BIN", "_estimator_make_or_buy": "buy"}):
        assert _Svc()._select_anchor_price_source(part)["source"] == "historical_quote_material_line", part


def test_the_reason_names_what_makes_it_ours():
    assert "job number" in ps.made_here_reason({"part_number": "12773-02-103"})
    assert "material letter" in ps.made_here_reason({"part_number": "11896-04-01-01M"})
    assert ps.made_here_reason({"part_number": "M6 CONNECTOR BOLT"}) == ""
    assert ps.made_here_reason({"part_number": "PACKAGING"}) == ""


# ── an abandoned lookup is counted, not silent (6364-01 14:30, 12 Nov 2026) ─────────────────
class _TimesOut:
    def cursor(self):
        raise TimeoutError("Query timeout expired")


def _svc_that_times_out():
    svc = ps.PricingService.__new__(ps.PricingService)
    svc.conn = _TimesOut()
    svc._connection_factory = lambda: _TimesOut()
    svc.lookup_failures = []
    svc._is_connection_error = lambda exc: False
    svc._is_query_timeout = lambda exc: True
    return svc


def test_a_lookup_that_times_out_is_counted_by_table():
    svc = _svc_that_times_out()
    assert svc._fetch_all_with_retry("SELECT x FROM dbo.historical_quote_material_line hml WHERE y LIKE ?", ["a"]) == []
    assert svc._fetch_one_with_retry("SELECT TOP 1 p FROM [dbo].[bought_in_parts] WHERE c = ?", ["a"]) is None
    assert svc._fetch_all_with_retry("SELECT x FROM dbo.historical_quote_material_line WHERE y LIKE ?", ["b"]) == []
    got = svc.lookup_failure_summary()
    assert got["count"] == 3
    assert got["by_table"] == {"dbo.historical_quote_material_line": 2, "dbo].[bought_in_parts": 1} \
        or got["by_table"]["dbo.historical_quote_material_line"] == 2
    assert "3 price lookup(s) were abandoned" in got["says"] and "Run it again" in got["says"]


def test_a_run_with_no_abandoned_lookup_says_nothing():
    svc = _svc_that_times_out()
    assert svc.lookup_failure_summary() == {"count": 0, "by_table": {}, "says": ""}


def test_the_record_carries_the_count():
    src = (Path(__file__).resolve().parents[1] / "src" / "estimator.py").read_text(encoding="utf-8")
    assert '"lookups_abandoned": _lookups_abandoned()' in src


def test_a_weldments_cut_list_item_is_ours_too():
    for code in ("6364-02-004-01", "6364-02-004-5MM", "6364-02-016-INNER-01", "6364-02-011"):
        assert _Svc()._select_anchor_price_source({"part_number": code, "description": "BIN SLOPE"})["source"] \
            != "historical_quote_material_line", code
    for code in ("MCCUE: GGC-10-401", "FIXING-MINIFIX-S100-FIXINGS-262.28", "P/P", "HARRISON: 86.7638"):
        assert ps.made_here_reason({"part_number": code}) == "", code
