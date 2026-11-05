"""When SolidWorks cannot be reached, the Document Manager reads the models — and says so.

SCRUM-184. The production extractor (sw_native_analyse.py) needs Windows and a licensed
SolidWorks seat. Without one, a job whose models sit beside its drawings was costed from the
drawings alone. The SOLIDWORKS Document Manager reads the same files headless — no seat, only a
licence key — but only what each file SAVED: it rebuilds nothing and measures nothing.

So the backup is held to four rules, and this file proves each:

  * SAME SCHEMA. sw_docmgr_analyse.py writes the record shape sw_native_analyse.py writes, with
    `"reader": "solidworks_docmgr"`, so normalize_native_extract consumes it unchanged. A field
    it cannot supply is null and named, never inferred. The licence key never appears in
    anything it prints or writes.
  * ONLY WHEN ASKED, ONLY WHEN NEEDED. The connector runs it only with SDI_SW_DOCMGR=1, only
    where there are models, and only when the COM analyser is switched off, absent, or failed.
    With the switch off nothing changes.
  * BELOW THE WORKER AND BELOW THE DXF. Its values enter as solidworks_docmgr, which may fill a
    gap and may never displace a SolidWorks COM measurement or a DXF — a DXF blank in particular
    is kept even where the COM path would have replaced it.
  * NO GUESSED BLANK. A formed part whose file saved no flat pattern is flagged as needing the
    SolidWorks worker; nothing stands in for its blank.

Every Document Manager call is driven through fake COM objects: this suite runs on Linux.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "solidworks"))

from source_connectors import solidworks as sw          # noqa: E402
import source_precedence as sp                          # noqa: E402
import sw_docmgr_analyse as dm                          # noqa: E402
import invariants as inv                                # noqa: E402

# Long and unmistakable, shaped like a real Document Manager key: a company, then grants.
KEY = ("SDITestCompany:swdocmgr_general-11111-22222-33333-44444-55555,"
       "swdocmgr_previews-66666-77777-88888-99999-00000")


# ── fake Document Manager COM objects ────────────────────────────────────────────────

class FakeConfig:
    def __init__(self, props=None, components=(), cut_list=()):
        self._props = dict(props or {})          # name -> (value, linked expression)
        self._components = list(components)
        self._cut = list(cut_list)

    def GetCustomPropertyNames(self):
        return tuple(self._props)

    def GetCustomPropertyValues(self, name):
        v, linked = self._props[name]
        return (v, 30, linked)                   # value, [out] type, [out] linkedTo

    def GetComponents(self):
        return tuple(self._components)

    def GetCutListItems2(self):
        return tuple(self._cut)


class FakeCutItem:
    def __init__(self, name, props, qty=1):
        self.Name = name
        self.Quantity = qty
        self._props = dict(props)

    def GetCustomPropertyNames(self):
        return tuple(self._props)

    def GetCustomPropertyValue2(self, name):
        v = self._props[name]
        if isinstance(v, tuple):
            return (v[0], 30, v[1])
        return (v, 30, "")


class FakeComponent:
    def __init__(self, path, config="Default", suppressed=False):
        self.PathName = str(path)
        self.Name2 = Path(str(path)).stem + "-1"
        self.ConfigurationName = config
        self.DocumentType = None
        self._sup = suppressed

    def IsSuppressed(self):
        return self._sup


class FakeConfigMgr:
    def __init__(self, configs, active):
        self._configs = dict(configs)
        self._active = active

    def GetConfigurationNames(self):
        return tuple(self._configs)

    def GetActiveConfigurationName(self):
        return self._active

    def GetConfigurationByName(self, name):
        return self._configs.get(name)


class FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self.RowCount = len(rows)
        self.ColumnCount = len(rows[0]) if rows else 0

    def GetCellText(self, r, c):
        return self._rows[r][c]


class FakeDoc:
    def __init__(self, props=None, config=None, refs=(), tables=None):
        self._props = dict(props or {})
        self.ConfigurationManager = FakeConfigMgr({"Default": config or FakeConfig()},
                                                  "Default")
        self._refs = tuple(str(r) for r in refs)
        self._tables = dict(tables or {})
        self.closed = 0

    def GetCustomPropertyNames(self):
        return tuple(self._props)

    def GetCustomPropertyValues(self, name):
        v, linked = self._props[name]
        return (v, 30, linked)

    def GetAllExternalReferences(self, _opt):
        return self._refs

    def GetTableNames(self, table_type):
        return tuple(self._tables) if table_type == 2 else ()

    def GetTable(self, name):
        return self._tables.get(name)

    def CloseDoc(self):
        self.closed += 1


class FakeApp:
    def __init__(self, docs):
        self._docs = {os.path.normcase(os.path.abspath(p)): d for p, d in docs.items()}
        self.opened = []

    def GetDocument(self, path, doctype, allow_read_only):
        self.opened.append((path, doctype, allow_read_only))
        d = self._docs.get(os.path.normcase(os.path.abspath(path)))
        return (d, 0) if d is not None else (None, 3)

    def GetSearchOptionObject(self):
        return object()

    def GetLatestSupportedFileVersion(self):
        return 8000


class FakeFactory:
    def __init__(self, app):
        self._app = app
        self.keys = []

    def GetApplication(self, key):
        self.keys.append(key)
        return self._app


# ── a small job: two parts, a GA assembly, a GA drawing ──────────────────────────────

def _sheet_metal_cut_list(flat=True, bends="2"):
    props = {
        "Sheet Metal Thickness": "1.5",
        "Bend Radius": "1.5",
        "Bends": bends,
        "Cutting Length-Outer": "485.32",
        "Cutting Length-Inner": "261.59",
        "Cut Outs": "3",
        "MATERIAL": ("Plain Carbon Steel", '"SW-Material@@@Cut-List-Item1@part.SLDPRT"'),
    }
    if flat:
        props["Bounding Box Length"] = "126.39"
        props["Bounding Box Width"] = "82.2"
    return [FakeCutItem("Cut-List-Item1", props)]


def _job(tmp_path):
    folder = tmp_path / "12345-01 Bracket"
    folder.mkdir()
    flat_part = folder / "12345-01-01M.SLDPRT"
    formed_part = folder / "12345-01-02M.SLDPRT"
    ga = folder / "12345-01-GA.SLDASM"
    drw = folder / "12345-01-GA.SLDDRW"
    for p in (flat_part, formed_part, ga, drw):
        p.write_bytes(b"\x00SLDFILE")
    docs = {
        str(flat_part): FakeDoc(
            props={"Description": ("BRACKET", ""), "Material": ("MILD STEEL", "")},
            config=FakeConfig(cut_list=_sheet_metal_cut_list(flat=True))),
        str(formed_part): FakeDoc(
            props={"Description": ("COVER", "")},
            config=FakeConfig(cut_list=_sheet_metal_cut_list(flat=False, bends="4"))),
        str(ga): FakeDoc(
            props={"Description": ("BRACKET ASSEMBLY", "")},
            config=FakeConfig(components=[
                FakeComponent(flat_part), FakeComponent(flat_part),
                FakeComponent(formed_part),
                FakeComponent(folder / "suppressed-thing.SLDPRT", suppressed=True)]),
            refs=[flat_part, formed_part]),
        str(drw): FakeDoc(
            tables={"Bill of Materials1": FakeTable([
                ["ITEM NO.", "PART NUMBER", "DESCRIPTION", "QTY."],
                ["1", "12345-01-01M", "BRACKET", "2"],
                ["2", "12345-01-02M", "COVER", "1"]])},
            refs=[ga]),
    }
    return folder, FakeApp(docs)


@pytest.fixture()
def key_env(monkeypatch):
    monkeypatch.setenv(dm.KEY_ENV, KEY)
    return KEY


def _run_reader(tmp_path, capsys):
    folder, app = _job(tmp_path)
    factory = FakeFactory(app)
    out = tmp_path / "out" / "docmgr.json"
    out.parent.mkdir()
    code = dm.main([str(folder), "--out", str(out)], class_factory=factory)
    printed = capsys.readouterr()
    return code, out, factory, printed, folder


# ── the extractor: same schema, reader stamped, nothing measured ─────────────────────

def test_the_backup_reader_writes_the_native_schema(tmp_path, capsys, key_env):
    code, out, factory, _printed, _folder = _run_reader(tmp_path, capsys)
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == dm.EXTRACT_SCHEMA_VERSION
    assert payload["reader"] == payload["_manifest"]["reader"] == "solidworks_docmgr"
    assert payload["_manifest"]["files_read"] == 4 and payload["_manifest"]["files_failed"] == 0
    assert sorted((r["title"], r["doctype"]) for r in payload["records"]) == [
        ("12345-01-01M", 1), ("12345-01-02M", 1), ("12345-01-GA", 2), ("12345-01-GA", 3)]
    recs = {r["title"]: r for r in payload["records"] if r["doctype"] != 3}
    for r in payload["records"]:
        assert r["reader"] == "solidworks_docmgr"
        for key in ("path", "title", "doctype", "custom_properties", "bbox_mm", "bom",
                    "route_signals", "errors"):
            assert key in r, f"record lacks {key}"
        assert r["errors"] == [], "a successful read must not look like a failed one"
        assert r["bbox_mm"] is None, "the Document Manager measures nothing"
    part = recs["12345-01-01M"]
    rs = part["route_signals"]
    assert part["doctype"] == 1
    assert (rs["flat_length_mm"], rs["flat_width_mm"]) == (126.39, 82.2)
    assert rs["thickness_mm"] == 1.5 and rs["bend_count"] == 2
    assert rs["cut_length_mm"] == pytest.approx(746.91)
    assert rs["cut_out_count"] == 3
    assert rs["material"] == "MILD STEEL" and rs["material_source"] == "custom_property"
    assert rs["bbox_mm"] is None and rs["volume_mm3"] is None and rs["surface_area_mm2"] is None
    for missing in ("bounding box", "volume", "surface area"):
        assert missing in rs["not_saved"]
    assert any("not saved in the file; only the SolidWorks worker measures it" in n for n in rs["notes"])
    # Every file opened read-only, and every document closed again.
    assert all(ro is True for _p, _t, ro in factory._app.opened)
    for path, doc in factory._app._docs.items():
        opens = sum(1 for p, _t, _ro in factory._app.opened
                    if os.path.normcase(os.path.abspath(p)) == path)
        assert doc.closed == opens, f"{path} opened {opens}x, closed {doc.closed}x"


def test_the_consumer_reads_the_backup_extract_unchanged(tmp_path, capsys, key_env):
    _code, out, _f, _p, _folder = _run_reader(tmp_path, capsys)
    job = sw.normalize_native_extract(sw.load_native_extract(out))
    assert job.found
    assert job.meta["extract_reader"] == "solidworks_docmgr"
    assert job.meta["extract_source"] == "solidworks_docmgr"
    nat = job.part_signals["12345-01-01M"]
    assert nat.source == "solidworks_docmgr"
    assert nat.has_flat() and nat.thickness_mm == 1.5
    # The GA's component list, quantities rolled up, the suppressed component left out.
    qty = {r.part_number: r.quantity for r in job.bom}
    assert qty == {"12345-01-01M": 2.0, "12345-01-02M": 1.0}
    assert all(r.source == "solidworks_docmgr" for r in job.bom)
    assert job.meta["top_assembly"] == "12345-01-GA"
    assert ("12345-01-01M", 2.0) in job.hierarchy.get("12345-01-GA", [])
    assert job.meta["docmgr_needs_worker"] == ["12345-01-02M"]
    assert "bounding box" in job.meta["docmgr_not_saved"]


def test_the_drawing_bom_table_is_read_by_its_part_number_column(tmp_path, capsys, key_env):
    _code, out, _f, _p, _folder = _run_reader(tmp_path, capsys)
    payload = json.loads(out.read_text(encoding="utf-8"))
    drw = next(r for r in payload["records"] if r["doctype"] == 3)
    assert [(b["part_number"], b["qty"]) for b in drw["bom"]] == [
        ("12345-01-01M", 2.0), ("12345-01-02M", 1.0)], \
        "the PART NUMBER column, not the ITEM NO. balloon"


def test_a_com_object_returned_by_a_property_is_not_called():
    """A pywin32 dispatch is callable (its default member). Calling the ConfigurationManager
    a property handed back would raise and read as 'no configurations'."""
    class _Dispatch:
        _oleobj_ = object()

        def __call__(self):
            raise RuntimeError("Member not found")

    class _Doc:
        ConfigurationManager = _Dispatch()

    assert isinstance(dm.configuration_manager(_Doc()), _Dispatch)


def test_a_table_that_is_not_bom_shaped_is_not_read_as_one():
    rows = [["REV", "DESCRIPTION", "DATE"], ["A", "FIRST ISSUE", "01/01/26"]]
    assert dm.bom_from_table_rows(rows) == []


def test_the_licence_key_never_appears_in_anything_it_prints_or_writes(tmp_path, capsys,
                                                                         key_env):
    code, out, factory, printed, _folder = _run_reader(tmp_path, capsys)
    assert code == 0
    assert factory.keys == [KEY], "the key must reach GetApplication"
    text = out.read_text(encoding="utf-8")
    for fragment in [KEY] + KEY.split(","):
        assert fragment not in text
        assert fragment not in printed.out and fragment not in printed.err


def test_an_error_that_echoes_the_key_is_scrubbed(tmp_path, capsys, key_env):
    folder, app = _job(tmp_path)

    def _boom(path, doctype, ro):
        raise RuntimeError(f"licence {KEY} rejected for {path}")
    app.GetDocument = _boom
    out = tmp_path / "x.json"
    code = dm.main([str(folder), "--out", str(out)], class_factory=FakeFactory(app))
    printed = capsys.readouterr()
    assert code == 1, "nothing could be read"
    text = out.read_text(encoding="utf-8")
    assert KEY not in text and KEY not in printed.out
    assert "[SDI_SW_DOCMGR_KEY]" in text


def test_without_the_key_it_reads_nothing_and_says_which_variable(tmp_path, capsys,
                                                                   monkeypatch):
    monkeypatch.delenv(dm.KEY_ENV, raising=False)
    folder, app = _job(tmp_path)
    code = dm.main([str(folder)], class_factory=FakeFactory(app))
    assert code == 2
    assert "SDI_SW_DOCMGR_KEY is not set" in capsys.readouterr().out
    assert app.opened == []


def test_a_weldment_box_is_never_read_as_a_flat_blank():
    """SolidWorks names a sheet-metal FLAT and a weldment member's SOLID box the same thing.
    Only a sheet-metal cut list's box is a blank."""
    weld = {"Bounding Box Length": {"value": "600", "linked_to": ""},
            "Bounding Box Width": {"value": "30", "linked_to": ""},
            "LENGTH": {"value": "600", "linked_to": ""},
            "Description": {"value": "TUBE, SQUARE 30 X 30 X 2.6", "linked_to": ""}}
    assert dm.classify_cut_list(weld) == "weldment"
    rs = dm.signals_from_saved("FRAME-01", {}, [{"name": "c", "quantity": 1, "props": weld}])
    assert rs["flat_length_mm"] is None and rs["flat_width_mm"] is None
    assert rs["has_weldment"] and rs["section_profile"]["profile_form"] == "SHS"
    assert rs["section_profile"]["length_mm"] == 600.0


