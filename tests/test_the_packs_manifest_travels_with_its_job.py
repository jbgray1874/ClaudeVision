"""THE PACK'S MANIFEST TRAVELS WITH ITS JOB (12 Nov 2026).

Every run on the laptop listed "manifest False": the pack resolver read the design share, its
findings chose the files, and then they were dropped. The covering note could only say "No
pack manifest was saved with this job, so missing references are not known here."

The watcher now sends what the resolver found with the job, and the service files it beside
the staged drawings, where the note already looks.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
BACKEND = ROOT / "sdi-intelligence-backend"

import live_enquiry_runner as L  # noqa: E402
import pack_used  # noqa: E402


def _found(**over):
    m = {"status": "provisional", "price_ok": True, "drawing": "12674-02-GA", "question": "",
         "references_read": True, "missing": ["12674-01-09J", "12674-02-01J"],
         "members": [{"drawing": "12674-02-GA", "referenced_by_ga": True,
                      "files": [{"path": Path("x/12674-02-GA.pdf")}]}]}
    m.update(over)
    return m


def test_the_manifest_that_travels_is_plain_json_and_says_where_the_files_came_from():
    out = L.carried_manifest(_found(), "the estimator's Live Enquiry folder")
    assert json.loads(json.dumps(out)) == out, "a path object would not cross HTTP"
    assert out["staged_from"] == "the estimator's Live Enquiry folder"
    assert out["references_read"] is True


def test_a_reference_the_estimators_folder_holds_is_not_missing_from_the_job():
    out = L.carried_manifest(_found(), "the folder", held=["12674-02-01J"])
    assert out["missing"] == ["12674-01-09J"]


def test_the_request_carries_the_manifest_and_a_job_with_none_says_none():
    class Row:
        customer, drawing = "A Customer", "12674-02-GA"
    class D:
        row, quantities = Row(), [1, 8]
        located = L.Located("found", "found", folder=Path("/share/A/12674-02-GA"),
                            manifest=L.carried_manifest(_found(), "the folder"))
    assert L.request_body(D(), ["a@b.c"])["pack_manifest"]["missing"] == ["12674-01-09J", "12674-02-01J"]
    D.located = L.Located("found", "found", folder=Path("/share/A/12674-02-GA"))
    assert L.request_body(D(), ["a@b.c"])["pack_manifest"] is None


def test_the_note_names_what_the_pack_lacks_once_the_manifest_is_in_the_job_folder(tmp_path):
    (tmp_path / "pack_manifest.json").write_text(json.dumps(
        L.carried_manifest(_found(), "the folder")), encoding="utf-8")
    g = pack_used.gather({"job_folder": str(tmp_path)})
    assert g["has_manifest"] and g["missing"] == ["12674-01-09J", "12674-02-01J"]
    assert g["parts_list_read"] is True
    assert not pack_used.gather({"job_folder": str(tmp_path / "none")})["has_manifest"]


def test_the_service_files_the_manifest_beside_the_staged_drawings_and_clears_an_old_one():
    src = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    at = src.index('_pack_manifest = Path(folder) / "pack_manifest.json"')
    block = src[at:at + 520]
    assert "if req.pack_manifest:" in block and "_pack_manifest.write_text(json.dumps(req.pack_manifest" in block
    assert "_pack_manifest.unlink()" in block, "an earlier run's manifest never describes this one"
    assert src.index('staged = staging.stage(_sources, client=client, drawing=drawing)') < at
    assert "pack_manifest: Optional[Dict[str, Any]] = None" in src
