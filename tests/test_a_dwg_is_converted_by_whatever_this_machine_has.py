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
    """Dispatch() returns a running SolidWorks if one is registered and STARTS ONE if not —
    hidden, prone to a licence prompt nobody can see, and a second seat competing with the
    estimate for the same desktop. GetActiveObject only ever attaches, so "not running" comes
    back as that sentence rather than as a mysterious new process."""
    import inspect
    src = inspect.getsource(cad_inputs._solidworks_dxf_export)
    assert "GetActiveObject" in src
    assert 'Dispatch("SldWorks.Application")' not in src
    assert "is not running on this machine" in src


def test_a_faulted_seat_is_not_restarted_behind_the_estimate():
    """Bringing SolidWorks back up is a large side effect on a machine whose whole job is one
    interactive seat, and the estimate may be mid-COM-call on it. A converter that reboots the
    tool the run depends on is a worse failure than four unread drawings."""
    import inspect
    src = inspect.getsource(cad_inputs.convert_dwgs_with_solidworks)
    assert "restart" not in src.lower().replace("restarted automatically", "")


# ── a general arrangement is not worth a CAD seat ────────────────────────────────────

def test_a_general_arrangement_dwg_is_never_opened(tmp_path):
    """WHAT THIS COST ON 12552, AND WHY IT IS THE FIRST THING THE CONVERTER SHOULD ASK.

    dwg_class has been able to tell a flat pattern from a general arrangement since it was
    written, and its own docstring says a GA "is worth approximately nothing… possibly worth
    less than nothing, if a viewport rectangle is taken for a blank". It was wired to the
    REPORTING and nothing else. Every DWG in the folder was still opened.

    12552's only DWG is 12552-00-GA — the general arrangement, the same sheet as the PDF the
    engine had already read. Opening it faulted the COM server (-2147023170,
    RPC_S_CALL_FAILED) and SolidWorks went down with a crash dialog, taking the seat that the
    NATIVE MODEL EXTRACT needs. On a pack with no DXFs that extract is the only measured
    geometry there is. The engine spent the seat on the file it had already judged worthless
    and lost the one that mattered.

    Reordering would not have helped: it only changes which operation is holding the session
    when the GA faults it. Not opening the file is the fix, and there was never a reason to."""
    (tmp_path / "12552-00-GA_Infinity Drawer_Rev C.DWG").write_bytes(b"dwg")
    calls = []
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=lambda d, x: calls.append(d) or True)
    assert calls == [], "a general arrangement was opened on a CAD seat for nothing"
    assert out["skipped_general_arrangement"] == ["12552-00-GA_Infinity Drawer_Rev C.DWG"]


def test_a_flat_pattern_is_still_converted_beside_a_skipped_ga(tmp_path):
    """The skip must not become "stop converting DWGs". A flat pattern is the strongest input
    this engine can be handed short of a model."""
    (tmp_path / "12552-00-GA_Infinity Drawer_Rev C.DWG").write_bytes(b"dwg")
    (tmp_path / "11650-04-01A_2MM PETG_REVG.DWG").write_bytes(b"dwg")
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=_writes_dxf)
    assert out["converted"] == ["11650-04-01A_2MM PETG_REVG.dxf"]
    assert out["skipped_general_arrangement"] == ["12552-00-GA_Infinity Drawer_Rev C.DWG"]


def test_the_skipped_ga_is_reported_as_skipped_not_as_failed(tmp_path):
    """"Not read" and "not worth reading" are different facts, and an estimator chasing unread
    geometry deserves to know which this is. A GA reported as a failure sends somebody after a
    converter for a file that would add nothing."""
    (tmp_path / "12552-00-GA_Infinity Drawer_Rev C.DWG").write_bytes(b"dwg")
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=_writes_dxf)
    assert not out["reason"], "a deliberate skip is being reported as a conversion failure"
    rec = [f for f in out["files"] if f["dwg"].startswith("12552")][0]
    assert rec["converted"] is False
    assert "general arrangement" in rec["reason"]


def test_the_skipped_rows_share_the_shape_of_every_other_row(tmp_path):
    """A second record shape in one list is how a consumer prints "None -> None" for half the
    rows — which is exactly what the first version of this did."""
    (tmp_path / "12552-00-GA_Infinity Drawer_Rev C.DWG").write_bytes(b"dwg")
    (tmp_path / "11650-04-01A_2MM PETG_REVG.DWG").write_bytes(b"dwg")
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=_writes_dxf)
    assert len(out["files"]) == 2
    for rec in out["files"]:
        assert set(rec) >= {"dwg", "converted", "dxf", "reason"}, rec