def test_a_material_linked_to_sw_material_is_the_library_appearance():
    linked = {"Material": {"value": "Plain Carbon Steel",
                           "linked_to": '"SW-Material@part.SLDPRT"'}}
    typed = {"Material": {"value": "MDF", "linked_to": ""}}
    assert dm.signals_from_saved("P", linked, [])["material_source"] == "applied_library"
    assert dm.signals_from_saved("P", typed, [])["material_source"] == "custom_property"
    unevaluated = {"Material": {"value": '"SW-Material@part.SLDPRT"', "linked_to": ""}}
    assert dm.signals_from_saved("P", unevaluated, [])["material"] == "", \
        "an expression is not a material"


def test_a_saved_mass_is_used_only_when_its_units_can_be_proven():
    cut = [{"name": "c", "quantity": 1, "props": {
        "Sheet Metal Thickness": {"value": "1.5", "linked_to": ""},
        "Bounding Box Length": {"value": "126.39", "linked_to": ""},
        "Bounding Box Width": {"value": "82.2", "linked_to": ""},
        "Mass": {"value": "122.3", "linked_to": ""}}}]          # grams, on this model
    rs = dm.signals_from_saved("P", {"Material": {"value": "MILD STEEL", "linked_to": ""}}, cut)
    assert rs["mass_kg"] == pytest.approx(0.1223)
    rs2 = dm.signals_from_saved("P", {}, cut)                     # no density: cannot prove
    assert rs2["mass_kg"] is None
    assert any(f.startswith("mass") for f in rs2["not_saved"])


