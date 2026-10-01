"""12173-02 Card Spinner, 17:34 book (D-378): the base's two 25 mm layers joined to the steel
frames, and the frame welded three times.

1. "12173-03-01J-1_25mm MDF" and "-01J-2" are the two 626 x 626 x 25 mm layers of the base
   12173-03-01J. With no exact hit, the trailing-segment fallback matched their last digit and
   joined them to the frames 12173-03-201 and -202 — a 25 mm MDF gauge on a steel weldment,
   and the base costed on a 3 mm floor. The near-match presumption Dave Wright ruled out.
2. 12173-03-202 and -203 state FINISH: WELDED on their own sheets; 12173-03-201, the FRAME WELD
   ASSEMBLY that holds them, states FINISH: POWDER COATED. All three were "inferred, not drawn",
   and 201 was welded again over its members.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import drawing_job_merge as d                                  # noqa: E402
import weld_symbols as ws                                      # noqa: E402

KEYS = ["12173-03-01J", "12173-03-02J", "12173-03-03J", "12173-03-201", "12173-03-202",
        "12173-03-203", "12173-03-04M"]


def _pbk():
    return {d._normalize_part_key(k): {"part_number": k} for k in KEYS}


def test_a_numbered_piece_resolves_to_its_own_part():
    pbk = _pbk()
    assert d._lookup_part(pbk, "12173-03-01J-1")["part_number"] == "12173-03-01J"
    assert d._lookup_part(pbk, "12173-03-01J-2")["part_number"] == "12173-03-01J"


def test_a_last_digit_is_never_a_match():
    pbk = {d._normalize_part_key(k): {"part_number": k} for k in ("12173-03-201", "12173-03-202")}
    assert d._lookup_part(pbk, "12173-03-01J-1") is None
    assert d._lookup_part(pbk, "12173-03-77X-2") is None


def test_a_digit_ended_code_is_a_part_not_a_piece():
    assert d._piece_of_known_part(_pbk(), "12173-03-201") is None


def test_both_spellings_of_a_piece_number_are_read():
    assert d._member_suffix_of_flat(Path("12173-03-01J-1_25mm MDF_revA.DXF")) == "1"
    assert d._member_suffix_of_flat(Path("12349-02-69-01A_-03_5MM.DXF")) == "03"
    assert d._member_suffix_of_flat(Path("12527-22-01M_0.9mm MS_REV A.DXF")) is None


def test_two_identical_numbered_layers_are_both_costed(tmp_path):
    import ezdxf
    for n in ("12173-03-01J-1_25mm MDF_revA.DXF", "12173-03-01J-2_25mm MDF_revA.DXF"):
        doc = ezdxf.new()
        doc.modelspace().add_lwpolyline([(0, 0), (626, 0), (626, 626), (0, 626)], close=True)
        doc.saveas(tmp_path / n)
    parts = [{"part_number": k, "description": "X", "quantity": 1} for k in
             ("12173-03-01J", "12173-03-201", "12173-03-202")]
    out = d.augment_summary_with_dxf({"manufacturing_writeup": {"parts": parts}, "pages": []},
                                     sorted(tmp_path.glob("*.DXF")), reestimate=False)
    got = {p["part_number"]: p for p in out["manufacturing_writeup"]["parts"]}
    assert {"12173-03-01J-01", "12173-03-01J-02"} <= set(got)
    for k in ("12173-03-01J-01", "12173-03-01J-02"):
        assert got[k]["normalized_thickness_mm"] == 25.0 and got[k]["normalized_material"] == "MDF"
    for k in ("12173-03-201", "12173-03-202"):
        assert not got[k].get("geometry_source"), "a frame took a board's flat"


def _sheets():
    return {
        "12173-03-201": {"finish": "POWDER COATED - MATT", "text": "12173-03-20212173-03-203"},
        "12173-03-202": {"finish": "WELDED", "text": "12173-03-04M12173-03-06M"},
        "12173-03-203": {"finish": "WELDED", "text": "12173-03-05M12173-03-06M"},
        "12173-03-04M": {"finish": "RAW", "text": ""},
    }


def test_a_sheet_that_says_welded_states_the_weld():
    parts = [{"part_number": k} for k in ("12173-03-201", "12173-03-202", "12173-03-203",
                                          "12173-03-04M")]
    got = ws.apply_finish_welds(parts, _sheets())
    assert got["stated"] == ["12173-03-202", "12173-03-203"]
    for p in parts[1:3]:
        assert "welding" in p["textual_operations"]
        assert p["operation_sources"]["welding"] == "drawing_deterministic"
    assert "textual_operations" not in parts[3]


def test_the_powder_parent_of_welded_members_is_not_welded_again():
    parts = [{"part_number": k} for k in ("12173-03-201", "12173-03-202", "12173-03-203")]
    got = ws.apply_finish_welds(parts, _sheets())
    assert got["ruled_out"] == ["12173-03-201"]
    ro = parts[0]["operations_ruled_out"]
    assert "welding" in ro and "dress_welds" in ro
    assert "FINISH: WELDED" in ro["welding"] and "POWDER" in ro["welding"]


def test_a_weldment_over_raw_members_keeps_its_weld():
    """12527-22-101: a powder-coated weldment of RAW panels is still the weld."""
    parts = [{"part_number": "W-101"}, {"part_number": "W-01M"}]
    sheets = {"W-101": {"finish": "POWDER COATED", "text": "W-01M"},
              "W-01M": {"finish": "SEE ASSEMBLY DRAWING", "text": ""}}
    assert ws.apply_finish_welds(parts, sheets) == {"stated": [], "ruled_out": []}


def test_every_pdf_in_the_pack_is_read():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert 'summary.get("job_source_pdfs")' in src.split("WELD SYMBOLS ON A PART'S OWN SHEET")[1][:2000]
