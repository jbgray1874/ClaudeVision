"""A member schedule is made in the portal, not in Notepad (D-535).

D-534 let a person's checked member schedule be priced in place of the model's read — but the
only way to file one was to hand-edit JSON in Notepad and copy it onto the share with
PowerShell, and the next run's staging then deleted it, because it was not on the list of the
job's own files. "This looks really hacky." So the schedule is made where the materials and the
customer's changes are: the last read (or the schedule on file) loads into a table, the
estimator corrects it, ticks and names it, and the LLM run files it beside the pack. Staging
keeps it; setting it aside renames it; the run's log says which construction it priced.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
os.environ.setdefault("SDI_OFFLINE", "1")

import accepted_construction as ac  # noqa: E402

JOB, CLIENT = "0000-TESTRAIL", "TESTCO"

READ_PARTS = [
    {"name": "UPRIGHT", "kind": "fabricated", "material_guess": "MILD STEEL",
     "sighted_material": "40 X 20 OVAL", "quantity": 2,
     "stock": {"form": "oval_tube", "section_mm": [40, 20], "wall_mm": 1.5, "length_mm": 1625},
     "assumed_blank_mm": {"length": 1625, "width": 40, "thickness": 20},
     "operations": ["saw", "hole_machining", "welding", "powder_coating"],
     "cutouts": [{"what": "hole", "count": 13, "length_mm": 9, "width_mm": 9},
                 {"what": "slot", "count": 2, "length_mm": 20, "width_mm": 8}],
     "seen": "side view", "why_size": "1625 dimensioned on the side view"},
    {"name": "WIRE HOOK", "kind": "fabricated", "material_guess": "MILD STEEL", "quantity": 4,
     "stock": {"form": "wire", "wire_mm": 6, "length_mm": 320},
     "operations": ["welding", "powder_coating"]},
    {"name": "TOP PANEL", "kind": "fabricated", "material_guess": "MILD STEEL", "quantity": 1,
     "stock": {"form": "sheet"}, "assumed_blank_mm": {"length": 600, "width": 400, "thickness": 1.5},
     "operations": ["laser_cutting", "folding"], "folds": 4, "banded_edges": ""},
    {"name": "125MM SWIVEL CASTOR", "kind": "bought_in", "quantity": 4,
     "operations": ["assembly"]},
]


def _submitted(**over):
    sub = {"accepted_by": "J. Estimator", "checked": True,
           "product": {"name": "TEST RAIL", "stated_weight_kg": "16",
                       "assumed_overall_mm": {"height": "1723", "width": "475", "depth": "732"}},
           "unit_operations": "welding, assembly, powder_coating",
           "parts": ac.rows_from_parts(READ_PARTS),
           "excluded": ["the tote crate drawn on the base"], "not_visible": []}
    sub.update(over)
    return sub


# ── the table and the file ───────────────────────────────────────────────────────────────

def test_a_read_goes_into_the_table_and_comes_back_in_its_own_shape():
    rows = ac.rows_from_parts(READ_PARTS)
    up = rows[0]
    assert (up["form"], up["section"], up["wall"], up["length"]) == ("oval_tube", "40 x 20", 1.5, 1625)
    assert (up["holes"], up["hole_mm"]) == (13, 9)
    assert rows[1]["section"] == "6" and rows[1]["length"] == 320
    assert (rows[2]["width"], rows[2]["thickness"], rows[2]["folds"]) == (400, 1.5, 4)
    parts, errors = ac.parts_from_rows(rows)
    assert not errors
    assert parts[0]["stock"] == {"form": "oval_tube", "section_mm": [40, 20], "wall_mm": 1.5,
                                 "length_mm": 1625}
    # the slot the table does not show rides through; the holes are the table's
    assert {"what": "slot", "count": 2, "length_mm": 20, "width_mm": 8} in parts[0]["cutouts"]
    assert {"what": "hole", "count": 13, "length_mm": 9, "width_mm": 9} in parts[0]["cutouts"]
    assert parts[0]["seen"] == "side view"
    assert parts[1]["stock"] == {"form": "wire", "wire_mm": 6, "length_mm": 320}
    assert parts[2]["assumed_blank_mm"] == {"length": 600, "width": 400, "thickness": 1.5}
    assert parts[3]["kind"] == "bought_in" and "stock" not in parts[3]


def test_a_checked_and_named_schedule_is_the_read_the_engine_prices(tmp_path):
    data, errors = ac.build_file(_submitted(), JOB, today="2026-10-14")
    assert not errors and data["written_by"] == ac.WRITTEN_BY
    assert data["unit_operations"] == ["welding", "assembly", "powder_coating"]
    assert data["product"]["assumed_overall_mm"] == {"height": 1723, "width": 475, "depth": 732}
    ac.write(tmp_path, JOB, data)
    import concept_scan as cs
    ans, f, problems = cs.find_accepted_construction([tmp_path], job=JOB)
    assert ans and not problems and Path(f).name == f"{JOB}_construction.json"
    recs = cs.parts_from_concept(ans, "J")
    up = next(r for r in recs if r["description"] == "UPRIGHT")
    assert up["section_stock"]["profile_form"] == "OVAL" and up["quantity"] == 2


@pytest.mark.parametrize("change, why", [
    ({"accepted_by": ""}, "say who checked"),
    ({"accepted_by": "DRAFT"}, "say who checked"),
    ({"checked": False}, "tick that every line"),
    ({"unit_operations": "welding, painting"}, "painting is not work"),
])
def test_an_unnamed_unticked_or_unpriceable_schedule_is_refused(change, why):
    data, errors = ac.build_file(_submitted(**change), JOB)
    assert not data and any(why in e for e in errors), errors


def test_a_line_that_cannot_be_priced_is_refused_on_its_line():
    rows = ac.rows_from_parts(READ_PARTS)
    rows[0]["section"] = ""                      # an oval with no section
    rows[1]["length"] = ""                       # a wire with no length
    rows[2]["thickness"] = ""                    # a sheet part with half a blank
    rows[3]["quantity"] = "0"
    rows.append({"name": "BAR", "kind": "fabricated", "quantity": 1, "form": "flat_bar",
                 "section": "50 x 10", "length": "520", "holes": "4", "hole_mm": "",
                 "operations": "saw, bending"})
    _d, errors = ac.build_file(_submitted(parts=rows), JOB)
    text = " | ".join(errors)
    assert "line 1 (UPRIGHT): an oval tube needs its section size" in text
    assert "line 2 (WIRE HOOK): a wire needs its diameter" in text
    assert "line 3 (TOP PANEL): a sheet part needs its blank length, width and thickness" in text
    assert "line 4 (125MM SWIVEL CASTOR): how many per unit?" in text
    assert "line 5 (BAR): give the hole diameter" in text
    assert "line 5 (BAR): bending is not work the engine can price" in text


def test_a_price_anywhere_is_refused_by_name():
    rows = ac.rows_from_parts(READ_PARTS)
    rows[3]["unit_price_gbp"] = 6.5
    _d, errors = ac.build_file(_submitted(parts=rows), JOB)
    assert any("money" in e and "unit_price_gbp" in e for e in errors)


def test_a_section_with_its_wall_in_the_size_takes_it():
    rows = [{"name": "BASE ANGLE", "kind": "fabricated", "quantity": 2, "form": "angle",
             "section": "50 x 50 x 5", "length": "732", "operations": ["saw"]}]
    parts, errors = ac.parts_from_rows(rows)
    assert not errors and parts[0]["stock"]["wall_mm"] == 5
    assert parts[0]["stock"]["section_mm"] == [50, 50]


def test_the_words_the_table_offers_are_the_engines_own():
    import concept_scan as cs
    assert set(ac.OPERATIONS) == set(cs.SIGHTABLE_OPERATIONS)
    assert set(cs.STOCK_FORMS) | {"oval_tube"} == set(ac.FORMS) | {"oval_tube"}
    assert set(ac.SECTION_FORMS) == set(cs.STOCK_SECTION_FORMS)
    assert set(ac.KINDS) == set(cs.CONCEPT_KINDS)


# ── on file, set aside, and where the table starts ─────────────────────────────────────

def test_the_panel_starts_from_the_schedule_on_file_or_the_last_read(tmp_path):
    import concept_scan as cs
    assert ac.on_file(tmp_path, JOB)["last_read"] is None
    cs.save_bill(tmp_path, JOB, {"product": {"name": "TEST RAIL"}, "parts": READ_PARTS,
                                 "unit_operations": ["welding"]})
    bill = json.loads((tmp_path / f"{JOB}_concept_bill.json").read_text(encoding="utf-8"))
    assert bill["read"]["source"] == "model" and len(bill["read"]["parts"]) == 4
    view = ac.on_file(tmp_path, JOB)
    assert view["on_file"] is None and view["last_read"]["complete"] is True
    assert view["last_read"]["rows"][0]["form"] == "oval_tube"
    data, _e = ac.build_file(_submitted(), JOB)
    ac.write(tmp_path, JOB, data)
    view = ac.on_file(tmp_path, JOB)
    assert view["on_file"]["accepted_by"] == "J. Estimator" and not view["on_file"]["problems"]
    assert len(view["on_file"]["rows"]) == 4


def test_a_bill_saved_before_the_panel_is_offered_as_a_summary(tmp_path):
    (tmp_path / f"{JOB}_concept_bill.json").write_text(json.dumps({"parts": [
        {"name": "UPRIGHT", "kind": "fabricated", "quantity": 2, "material": "MILD STEEL",
         "length": 1723, "width": 40, "thickness": 20, "why": "1723 from floor to top"}]}),
        encoding="utf-8")
    lr = ac.on_file(tmp_path, JOB)["last_read"]
    assert lr["complete"] is False and lr["rows"][0]["name"] == "UPRIGHT"
    assert lr["rows"][0]["quantity"] == 2


def test_setting_aside_renames_it_so_the_model_reads_and_it_can_be_loaded_again(tmp_path):
    data, _e = ac.build_file(_submitted(), JOB)
    ac.write(tmp_path, JOB, data)
    new = ac.set_aside(tmp_path, JOB)
    assert Path(new).name == f"{JOB}_construction_set_aside.json"
    assert ac.find([tmp_path], job=JOB) == (None, "", [])
    view = ac.on_file(tmp_path, JOB)
    assert view["on_file"] is None and view["set_aside"]["accepted_by"] == "J. Estimator"
    assert ac.set_aside(tmp_path, JOB) is None


# ── staging keeps it ─────────────────────────────────────────────────────────────────────

@pytest.fixture()
def staging(tmp_path, monkeypatch):
    stub = types.ModuleType("config")
    stub.STAGING_ROOT = str(tmp_path / "SDIIntelligenceAISheet")
    monkeypatch.setitem(sys.modules, "config", stub)
    spec = importlib.util.spec_from_file_location(
        "staging", ROOT / "sdi-intelligence-backend" / "staging.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_restage_keeps_the_schedule_as_the_jobs_own_data(staging, tmp_path):
    pdf = tmp_path / "src" / f"{JOB}.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4 drawing")
    res = staging.stage([str(pdf)], client=CLIENT, drawing=JOB)
    folder = Path(res["folder"])
    for name in (f"{JOB}_construction.json", f"{JOB}_construction_set_aside.json"):
        (folder / name).write_text("{}", encoding="utf-8")
    res2 = staging.stage([str(pdf)], client=CLIENT, drawing=JOB)
    assert f"{JOB}_construction.json" in res2["job_data_kept"]
    assert (folder / f"{JOB}_construction_set_aside.json").is_file()
    res3 = staging.stage_brief_only(client=CLIENT, drawing=JOB, brief="a test rail")
    assert f"{JOB}_construction.json" in res3["job_data_kept"]
    assert (folder / f"{JOB}_construction.json").is_file()


# ── the service ──────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def er(monkeypatch, tmp_path):
    import estimate_routes
    estimate_routes._RUNS.clear()
    estimate_routes._RUNNERS.clear()
    monkeypatch.setattr(estimate_routes, "_other_local_services", lambda port: [])
    monkeypatch.setattr(estimate_routes.staging, "staging_root", lambda: tmp_path / "stage")
    monkeypatch.setattr(estimate_routes, "_within_a_root", lambda p: Path(p))
    monkeypatch.setattr(estimate_routes, "OUTPUT_ROOT", tmp_path / "out")
    monkeypatch.setattr(estimate_routes.config, "API_KEY", "portal-key", raising=False)
    estimate_routes._RUNNERS["LAPTOP-abc"] = estimate_routes.Runner(runner_id="LAPTOP-abc",
                                                                    hostname="LAPTOP")
    return estimate_routes


def _llm(er, construction=None, method="llm"):
    return er.start(er.EstimateRequest(client=CLIENT, drawing_number=JOB, units=1,
                                       method=method, enquiry_brief="a test rail",
                                       construction=construction), x_sdi_key="portal-key")


def test_the_run_files_it_then_prices_what_is_on_file_then_sets_it_aside(er, tmp_path):
    out = _llm(er, construction=_submitted())
    assert out["construction"] == "filed"
    folder = Path(er._RUNS[out["run_id"]].job_folder)
    assert (folder / f"{JOB}_construction.json").is_file()
    assert any("MEMBER SCHEDULE filed — 4 line(s) accepted by J. Estimator" in l
               for l in er._RUNS[out["run_id"]].log)
    er._RUNS.clear()
    out2 = _llm(er)                              # nothing sent: the schedule on file stands
    assert out2["construction"] == "on_file"
    assert (folder / f"{JOB}_construction.json").is_file()
    assert any("MEMBER SCHEDULE on file" in l and "NOT asked" in l
               for l in er._RUNS[out2["run_id"]].log)
    er._RUNS.clear()
    out3 = _llm(er, construction={"set_aside": True})
    assert out3["construction"] == "set_aside"
    assert not (folder / f"{JOB}_construction.json").exists()
    assert (folder / f"{JOB}_construction_set_aside.json").is_file()
    assert any("MEMBER SCHEDULE set aside" in l for l in er._RUNS[out3["run_id"]].log)


def test_a_refused_schedule_stops_the_run_before_anything_is_staged(er, tmp_path):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _llm(er, construction=_submitted(accepted_by=""))
    assert exc.value.status_code == 400 and "Member schedule not accepted" in exc.value.detail
    assert not (tmp_path / "stage" / CLIENT / JOB).exists()
    with pytest.raises(HTTPException) as exc2:
        _llm(er, construction=_submitted(), method="both")
    assert exc2.value.status_code == 400 and "LLM read method only" in exc2.value.detail


def test_the_panel_reads_the_job_and_checks_before_run(er, tmp_path):
    empty = er.construction_read(er.ConstructionReadRequest(client=CLIENT, drawing_number=JOB),
                                 x_sdi_key="portal-key")
    assert empty["status"] == "no_job" and "oval_tube" in empty["vocabulary"]["forms"]
    _llm(er, construction=_submitted())
    got = er.construction_read(er.ConstructionReadRequest(client=CLIENT, drawing_number=JOB),
                               x_sdi_key="portal-key")
    assert got["status"] == "ok" and got["on_file"]["accepted_by"] == "J. Estimator"
    opened = er.construction_read(er.ConstructionReadRequest(schedule={"parts": READ_PARTS}),
                                  x_sdi_key="portal-key")
    assert len(opened["opened"]["rows"]) == 4
    assert any("accepted_by" in p for p in opened["opened"]["problems"])
    ok = er.construction_check(er.ConstructionCheckRequest(drawing_number=JOB,
                                                           construction=_submitted()),
                               x_sdi_key="portal-key")
    assert ok == {"ok": True, "errors": [], "lines": 4}
    bad = er.construction_check(er.ConstructionCheckRequest(
        drawing_number=JOB, construction=_submitted(checked=False)), x_sdi_key="portal-key")
    assert bad["ok"] is False and bad["errors"]


def test_the_page_sends_the_schedule_only_when_asked_and_stops_if_it_was_not_filed():
    page = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(
        encoding="utf-8")
    for ident in ('id="kPanel"', 'id="kLoad"', 'id="kOpen"', 'id="kWho"', 'id="kChecked"',
                  'id="kUse"', 'id="kSetAside"', 'id="kTable"'):
        assert ident in page
    assert "construction: _k," in page
    assert 'started.construction !== "filed"' in page
    assert "/api/estimate/construction/read" in page and "/api/estimate/construction/check" in page
    guide = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-guide.html").read_text(
        encoding="utf-8")
    assert "Member schedule — checked against the drawing" in guide
