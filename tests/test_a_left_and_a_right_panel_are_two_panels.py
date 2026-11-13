"""A LEFT AND A RIGHT PANEL ARE TWO PANELS (reviewer, 12 Nov 2026).

"23 named component DXFs became 18 costed children, each quantity 1. Similar-shaped pieces
must not disappear through deduplication."

A carcass is exported as one DXF per piece, named in words: _LHS_, _RHS_, _TOP_, _BASE_, _REAR_,
_RIB_. A left and a right side share outline, gauge and material and carry no member number,
so they were clustered as one flat and one of each pair was dropped. Synthetic names in the
drawing office's pattern; no job's files.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawing_job_merge as M  # noqa: E402

CARCASS = {
    "10000-02-01-03J_BASE_MDF_18.0mm_REV F.DXF": (900.0, 400.0),
    "10000-02-01-03J_TOP_MDF_18.0mm_REV F.DXF": (900.0, 400.0),
    "10000-02-01-03J_LHS_MF-MDF_18.0mm_REV F.DXF": (600.0, 400.0),
    "10000-02-01-03J_RHS_MF-MDF_18.0mm_REV F.DXF": (600.0, 400.0),
    "10000-02-01-03J_REAR_MDF_18.0mm_REV F.DXF": (900.0, 600.0),
    "10000-02-01-03J_TOP LOCATOR_MDF_18.0mm_REV F.DXF": (300.0, 80.0),
}


def _clusters(sizes, monkeypatch):
    monkeypatch.setattr(M, "_dxf_bbox_wh", lambda p: sizes[Path(p).name])
    return M._cluster_paths_by_bbox([Path("/pack") / n for n in sizes])


def test_the_piece_is_the_words_between_the_part_code_and_its_stock():
    f = M.piece_label_from_filename
    assert f(Path("10000-02-01-03J_LHS_MF-MDF_18.0mm_REV F.DXF")) == "LHS"
    assert f(Path("10000-02-01-04J_TOP LOCATOR_MDF_18.0mm_REV D.DXF")) == "TOP LOCATOR"
    assert f(Path("10000-02-01-07J_AV PANEL_MF-MDF_18.0mm_REV F.DXF")) == "AV PANEL"
    assert f(Path("10000-02-01-01J_MF-MDF-18.0mm_REV F.DXF")) == "", "stock straight after the code: no piece"
    assert f(Path("10000-02-69-01A_-07_5MM_HIPS.DXF")) == "", "a numbered member is read as a number"
    assert f(Path("10000-02-01A_FLAT_3MM.DXF")) == "", "a word that names no piece"
    assert f(Path("10000-02-01A.DXF")) == ""


def test_every_named_piece_of_a_carcass_is_its_own_flat(monkeypatch):
    got = _clusters(CARCASS, monkeypatch)
    assert len(got) == 6, [[p.name for p in m] for _bb, m in got]
    assert all(len(members) == 1 for _bb, members in got)


def test_the_same_piece_at_two_revisions_or_copied_is_still_one_flat(monkeypatch):
    sizes = {"10000-02-01-03J_LHS_MF-MDF_18.0mm_REV D.DXF": (600.0, 400.0),
             "10000-02-01-03J_LHS_MF-MDF_18.0mm_REV F.DXF": (600.0, 400.0),
             "10000-02-01-03J_LHS_MF-MDF_18.0mm_REV F (1).DXF": (600.0, 400.0),
             "10000-02-01-03J_RHS_MF-MDF_18.0mm_REV F.DXF": (600.0, 400.0)}
    got = _clusters(sizes, monkeypatch)
    assert sorted(len(m) for _bb, m in got) == [1, 3]


def test_unnamed_exports_of_one_outline_merge_as_before(monkeypatch):
    sizes = {"10000-02-01A_3MM.DXF": (200.0, 100.0), "10000-02-01A_FLAT_3MM.DXF": (200.0, 100.0)}
    assert len(_clusters(sizes, monkeypatch)) == 1
