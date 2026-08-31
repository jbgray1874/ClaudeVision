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


def test_the_call_does_only_what_is_documented():
    """This test used to require the OPPOSITE — that unverified preference toggles were sent
    and wrapped in try/except. They were 226 and 227, guessed at, and they faulted the COM
    server rather than raising: four DWGs, four identical RPC_S_CALL_FAILED, one dead session
    shared with the estimate.

    The rule the file now holds to is narrower and correct: open the document, save it, close
    it. If the import wizard turns out to block on a real seat, the toggle that suppresses it
    gets looked up for that SolidWorks release and verified against it — not guessed at
    because a try/except made guessing feel free."""
    import inspect
    src = inspect.getsource(cad_inputs._solidworks_dxf_export)
    assert "OpenDoc6" in src and "SaveAs" in src and "CloseDoc" in src


def test_it_opens_the_dwg_read_only():
    """A conversion that modifies the customer's drawing is not a conversion."""
    import inspect
    src = inspect.getsource(cad_inputs._solidworks_dxf_export)
    assert "OPEN_SILENT_READONLY = 1 | 2" in src


def test_the_real_export_is_only_used_when_nothing_was_injected():
    import inspect
    src = inspect.getsource(cad_inputs.convert_dwgs_with_solidworks)
    assert "export or _solidworks_dxf_export" in src


# ── you can check what happened to each drawing ──────────────────────────────────────
#
# "converted 2 DWG(s)" is a number nobody can act on. It does not say WHICH two, whether the
# other two failed or are 3D, or whether the two that converted were then used for anything.
# A DWG that converts and contributes nothing looks exactly like one that was never in the
# folder — which is the failure this whole module exists to end.

def test_every_dwg_gets_its_own_line_in_the_record(folder):
    out = cad_inputs.convert_dwgs(folder, solidworks=_writes_dxf)
    assert {f["dwg"] for f in out["files"]} == set(out["found"])
    for f in out["files"]:
        assert f["converted"] is True
        assert f["dxf"].endswith(".dxf")
        assert f["backend"] == "solidworks"


def test_a_dwg_that_did_not_convert_says_why_on_its_own_line(folder):
    def one_only(dwg, dxf):
        if dwg.name.startswith("11650-04-SA01"):
            dxf.write_text("x", encoding="utf-8")
            return True
        return False
    files = {f["dwg"]: f for f in
             cad_inputs.convert_dwgs(folder, solidworks=one_only)["files"]}
    good = files["11650-04-SA01 SIDE PANEL_revB.DWG"]
    bad = files["11650-04-SIDE PANELS_revF.DWG"]
    assert good["converted"] and not good["reason"]
    assert not bad["converted"] and "would not open" in bad["reason"]


def test_a_seat_that_throws_records_the_error_against_that_file(folder):
    def busy(dwg, dxf):
        raise RuntimeError("seat busy")
    for f in cad_inputs.convert_dwgs(folder, solidworks=busy)["files"]:
        assert f["converted"] is False
        assert "seat busy" in f["reason"]


def test_a_backend_claiming_success_with_no_file_says_that_specifically(folder):
    """Distinct from "would not open". One is a broken DWG, the other is a converter lying —
    and they send a person to different places."""
    for f in cad_inputs.convert_dwgs(folder, solidworks=lambda d, x: True)["files"]:
        assert "wrote no DXF" in f["reason"]


def test_the_oda_account_is_reconstructed_per_file(folder, monkeypatch):
    """ODA converts a FOLDER and reports an exit code, so which file produced which DXF has
    to be recovered by stem — the only thing it tells us. A DWG with no DXF of its own name
    did not convert, whatever the exit code said."""
    out_dir = folder / "_dxf_from_dwg"

    def fake_oda(cmd):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "11650-04-SA01 SIDE PANEL_revB.dxf").write_text("x", encoding="utf-8")
        return 0

    out = cad_inputs.convert_dwgs(folder, runner=fake_oda, converter="X")
    assert out["backend"] == "oda"
    files = {f["dwg"]: f for f in out["files"]}
    assert files["11650-04-SA01 SIDE PANEL_revB.DWG"]["converted"] is True
    missed = files["11650-04-SIDE PANELS_revF.DWG"]
    assert missed["converted"] is False
    assert "3D DWG" in missed["reason"]


