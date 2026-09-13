"""Seven cut files went in and six flats came out.

12349-02's folder holds seven 01A flats — `-01` at 2 mm, `-02` at 3 mm and five at 5 mm — and
the 13 Sep estimate costed six of them. `-03` is missing: a cut file the drawing office
supplied, absent from the sheet that prices the job, while the pack's own provenance tab lists
its path among the files it read.

WHY. Flats are clustered so that one physical thing is cut once, and the cluster key was
(gauge, material) with the bounding box breaking ties inside it. Two 5 mm High Impact Acrylic
members with the same OUTLINE therefore clustered, one was picked, and the other was
discarded. Two parts can share an outline and differ completely inside it — which is exactly
why their cut lengths differ on the sheet — and a bounding box cannot see that.

THE RULE: the member number the drawing office wrote into the filename joins the key. `-03`
and `-04` are two numbers a person wrote down and no outline comparison overrules them. A
re-export or a revision still collapses, because it carries the SAME number; a pack that
numbers nothing is untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawing_job_merge as djm                                         # noqa: E402

PACK = "12349-02-69-01A"


def _paths(*names):
    return [Path("/pack") / n for n in names]


def _one_outline(monkeypatch, wh=(300.0, 200.0)):
    """Every flat in this pack has the SAME bounding box — the condition that lost -03."""
    monkeypatch.setattr(djm, "_dxf_bbox_wh", lambda p: wh)


def _codes(clusters):
    return sorted(djm.member_number_from_filename(m[0]) for _bb, m in clusters)


# ── the member number is read from both house spellings ──────────────────────────────────

def test_the_member_number_is_read_from_either_naming_convention():
    assert djm.member_number_from_filename(
        Path(f"{PACK} -03 5MM High Impact Acrylic RevA.DXF")) == "3"
    assert djm.member_number_from_filename(
        Path(f"{PACK}_-07_5MM_High Impact Acrylic_RevA.DXF")) == "7"


def test_a_file_with_no_member_number_says_so():
    """04M and 06A are whole parts, not members — they must not acquire a number."""
    assert djm.member_number_from_filename(
        Path("12349-02-69-04M_1.2MM_MS_RevA.DXF")) == ""
    assert djm.member_number_from_filename(
        Path("12349-02-69-06A_5MM_High Impact Acrylic_RevA.DXF")) == ""


# ── the defect, on this pack's real filenames ────────────────────────────────────────────

def test_two_numbered_members_of_one_gauge_stay_two_parts(monkeypatch):
    """-03 and -04: same gauge, same material, same outline, different numbers."""
    _one_outline(monkeypatch)
    clusters = djm._cluster_paths_by_bbox(_paths(
        f"{PACK} -03 5MM High Impact Acrylic RevA.DXF",
        f"{PACK} -04 5MM High Impact Acrylic RevA.DXF"))
    assert len(clusters) == 2, "a numbered flat was merged away by an outline match"
    assert _codes(clusters) == ["3", "4"]


def test_all_seven_flats_survive(monkeypatch):
    """The whole 01A folder, every file sharing one outline: seven in, seven out."""
    _one_outline(monkeypatch)
    clusters = djm._cluster_paths_by_bbox(_paths(
        f"{PACK} -01 2MM High Impact Acrylic RevA.DXF",
        f"{PACK} -02 3MM High Impact Acrylic RevA.DXF",
        f"{PACK} -03 5MM High Impact Acrylic RevA.DXF",
        f"{PACK} -04 5MM High Impact Acrylic RevA.DXF",
        f"{PACK} -05 5MM High Impact Acrylic RevA.DXF",
        f"{PACK} -06 5MM High Impact Acrylic RevA.DXF",
        f"{PACK} -07 5MM High Impact Acrylic RevA.DXF"))
    assert len(clusters) == 7
    assert _codes(clusters) == ["1", "2", "3", "4", "5", "6", "7"]


# ── what must still collapse, and what must still never merge ────────────────────────────

def test_the_same_member_exported_twice_is_still_one_flat(monkeypatch):
    """The reason clustering exists: a re-export carries the same number."""
    _one_outline(monkeypatch)
    clusters = djm._cluster_paths_by_bbox(_paths(
        f"{PACK} -04 5MM High Impact Acrylic RevA.DXF",
        f"{PACK}_-04_5MM_High Impact Acrylic_RevA.DXF"))
    assert len(clusters) == 1


def test_one_member_number_at_two_gauges_is_still_two_flats(monkeypatch):
    """The estimator's own complaint, unchanged: 2 mm must not fold into 5 mm."""
    _one_outline(monkeypatch)
    clusters = djm._cluster_paths_by_bbox(_paths(
        f"{PACK} -01 2MM High Impact Acrylic RevA.DXF",
        f"{PACK} -01 5MM High Impact Acrylic RevA.DXF"))
    assert len(clusters) == 2


def test_a_pack_that_numbers_nothing_behaves_exactly_as_before(monkeypatch):
    """No member numbers and no gauges: one shared key, and the outline decides — the old
    behaviour, which packs from other drawing offices still depend on."""
    _one_outline(monkeypatch)
    same = djm._cluster_paths_by_bbox(_paths("PANEL_A.DXF", "PANEL_B.DXF"))
    assert len(same) == 1
    monkeypatch.setattr(djm, "_dxf_bbox_wh",
                        lambda p: (300.0, 200.0) if p.stem.endswith("A") else (900.0, 40.0))
    apart = djm._cluster_paths_by_bbox(_paths("PANEL_A.DXF", "PANEL_B.DXF"))
    assert len(apart) == 2


def test_a_flat_with_no_readable_outline_is_still_its_own_flat(monkeypatch):
    """An unreadable DXF must not be merged into whatever happens to be beside it."""
    monkeypatch.setattr(djm, "_dxf_bbox_wh", lambda p: None)
    clusters = djm._cluster_paths_by_bbox(_paths(
        f"{PACK} -03 5MM High Impact Acrylic RevA.DXF",
        f"{PACK} -04 5MM High Impact Acrylic RevA.DXF"))
    assert len(clusters) == 2