# ── a formed part with no saved flat ─────────────────────────────────────────────────

def test_a_formed_part_without_a_saved_flat_is_flagged_by_the_reader(tmp_path, capsys,
                                                                      key_env):
    _code, out, _f, _p, _folder = _run_reader(tmp_path, capsys)
    payload = json.loads(out.read_text(encoding="utf-8"))
    rs = next(r for r in payload["records"] if r["title"] == "12345-01-02M")["route_signals"]
    assert rs["needs_solidworks_worker"] is True
    assert "4 bend(s)" in rs["needs_solidworks_worker_reason"]
    assert rs["flat_length_mm"] is None and rs["flat_width_mm"] is None
    assert "flat blank" in rs["not_saved"]


def test_a_formed_part_without_a_saved_flat_is_not_priced_on_a_guess(tmp_path, capsys,
                                                                      key_env):
    _code, out, _f, _p, _folder = _run_reader(tmp_path, capsys)
    job = sw.normalize_native_extract(sw.load_native_extract(out))
    part = {"part_number": "12345-01-02M", "quantity": 1}
    counts = sw.apply_native_to_pre_estimate([part], job)
    assert part["needs_solidworks_worker"] is True
    assert not part.get("blank_length_mm") and not part.get("blank_width_mm")
    assert not part.get("native_flat_pattern")
    assert any("NEEDS THE SOLIDWORKS WORKER" in f for f in part["review_flags"])
    assert any(q.get("source") == "solidworks.docmgr_needs_worker"
               for q in part.get("manufacturing_questions") or [])
    assert counts["needs_solidworks_worker_parts"] == ["12345-01-02M"]