def test_the_console_reports_each_file_rather_than_a_count():
    """Read off main.py, because this is the only place a person sees it during a run."""
    src = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text(encoding="utf-8")
    assert "NOT CONVERTED" in src
    assert 'for _f in (_cad_conv.get("files") or [])' in src


def test_a_converted_drawing_sheet_is_reported_as_converted_but_unused():
    """Refusing a converted GA as a flat pattern is the CORRECT outcome. Reported as a bare
    count it reads as a failure — or worse, the conversion reads as a success that fed the
    estimate when it fed nothing."""
    src = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text(encoding="utf-8")
    assert "used_for_geometry" in src
    assert "not a part flat pattern" in src


# ── a faulted COM session is one event, not four ─────────────────────────────────────
#
# 11650-04 reported the identical -2147023170 (RPC_S_CALL_FAILED) against all four DWGs. The
# session died on the first file and the other three were calls into a corpse — four alarming
# lines describing one event. And it is the ESTIMATE'S OWN SolidWorks session: continuing to
# hammer it is how a converter takes down the run it was meant to help.

class _ComError(Exception):
    pass


def _com_fault(*_a):
    raise _ComError(-2147023170, "The remote procedure call failed.", None, None)


def test_a_com_fault_stops_the_batch_rather_than_repeating(folder):
    tried = []

    def fault(dwg, dxf):
        tried.append(dwg.name)
        _com_fault()

    out = cad_inputs.convert_dwgs(folder, solidworks=fault)
    assert len(tried) == 1, "the session was dead after the first call; asking again is noise"
    assert out["converted"] == []


def test_the_files_not_attempted_say_so_rather_than_claiming_they_failed(folder):
    def fault(dwg, dxf):
        _com_fault()
    files = cad_inputs.convert_dwgs(folder, solidworks=fault)["files"]
    attempted = [f for f in files if "not attempted" not in f["reason"]]
    skipped = [f for f in files if "not attempted" in f["reason"]]
    assert len(attempted) == 1 and len(skipped) == 1
    assert "faulted" in skipped[0]["reason"]


def test_the_reason_describes_the_session_not_a_list_of_identical_errors(folder):
    def fault(dwg, dxf):
        _com_fault()
    reason = cad_inputs.convert_dwgs(folder, solidworks=fault)["reason"]
    assert "COM session faulted" in reason
    assert "check the SolidWorks window" in reason
    assert "estimate is unaffected" in reason


def test_a_fault_is_recognised_by_its_code_and_not_only_its_wording(folder):
    """A COM error's TEXT is localised and varies by fault; its HRESULT does not.
    -2147417848 is "the object invoked has disconnected from its clients" — a dead session
    that says nothing about remote procedure calls, and one that a message-only check would
    hammer three more times."""
    tried = []

    def disconnected(dwg, dxf):
        tried.append(dwg.name)
        raise _ComError(-2147417848, "The object invoked has disconnected from its clients.",
                        None, None)

    out = cad_inputs.convert_dwgs(folder, solidworks=disconnected)
    assert len(tried) == 1
    assert "COM session faulted" in out["reason"]


def test_an_ordinary_refusal_does_not_stop_the_batch(folder):
    """A DWG SolidWorks will not open is a fact about that file. Treating it like a dead
    session would abandon every drawing after the first awkward one."""
    tried = []

    def picky(dwg, dxf):
        tried.append(dwg.name)
        raise ValueError("not a drawing")

    cad_inputs.convert_dwgs(folder, solidworks=picky)
    assert len(tried) == 2


