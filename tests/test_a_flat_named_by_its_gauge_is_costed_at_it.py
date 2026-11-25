"""A flat named "MS T2.0mm" is costed at 2 mm (12517-00-GA, 25 Nov 2026).

Every flat in the 12517 pack is named like "12517-05-01M MS T2.0mm RevB.DXF". The merge
read 2.0 from that name; the costing step's own pattern did not (the "T" sits where it
wanted a separator), and then refused the merge's 2.0 as tolerance-table noise because
the part had a DXF. All 31 sheet-steel rows went to the workbook with no gauge and £0.
"""
from estimator import _safe_thickness_and_stage

UNC = r"\\sdi-dc01\shareddata$\Shared\Estimating\Live Enquiry\M&S\12517-00"


def _flat(name, thk, source="dxf_filename"):
    return {"part_number": name.split()[0], "normalized_material": "PLAIN CARBON STEEL",
            "dxf_source_file": UNC + "\\" + name, "normalized_thickness_mm": thk,
            "thickness_source": source, "thicknesses_mm": []}


def test_the_gauge_in_a_t_prefixed_dxf_name_is_read():
    for name, gauge in (("12517-05-01M MS T2.0mm RevB.DXF", 2.0),
                        ("12517-06-06M MS T3.0mm RevB.dxf", 3.0),
                        ("12517-01-08M MS T1.0mm RevB.DXF", 1.0)):
        part = _flat(name, None, source="")
        assert _safe_thickness_and_stage(part) == (gauge, "dxf_filename")


def test_a_gauge_resolved_from_the_cut_file_is_not_refused_as_table_noise():
    part = _flat("12517-05-01M flat RevB.DXF", 2.0)          # name carries no gauge
    assert _safe_thickness_and_stage(part)[0] == 2.0


def test_a_table_value_read_only_off_drawing_text_is_still_refused_beside_a_dxf():
    part = _flat("12517-05-01M flat RevB.DXF", 2.0, source="drawing_deterministic")
    assert _safe_thickness_and_stage(part) == (None, "")
