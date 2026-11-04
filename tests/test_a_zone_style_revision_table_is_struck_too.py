"""A revision table headed ZONE / REV. / CN / REASON is struck like any other (D-690).

12693-01's sheets head their revision table "REVISIONS" over "ZONE REV. CN REASON DATE
APPROVED ON APPROVED BY", with rows like "A // INITIAL DESIGN 30/09/2026 27/10/2026 EXT": a
change number of "//" and two dates before the initials. The stripper knew the "REV DRG NO
DESCRIPTION DATE" style only, and ran only once a row had been parsed, so on this style
nothing was struck and every labelled field ran on into the table:

    12693-01-04J   material "MRMDF REVISIONS", finish "/ ZONE REV. CN REASON"
    12693-01-03M   finish "SEE WELDMENT ZONE REV. CN REASON"
    12693-01-GA    revision read as "S", colour carrying the row "A // INITIAL DESIGN ..."

The insert's colour field, which names the board's decor, never reached the record clean,
and the decor is what the catalogue files the board under.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from extractor_patterns import (REVISION_TABLE_STOP, extract_title_block_fields,  # noqa: E402
                                parse_revision_table, strip_revision_table)

INSERT = """MATERIAL: MRMDF REVISIONS
FINISH: / ZONE REV. CN REASON DATE APPROVED ON APPROVED BY
COLOUR: EGGER U999 ST2 A // INITIAL DESIGN 30/09/2026 27/10/2026 EXT
GENERAL TOLERANCES:"""

STEEL = """MATERIAL: MILD STEEL REVISIONS
FINISH: SEE WELDMENT ZONE REV. CN REASON DATE APPROVED ON APPROVED BY
COLOUR: SEE WELDMENT A // INITIAL DESIGN 30/09/2026 27/10/2026 EXT"""


def test_the_row_is_read_as_history():
    rows = parse_revision_table(INSERT)["rows"]
    assert rows == [{"rev": "A", "number": "", "description": "INITIAL DESIGN",
                     "date": "30/09/2026", "by": "EXT"}]


def test_the_insert_fields_end_where_the_table_begins():
    f = extract_title_block_fields(INSERT)
    assert f["materials"] == ["MRMDF"]
    assert f["colours"] == ["EGGER U999 ST2"]
    assert all("ZONE" not in x and "REASON" not in x for x in f["surface_finishes"])


def test_a_steel_parts_finish_is_its_own_words():
    f = extract_title_block_fields(STEEL)
    assert f["surface_finishes"] == ["SEE WELDMENT"]
    assert f["colours"] == ["SEE WELDMENT"]


def test_the_header_alone_is_struck_when_no_row_is_read():
    """A row in a style not yet known must not let the field run on into the header."""
    text = "FINISH: POWDER COAT ZONE REV. CN REASON DATE APPROVED ON APPROVED BY"
    f = extract_title_block_fields(text)
    assert len(f["surface_finishes"]) == 1
    assert f["surface_finishes"][0].startswith("POWDER COAT")
    assert "ZONE" not in f["surface_finishes"][0] and "REASON" not in f["surface_finishes"][0]


def test_the_word_revisions_is_kept_where_no_such_table_is_on_the_page():
    text = "NOTE: ALL REVISIONS TO BE AGREED"
    assert strip_revision_table(text) == text


def test_the_older_style_is_still_struck():
    text = "MATERIAL: STEEL REV DWG NO DESCRIPTION DATE BY FINISH: POWDER COATED"
    assert REVISION_TABLE_STOP in strip_revision_table(text)
