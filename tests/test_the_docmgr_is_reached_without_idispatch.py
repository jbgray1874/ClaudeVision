"""The Document Manager is reached through comtypes when pywin32 cannot reach it (D-711).

JG's laptop, 5 Nov 2026, the first real run of the backup reader: the library is registered and
the key is set, and Dispatch("SwDocumentMgr.SwDMClassFactory") answered "No such interface
supported" (-2147467262). The class factory has no IDispatch, which is all pywin32 can bind to.
comtypes binds to the interface itself from the type library the Document Manager registers.

These run on Linux, so they hold the routing and the messages, not the COM calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "solidworks"))

import sw_docmgr_analyse as dm  # noqa: E402


def test_with_neither_route_the_message_says_how_to_install_the_second(monkeypatch):
    monkeypatch.setitem(sys.modules, "win32com", None)
    monkeypatch.setitem(sys.modules, "win32com.client", None)
    monkeypatch.setitem(sys.modules, "comtypes", None)
    monkeypatch.setitem(sys.modules, "comtypes.client", None)
    with pytest.raises(RuntimeError) as got:
        dm.dispatch_class_factory()
    assert "pip install comtypes" in str(got.value)


def test_a_newer_interface_is_reached_by_queryinterface_under_comtypes(monkeypatch):
    class ISwDMComponent6:
        pass

    class Bare:
        """A component as an array hands it back: an IUnknown pointer with no members."""
        def QueryInterface(self, cls):
            assert cls is ISwDMComponent6
            return type("C", (), {"PathName": r"K:\job\J-01M.SLDPRT"})()

    types = type("Types", (), {"ISwDMComponent6": ISwDMComponent6})
    monkeypatch.setitem(dm._BINDING, "via", "comtypes")
    monkeypatch.setitem(dm._BINDING, "types", types)
    assert dm._member(Bare(), "PathName", dm._COMP_IFACES) == r"K:\job\J-01M.SLDPRT"


def test_a_factory_that_cannot_start_is_said_plainly(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(dm.KEY_ENV, "TEST-KEY-not-real-0000")
    (tmp_path / "J-01M.SLDPRT").write_bytes(b"\0")
    monkeypatch.setattr(dm, "com_available", lambda: (True, ""))

    def _no():
        raise RuntimeError("comtypes could not load the Document Manager's type library")
    monkeypatch.setattr(dm, "dispatch_class_factory", _no)
    assert dm.main([str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert "could not be started from Python" in out and "type library" in out
    assert "not installed or not registered" not in out


# ── comtypes hands back the retval LAST (D-712) ─────────────────────────────────────────
#
# The laptop's first comtypes run, 5 Nov 2026: the factory and the key worked, and all 12 files
# of 12678-01-GA failed with "open: invalid literal for int() with base 10: b'\xe8\xce\x9dr\xe9
# \x01\x00\x00'". comtypes returns GetDocument's outputs as (result, document); the reader took
# the document pointer for the error number and int() read its raw bytes.

import ctypes  # noqa: E402

import test_a_docmgr_extract_backs_up_solidworks as base  # noqa: E402

_OUT_METHODS = {"GetDocument", "GetCustomPropertyValues", "GetCustomPropertyValue2",
                "GetCustomPropertyValue", "GetCustomProperty", "GetAllExternalReferences4"}
_PRIMS = (str, bytes, int, float, bool, type(None))


class ComtypesOrder:
    """A stand-in COM object returning results the way comtypes does: a method's [out]
    parameters in order and its retval last; every object it hands back wrapped the same way."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return _wrap(attr)

        def call(*a, **k):
            r = attr(*a, **k)
            if name in _OUT_METHODS and isinstance(r, tuple) and len(r) > 1:
                r = tuple(r[1:]) + (r[0],)                 # retval moves to the end
            return _wrap(r)
        return call


def _wrap(v):
    if isinstance(v, _PRIMS):
        return v
    if isinstance(v, tuple):
        return tuple(_wrap(x) for x in v)
    return ComtypesOrder(v)


