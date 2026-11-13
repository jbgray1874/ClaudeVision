"""ONE PACK AND THE VERSIONS KEPT OF IT ARE ONE PACK (JG, 13 Nov 2026).

Three rows of the Live Enquiry sheet were held on the evening of 13 November with "2 folders
fit: X, X v2 - leave one". The second folder was the pack store's own: when the design share's
pack changes, src/pack_store.py files the new one beside the old as "X v2" so nothing is lost.
The next read of the sheet then met two folders for the drawing and stopped, and the only way
on was to delete a version that was kept on purpose.

The folder to price is now chosen and said, and nothing is deleted:
  * a folder a person made (no pack manifest of ours, drawings in it) is the pack (10 Nov rule);
  * otherwise the newest version the store filed;
  * two folders a person made, or two different packs, are still a question for a person.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

import live_enquiry_runner as L  # noqa: E402
import pack_store as ps  # noqa: E402

HEADER = [None, "Date Received", "Account Manager", "Customer", "Description", "Drawing No.",
          "Due Date", "AI CHECK", "Estimator", None]


def _row(customer, drawing):
    line = [None, datetime(2026, 11, 9), "A Manager", customer, "5 off", drawing,
            datetime(2026, 11, 16), "YES", "An Estimator", None]
    return L.rows_from_table([[None] * 10, HEADER, line])[0]


def _folder(root: Path, client: str, name: str, *files: str, ours: bool = False) -> Path:
    d = root / client / name
    d.mkdir(parents=True, exist_ok=True)
    for n in files:
        (d / n).write_bytes(b"%PDF-1.4 " + n.encode())
    if ours:
        (d / ps.MANIFEST).write_text("{}", encoding="utf-8")
    return d


def _find(root, customer, drawing):
    return L.LiveEnquiryShare(root).find(_row(customer, drawing))


def test_the_newest_version_the_store_filed_is_the_pack_and_the_old_one_is_kept(tmp_path):
    old = _folder(tmp_path, "Acme", "70001-01-00-GA", "70001-01-00-GA.pdf", ours=True)
    new = _folder(tmp_path, "Acme", "70001-01-00-GA v2", "70001-01-00-GA.pdf", "70001-01-01.pdf",
                  ours=True)
    got = _find(tmp_path, "Acme", "70001-01-00-GA")
    assert got.status == "found" and got.folder == new
    assert "70001-01-00-GA" in got.reason and "kept beside it and not read" in got.reason
    assert old.is_dir() and (old / "70001-01-00-GA.pdf").exists(), "a kept version was removed"


def test_three_versions_take_the_third_whatever_order_they_are_listed_in(tmp_path):
    for n in ("70002-01-GA v3", "70002-01-GA", "70002-01-GA v2"):
        _folder(tmp_path, "Acme", n, "70002-01-GA.pdf", ours=True)
    assert _find(tmp_path, "Acme", "70002-01-GA").folder.name == "70002-01-GA v3"


def test_a_folder_a_person_made_wins_over_a_version_filed_beside_it(tmp_path):
    """10 Nov: the estimator's full pack stood beside a 'v2' the store had made from a lone
    DXF. The person's pack is the pack, whichever number the other carries."""
    by_hand = _folder(tmp_path, "Acme", "70003-01-GA", "70003-01-GA.pdf", "70003-01-01.pdf")
    _folder(tmp_path, "Acme", "70003-01-GA v2", "70003-01-GA.pdf", ours=True)
    got = _find(tmp_path, "Acme", "70003-01-GA")
    assert got.status == "found" and got.folder == by_hand


def test_two_folders_a_person_made_are_still_a_question_for_a_person(tmp_path):
    _folder(tmp_path, "Acme", "70004-01-GA", "a.pdf")
    _folder(tmp_path, "Acme", "70004-01-GA v2", "b.pdf")
    got = _find(tmp_path, "Acme", "70004-01-GA")
    assert got.status == "held" and "2 folders" in got.reason and "leave one" in got.reason


def test_two_different_packs_for_one_number_are_not_versions_of_each_other(tmp_path):
    """The contrasting case the old rule was written for, and it still holds."""
    _folder(tmp_path, "Acme", "70005-02-GA", "a.pdf", ours=True)
    _folder(tmp_path, "Acme", "70005-02 Beer Plinth", "b.pdf", ours=True)
    got = _find(tmp_path, "Acme", "70005-02-GA")
    assert got.status == "held" and "2 folders" in got.reason


def test_the_store_and_the_share_agree_on_which_folder_is_the_pack(tmp_path):
    """The store's own idea of the newest version is the one the share reads."""
    for n in ("70006-01-GA", "70006-01-GA v2"):
        _folder(tmp_path, "Acme", n, "70006-01-GA.pdf", ours=True)
    newest = ps._versions(tmp_path / "Acme" / "70006-01-GA")[-1][1]
    assert _find(tmp_path, "Acme", "70006-01-GA").folder == newest


def test_the_design_share_no_longer_stands_aside_for_its_own_kept_versions(tmp_path):
    """It returned nothing whenever the share said two folders fit, so its own second version
    stopped it for good. With one folder chosen it resolves and stores as it always did."""
    for n in ("70007-01-GA", "70007-01-GA v2"):
        _folder(tmp_path, "Acme", n, "70007-01-GA.pdf", ours=True)
    share = L.LiveEnquiryShare(tmp_path).find(_row("Acme", "70007-01-GA"))
    assert not (share.status == "held" and " fit " in share.reason)