def test_with_a_dxf_the_formed_part_keeps_the_dxf_and_is_not_flagged(tmp_path, capsys,
                                                                       key_env):
    _code, out, _f, _p, _folder = _run_reader(tmp_path, capsys)
    job = sw.normalize_native_extract(sw.load_native_extract(out))
    part = _dxf_part("12345-01-02M", 200.0, 150.0)
    sw.apply_native_to_pre_estimate([part], job)
    assert not part.get("needs_solidworks_worker")
    assert (part["blank_length_mm"], part["blank_width_mm"]) == (200.0, 150.0)


# ── the fallback: only with the switch on, only when the worker cannot run ───────────

def _docmgr_records(title="12345-01-01M"):
    rs = dm.signals_from_saved(title, {"Material": {"value": "MILD STEEL", "linked_to": ""}},
                               [{"name": "c", "quantity": 1, "props": {
                                   k: {"value": (v[0] if isinstance(v, tuple) else v),
                                       "linked_to": ""}
                                   for k, v in _sheet_metal_cut_list()[0]._props.items()}}])
    return [{"path": f"{title}.SLDPRT", "title": title, "doctype": 1, "reader": dm.READER,
             "custom_properties": {}, "bbox_mm": None, "bom": [], "route_signals": rs,
             "errors": [], "notes": []}]


