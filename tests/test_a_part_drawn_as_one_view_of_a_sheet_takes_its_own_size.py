"""A part drawn as one view of a sheet that draws several takes its size from its own view
(Hotel Chocolat, 1050mm plinth, 26 Nov 2026).

A.34494 lists drawing B.34495 three times: TOP PANEL x1, SIDE PANEL x4, BASE PANEL x1. B.34495
draws all three, each view labelled by a SolidWorks Part Information Block and dimensioned at
1:2.25. Its DXF is a drawing sheet, so it gives no blank, and the panels were one part at 400 x
300 x6 on the pilot book. Built here in miniature: two labelled views at 1:2.25.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import ezdxf  # noqa: E402

from sheet_view_sizes import apply_sheet_view_sizes, views_on_sheet  # noqa: E402

MDF = "MATERIAL:18mm THICK FR B MDF 3050 X 1220mm (30001651)"


def _sheet(path: Path, side_axes=("v", "h")) -> Path:
    doc = ezdxf.new("R2010", setup=True)
    blk = doc.blocks.new(name="Part Information Block")
    blk.add_attdef("AUTOATTR0_0", (0, 0))
    blk.add_attdef("AUTOATTR0_1", (0, -5))
    msp = doc.modelspace()
    s = 1 / 2.25

    def label(at, text):
        ins = msp.add_blockref("Part Information Block", at)
        ins.add_attrib("AUTOATTR0_0", text, (at[0], at[1]))
        ins.add_attrib("AUTOATTR0_1", MDF, (at[0], at[1] - 5))

    def dim(p1, p2, text, angle):
        msp.add_linear_dim(base=(p1[0] - 10, p1[1] - 10), p1=p1, p2=p2, angle=angle,
                           text=text).render()

    # The side panel: 1050 x 300 x 18, label underneath it.
    x0, y0 = 100, 70
    dim((x0, y0), (x0, y0 + 1050 * s), "1050", 90 if "v" in side_axes else 0)
    if "h" in side_axes:
        dim((x0, y0), (x0 + 300 * s, y0), "300", 0)
    dim((x0 + 300 * s, y0), (x0 + 318 * s, y0), "18", 0)
    label((x0 + 30, 20), "PLINTH TOWER 1050mm HIGH SIDE PANEL")
    # The base panel: 281 x 281 x 18, well to the right.
    x1, y1 = 430, 130
    dim((x1, y1), (x1, y1 + 281 * s), "281", 90)
    dim((x1, y1), (x1 + 281 * s, y1), "281", 0)
    dim((x1 + 281 * s, y1), (x1 + 299 * s, y1), "18", 0)
    label((x1 + 20, 80), "PLINTH TOWER X 1050mm HIGH BASE PANEL")
    doc.saveas(path)
    return path


def _members():
    return [{"part_number": "B34495-2", "description": "PLINTH TOWER 1050mm HIGH SIDE PANEL", "quantity": 4},
            {"part_number": "B34495-3", "description": "PLINTH TOWER X 1050mm HIGH BASE PANEL", "quantity": 1}]


def test_each_view_is_sized_by_the_figures_it_prints_not_its_length_on_the_sheet(tmp_path):
    views = {v["label"]: v for v in views_on_sheet(_sheet(tmp_path / "nc1-b34495.DXF"))}
    side = views["PLINTH TOWER 1050mm HIGH SIDE PANEL"]
    base = views["PLINTH TOWER X 1050mm HIGH BASE PANEL"]
    assert (side["length_mm"], side["width_mm"], side["gauge_mm"]) == (1050, 300, 18)
    assert (base["length_mm"], base["width_mm"]) == (281, 281)
    assert "30001651" in side["material"]


def test_each_member_takes_its_own_view(tmp_path):
    sheet = _sheet(tmp_path / "nc1-b34495.DXF")
    parts = _members()
    assert apply_sheet_view_sizes(parts, {}, [sheet]) == ["B34495-2", "B34495-3"]
    side, base = parts
    assert (side["blank_length_mm"], side["blank_width_mm"]) == (1050, 300)
    assert (base["blank_length_mm"], base["blank_width_mm"]) == (281, 281)
    assert side["blank_length_mm_source"] == "drawing_view_dimensions"
    assert "from its own view on drawing B34495" in side["review_flags"][-1]


def test_the_sheet_is_found_in_the_dxf_merge_report(tmp_path):
    sheet = _sheet(tmp_path / "nc1-b34495.DXF")
    summary = {"dxf_augmentation": {"skipped": [{"path": str(sheet), "reason": "drawing_export_not_a_flat"}]}}
    parts = _members()
    assert apply_sheet_view_sizes(parts, summary) == ["B34495-2", "B34495-3"]


def test_no_size_without_both_axes_a_matching_label_or_over_a_measured_blank(tmp_path):
    one_axis = _sheet(tmp_path / "nc1-b34495.DXF", side_axes=("v",))
    parts = _members()
    assert apply_sheet_view_sizes(parts, {}, [one_axis]) == ["B34495-3"]
    assert "blank_length_mm" not in parts[0]

    (tmp_path / "other").mkdir()
    sheet = _sheet(tmp_path / "other" / "nc1-b34495.DXF")
    stranger = [{"part_number": "B34495-1", "description": "PLINTH TOWER X 1050mm HIGH TOP PANEL"}]
    assert apply_sheet_view_sizes(stranger, {}, [sheet]) == []

    measured = _members()[:1]
    measured[0].update(blank_length_mm=1049.0, blank_width_mm=299.0,
                       blank_length_mm_source="dxf", blank_width_mm_source="dxf")
    apply_sheet_view_sizes(measured, {}, [sheet])
    assert measured[0]["blank_length_mm"] == 1049.0


def test_a_sheet_without_labelled_views_sizes_nothing(tmp_path):
    doc = ezdxf.new("R2010", setup=True)
    doc.modelspace().add_linear_dim(base=(0, -10), p1=(0, 0), p2=(100, 0), text="300").render()
    doc.saveas(tmp_path / "nc1-a34494.DXF")
    assert views_on_sheet(tmp_path / "nc1-a34494.DXF") == []


def test_a_member_takes_its_own_views_material_and_gauge(tmp_path):
    sheet = _sheet(tmp_path / "nc1-b34495.DXF")
    parts = _members()
    apply_sheet_view_sizes(parts, {}, [sheet])
    assert all(p["normalized_material"] == "MDF" and p["normalized_thickness_mm"] == 18 for p in parts)


def test_a_sheets_dxf_gives_its_part_the_finish_and_the_coat_it_names(tmp_path):
    """A.34494's PDF has no text; its DXF title says FINISH: SPRAYED TO MATCH ... RAL 8014 and
    FINISHED PART NO. : - 10100892. The plinth tower was priced with no coat at all."""
    from sheet_view_sizes import apply_sheet_title_facts
    doc = ezdxf.new("R2010", setup=True)
    blk = doc.blocks.new(name="SW_BROKEN_VIEW_0")
    blk.add_mtext("PLINTH TOWER ASSEMBLY\\PFINISHED PART NO. : - 10100892\\P"
                  "FINISH: SPRAYED TO MATCH SEPIA BROWN RAL 8014")
    note = doc.blocks.new(name="SW_NOTE_0")
    note.add_mtext("2mm PVC EDGING TO RECIEVE A 2mm RADIUS")
    doc.modelspace().add_blockref("SW_BROKEN_VIEW_0", (0, 0))
    doc.modelspace().add_blockref("SW_NOTE_0", (0, 50))
    doc.saveas(tmp_path / "nc1-a34494.DXF")
    tower = {"part_number": "10100892", "description": "PLINTH TOWER ASSEMBLY", "quantity": 1}
    other = {"part_number": "30000711", "description": "INSERT NUT", "quantity": 4}
    assert apply_sheet_title_facts([tower, other], {}, [tmp_path / "nc1-a34494.DXF"]) == ["10100892"]
    assert "SPRAYED" in tower["normalized_finish"] and "wet_spray" in tower["textual_operations"]
    assert "normalized_thickness_mm" not in tower          # the edging note is not its gauge
    assert "normalized_finish" not in other
