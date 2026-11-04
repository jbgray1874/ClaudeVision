"""One quote names one board one way, and never presents a short bill as the product (D-675).

12203-65-GA, 4 Nov 09:55 quote:
  * the first page said "Material | Mdf" and "...Rev A. Mdf." while the pages after it said
    "MDF": the price page titled the word itself (client_quote_html._title_material) and the
    story kept a board's initials (quote_story._name_case, D-668). One rule now names it;
  * the story said "0 parts SDI makes", "No made parts — every line is bought in" and "0 made
    parts sized from your drawings" while the box's five panels sat in the pack, recognised and
    set aside as not linked to the product. A count of a short bill is not a fact about the
    product: the lines drawn and not costed are named, and every count says it is so far.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("SDI_OFFLINE", "1")

import client_quote_html                                               # noqa: E402
import quote_story                                                     # noqa: E402
import test_the_quote_shows_how_it_was_read_and_priced as base        # noqa: E402

PANELS = [f"BOX-01J-0{n}" for n in range(1, 6)]


def _text(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_the_price_page_and_the_story_name_a_board_the_same_way():
    assert client_quote_html._title_material("MDF") == "MDF"
    assert client_quote_html._title_material("MILD_STEEL") == "Mild Steel"
    assert client_quote_html._title_material("MFMDF") == "MFMDF"
    assert client_quote_html._title_material("STAINLESS STEEL") == "Stainless Steel"
    assert client_quote_html._title_material("MDF") == quote_story._material_name(
        {"normalized_material": "MDF"})


def test_the_first_page_says_mdf(tmp_path):
    summary = base._summary(tmp_path)
    for p in summary["estimate_summary"]["canonical_part_estimates"]:
        if p.get("normalized_material"):
            p["normalized_material"] = "MDF"
    html = client_quote_html.build_quote_html(summary, job_stem="UNIT-GA",
                                              customer="Acme Retail")
    first = _text(html.split('<div class="sheet qs">')[0])
    assert "MDF" in first and "Mdf" not in first
    assert "Mdf" not in _text(html), "nor anywhere after the price page"


def _short_bill(tmp_path):
    summary = base._summary(tmp_path)
    parts = [p for p in summary["estimate_summary"]["canonical_part_estimates"]
             if p.get("concept_kind") == "bought_in" or p.get("_commercial_placeholder")]
    summary["estimate_summary"]["canonical_part_estimates"] = parts
    summary["set_aside_outside_product"] = [
        {"part_number": pn, "description": "BOX PANEL", "root": "",
         "reason": "not_linked_to_the_product"} for pn in PANELS]
    return summary, parts


def test_a_short_bill_is_not_called_the_product(tmp_path):
    summary, parts = _short_bill(tmp_path)
    facts = quote_story.job_facts(summary, parts, 50)
    assert facts["not_costed"] == PANELS
    items = {i["topic"]: i for i in quote_story.evidence_items(summary, facts)}
    assert items["parts"]["concluded"].startswith("Not complete: 5 lines drawn in your pack")
    assert "BOX-01J-01" in items["parts"]["concluded"]
    assert "No made parts" not in items["material"]["concluded"]
    assert items["material"]["concluded"].startswith("Not complete")


def test_every_count_on_the_story_pages_says_so_far(tmp_path):
    summary, parts = _short_bill(tmp_path)
    _css, html = base._pages(summary)
    text = _text(html)
    assert "No made parts" not in text
    assert "0 parts SDI makes, 1 bought in so far; 5 more drawn in your pack" in text
    assert "5 more drawn lines not yet costed" in text


def test_a_lines_set_aside_as_another_products_are_not_called_missing(tmp_path):
    """A line from another GA in the pack is not this product's; it is not 'not yet costed'."""
    summary, parts = _short_bill(tmp_path)
    for e in summary["set_aside_outside_product"]:
        e["reason"] = "outside_the_product"
    facts = quote_story.job_facts(summary, parts, 50)
    assert facts["not_costed"] == []


def test_a_complete_bill_reads_as_before(tmp_path):
    summary = base._summary(tmp_path)
    _css, html = base._pages(summary)
    text = _text(html)
    assert "Not complete" not in text and "so far" not in text