def _com_records(title="12345-01-01M"):
    return [{"path": f"{title}.SLDPRT", "title": title, "doctype": 1,
             "custom_properties": {}, "bbox_mm": [126.0, 80.0, 20.0], "bom": [],
             "route_signals": {"material": "MILD STEEL", "is_sheet_metal": True,
                               "bend_count": 2, "flat_length_mm": 126.39,
                               "flat_width_mm": 82.2, "thickness_mm": 1.5,
                               "bbox_mm": [126.0, 80.0, 20.0]},
             "errors": []}]


def _write_extract(path, records, folder, reader=None):
    man = {"schema_version": sw._MIN_EXTRACT_SCHEMA_VERSION,
           "native_files_fingerprint": sw.native_files_state(folder)["fingerprint"],
           "generated_from": str(folder)}
    if reader:
        man["reader"] = reader
    Path(path).write_text(json.dumps({"schema_version": sw._MIN_EXTRACT_SCHEMA_VERSION,
                                      "_manifest": man, "records": records}),
                          encoding="utf-8")


@pytest.fixture()
def model_folder(tmp_path):
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "12345-01-01M.SLDPRT").write_bytes(b"\x00SLDPRT")
    return folder


@pytest.fixture()
def runners(monkeypatch):
    """The two analysers, faked: each records its calls and does what the test says."""
    calls = {"com": [], "docmgr": []}
    behaviour = {"com_error": None, "com_writes": False, "docmgr_error": None,
                 "docmgr_writes": True, "com_available": (True, "")}

    def _com(folder, analyser=None, python_exe=None, out_path=None, produced=None):
        calls["com"].append(str(folder))
        if behaviour["com_writes"] and out_path:
            _write_extract(out_path, _com_records(), folder)
        return behaviour["com_error"]

    def _docmgr(folder, analyser=None, python_exe=None, out_path=None, produced=None):
        calls["docmgr"].append({"folder": str(folder), "out": str(out_path)})
        if behaviour["docmgr_writes"] and out_path:
            _write_extract(out_path, _docmgr_records(), folder, reader=dm.READER)
        return behaviour["docmgr_error"]

    monkeypatch.setattr(sw, "_run_analyser", _com)
    monkeypatch.setattr(sw, "_run_docmgr_analyser", _docmgr)
    monkeypatch.setattr(sw, "solidworks_com_available", lambda: behaviour["com_available"])
    monkeypatch.delenv("SDI_SW_DOCMGR", raising=False)
    return calls, behaviour


def test_with_the_switch_off_the_backup_never_runs(model_folder, runners):
    calls, behaviour = runners
    behaviour["com_error"] = "the SolidWorks analyser exited 1: no licence"
    job = sw.native_extract_for_job(folder=model_folder, run=True)
    assert calls["docmgr"] == [] and len(calls["com"]) == 1
    assert job.meta.get("analyser_error") == "the SolidWorks analyser exited 1: no licence"
    assert "docmgr_backup_reason" not in job.meta
    job = sw.native_extract_for_job(folder=model_folder, run=False)
    assert calls["docmgr"] == []
    assert job.meta.get("native_present_but_unread") is True


