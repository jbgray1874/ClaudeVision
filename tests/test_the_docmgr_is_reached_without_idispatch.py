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
