"""The TTI pricer prices each row of a TTI tracker and writes the unit cost into column P (JG, 9 Nov 2026).

Column L is the drawing number, looked for under the design area and then the prototype area,
preferring a folder with "Technical" in its path and the newest drawings. Column G is the notes,
columns I and J the thumbnails. A row whose drawings are found is a full estimate; a row with none
is an LLM estimate from its notes and thumbnails, and says so. A dry run finds and writes nothing.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tti_pricer as tp  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")
ROUTES = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")


def _png() -> bytes:
    PIL = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    PIL.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _sheet(tmp_path: Path) -> Path:
    from openpyxl.drawing.image import Image as XLImage
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tracker"
    ws["A1"] = "MILWAUKEE AMSTERDAM CONFERENCE 2027"
    for col, head in {"B": "Item Description", "D": "Qty", "G": "Notes", "I": "Thumb 1", "J": "Thumb 2",
                      "L": "DrawingNumber", "P": "AICost"}.items():
        ws[f"{col}2"] = head
    ws["B3"], ws["D3"], ws["G3"], ws["L3"], ws["P3"] = "Counter unit", 4, "MDF, white gloss", "TTI-10234", 99.0
    ws["B4"], ws["D4"], ws["G4"], ws["L4"] = "Header sign", 2, "Foamex 5mm, printed", "TTI-55555"
    ws["B5"] = ""
    ws["B6"], ws["G6"] = "Plinth", "1200 x 600 x 100, black"
    img = XLImage(io.BytesIO(_png()))
    ws.add_image(img, "I4")
    p = tmp_path / "TRACKER.xlsx"
    wb.save(p)
    return p


def _areas(tmp_path: Path, monkeypatch) -> tuple:
    design = tmp_path / "W" / "Design" / "Customers April 08 Onwards" / "TTI"
    proto = tmp_path / "W" / "Prototype" / "TTi"
    tech = design / "Conference 2027" / "TTI-10234 Counter" / "Technical"
    concept = design / "Conference 2027" / "TTI-10234 Counter" / "Concept"
    for d in (tech, concept, design / "Archive" / "TTI-10234 old", design / "TTI-102345 Other"):
        d.mkdir(parents=True)
    (tech / "TTI-10234 rev B.pdf").write_text("tech")
    (concept / "TTI-10234 sketch.pdf").write_text("concept")
    os.utime(tech / "TTI-10234 rev B.pdf", (1_000_000, 1_000_000))   # the concept is newer, yet Technical wins
    (design / "Archive" / "TTI-10234 old" / "x.pdf").write_text("old")
    (design / "TTI-102345 Other" / "y.pdf").write_text("other")
    proto.mkdir(parents=True)
    monkeypatch.setenv("SDI_TTI_DESIGN_ROOT", str(design))
    monkeypatch.setenv("SDI_TTI_PROTOTYPE_ROOT", str(proto))
    monkeypatch.setenv("SDI_TTI_INPUTS", str(tmp_path / "held"))
    monkeypatch.setenv("SDI_PACK_STORE", str(tmp_path / "held" / "LiveEnquiry"))
    return design, proto, tech


def _args(sheet: Path, **kw) -> Namespace:
    a = tp.build_parser().parse_args(["--sheet", str(sheet)])
    for k, v in kw.items():
        setattr(a, k, v)
    return a


class FakePortal:
    def __init__(self, price=123.456):
        self.started, self.price = [], price

    def start(self, body):
        self.started.append(body)
        return {"run_id": f"r{len(self.started)}"}

    def status(self, run_id):
        return {"status": "done", "quantity_prices": [{"quantity": self.started[-1]["units"], "unit_gbp": self.price}],
                "output_path": f"X:\\out\\{run_id}"}


def test_the_rows_are_read_from_the_header_down_with_notes_quantities_and_thumbnails(tmp_path):
    sheet = _sheet(tmp_path)
    got = tp.read_rows(sheet, {"drawing": "L", "notes": "G", "thumbs": ["I", "J"], "cost": "P"})
    assert got["header_row"] == 2 and got["header"]["cost"] == "AICost"
    rows = {r["row"]: r for r in got["rows"]}
    assert sorted(rows) == [3, 4, 6], "an empty row is not a job"
    assert rows[3]["drawing"] == "TTI-10234" and rows[3]["quantity"] == 4 and rows[3]["cost_before"] == 99.0
    assert len(rows[4]["pictures"]) == 1 and rows[4]["notes"] == "Foamex 5mm, printed"
    assert rows[6]["drawing"] == "" and rows[6]["quantity"] == 1


def test_the_drawings_come_from_the_technical_folder_and_a_longer_number_is_not_a_match(tmp_path, monkeypatch):
    design, proto, tech = _areas(tmp_path, monkeypatch)
    listings = [("design", tp.list_folders(design)), ("prototype", tp.list_folders(proto))]
    f = tp.find_drawings("TTI-10234", listings)
    assert f["area"] == "design" and f["technical"] and f["folder"] == str(tech)
    assert [Path(x).name for x in f["files"]] == ["TTI-10234 rev B.pdf"]
    assert not any("Archive" in x for x in [f["folder"], *f["other_folders"]]), "archives are never walked"
    assert tp.find_drawings("TTI-55555", listings) == {}
    assert tp.find_drawings("12", listings) == {}, "too short to be a drawing number"


def test_the_prototype_area_is_looked_in_when_design_has_nothing(tmp_path, monkeypatch):
    design, proto, _ = _areas(tmp_path, monkeypatch)
    (proto / "TTI-55555 header").mkdir()
    (proto / "TTI-55555 header" / "TTI-55555.pdf").write_text("p")
    f = tp.find_drawings("TTI-55555", [("design", tp.list_folders(design)), ("prototype", tp.list_folders(proto))])
    assert f["area"] == "prototype"


def test_the_unit_cost_is_the_price_at_the_rows_quantity():
    st = {"quantity_prices": [{"quantity": 1, "unit_gbp": 50}, {"quantity": 4, "unit_gbp": 41.239}], "engine_price_gbp": 50}
    assert tp.unit_cost_of(st, 4) == 41.24
    assert tp.unit_cost_of(st, 9) == 50.0, "a quantity not swept falls back to the run's unit price"
    assert tp.unit_cost_of({}, 1) is None


def test_a_dry_run_finds_the_drawings_and_queues_and_writes_nothing(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    before = sheet.read_bytes()
    rep = tp.run_batch(_args(sheet, dry_run=True), portal=None, status_path=tmp_path / "s.json")
    kinds = {r["row"]: r["kind"] for r in rep["rows"]}
    assert kinds == {3: "full estimate (provisional pack)", 4: "LLM estimate (no drawings found)",
                     6: "LLM estimate (no drawings found)"}
    assert sheet.read_bytes() == before and not (tmp_path / "held").exists()
    assert json.loads((tmp_path / "s.json").read_text())["finished"]


def test_each_row_is_priced_and_its_cost_written_to_column_p_with_a_backup(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "__init__", lambda self, s, n, c: (
        setattr(self, "sheet", s), setattr(self, "sheet_name", n), setattr(self, "col", c),
        setattr(self, "backup", None), setattr(self, "how", "openpyxl")) and None)
    portal = FakePortal()
    rep = tp.run_batch(_args(sheet, replace_costs=True), portal=portal, status_path=tmp_path / "s.json", sleep=lambda s: None)
    by_row = {b["enquiry_brief"].split("row ")[1].split(".")[0]: b for b in portal.started}
    assert by_row["3"]["method"] == "both" and [Path(f).name for f in by_row["3"]["files"]] == ["TTI-10234 rev B.pdf"]
    assert by_row["3"]["client"] == "TTI" and by_row["3"]["units"] == 4
    assert by_row["4"]["method"] == "llm" and [Path(f).name for f in by_row["4"]["files"]] == ["thumbnail_1.png"]
    assert "Foamex 5mm" in by_row["4"]["enquiry_brief"]
    assert by_row["6"]["method"] == "llm" and by_row["6"]["files"] == [] and by_row["6"]["drawing_number"] == "TTI-row6"
    assert all(str(f).startswith(str(tmp_path / "held")) for b in portal.started for f in b["files"])
    ws = openpyxl.load_workbook(sheet)["Tracker"]
    assert [ws["P3"].value, ws["P4"].value, ws["P6"].value] == [123.46, 123.46, 123.46], "a rerun overwrites P"
    assert len(ws._images) == 1, "the thumbnails survive the write"
    assert rep["backup"] and Path(rep["backup"]).is_file() and "before AI cost" in rep["backup"]
    assert openpyxl.load_workbook(rep["backup"])["Tracker"]["P3"].value == 99.0


def test_a_locked_workbook_keeps_the_price_and_says_why(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)

    def locked(self, row, value):
        raise PermissionError("the file is open in Excel")
    monkeypatch.setattr(tp.SheetWriter, "write", locked)
    rep = tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=FakePortal(), status_path=None, sleep=lambda s: None)
    (r,) = rep["rows"]
    assert r["unit_cost"] == 123.46 and "could not be written" in r["why"] and "written" not in r


def test_inputs_are_held_under_the_staging_share_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SDI_TTI_INPUTS", raising=False)
    monkeypatch.setenv("SDI_STAGING_ROOT", str(tmp_path / "stage"))
    assert tp.inputs_root() == tmp_path / "stage" / "_held" / "tti"


def test_the_service_starts_the_pricer_and_the_page_offers_it():
    assert '@router.post("/tti/run")' in ROUTES and '@router.get("/tti/{tid}")' in ROUTES
    assert 'env["SDI_TTI_INPUTS"] = str(_held_dir("tti"))' in ROUTES
    assert '_held_dir("parity_rerun")' in ROUTES, "a parity re-estimate's drawings are held where start() may read them"
    assert 'id="ttiCard"' in PAGE and '"/api/estimate/tti/run"' in PAGE and "column P (AICost)" in PAGE


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    backend = str(ROOT / "sdi-intelligence-backend")
    sys.path.insert(0, backend)
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import estimate_routes as er
        monkeypatch.setattr(er, "_ENGINE_PYTHON", sys.executable)
        monkeypatch.setattr(er.staging.config, "STAGING_ROOT", str(tmp_path / "stage"))
        app = FastAPI()
        app.include_router(er.router)
        tc = TestClient(app)
        key = getattr(er.config, "API_KEY", "") or ""
        if key:
            tc.headers.update({"X-SDI-Key": key})
        yield tc, tmp_path
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        sys.path.remove(backend)
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_the_service_refuses_a_bad_sheet_and_runs_a_dry_run_to_its_status(service, monkeypatch):
    tc, tmp = service
    assert tc.post("/api/estimate/tti/run", json={"sheet": str(tmp / "nope.xlsx")}).status_code == 400
    sheet = _sheet(tmp)
    _areas(tmp, monkeypatch)
    assert tc.post("/api/estimate/tti/run", json={"sheet": str(sheet), "rows": "5 to 9"}).status_code == 400
    r = tc.post("/api/estimate/tti/run", json={"sheet": str(sheet), "dry_run": True}).json()
    deadline = time.time() + 60
    st = {}
    while time.time() < deadline:
        st = tc.get(r["status_url"]).json()
        if st.get("finished"):
            break
        time.sleep(0.5)
    assert st.get("finished"), st.get("log_tail")
    assert [x["kind"] for x in st["rows"]][0].startswith("full estimate") and st["dry_run"] is True


def test_a_title_row_above_the_header_is_not_the_header_and_drawing_cells_are_read_for_their_number(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["L1"] = "Conference drawings and costs"
    ws["L2"], ws["G2"], ws["P2"] = "Drawing Number", "Notes", "AICost"
    ws["L3"], ws["G3"] = "12535-00-GA REV A (LARGER GRAPHICS)", "graphics panel"
    ws["L4"], ws["G4"] = "7438 AS BASE", "base"
    ws["L5"], ws["G5"] = "N/A", "loose item"
    ws["L6"] = "Drawing Number"
    p = tmp_path / "t.xlsx"
    wb.save(p)
    got = tp.read_rows(p, {"drawing": "L", "notes": "G", "thumbs": ["I", "J"], "cost": "P"})
    assert got["header_row"] == 2
    assert [(r["row"], r["drawing"]) for r in got["rows"]] == [(3, "12535-00-GA"), (4, "7438"), (5, "")]
    assert "the sheet says: 12535-00-GA REV A" in tp.brief_for(got["rows"][0])


def test_a_drawing_not_found_names_the_folders_holding_its_job_number(tmp_path, monkeypatch):
    design, proto, _ = _areas(tmp_path, monkeypatch)
    (design / "Conference 2027" / "12181 Stand build").mkdir(parents=True)
    listings = [("design", tp.list_folders(design)), ("prototype", tp.list_folders(proto))]
    assert tp.find_drawings("12181-00-GA", listings) == {}
    assert [Path(x).name for x in tp.job_folders("12181-00-GA", listings)] == ["12181 Stand build"]


def test_the_same_drawing_at_the_same_quantity_is_priced_once(tmp_path, monkeypatch):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["L1"], ws["G1"], ws["D1"], ws["P1"] = "Drawing Number", "Notes", "Qty", "AICost"
    for r in (2, 3):
        ws[f"L{r}"], ws[f"G{r}"], ws[f"D{r}"] = "12110-01-GA1", "stand", 2
    p = tmp_path / "d.xlsx"
    wb.save(p)
    _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    portal = FakePortal()
    rep = tp.run_batch(_args(p), portal=portal, status_path=None, sleep=lambda s: None)
    assert len(portal.started) == 1
    assert rep["rows"][1]["same_as_row"] == 2 and rep["rows"][1]["unit_cost"] == 123.46


def test_a_job_folder_named_by_job_number_is_used_when_no_file_carries_the_drawing_number(tmp_path, monkeypatch):
    design, proto, _ = _areas(tmp_path, monkeypatch)
    job = design / "12181 - Sander Application Demo [Rome 2026]"
    (job / "Technical").mkdir(parents=True)
    (job / "Concept").mkdir()
    (job / "Technical" / "GA sheet.pdf").write_text("ga")
    (job / "Concept" / "idea.pdf").write_text("c")
    (design / "121810 Other job").mkdir()
    (design / "121810 Other job" / "z.pdf").write_text("z")
    tp._FILES.clear()
    listings = [("design", tp.list_folders(design)), ("prototype", tp.list_folders(proto))]
    f = tp.find_drawings("12181-00-GA", listings)
    assert f["match"] == "job folder" and f["folder"] == str(job / "Technical")
    assert [Path(x).name for x in f["files"]] == ["GA sheet.pdf"]
    assert tp.find_drawings("TTI-10234", listings)["match"] == "drawing number", "a named drawing still wins"


def test_nothing_is_priced_when_neither_drawing_area_can_be_read(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    monkeypatch.setenv("SDI_TTI_DESIGN_ROOT", str(tmp_path / "gone1"))
    monkeypatch.setenv("SDI_TTI_PROTOTYPE_ROOT", str(tmp_path / "gone2"))
    portal = FakePortal()
    with pytest.raises(SystemExit) as exc:
        tp.run_batch(_args(sheet), portal=portal, status_path=None, sleep=lambda s: None)
    assert "Nothing was queued or written" in str(exc.value) and portal.started == []


def test_every_found_pack_is_labelled_a_candidate_not_a_verified_pack(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    rep = tp.run_batch(_args(sheet, dry_run=True), portal=None, status_path=None)
    by = {r["row"]: r for r in rep["rows"]}
    assert by[3]["pack"].startswith("provisional pack: 1 drawing(s), revision B"), "a name-only match is never verified"
    assert by[3]["pack_detail"]["assumptions"] and by[3]["pack_status"] == "provisional"
    assert by[4]["pack"] == "" and by[6]["pack"] == ""
    assert "not verified" in tp.PACK_JOB_FOLDER and "r.pack" in PAGE


def test_a_priced_rows_pack_is_kept_in_live_enquiry_and_reused_next_time(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    first = tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=FakePortal(), status_path=None, sleep=lambda s: None)
    kept = first["rows"][0]["kept"]
    assert kept["state"] == "new" and kept["folder"] == str(tmp_path / "held" / "LiveEnquiry" / "TTI" / "TTI-10234")
    again = tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=FakePortal(), status_path=None, sleep=lambda s: None)
    assert again["rows"][0]["kept"]["state"] == "unchanged"
    portal = FakePortal()
    tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=portal, status_path=None, sleep=lambda s: None)
    assert "Drawing pack provisional:" in portal.started[0]["enquiry_brief"], "the pack's assumptions travel with the job"


def test_the_number_of_units_comes_from_the_column_named_and_is_shown(tmp_path):
    """JG, 10 Nov 2026: the number of units is column N, headed Quantity. A sheet that also has a
    column whose header mentions a quantity earlier on is read from the column named."""
    p = tmp_path / "T.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["C1"], ws["G1"], ws["L1"], ws["N1"], ws["P1"] = "Qty per pallet", "Notes", "Drawing Number", \
        "Quantity", "AICost"
    ws["C2"], ws["G2"], ws["L2"], ws["N2"] = 40, "x", "12345-01-GA", 7
    wb.save(p)
    cols = {"drawing": "L", "notes": "G", "thumbs": ["I", "J"], "cost": "P"}
    assert tp.read_rows(p, cols)["rows"][0]["quantity"] == 40, "the first Qty header, unnamed"
    got = tp.read_rows(p, dict(cols, qty="N"))
    assert got["rows"][0]["quantity"] == 7
    assert got["header"]["quantity_column"] == "N" and got["header"]["quantity"] == "Quantity"
    assert tp.build_parser().parse_args(["--sheet", "x", "--col-qty", "N"]).col_qty == "N"


def test_drawings_only_prices_the_rows_with_a_drawing_and_lists_the_rest(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    portal = FakePortal()
    rep = tp.run_batch(_args(sheet, drawings_only=True), portal=portal, status_path=None,
                       sleep=lambda s: None)
    rows = {r["row"]: r for r in rep["rows"]}
    assert rows[6]["state"] == "skipped" and "no drawing number" in rows[6]["why"]
    assert all(b["drawing_number"] != "TTI-row6" for b in portal.started)


def test_the_latest_feedback_goes_into_the_brief(tmp_path):
    p = tmp_path / "T.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["G1"], ws["H1"], ws["L1"], ws["N1"], ws["Q1"] = "Notes", "Latest Feedback", \
        "Drawing Number", "Quantity", "AI Cost"
    ws["G2"], ws["H2"], ws["L2"], ws["N2"] = "benches", "quantity reduced from 5 to 3", "12345-00-GA", 3
    wb.save(p)
    r = tp.read_rows(p, {"drawing": "L", "notes": "G", "thumbs": ["I", "J"], "cost": "Q"})["rows"][0]
    assert r["feedback"] == "quantity reduced from 5 to 3"
    assert "Latest feedback: quantity reduced from 5 to 3." in tp.brief_for(r)


def test_the_pack_line_names_what_the_pack_lacks_or_that_its_references_were_unchecked():
    m = {"status": "provisional", "members": [1], "revision": "B", "missing": [{"drawing": "X-01M"}],
         "assumptions": []}
    assert "no drawing: X-01M" in tp.pack_line(m) and "INCOMPLETE" in tp.pack_line(m)
    m = {"status": "provisional", "members": [1], "revision": "B", "missing": [],
         "assumptions": ["the GA was matched by its file name; its own text was not read"]}
    assert "references are unchecked" in tp.pack_line(m)


def test_the_pack_line_separates_the_ga_identity_from_the_pack_and_lists_bought_items():
    m = {"status": "provisional", "identity": "verified", "complete": True, "members": [1] * 16,
         "revision": "B", "missing": [], "bought_in_unmatched": ["12736-01-04X"], "assumptions": []}
    line = tp.pack_line(m)
    assert line.startswith("provisional pack: 16 drawing(s), revision B")
    assert "GA identity verified from its title block" in line
    assert "bought-in, no drawing needed" in line and "12736-01-04X" in line
    assert "verified pack" not in line


def test_a_row_that_could_not_be_queued_says_why_on_screen(tmp_path, monkeypatch, capsys):
    import live_enquiry_runner as ler
    monkeypatch.setattr(ler, "Portal", lambda *a, **k: object())
    rep = {"roots": {"design": "D", "prototype": "P", "design_folders": 1, "prototype_folders": 1,
                     "design_readable": True, "prototype_readable": True, "source": "walk"},
           "header_row": 1, "header": {"drawing": "Drawing Number", "cost": "AI Cost"},
           "rows": [{"row": 7, "drawing": "12736-00-01", "quantity": 1, "kind": "full estimate",
                     "state": "not queued", "why": "the service at http://localhost:8071 refused the key",
                     "found": {"folder": "X"}}]}
    monkeypatch.setattr(tp, "run_batch", lambda *a, **k: rep)
    tp.main(["--sheet", str(tmp_path / "s.xlsx"), "--status-file", str(tmp_path / "st.json")])
    assert "why: the service at http://localhost:8071 refused the key" in capsys.readouterr().out


# ── the batch: pack rows only, existing costs kept, resumed not duplicated (JG, 11 Nov 2026) ──

class _Portal(FakePortal):
    def __init__(self, status="done", price=123.456, start_error=None):
        super().__init__(price)
        self.state, self.start_error, self.asked = status, start_error, []

    def start(self, body):
        if self.start_error:
            raise RuntimeError(self.start_error)
        return super().start(body)

    def status(self, run_id):
        self.asked.append(run_id)
        if self.state != "done":
            return {"status": self.state, "error": "engine stopped" if self.state == "error" else ""}
        return {"status": "done", "quantity_prices": [{"quantity": 4, "unit_gbp": self.price}]}


def _quiet(monkeypatch):
    """Write into the test's own sheet with openpyxl (no Excel, no backup copy), so the
    read-back check sees what was written."""
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: self._openpyxl(row, value))
    monkeypatch.setattr(tp.shutil, "copy2", lambda *a, **k: None)


def test_a_cost_already_in_the_cell_is_kept_and_not_priced_again(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)                                   # row 3 holds 99.0
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    portal = _Portal()
    rep = tp.run_batch(_args(sheet, rows="3"), portal=portal, status_path=tmp_path / "s.json", sleep=lambda s: None)
    (r,) = rep["rows"]
    assert r["state"] == "has a cost" and "99" in r["why"] and portal.started == []


def test_drawings_only_prices_a_resolved_pack_and_never_a_thumbnail(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)                                   # row 4: number, thumbnail, no drawings
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    portal = _Portal()
    rep = tp.run_batch(_args(sheet, rows="4-6", drawings_only=True), portal=portal,
                       status_path=tmp_path / "s.json", sleep=lambda s: None)
    by = {r["row"]: r for r in rep["rows"]}
    assert by[4]["state"] == "needs drawing" and by[6]["state"] == "skipped"
    assert portal.started == [], "no thumbnail-only or description-only estimate is queued"


def test_a_rerun_waits_for_its_own_running_job_instead_of_starting_another(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    status = tmp_path / "s.json"
    first = _Portal(status="running")
    calls = {"n": 0}

    def short_wait(portal, run_id, sleep=None, **k):
        calls["n"] += 1
        return {"status": "timeout"}
    monkeypatch.setattr(tp, "wait_for", short_wait)
    rep = tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=first, status_path=status, sleep=lambda s: None)
    assert len(first.started) == 1 and rep["rows"][0]["state"] == "timeout"
    assert "left as it was" in rep["rows"][0]["why"], "an unfinished run writes nothing"
    ledger = tp.load_ledger(tp.ledger_path(sheet, status))
    (entry,) = ledger.values()
    assert entry["run_id"] == "r1" and entry["approval"] == "not finished" and entry["pack_key"]
    again = _Portal(status="running")
    rep = tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=again, status_path=status, sleep=lambda s: None)
    assert again.started == [], "the batch resumed its own run, it did not submit a duplicate"
    assert rep["rows"][0]["run_id"] == "r1" and "earlier batch" in rep["rows"][0]["resumed"]


def test_a_finished_run_from_an_earlier_batch_is_used_not_rerun(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    status = tmp_path / "s.json"
    monkeypatch.setattr(tp, "wait_for", lambda portal, run_id, sleep=None, **k: {"status": "timeout"})
    tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=_Portal(status="running"),
                 status_path=status, sleep=lambda s: None)
    done = _Portal(status="done")
    rep = tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=done, status_path=status, sleep=lambda s: None)
    (r,) = rep["rows"]
    assert done.started == [] and r["unit_cost"] == 123.46 and r["written"] == "P3 = 123.46"
    assert r["approval"].startswith("provisional"), "finished and written is not the same as approved"


def test_a_failed_run_writes_nothing_and_the_ledger_says_why(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    wrote = []
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: wrote.append((row, value)))
    status = tmp_path / "s.json"
    rep = tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=_Portal(status="error"),
                       status_path=status, sleep=lambda s: None)
    assert wrote == [] and rep["rows"][0]["state"] == "error"
    (entry,) = tp.load_ledger(tp.ledger_path(sheet, status)).values()
    assert entry["written"] is None and entry["approval"] == "not finished" and entry["why"]


def test_a_job_another_hand_started_is_named_not_duplicated(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    msg = ("409: TTI-10234 for TTI is already running (290s). Running it again now would replace the "
           "drawings that run is reading, so it is refused. POST /api/estimate/8bb60b92c9d8/abandon")
    rep = tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=_Portal(start_error=msg),
                       status_path=tmp_path / "s.json", sleep=lambda s: None)
    (r,) = rep["rows"]
    assert r["state"] == "not queued" and "did not start run 8bb60b92c9d8" in r["why"]


def test_a_ga_and_its_ga2_are_two_scopes():
    import pack_resolver as pr
    assert not pr._same("12181-00-GA", "12181-00-GA2")
    assert tp.row_key({"row": 9, "drawing": "12181-00-GA", "quantity": 1}) != \
        tp.row_key({"row": 10, "drawing": "12181-00-GA2", "quantity": 1})


# ── the 11 Nov 2026 review: inputs, lost workers, approval, the named tab, read-back ──────

def _done_with(quality):
    class P(_Portal):
        def status(self, run_id):
            st = super().status(run_id)
            st["quality"] = quality
            return st
    return P()


def test_a_cost_priced_from_other_inputs_is_kept_but_flagged_outdated(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    status = tmp_path / "s.json"
    tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=_Portal(), status_path=status, sleep=lambda s: None)
    portal = _Portal()
    rep = tp.run_batch(_args(sheet, rows="3", method="targeted"), portal=portal, status_path=status, sleep=lambda s: None)
    (r,) = rep["rows"]
    assert portal.started == [] and r["state"] == "has a cost" and r["outdated"] == ["method"]
    assert "POSSIBLY OUTDATED" in r["why"] and r["approval"].startswith("outdated")


def test_a_restarted_batch_neither_submits_nor_writes_twice(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    status = tmp_path / "s.json"
    first = _Portal()
    tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=first, status_path=status, sleep=lambda s: None)
    assert len(first.started) == 1
    writes = []
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: writes.append(row))
    again = _Portal()
    rep = tp.run_batch(_args(sheet, rows="3"), portal=again, status_path=status, sleep=lambda s: None)
    assert again.started == [] and writes == [], "the cost in the cell is this batch's own: nothing again"
    assert rep["rows"][0]["state"] == "done" and "earlier batch" in rep["rows"][0]["why"]


def test_a_run_whose_worker_went_silent_is_held_not_resubmitted(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    status = tmp_path / "s.json"
    monkeypatch.setattr(tp, "wait_for", lambda portal, run_id, sleep=None, **k: {"status": "timeout"})
    tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=_Portal(status="running"),
                 status_path=status, sleep=lambda s: None)

    class Lost(_Portal):
        def status(self, run_id):
            return {"status": "error", "runner": "PC-s2",
                    "error": "The runner (PC-s2) stopped responding 40334s into the run. Nothing was filed."}
    lost = Lost()
    rep = tp.run_batch(_args(sheet, rows="3", replace_costs=True), portal=lost, status_path=status, sleep=lambda s: None)
    (r,) = rep["rows"]
    assert lost.started == [] and r["state"] == "held: lost worker" and "--resubmit-lost" in r["why"]
    again = Lost()
    tp.run_batch(_args(sheet, rows="3", replace_costs=True, resubmit_lost=True), portal=again,
                 status_path=status, sleep=lambda s: None)
    assert len(again.started) == 1, "submitted once a person says the old worker is gone"


def test_ready_for_approval_needs_a_clean_estimate_not_only_a_verified_pack(tmp_path, monkeypatch):
    item = {"state": "done", "unit_cost": 10.0, "written": "Q7 = 10.0", "write_check": ""}
    verified = {"status": "verified", "missing": [], "bought_in_unmatched": []}
    assert tp.approval_of(dict(item, quality={"state": "complete"}), verified) == "ready for estimator approval"
    a = tp.approval_of(dict(item, quality={"state": "missing costs", "label": "Finished: 2 missing costs"}), verified)
    assert a.startswith("provisional") and "2 missing costs" in a
    a = tp.approval_of(dict(item, quality={}), verified)
    assert a.startswith("provisional") and "no review tally" in a
    b = tp.approval_of(dict(item, quality={"state": "complete"}),
                       {"status": "provisional", "missing": [], "bought_in_unmatched": ["12736-01-04X"]})
    assert b.startswith("provisional") and "12736-01-04X" in b
    assert tp.approval_of(dict(item, write_check="P7 changed"), verified).startswith("written, but the check failed")


def test_the_cost_goes_to_the_named_tab_and_is_read_back(tmp_path, monkeypatch):
    sheet = _sheet(tmp_path)                                   # rows on the "Tracker" tab
    wb = openpyxl.load_workbook(sheet)
    other = wb.create_sheet("Notes", 0)
    other["P3"] = "leave me"
    wb.active = 0                                              # another tab is the active one
    wb.save(sheet)
    _areas(tmp_path, monkeypatch)
    _quiet(monkeypatch)
    rep = tp.run_batch(_args(sheet, rows="3", replace_costs=True, sheet_name="Tracker"),
                       portal=_done_with({"state": "complete"}), status_path=tmp_path / "s.json", sleep=lambda s: None)
    (r,) = rep["rows"]
    wb = openpyxl.load_workbook(sheet)
    assert wb["Tracker"]["P3"].value == 123.46 and wb["Notes"]["P3"].value == "leave me"
    assert r["write_check"] == "" and "'Tracker'" in r["write_checked"]


def test_a_read_back_names_any_other_cell_that_moved():
    before = {"N": 2, "P": 50.0, "Q": None}
    assert tp.check_write(before, {"N": 2, "P": 50.0, "Q": 12.5}, "Q", 12.5) == ""
    msg = tp.check_write(before, {"N": 2, "P": 12.5, "Q": 12.5}, "Q", 12.5)
    assert "P changed from 50.0 to 12.5" in msg
    assert "reads None" in tp.check_write(before, before, "Q", 12.5)


class _BreaksPortal(FakePortal):
    """Prices the run's own quantity and every break it was asked for: £100 a unit less £10 a step."""

    def status(self, run_id):
        body = self.started[int(run_id[1:]) - 1]
        qs = [body["units"]] + list(body.get("quantity_breaks") or [])
        return {"status": "done", "run_id": run_id,
                "quantity_prices": [{"quantity": q, "unit_gbp": 100.0 - 10 * i} for i, q in enumerate(sorted(qs))]}