def test_with_the_switch_off_a_backup_extract_on_disk_is_not_read(model_folder, runners):
    calls, _ = runners
    _write_extract(model_folder / sw.DOCMGR_EXTRACT_FILENAME, _docmgr_records(), model_folder,
                   reader=dm.READER)
    job = sw.native_extract_for_job(folder=model_folder, run=False)
    assert not job.found and calls["docmgr"] == []


def test_switch_on_and_the_analyser_switched_off_reads_with_the_backup(model_folder, runners,
                                                                      monkeypatch):
    calls, _ = runners
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    job = sw.native_extract_for_job(folder=model_folder, run=False)
    assert calls["com"] == [] and len(calls["docmgr"]) == 1
    assert calls["docmgr"][0]["out"] == str(model_folder / sw.DOCMGR_EXTRACT_FILENAME), \
        "its own file — never over the COM extract"
    assert job.found
    assert job.meta["extract_reader"] == "solidworks_docmgr"
    assert "SDI_SW_RUN_ANALYSER=0" in job.meta["docmgr_backup_reason"]
    assert job.meta["extract_path"].endswith(sw.DOCMGR_EXTRACT_FILENAME)
    assert not job.meta.get("extract_stale")


def test_switch_on_and_no_solidworks_goes_straight_to_the_backup(model_folder, runners,
                                                                monkeypatch):
    calls, behaviour = runners
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    behaviour["com_available"] = (False, "this machine is not Windows")
    job = sw.native_extract_for_job(folder=model_folder, run=True)
    assert calls["com"] == [], "an analyser that can only fail is not launched"
    assert len(calls["docmgr"]) == 1
    assert job.meta["extract_reader"] == "solidworks_docmgr"
    assert "no SolidWorks on this machine" in job.meta["docmgr_backup_reason"]


def test_switch_on_and_a_failed_analyser_falls_back(model_folder, runners, monkeypatch):
    calls, behaviour = runners
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    behaviour["com_error"] = "the SolidWorks analyser exited 1: no licence"
    job = sw.native_extract_for_job(folder=model_folder, run=True)
    assert len(calls["com"]) == 1 and len(calls["docmgr"]) == 1
    assert job.meta["extract_reader"] == "solidworks_docmgr"
    assert "no licence" in job.meta["docmgr_backup_reason"]
    assert job.meta["analyser_error"] == "the SolidWorks analyser exited 1: no licence", \
        "the worker's failure is still on the record"


def test_switch_on_but_a_working_analyser_is_used_and_the_backup_is_not(model_folder, runners,
                                                                       monkeypatch):
    calls, behaviour = runners
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    behaviour["com_writes"] = True
    job = sw.native_extract_for_job(folder=model_folder, run=True)
    assert len(calls["com"]) == 1 and calls["docmgr"] == []
    assert job.meta["extract_reader"] == "solidworks_api"
    assert job_source_is_com(job)


def job_source_is_com(job):
    return sw.job_source(job) == "solidworks_api" and "docmgr_backup_reason" not in job.meta


def test_switch_on_but_no_models_runs_no_reader_at_all(tmp_path, runners, monkeypatch):
    calls, _ = runners
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    folder = tmp_path / "drawings-only"
    folder.mkdir()
    (folder / "ga.pdf").write_bytes(b"%PDF")
    job = sw.native_extract_for_job(folder=folder, run=False)
    assert calls["docmgr"] == [] and not job.meta.get("analyser_error")


def test_a_backup_that_fails_is_reported_not_silent(model_folder, runners, monkeypatch):
    calls, behaviour = runners
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    behaviour["docmgr_writes"] = False
    behaviour["docmgr_error"] = "SDI_SW_DOCMGR_KEY is not set"
    job = sw.native_extract_for_job(folder=model_folder, run=False)
    assert not job.found
    assert job.meta["docmgr_error"] == "SDI_SW_DOCMGR_KEY is not set"
    assert "Document Manager backup reader failed" in job.meta["analyser_error"]
    assert job.meta.get("native_present_but_unread") is True
    assert "Document Manager backup failed" in job.meta["native_unread_reason"]


def test_a_fresh_backup_extract_is_reused_not_re_read(model_folder, runners, monkeypatch):
    calls, _ = runners
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    _write_extract(model_folder / sw.DOCMGR_EXTRACT_FILENAME, _docmgr_records(), model_folder,
                   reader=dm.READER)
    job = sw.native_extract_for_job(folder=model_folder, run=False)
    assert calls["docmgr"] == [] and job.found
    assert job.meta["docmgr_ran"] is False
    assert job.meta["extract_reader"] == "solidworks_docmgr"


