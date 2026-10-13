"""The TTI job carries the Milwaukee mark — mapped in config, never in logic.

"The TTI job should use the Milwaukee logo" — James Gray, 13 Oct 2026. TTI (Techtronic
Industries) is the customer SDI invoices; Milwaukee is the brand on the product and the
mark their documents carry. That is a fact about the CUSTOMER, like their weld-dressing
standard, so it lives in config (CUSTOMER_LOGO_BRANDS) beside CUSTOMER_FINISH_STANDARDS —
and the lookup maps it at the one place a logo file is chosen, so the quote AND the job
report (which borrows the quote's loader) agree.

ONLY THE MARK IS MAPPED. The heading still prints the customer's own name: a quote headed
"Milwaukee" would misstate who is being quoted.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import client_quote_html as q                                          # noqa: E402
import config                                                          # noqa: E402

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40">'
        '<rect width="100" height="40" fill="#d2042d"/></svg>')


def _logos_dir(tmp_path, monkeypatch, *stems):
    d = tmp_path / "logos"
    d.mkdir()
    for stem in stems:
        (d / f"{stem}.svg").write_text(_SVG, encoding="utf-8")
    monkeypatch.setattr(q, "ASSETS_LOGOS", str(d))
    return d


def test_the_mapped_customer_takes_its_brands_file(tmp_path, monkeypatch):
    """TTI finds Milwaukee.svg although no TTI.* exists — the config row does the mapping."""
    _logos_dir(tmp_path, monkeypatch, "Milwaukee")
    markup = q._load_logo_markup("TTI")
    assert "<svg" in markup


def test_the_mapping_is_the_config_table_not_a_rule_in_code():
    assert config.CUSTOMER_LOGO_BRANDS.get("TTI") == "Milwaukee"


def test_the_map_matches_normalised_spellings(tmp_path, monkeypatch):
    """'T.T.I.' and 'tti' are one customer, the way every other customer table matches."""
    _logos_dir(tmp_path, monkeypatch, "Milwaukee")
    assert "<svg" in q._load_logo_markup("T.T.I.")
    assert "<svg" in q._load_logo_markup("tti")


def test_an_unmapped_customer_keeps_todays_behaviour(tmp_path, monkeypatch):
    """A customer not in the table still finds its own file, and nothing else."""
    _logos_dir(tmp_path, monkeypatch, "Harrods")
    assert "<svg" in q._load_logo_markup("Harrods")
    assert q._load_logo_markup("Dyson") == ""


def test_the_customers_own_file_is_not_found_once_mapped(tmp_path, monkeypatch):
    """The map REPLACES the key: with a mapping in place, a stale TTI.* file cannot race the
    brand's file — the lookup asks only for Milwaukee."""
    _logos_dir(tmp_path, monkeypatch, "TTI")                 # only the customer-named file
    assert q._load_logo_markup("TTI") == ""                  # the map points at Milwaukee.*


def test_the_heading_name_is_not_what_the_map_changes():
    """The map lives in the logo loader; the display name goes through _clean_customer_name,
    which leaves 'TTI' exactly as it is."""
    assert q._clean_customer_name("TTI") == "TTI"