def test_a_general_arrangement_with_the_role_glued_on_is_never_opened_either(tmp_path):
    """12645's only DWG is "12645-01GA V2.DWG" — the body's general arrangement, with the role
    glued to the sheet number. The whole-word marker did not see it, so the 18:09 run opened it
    on the seat: with no SolidWorks running the attach failed, and the log told the reader to
    open SolidWorks for a file that was never worth opening. The model extract needs no such
    thing — the analyser starts its own instance — so the instruction sent somebody to fix a
    machine that was fine."""
    (tmp_path / "12645-01GA V2.DWG").write_bytes(b"dwg")
    calls = []
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=lambda d, x: calls.append(d) or True)
    assert calls == [], "a general arrangement was opened on a CAD seat for nothing"
    assert out["skipped_general_arrangement"] == ["12645-01GA V2.DWG"]
    assert not out["reason"], "a deliberate skip is being reported as a conversion failure"


def test_the_skip_names_the_pdf_of_the_same_sheet_when_there_is_one(tmp_path):
    """"The same content as the PDF of this sheet, which was read" was said for every GA,
    whether or not a PDF of it was in the folder. Now it names the one it found — and only a
    PDF of the SAME sheet, by the engine's one resolver, not any PDF in the pack."""
    (tmp_path / "12645-01GA V2.DWG").write_bytes(b"dwg")
    (tmp_path / "12645-01GA V2_REVA.PDF").write_bytes(b"%PDF")
    (tmp_path / "12645-02GA_REVA.PDF").write_bytes(b"%PDF")
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=_writes_dxf)
    rec = out["files"][0]
    assert "12645-01GA V2_REVA.PDF" in rec["reason"] and "which is in the folder" in rec["reason"]
    assert "12645-02GA" not in rec["reason"]
    # PRESENT, NOT "READ". Whether the PDF reader could open it is that reader's fact to
    # state; this step only looked in the folder, and says only that.
    assert "which was read" not in rec["reason"] and "which is read" not in rec["reason"]


def test_two_revisions_of_the_sheet_are_both_named(tmp_path):
    """Naming the alphabetically first match names the superseded revision, in the singular."""
    (tmp_path / "12645-01GA V2.DWG").write_bytes(b"dwg")
    (tmp_path / "12645-01GA V2_REVA.PDF").write_bytes(b"%PDF")
    (tmp_path / "12645-01GA V2_REVB.PDF").write_bytes(b"%PDF")
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=_writes_dxf)
    reason = out["files"][0]["reason"]
    assert "12645-01GA V2_REVA.PDF" in reason and "12645-01GA V2_REVB.PDF" in reason


def test_the_skip_says_when_no_pdf_of_the_sheet_is_in_the_folder(tmp_path):
    """The conclusion is the same — a GA converted to DXF is viewports and text that nothing
    reads as a parts list — but if the sheet was never read at all, the fix is to ask for the
    PDF, not to chase a converter, and the reader deserves to be told which."""
    (tmp_path / "12552-00-GA_Infinity Drawer_Rev C.DWG").write_bytes(b"dwg")
    (tmp_path / "12552-01_2MM MS_REVA.PDF").write_bytes(b"%PDF")
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=_writes_dxf)
    rec = out["files"][0]
    assert "No PDF of this sheet" in rec["reason"] and "ask for the PDF" in rec["reason"]
    assert "which is in the folder" not in rec["reason"]
    assert "general arrangement" in rec["reason"]


def test_a_ga_whose_number_the_engine_cannot_read_claims_nothing_about_the_folder(tmp_path):
    """A reviewer's catch on the first wording: "AC0706-02" is not a drawing number the engine
    reads, so no PDF could be matched — and the skip said "No PDF of this sheet is in the
    folder" with the PDF sitting right there, then told the estimator to ask the customer for
    it. Not knowing and knowing-there-is-none are different facts."""
    (tmp_path / "AC0706-02_BOOTS_GA-REVG.DWG").write_bytes(b"dwg")
    (tmp_path / "AC0706-02_BOOTS_GA-REVG.PDF").write_bytes(b"%PDF")
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=_writes_dxf)
    rec = out["files"][0]
    assert "general arrangement" in rec["reason"]
    assert "not matched to a PDF" in rec["reason"] and "no drawing number" in rec["reason"]
    assert "No PDF of this sheet" not in rec["reason"]
    assert "which is in the folder" not in rec["reason"]
    assert "ask for the PDF" not in rec["reason"]