def test_the_key_is_never_on_the_command_line_and_is_scrubbed_from_errors(monkeypatch,
                                                                         tmp_path):
    monkeypatch.setenv(sw.DOCMGR_KEY_ENV, KEY)
    seen = {}

    class _R:
        returncode, stdout, stderr = 1, "", f"GetApplication refused {KEY}"

    def _run(cmd, **kw):
        seen["cmd"] = cmd
        return _R()
    monkeypatch.setattr(sw.subprocess, "run", _run)
    msg = sw._run_docmgr_analyser(tmp_path)
    assert all(KEY not in str(a) for a in seen["cmd"])
    assert KEY not in msg and "[SDI_SW_DOCMGR_KEY]" in msg
    assert "exited 1" in msg


def test_without_the_key_the_backup_is_not_launched(monkeypatch, tmp_path):
    monkeypatch.delenv(sw.DOCMGR_KEY_ENV, raising=False)
    monkeypatch.setattr(sw.subprocess, "run",
                        lambda *a, **k: pytest.fail("launched without a key"))
    assert "SDI_SW_DOCMGR_KEY is not set" in sw._run_docmgr_analyser(tmp_path)


# ── below the worker, below the DXF ──────────────────────────────────────────────────

def test_docmgr_ranks_below_the_worker_and_below_the_dxf():
    assert sp.rank("solidworks_docmgr") < sp.rank("dxf") < sp.rank("solidworks_api")
    for field in ("normalized_thickness_mm", "blank_length_mm", "quantity",
                  "normalized_material"):
        assert sp.field_rank("solidworks_docmgr", field) < sp.field_rank("dxf", field)
        assert sp.field_rank("solidworks_docmgr", field) < sp.field_rank("solidworks_api", field)
    assert sp.field_rank("solidworks_docmgr", "normalized_thickness_mm") < \
        sp.field_rank("dxf_filename", "normalized_thickness_mm")
    assert sp.rank("solidworks_docmgr_applied_material") < sp.rank("drawing_deterministic"), \
        "a library appearance still loses to the drawing's word"
    assert sp.evidence_family("solidworks_docmgr") == sp.evidence_family("solidworks_api"), \
        "one model file, read twice, is one voice"
    assert sp.display_name("solidworks_docmgr") != "solidworks docmgr"


@pytest.mark.parametrize("held_source", ["dxf", "dxf_flat_pattern", "solidworks_api"])
def test_a_docmgr_value_never_overwrites_a_measurement(held_source):
    part = {}
    assert sp.apply_field(part, "blank_length_mm", 132.39, held_source)
    assert not sp.apply_field(part, "blank_length_mm", 126.39, "solidworks_docmgr")
    assert part["blank_length_mm"] == 132.39
    assert part["blank_length_mm_source"] == held_source


def test_a_docmgr_value_fills_a_gap():
    part = {}
    assert sp.apply_field(part, "normalized_thickness_mm", 1.5, "solidworks_docmgr")
    assert sp.source_of(part, "normalized_thickness_mm") == "solidworks_docmgr"


def _dxf_part(pn, length, width):
    return {"part_number": pn, "quantity": 1,
            "dxf_source_file": f"{pn}.DXF", "dxf_augmented": True,
            "geometry_source": "dxf_flat_pattern",
            "blank_length_mm": length, "blank_width_mm": width,
            "normalized_geometry": {"blank_length_mm": length, "blank_width_mm": width,
                                    "geometry_source": "dxf_flat_pattern"}}


def test_a_dxf_blank_is_not_overwritten_by_a_saved_flat():
    """The DXF here measures a quarter of the model's flat. From the COM worker that flat
    would replace the DXF as incomplete; from a SAVED flat it may not. The DXF is kept and the
    disagreement is left unreconciled for a person."""
    job = sw.normalize_native_extract(_docmgr_records())
    part = _dxf_part("12345-01-01M", 63.0, 41.0)
    sw.apply_native_to_pre_estimate([part], job)
    assert (part["blank_length_mm"], part["blank_width_mm"]) == (63.0, 41.0)
    assert part["normalized_geometry"]["blank_length_mm"] == 63.0
    assert not part.get("dxf_geometry_rejected") and "rejected_dxf_geometry" not in part
    assert part["geometry_source"] == "dxf_flat_pattern"
    assert part["flat_unreconciled"] is True
    assert part["flat_arbitration"]["winner"] == "dxf"
    assert any("is KEPT" in f for f in part["review_flags"])


