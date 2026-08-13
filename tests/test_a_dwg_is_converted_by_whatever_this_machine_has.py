"""A capability that depends on a vendor's website being reachable is not a capability.

DWG -> DXF fed the geometry reader we already trust, through the ODA File Converter: free,
batch, offline. And the download host is blocked on the machine that needs it — browser,
phone and `winget install ODA.ODAFileConverter` all fail the same way (0x80072efd,
ERROR_INTERNET_CANNOT_CONNECT). So on the one machine where this matters, the answer to
"install the converter" was "you cannot", and four drawings stayed unread.

THE SECOND BACKEND WAS ALREADY PAID FOR. The runner must have a licensed interactive
SolidWorks seat regardless — Excel and SOLIDWORKS are driven over COM on a real desktop, which
is the whole reason it cannot be a Windows service. A machine that can estimate can convert.
ODA stays first when present: it is faster per file, needs no seat, and does not compete with
the estimate for the same session.

WHAT THIS FILE DOES NOT PROVE. The COM call itself cannot be exercised here — there is no
SolidWorks on this machine, and the import-wizard toggles are version-dependent. What is
guarded is everything around it: that the second backend is reached, that a failure costs the
DWGs and never the estimate, that a partial conversion is reported as partial, and that the
document is closed whatever happens. The first real run needs watching.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import cad_inputs  # noqa: E402


@pytest.fixture()
def folder(tmp_path):
    (tmp_path / "11650-04-SA01 SIDE PANEL_revB.DWG").write_bytes(b"dwg")
    (tmp_path / "11650-04-SIDE PANELS_revF.DWG").write_bytes(b"dwg")
    return tmp_path


def _writes_dxf(dwg: Path, dxf: Path) -> bool:
    dxf.write_text("0\nSECTION\n", encoding="utf-8")
    return True


# ── the second backend is reached ────────────────────────────────────────────────────

def test_solidworks_converts_when_oda_is_not_installed(folder):
    out = cad_inputs.convert_dwgs(folder, solidworks=_writes_dxf)
    assert out["backend"] == "solidworks"
    assert len(out["converted"]) == 2
    assert not out["reason"], "a complete conversion has nothing to explain"


def test_the_backend_is_named_so_a_reader_knows_which_tool_drew_the_outline(folder):
    """They are not identical in fidelity. A geometry question six months from now deserves
    to know which one produced the DXF."""
    out = cad_inputs.convert_dwgs(folder, solidworks=_writes_dxf)
    assert out["backend"] == "solidworks"


def test_nothing_is_attempted_when_there_are_no_dwgs(tmp_path):
    calls = []
    cad_inputs.convert_dwgs(tmp_path, solidworks=lambda d, x: calls.append(d))
    assert calls == [], "a folder with no DWGs must not wake a CAD seat"
    # ASKED OF THE CONVERTER DIRECTLY TOO. convert_dwgs has its own early return, so going
    # only through it leaves this guard untested — and this is a public function that a
    # future caller will reach with an empty list on a machine where waking SolidWorks costs
    # thirty seconds and a licence check.
    out = cad_inputs.convert_dwgs_with_solidworks([], tmp_path / "out",
                                                  export=lambda d, x: calls.append(d))
    assert calls == []
    assert out["converted"] == [] and not out["reason"]


def test_the_converted_files_land_where_the_engine_looks(folder):
    out = cad_inputs.convert_dwgs(folder, solidworks=_writes_dxf)
    for path in out["converted_paths"]:
        assert Path(path).is_file()
        assert Path(path).suffix == ".dxf"


# ── failure costs the DWGs, never the estimate ───────────────────────────────────────

def test_a_seat_that_refuses_is_reported_not_raised(folder):
    def busy(dwg, dxf):
        raise RuntimeError("seat busy")
    out = cad_inputs.convert_dwgs(folder, solidworks=busy)
    assert out["converted"] == []
    assert "could not convert" in out["reason"]
    assert "seat busy" in out["reason"], "the reason a person can act on is the real one"


def test_a_partial_conversion_says_it_was_partial(folder):
    """Silently returning one DXF out of two reads as "the DWGs are handled" while half the
    geometry is still unread."""
    def one_only(dwg, dxf):
        if dwg.name.startswith("11650-04-SA01"):
            dxf.write_text("x", encoding="utf-8")
            return True
        return False
    out = cad_inputs.convert_dwgs(folder, solidworks=one_only)
    assert len(out["converted"]) == 1
    assert "1 of 2" in out["reason"]
    assert "would not open" in out["reason"]


def test_a_backend_that_claims_success_without_writing_anything_is_not_believed(folder):
    """The file on disk is the evidence, not the return value. A converter reporting success
    and producing nothing would have the engine list DXFs that are not there."""
    out = cad_inputs.convert_dwgs(folder, solidworks=lambda dwg, dxf: True)
    assert out["converted"] == []
    assert out["reason"]


def test_solidworks_can_be_refused_outright(folder):
    """For a machine where the seat is needed for something else, or where this has not been
    proven yet. It falls back to exactly the message it gave before there was a second
    backend."""
    out = cad_inputs.convert_dwgs(folder, solidworks=False)
    assert out["converted"] == []
    assert "ODA File Converter was not located" in out["reason"]


# ── the COM call itself, as far as it can be checked here ────────────────────────────

def test_the_document_is_closed_whatever_happens():
    """This runs on somebody's actual desktop beside the estimate using the same seat. A
    drawing left open puts a modal dialog in front of the next COM call the engine makes —
    a failure that gets blamed on the estimate rather than on this."""
    import inspect
    src = inspect.getsource(cad_inputs._solidworks_dxf_export)
    assert "finally:" in src
    assert src.index("finally:") < src.index("CloseDoc")


def test_the_import_wizard_toggles_are_attempted_and_not_depended_on():
    """The numbers move between SolidWorks releases. Shown, the wizard blocks on a desktop
    nobody is watching; a wrong toggle number must not be fatal in its own right."""
    import inspect
    src = inspect.getsource(cad_inputs._solidworks_dxf_export)
    assert "SetUserPreferenceToggle" in src
    wizard = src[src.index("SetUserPreferenceToggle"):]
    assert "except Exception" in wizard[:400], "a rejected toggle must not end the conversion"


def test_it_opens_the_dwg_read_only():
    """A conversion that modifies the customer's drawing is not a conversion."""
    import inspect
    src = inspect.getsource(cad_inputs._solidworks_dxf_export)
    assert "OPEN_SILENT_READONLY = 1 | 2" in src


def test_the_real_export_is_only_used_when_nothing_was_injected():
    import inspect
    src = inspect.getsource(cad_inputs.convert_dwgs_with_solidworks)
    assert "export or _solidworks_dxf_export" in src