@pytest.fixture()
def as_comtypes(monkeypatch):
    monkeypatch.setitem(dm._BINDING, "via", "comtypes")
    monkeypatch.setitem(dm._BINDING, "types", None)


def test_a_document_comes_back_last_and_is_still_the_document(as_comtypes):
    doc = object()

    class App:
        def GetDocument(self, path, doctype, ro):
            return (0, doc)                                 # comtypes: (result, document)
    assert dm.open_document(App(), "J-01M.SLDPRT", 1) == (doc, 0)


def test_a_pointer_is_never_read_as_the_error_number(as_comtypes):
    ptr = ctypes.c_void_p(0x1E9729DCEE8)                    # what the laptop's error printed

    class App:
        def GetDocument(self, path, doctype, ro):
            return (ptr, 0)                                 # either order: told apart by type
    doc, err = dm.open_document(App(), "J-01M.SLDPRT", 1)
    assert doc is ptr and err == 0


def test_a_null_document_is_no_document_with_its_error(as_comtypes):
    class App:
        def GetDocument(self, path, doctype, ro):
            return (3, ctypes.c_void_p())                   # NULL pointer, open error 3
    assert dm.open_document(App(), "J-01M.SLDPRT", 1) == (None, 3)


def test_a_property_comes_back_value_last_and_is_read(as_comtypes):
    assert dm._unpack_property((30, '"SW-Material@x"', "Plain Carbon Steel")) == (
        "Plain Carbon Steel", '"SW-Material@x"')