def test_the_same_disagreement_from_the_worker_does_replace_the_dxf():
    """The contrast that proves the rule above is the backup's and not an accident: the COM
    extract's measured flat supersedes the incomplete DXF exactly as before."""
    job = sw.normalize_native_extract(_com_records())
    part = _dxf_part("12345-01-01M", 63.0, 41.0)
    sw.apply_native_to_pre_estimate([part], job)
    assert part.get("dxf_geometry_rejected") is True
    assert part["blank_length_mm"] == 126.39


def test_a_saved_flat_fills_a_part_with_no_dxf_under_its_own_source():
    job = sw.normalize_native_extract(_docmgr_records())
    part = {"part_number": "12345-01-01M", "quantity": 1}
    sw.apply_native_to_pre_estimate([part], job)
    assert (part["blank_length_mm"], part["blank_width_mm"]) == (126.39, 82.2)
    assert part["blank_length_mm_source"] == "solidworks_docmgr"
    assert part["native_flat_pattern"] is True
    assert sp.source_of(part, "normalized_thickness_mm") == "solidworks_docmgr"
    assert sp.source_of(part, "geometry_rollup.estimated_cut_length_mm") == "solidworks_docmgr"
    assert sp.source_of(part, "normalized_material") == "solidworks_docmgr"
    assert part["solidworks_reader"] == "solidworks_docmgr"
    assert "bounding box" in part["solidworks_not_saved"]
    assert any("not saved in the file; only the SolidWorks worker measures them" in f
               for f in part["review_flags"])
    assert "bbox_mm" not in part, "nothing stands in for the envelope"


def test_a_saved_flat_does_not_displace_a_blank_a_person_confirmed():
    job = sw.normalize_native_extract(_docmgr_records())
    part = {"part_number": "12345-01-01M", "quantity": 1}
    sp.apply_field(part, "blank_length_mm", 130.0, "estimator_confirmed")
    sp.apply_field(part, "blank_width_mm", 85.0, "estimator_confirmed")
    sw.apply_native_to_pre_estimate([part], job)
    assert (part["blank_length_mm"], part["blank_width_mm"]) == (130.0, 85.0)
    assert not part.get("native_flat_pattern")


def test_with_the_switch_off_a_com_extract_applies_exactly_as_before():
    job = sw.normalize_native_extract(_com_records())
    assert job.meta["extract_reader"] == "solidworks_api"
    part = {"part_number": "12345-01-01M", "quantity": 1}
    sw.apply_native_to_pre_estimate([part], job)
    assert part["blank_length_mm"] == 126.39
    assert "blank_length_mm_source" not in part, "the COM flat is written as it always was"
    assert sp.source_of(part, "normalized_thickness_mm") == "solidworks_api"
    assert "solidworks_reader" not in part and "solidworks_not_saved" not in part
    assert sw.extract_reader_summary(job) == {"source": "solidworks_api",
                                              "extract_reader": "solidworks_api"}


# ── the estimate says it was a backup read ───────────────────────────────────────────

def _violations(sw_node):
    return {v["code"]: v for v in inv.check_native_evidence_is_current(
        {"solidworks_native": sw_node})}


def test_a_backup_read_is_a_warning_and_an_unmeasured_formed_part_blocks():
    node = {"found": True, "extract_reader": "solidworks_docmgr",
            "docmgr_backup_reason": "no SolidWorks on this machine",
            "docmgr_not_saved": ["bounding box", "volume", "surface area"]}
    v = _violations(node)["native_extract_from_docmgr"]
    assert v["severity"] == inv.WARNING
    node["applied"] = {"needs_solidworks_worker_parts": ["12345-01-02M"]}
    v = _violations(node)["native_extract_from_docmgr"]
    assert v["severity"] == inv.BLOCKING and "12345-01-02M" in v["message"]
    assert "native_extract_from_docmgr" not in _violations(
        {"found": True, "extract_reader": "solidworks_api"})


def test_the_summary_carries_the_reader_and_the_reason(model_folder, runners, monkeypatch):
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    job = sw.native_extract_for_job(folder=model_folder, run=False)
    s = sw.extract_reader_summary(job)
    assert s["source"] == s["extract_reader"] == "solidworks_docmgr"
    assert "SDI_SW_RUN_ANALYSER=0" in s["docmgr_backup_reason"]


def test_both_switches_are_written_down_where_an_operator_looks():
    doc = (ROOT / "tools" / "solidworks" / "README.md").read_text(encoding="utf-8")
    assert "SDI_SW_DOCMGR=1" in doc and "SDI_SW_DOCMGR_KEY" in doc
    assert KEY not in doc


if __name__ == "__main__":                                              # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
