"""Found, read, linked and costed are four facts, reported apart (reviewer, 12 Nov 2026).

"Finding a model file is not proof that it was successfully read or supplied the required
specification." 12674-02-GA's side panels were found, refused by SolidWorks, and priced at
nothing; the base was linked and priced from a metal allowance."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pack_use as pu  # noqa: E402


def _record():
    return {
        "declared_product": "X-02-GA",
        "solidworks_native": {"extract_errors": [
            {"path": r"\\share\pack\X-01-02J.SLDPRT",
             "errors": ["OpenDoc6 failed: errs=65536 (swFileWithSameTitleAlreadyOpen)"]}]},
        "parts": [
            {"part_number": "X-01-01J", "solidworks_native": True, "bbox_mm_source": "solidworks_api",
             "normalized_material": "MDF", "normalized_thickness_mm": 18, "_costed_blank_mm": [2399.6, 1164]},
            {"part_number": "X-01-02J", "normalized_material": None, "review_flags": ["no geometry"]},
            {"part_number": "X-02-05J", "normalized_material": "MILD STEEL"},
            {"part_number": "X-03-203.SLDPRT1", "solidworks_native": True},
            {"part_number": "HAFELE: 1"},
        ],
        "cost_breakdown": {"material": {"per_part": [
            {"part_number": "X-01-01J", "extended_material_cost_gbp": 36.13, "supplier_source": "SDI Live"},
            {"part_number": "X-02-05J", "extended_material_cost_gbp": 8.32, "supplier_source": "historical_quote_material_line"},
        ]}},
    }


def _manifest():
    def m(d, *fmts):
        return {"drawing": d, "files": [{"format": f} for f in fmts]}
    return {"references_read": True, "missing": ["X-02-09J"], "bought_in_unmatched": [],
            "members": [m("X-01-01J", "sldprt"), m("X-01-02J", "sldprt"), m("X-02-05J", "sldprt"),
                        m("X-03-203", "sldprt"), m("X-02-101SA", "sldasm")]}


def test_each_member_says_found_read_linked_and_costed_apart():
    t = pu.trace(_record(), _manifest())
    by = {r["drawing"]: r for r in t["members"]}
    assert by["X-01-01J"]["read"].startswith("model read") and by["X-01-01J"]["material_gbp"] == 36.13
    assert by["X-01-02J"]["read"].startswith("MODEL NOT READ") and "65536" in by["X-01-02J"]["read"]
    assert by["X-01-02J"]["linked"] and by["X-01-02J"]["material_gbp"] == 0
    assert by["X-02-05J"]["read"] == "MODEL FOUND, NOTHING TAKEN FROM IT" and by["X-02-05J"]["weak_price"]
    assert by["X-03-203"]["linked"], "a model file's name is the part"
    assert not by["X-02-101SA"]["linked"]


def test_what_is_unresolved_stays_visible():
    t = pu.trace(_record(), _manifest())
    assert t["referenced_no_file"] == ["X-02-09J"]
    assert t["not_linked"] == ["X-02-101SA"]
    assert "X-01-02J" in t["linked_uncosted"] and "X-01-02J" in t["not_read"]
    assert t["in_estimate_not_in_pack"] == ["HAFELE: 1"]
    assert t["weak_prices"] == [{"drawing": "X-02-05J", "gbp": 8.32, "source": "historical_quote_material_line"}]
    assert list(t["models_failed"]) == ["X-01-02J"]


def test_it_prints_and_says_when_the_parts_list_was_not_read(tmp_path, capsys):
    import json
    rec, man = tmp_path / "r.json", tmp_path / "m.json"
    rec.write_text(json.dumps(_record()))
    man.write_text(json.dumps(dict(_manifest(), references_read=False)))
    assert pu.main(["--record", str(rec), "--manifest", str(man)]) == 0
    out = capsys.readouterr().out
    assert "MODEL NOT READ" in out and "WEAK" in out and "not proved complete" in out
