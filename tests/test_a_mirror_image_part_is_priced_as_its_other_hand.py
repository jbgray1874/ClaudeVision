"""A right-hand part is priced as the mirror of its measured left hand (12517-00-GA).

Two faults left 12517's RH shelf brackets sized off a PDF at 384 x 260 beside their LH
twins' 384 x 100.2 flats: the RH DXFs, byte-identical to the LH ones, were dropped as
copies; and a pair named only by "LH"/"RH" in the description was never seen as a pair.
"""
from pathlib import Path

from drawing_job_merge import (_drop_duplicate_files, apply_mirror_geometry,
                               stamp_handed_descriptions, stamp_mirror_notes)


def test_identical_flats_under_two_part_numbers_are_both_kept(tmp_path):
    lh = tmp_path / "12517-06-06M MS T3.0mm RevB.dxf"
    rh = tmp_path / "12517-06-07M MS T3.0mm RevB.dxf"
    lh.write_bytes(b"0\nSECTION\nsame outline"); rh.write_bytes(lh.read_bytes())
    assert _drop_duplicate_files([lh, rh]) == [lh, rh]


def test_the_same_flat_copied_twice_is_still_one_file(tmp_path):
    a = tmp_path / "12517-06-06M MS T3.0mm RevB.dxf"
    (tmp_path / "copy").mkdir()
    b = tmp_path / "copy" / "12517-06-06M MS T3.0mm RevB.dxf"
    a.write_bytes(b"0\nSECTION\nsame outline"); b.write_bytes(a.read_bytes())
    assert _drop_duplicate_files([a, b]) == [a]


def _lh():
    return {"part_number": "12517-06-06M", "description": "LH SHELF SYSTEM BRACKET 1",
            "normalized_material": "PLAIN CARBON STEEL", "normalized_thickness_mm": 3.0,
            "geometry_source": "dxf_flat_pattern", "blank_length_mm": 384.0,
            "blank_width_mm": 100.22,
            "normalized_geometry": {"geometry_source": "dxf_flat_pattern",
                                    "blank_length_mm": 384.0, "blank_width_mm": 100.22,
                                    "developed_length_mm": 384.0, "developed_width_mm": 100.22,
                                    "bounding_box_flat_mm": {"length": 384.0, "width": 100.22},
                                    "cut_length_mm": 1288.0}}


def _rh():
    return {"part_number": "12517-06-07M", "description": "RH SHELF SYSTEM BRACKET 1",
            "normalized_material": "PLAIN CARBON STEEL", "flat_pattern_detected": True,
            "normalized_geometry": {"blank_basis": "pdf_flat_pattern_candidates",
                                    "developed_length_mm": 384.0, "developed_width_mm": 260.0,
                                    "bounding_box_flat_mm": {"length": 384.0, "width": 260.0}}}


def test_an_lh_rh_pair_named_by_description_is_a_mirror_pair():
    lh, rh = _lh(), _rh()
    assert stamp_mirror_notes([lh, rh], {"pages": []}) == 1
    assert rh["mirror_of"] == "12517-06-06M" and "mirror_of" not in lh
    assert any("MIRROR IMAGE, BY JUDGEMENT" in f for f in rh["review_flags"])
    apply_mirror_geometry([lh, rh])
    ng = rh["normalized_geometry"]
    assert (ng["developed_length_mm"], ng["developed_width_mm"]) == (384.0, 100.22)
    assert ng["geometry_source"] == "mirror_of_measured"


def test_no_pair_when_the_match_is_ambiguous_or_both_hands_are_measured():
    lh, rh = _lh(), _rh()
    other = dict(_lh(), part_number="12517-15-04M")          # two LH with one description
    assert stamp_handed_descriptions([lh, other, rh]) == 0
    rh2 = dict(_rh(), geometry_source="dxf_flat_pattern",
               normalized_geometry={"geometry_source": "dxf_flat_pattern"})
    assert stamp_handed_descriptions([_lh(), rh2]) == 0       # has its own DXF


def test_a_description_with_no_hand_or_two_hands_pairs_nothing():
    a = dict(_lh(), description="SHELF BRACKET")
    b = dict(_rh(), description="LH AND RH SHELF BRACKET")
    assert stamp_handed_descriptions([a, b]) == 0