def test_the_whole_pack_reads_the_same_under_either_binding(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(dm.KEY_ENV, base.KEY)
    folder, app = base._job(tmp_path)
    a = tmp_path / "pywin32.json"
    assert dm.main([str(folder), "--out", str(a)], class_factory=base.FakeFactory(app)) == 0
    monkeypatch.setitem(dm._BINDING, "via", "comtypes")
    monkeypatch.setitem(dm._BINDING, "types", None)
    b = tmp_path / "comtypes.json"
    code = dm.main([str(folder), "--out", str(b)],
                   class_factory=base.FakeFactory(ComtypesOrder(app)))
    out = capsys.readouterr().out
    assert code == 0, out
    import json
    ra, rb = (json.loads(p.read_text(encoding="utf-8"))["records"] for p in (a, b))
    assert len(rb) == len(ra) == 4 and not any(r.get("errors") for r in rb)
    assert [r["route_signals"] for r in rb] == [r["route_signals"] for r in ra]
    assert [r["custom_properties"] for r in rb] == [r["custom_properties"] for r in ra]
    assert [r["bom"] for r in rb] == [r["bom"] for r in ra]


# ── --trace says what each call answered (D-713) ────────────────────────────────────────
#
# The laptop's first full read, 5 Nov 2026: all 12 files of 12678-01-GA opened, and the three
# assemblies came back with no components and the bent parts with no cut list, with nothing on
# screen to say which call answered nothing.

def test_trace_names_the_call_that_answered_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(dm.KEY_ENV, base.KEY)
    folder, app = base._job(tmp_path)
    ga = next(d for p, d in app._docs.items() if p.lower().endswith(".sldasm"))
    cfg = ga.ConfigurationManager._configs["Default"]
    cfg.GetComponents = lambda: None                        # the call that answers nothing
    out = tmp_path / "t.json"
    assert dm.main([str(folder), "--out", str(out), "--trace"],
                   class_factory=base.FakeFactory(app)) == 0
    printed = capsys.readouterr().out
    assert "trace: GetComponents -> None" in printed
    assert "trace: configurations ['Default'], active 'Default'" in printed
    assert "trace: thickness 1.5 from the cut list" in printed
    assert base.KEY not in printed


def test_without_trace_nothing_extra_is_printed(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(dm.KEY_ENV, base.KEY)
    folder, app = base._job(tmp_path)
    assert dm.main([str(folder), "--out", str(tmp_path / "t.json")],
                   class_factory=base.FakeFactory(app)) == 0
    assert "trace:" not in capsys.readouterr().out


# ── opened is not read; unknown is not no (D-714) ───────────────────────────────────────
#
# The laptop's trace of 12678-01-GA, 5 Nov 2026: GetComponents() and GetCutListItems() raised
# KeyError: 13 (comtypes could not unpack an array of interface pointers), so the assemblies
# read as having no components and 04M as not sheet metal with no bends; and the MDF panel
# 01J's thickness came from a linked property's saved value, 1.5mm, that SolidWorks did not
# report.

def _one(tmp_path, monkeypatch, name, doc):
    monkeypatch.setenv(dm.KEY_ENV, base.KEY)
    folder = tmp_path / "pack"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(b"\0")
    app = base.FakeApp({str(path): doc})
    rec = dm.analyse_file(app, str(path))
    return rec


class _Raises:
    def __init__(self, exc):
        self.exc = exc

    def __call__(self, *a, **k):
        raise self.exc


def test_a_cut_list_that_cannot_be_read_leaves_the_part_unknown_and_calls_the_worker(
        tmp_path, monkeypatch):
    cfg = base.FakeConfig()
    cfg.GetCutListItems2 = _Raises(KeyError(13))
    doc = base.FakeDoc(props={"Thickness": ("2.5mm", '"Thickness@Default@04M.SLDPRT"mm')},
                       config=cfg)
    rs = _one(tmp_path, monkeypatch, "J-04M.SLDPRT", doc)["route_signals"]
    assert rs["is_sheet_metal"] is None and rs["bend_count"] is None, "unknown, not no"
    assert rs["needs_solidworks_worker"] is True
    assert "cut list could not be read" in rs["needs_solidworks_worker_reason"]
    assert rs["thickness_mm"] is None, "a linked value with no cut list behind it is not taken"


def test_a_part_with_no_cut_list_saved_is_known_not_sheet_metal(tmp_path, monkeypatch):
    doc = base.FakeDoc(props={"Thickness": ("18mm", "")}, config=base.FakeConfig(cut_list=()))
    rs = _one(tmp_path, monkeypatch, "J-01J.SLDPRT", doc)["route_signals"]
    assert rs["is_sheet_metal"] is False and not rs["needs_solidworks_worker"]
    assert rs["thickness_mm"] == 18.0, "a typed thickness is the designer's word"


def test_a_linked_thickness_on_a_board_part_is_said_and_not_taken(tmp_path, monkeypatch):
    doc = base.FakeDoc(props={"Thickness": ("1.5mm", '"Thickness@Default@01J.SLDPRT"mm')},
                       config=base.FakeConfig(cut_list=()))
    rs = _one(tmp_path, monkeypatch, "J-01J.SLDPRT", doc)["route_signals"]
    assert rs["thickness_mm"] is None
    assert any("saved value of the linked expression" in n for n in rs["notes"])
    assert any(n.startswith("thickness (only a linked") for n in rs["not_saved"])


def test_an_assembly_whose_components_cannot_be_read_is_a_failed_read(tmp_path, monkeypatch):
    cfg = base.FakeConfig()
    cfg.GetComponents = _Raises(KeyError(13))
    rec = _one(tmp_path, monkeypatch, "J-101SA.SLDASM", base.FakeDoc(config=cfg))
    assert rec["errors"] and "components could not be read" in rec["errors"][0]
    assert rec["bom"] == [], "no quantities are invented"


def test_a_sub_assembly_whose_components_cannot_be_read_fails_its_parent(tmp_path, monkeypatch):
    monkeypatch.setenv(dm.KEY_ENV, base.KEY)
    folder = tmp_path / "pack"
    folder.mkdir()
    ga, sub = folder / "J-GA.SLDASM", folder / "J-101SA.SLDASM"
    for p in (ga, sub):
        p.write_bytes(b"\0")
    bad = base.FakeConfig()
    bad.GetComponents = _Raises(KeyError(13))
    docs = {str(ga): base.FakeDoc(config=base.FakeConfig(components=[base.FakeComponent(sub)])),
            str(sub): base.FakeDoc(config=bad)}
    rec = dm.analyse_file(base.FakeApp(docs), str(ga))
    assert rec["errors"] and "sub-assembly J-101SA" in rec["errors"][0]
    assert "quantities below it are unknown" in rec["errors"][0]