def _same_ga_three_quantities(tmp_path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["L1"], ws["G1"], ws["D1"], ws["P1"] = "Drawing Number", "Notes", "Qty", "AICost"
    for r, q in ((2, 1), (3, 2), (4, 3), (5, 1)):
        ws[f"L{r}"], ws[f"G{r}"], ws[f"D{r}"] = "12110-01-GA1", "booth", q
    p = tmp_path / "d.xlsx"
    wb.save(p)
    return p


def test_one_run_prices_every_quantity_the_sheet_asks_for_one_drawing(tmp_path, monkeypatch):
    """11 Nov 2026 dry run: 12110-01-GA1 on five rows at 1, 2 and 3 off was three full estimates."""
    p = _same_ga_three_quantities(tmp_path)
    _areas(tmp_path, monkeypatch)
    monkeypatch.setattr(tp.SheetWriter, "write", lambda self, row, value: None)
    portal = _BreaksPortal()
    rep = tp.run_batch(_args(p), portal=portal, status_path=None, sleep=lambda s: None)
    assert len(portal.started) == 1, "one run for one drawing"
    assert portal.started[0]["units"] == 1 and portal.started[0]["quantity_breaks"] == [2, 3]
    by = {x["row"]: x for x in rep["rows"]}
    assert (by[2]["unit_cost"], by[3]["unit_cost"], by[4]["unit_cost"], by[5]["unit_cost"]) == (100.0, 90.0, 80.0, 100.0)
    assert by[3]["same_run_as_row"] == 2 and "2-off break" in by[3]["why"]


def test_a_dry_run_says_which_rows_share_a_run_and_which_are_asked(tmp_path, monkeypatch):
    p = _same_ga_three_quantities(tmp_path)
    _areas(tmp_path, monkeypatch)
    rep = tp.run_batch(_args(p, dry_run=True), portal=None, status_path=None, sleep=lambda s: None)
    by = {x["row"]: x for x in rep["rows"]}
    assert by[3]["state"] == "same run as row 2" and by[5]["state"] == "same as row 2"
    monkeypatch.setattr(tp, "pack_for", lambda d, l, c: (
        {"folder": "X", "files": [], "match": "pack"},
        {"status": "ambiguous", "price_ok": False, "question": "Which copy is the issued one?",
         "assumptions": [], "members": [], "conflicts": ["x"]}))
    rep = tp.run_batch(_args(p, dry_run=True), portal=None, status_path=None, sleep=lambda s: None)
    assert rep["rows"][0]["state"] == "ask", "an ambiguous pack is asked in a dry run too, not 'planned'"
