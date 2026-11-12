"""The covering note, and so the e-mail, says which files the estimate was made from (JG, 12 Nov 2026).

Built from the run's own record: files read, models read, models that failed with the reader's
reason, supporting files; and from the pack manifest staged with the job: missing references,
unassigned files, an unread parts list. Not from a folder looked at afterwards."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pack_used as pu  # noqa: E402


def _record():
    return {"cad_inputs": {"read": ["0359829_12674-02-GA_Table_revB.PDF", "12674-02-GA.dxf"],
                           "solidworks": ["12674-01-01J.SLDPRT", "12674-01-02J.SLDPRT", "12674-02-GA.SLDDRW"],
                           "converted": [], "unread": ["12674-02-05J.igs"], "unknown": ["notes.docx"]},
            "solidworks_native": {"extract_reader": "solidworks_api", "extract_errors": [
                {"path": r"\\share\job\12674-01-02J.SLDPRT", "errors": ["OpenDoc6 failed: errs=65536 same title already open"]}]},
            "staged_inputs": [r"\\share\job\0359829_12674-02-GA_Table_revB.PDF"]}


def _manifest():
    return {"status": "provisional", "references_read": True, "missing": ["12674-02-09J"],
            "bought_in_unmatched": ["12674-02-04X"],
            "unassigned_files": [{"path": r"\\share\job\Side panel flat.DXF", "why": "x"}],
            "members": [{"drawing": "12674-02-GA", "revision": "B"}, {"drawing": "12674-01-01J", "revision": "C"}]}


def test_every_input_says_what_became_of_it():
    g = pu.gather(_record(), _manifest())
    by = {r["file"]: r for r in g["rows"]}
    assert by["0359829_12674-02-GA_Table_revB.PDF"]["state"] == "read"
    assert by["0359829_12674-02-GA_Table_revB.PDF"]["drawing"] == "12674-02-GA"
    assert by["0359829_12674-02-GA_Table_revB.PDF"]["revision"] == "B"
    assert by["12674-01-01J.SLDPRT"]["state"] == "read" and by["12674-01-01J.SLDPRT"]["revision"] == "C"
    assert by["12674-01-02J.SLDPRT"]["state"] == "NOT READ" and "65536" in by["12674-01-02J.SLDPRT"]["why"]
    assert by["12674-02-GA.SLDDRW"]["state"] == "supporting"
    assert by["12674-02-05J.igs"]["state"] == "NOT READ"
    assert by["notes.docx"]["state"] == "supporting"
    assert len(g["rows"]) == 7, "a file listed twice by the run appears once"


def test_the_section_shows_failed_reads_missing_references_and_unused_files():
    s = pu.section(_record(), _manifest())
    for text in (s["html"], s["text"]):
        assert "rawing pack used for this estimate".lower() in text.lower()
        assert "12674-01-02J.SLDPRT" in text and "NOT READ" in text
        assert "12674-02-09J" in text and "12674-02-04X" in text
        assert "Side panel flat.DXF" in text
    assert "pack provisional" in s["text"]


def test_an_unread_parts_list_and_a_missing_manifest_are_said():
    s = pu.section(_record(), dict(_manifest(), references_read=False))
    assert "not proved complete" in s["text"]
    s = pu.section(_record(), {})
    assert "No pack manifest was saved" in s["text"]


def test_it_goes_near_the_top_of_the_note_once_and_leaves_the_subject_first():
    note = {"html": "<!-- subject: x -->\n<div style='a'><h1>Estimate</h1></div>", "text": "Estimate"}
    out = pu.into_note(note, _record(), _manifest())
    assert out["html"].startswith("<!-- subject: x -->")
    assert out["html"].index("Drawing pack used") < out["html"].index("<h1>")
    assert out["text"].startswith("DRAWING PACK USED")
    assert pu.into_note(out, _record(), _manifest())["html"] == out["html"]


def test_a_run_that_recorded_no_inputs_adds_nothing():
    note = {"html": "<div>x</div>", "text": "x"}
    assert pu.into_note(note, {}, {}) == note


def test_a_failure_in_the_section_never_stops_the_note(capsys):
    note = {"html": "<div>x</div>", "text": "x"}
    assert pu.into_note_safely(note, {"cad_inputs": "not a dict"}) == note
    assert "no drawing pack section" in capsys.readouterr().out
    src = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text(encoding="utf-8")
    assert "into_note_safely" in src