def test_a_pdf_in_a_subfolder_is_not_this_jobs_pdf(tmp_path):
    """file_scan groups a job's PDFs by their own parent folder, so a PDF under Superseded\\
    belongs to another folder-job, or to none. Naming it as "the PDF of this sheet" would name
    a file this run does not open — and, being the superseded version, the wrong one."""
    (tmp_path / "12645-01GA V2.DWG").write_bytes(b"dwg")
    (tmp_path / "Superseded").mkdir()
    (tmp_path / "Superseded" / "12645-01GA V1_REVA.PDF").write_bytes(b"%PDF")
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=_writes_dxf)
    reason = out["files"][0]["reason"]
    assert "No PDF of this sheet" in reason and "V1_REVA" not in reason


def test_a_folder_that_cannot_be_listed_is_not_reported_as_empty(tmp_path, monkeypatch):
    """A share dropping mid-walk is a failure to look, not an observation that nothing was
    there — and "No PDF … ask for the PDF" is the observation."""
    (tmp_path / "12645-01GA V2.DWG").write_bytes(b"dwg")
    (tmp_path / "12645-01GA V2_REVA.PDF").write_bytes(b"%PDF")

    def _boom(self):
        raise OSError(59, "An unexpected network error occurred")
    monkeypatch.setattr(Path, "iterdir", _boom)
    reason = cad_inputs._skipped_ga_reason(tmp_path / "12645-01GA V2.DWG", tmp_path)
    assert "could not be searched" in reason
    assert "No PDF of this sheet" not in reason and "ask for the PDF" not in reason


def test_a_numbered_role_and_a_top_sheet_are_not_opened_either(tmp_path):
    """"7332-01-GA2" is a job's second general arrangement, and "12645 - DRS External Shelter
    V2" is the shelter's own top sheet. Neither carries the word GA the way the whole-word
    marker wanted it, and both went to the seat."""
    (tmp_path / "7332-01-GA2_revK.dwg").write_bytes(b"dwg")
    (tmp_path / "12645 - DRS External Shelter V2.DWG").write_bytes(b"dwg")
    calls = []
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=lambda d, x: calls.append(d) or True)
    assert calls == []
    assert sorted(out["skipped_general_arrangement"]) == \
        ["12645 - DRS External Shelter V2.DWG", "7332-01-GA2_revK.dwg"]


def test_the_folder_converter_converts_the_ga_anyway_so_its_dxf_is_discarded(tmp_path):
    """ODA takes a wildcard, not a list: "*.DWG" converts every DWG in the folder, skip or no
    skip. The GA's DXF then sat in converted_paths beside the flats — and with the glued
    spelling the DXF gate let it through to the geometry reader. Its row also said "not
    attempted", which it was not."""
    (tmp_path / "12645-01GA V2.DWG").write_bytes(b"dwg")
    (tmp_path / "12645-01-01M_2MM MS_REVA.DWG").write_bytes(b"dwg")

    def fake_oda(cmd):
        src, dst = Path(cmd[1]), Path(cmd[2])
        for d in src.glob("*.DWG"):
            (dst / (d.stem + ".dxf")).write_text("x", encoding="utf-8")
        return 0

    out = cad_inputs.convert_dwgs(tmp_path, runner=fake_oda, converter="X")
    assert out["converted"] == ["12645-01-01M_2MM MS_REVA.dxf"]
    assert all("12645-01GA" not in p for p in out["converted_paths"])
    assert not (tmp_path / "_dxf_from_dwg" / "12645-01GA V2.dxf").exists()
    rec = {f["dwg"]: f for f in out["files"]}["12645-01GA V2.DWG"]
    assert rec["converted"] is False
    assert "discarded" in rec["reason"] and "not attempted" not in rec["reason"]
    assert not out["reason"], "every flat converted; the discarded GA is not a failure"


def test_the_ga_still_appears_in_found(tmp_path):
    """It was in the folder. A file that vanishes from the inventory because the engine chose
    not to open it is the opposite of what this module is for."""
    (tmp_path / "12552-00-GA_Infinity Drawer_Rev C.DWG").write_bytes(b"dwg")
    out = cad_inputs.convert_dwgs(tmp_path, solidworks=_writes_dxf)
    assert out["found"] == ["12552-00-GA_Infinity Drawer_Rev C.DWG"]