def test_no_unverified_preference_ids_are_sent_to_solidworks():
    """THE ACTUAL CAUSE. Two swUserPreferenceToggle_e ids were guessed at and wrapped in
    try/except on the assumption a wrong one raises cleanly. It does not — it faults the COM
    server, and that server is shared with the estimate. A constant nobody has verified is
    not a guess with a safety net; it is an instruction to a program that does what it is
    told."""
    import inspect
    src = inspect.getsource(cad_inputs._solidworks_dxf_export)
    assert "SetUserPreferenceToggle" not in src
    assert "SetUserPreferenceIntegerValue" not in src


def test_solidworks_is_attached_to_and_never_launched():
    """NEVER LAUNCH IS THE INVARIANT. "Never call Dispatch" was how it used to be written, and
    that turned out to be the mechanism rather than the property.

    Dispatch() returns a running SolidWorks if one is registered and STARTS ONE if not —
    hidden, prone to a licence prompt nobody can see, and a second seat competing with the
    estimate for the same desktop. GetActiveObject only ever attaches, so it was the safe call
    and Dispatch was banned outright.

    THEN A REINSTALL BROKE THE OTHER REGISTRATION. GetActiveObject reads the Running Object
    Table; Dispatch goes through the class registration (CLSID / LocalServer32). On SDI's
    machine the reinstall left the class registration working and the ROT not, so every report
    from 30 August carried -2147221021 from this line while a plain
    `Dispatch('SldWorks.Application')` attached first time — on a job whose only geometry is
    the models. A ban on the mechanism cost the engine the seat it was paying for.

    So Dispatch is allowed, and the hazard is answered directly: it may only be reached when
    SLDWORKS.exe is ALREADY RUNNING, and with a process up CoCreateInstance binds to the
    running server instead of starting one. A genuinely closed seat still comes back as the
    sentence it always did."""
    import inspect
    src = inspect.getsource(cad_inputs._solidworks_dxf_export)
    assert "GetActiveObject" in src, "the attach-first lookup is gone"
    assert "is not running on this machine" in src

    # Dispatch is permitted ONLY behind the already-running check. Both must be present, and
    # the guard must come first in the source, or the ban has simply been lifted.
    if 'Dispatch("SldWorks.Application")' in src:
        assert "solidworks_processes()" in src, (
            "Dispatch is reachable with nothing running — it will START a hidden SolidWorks")
        assert src.index("solidworks_processes()") < src.index(
            'Dispatch("SldWorks.Application")'), (
            "the already-running check does not gate the Dispatch call")


def test_the_fallback_cannot_be_reached_when_no_seat_is_running():
    """THE HAZARD THE OLD BAN EXISTED FOR. With no SolidWorks up, Dispatch starts one: hidden,
    unlicensed-prompt-prone, and competing with the estimate for the desktop. The guard is the
    whole reason the ban could be lifted, so it is asserted on its own rather than only as an
    ordering."""
    import inspect
    src = inspect.getsource(cad_inputs._solidworks_dxf_export)
    at = src.find('Dispatch("SldWorks.Application")')
    if at == -1:
        return                                    # no fallback present; nothing to guard
    window = src[max(0, at - 400):at]
    assert "if solidworks_processes():" in window, (
        "nothing between the ROT failure and the Dispatch call establishes that a seat is "
        "already up")


def test_a_faulted_seat_is_not_restarted_behind_the_estimate():
    """Bringing SolidWorks back up is a large side effect on a machine whose whole job is one
    interactive seat, and the estimate may be mid-COM-call on it. A converter that reboots the
    tool the run depends on is a worse failure than four unread drawings."""
    import inspect
    src = inspect.getsource(cad_inputs.convert_dwgs_with_solidworks)
    assert "restart" not in src.lower().replace("restarted automatically", "")
