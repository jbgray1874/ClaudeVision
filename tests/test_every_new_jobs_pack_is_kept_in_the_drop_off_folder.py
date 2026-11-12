"""EVERY NEW JOB'S DRAWING PACK IS ALSO KEPT IN THE DROP-OFF FOLDER (JG, 12 Nov 2026).

"We should auto create a client name folder where none exists at the time of creation of the
job, then a folder below that with the job number / name identifier and all the drawings."
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "sdi-intelligence-backend"
sys.path.insert(0, str(BACKEND))

import pack_dropoff as D  # noqa: E402


def _staged(tmp_path):
    s = tmp_path / "staging" / "A Customer" / "12345-01-GA"
    s.mkdir(parents=True)
    for n in ("12345-01-GA_revB.pdf", "12345-01-01M.DXF", "12345-01-02M.SLDPRT", "pack_manifest.json",
              "CONCEPT_DOCUMENT.json", "ENQUIRY_BRIEF.txt"):
        (s / n).write_text(n)
    return s


def _drop(tmp_path, monkeypatch):
    d = tmp_path / "repo" / "chatgptdropoff"
    d.mkdir(parents=True)
    monkeypatch.delenv("SDI_PACK_DROPOFF_DIR", raising=False)
    return d


def test_the_client_folder_is_made_and_the_job_folder_holds_every_drawing(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    got = D.save(_staged(tmp_path), "A Customer", "12345-01-GA", tmp_path / "repo")
    assert got["saved"] and Path(got["folder"]) == drop / "A Customer" / "12345-01-GA"
    assert sorted(p.name for p in (drop / "A Customer" / "12345-01-GA").iterdir()) == [
        "12345-01-01M.DXF", "12345-01-02M.SLDPRT", "12345-01-GA_revB.pdf", "pack_manifest.json"]


def test_a_second_job_for_the_client_goes_beside_the_first(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    s = _staged(tmp_path)
    D.save(s, "A Customer", "12345-01-GA", tmp_path / "repo")
    D.save(s, "A Customer", "12345-02-GA", tmp_path / "repo")
    assert sorted(p.name for p in (drop / "A Customer").iterdir()) == ["12345-01-GA", "12345-02-GA"]


def test_running_the_job_again_replaces_its_files_and_deletes_nothing(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    s = _staged(tmp_path)
    D.save(s, "A Customer", "12345-01-GA", tmp_path / "repo")
    kept = drop / "A Customer" / "12345-01-GA" / "a note somebody left.txt"
    kept.write_text("mine")
    (s / "12345-01-01M.DXF").unlink()
    (s / "12345-01-GA_revB.pdf").write_text("a later issue")
    D.save(s, "A Customer", "12345-01-GA", tmp_path / "repo")
    dest = drop / "A Customer" / "12345-01-GA"
    assert (dest / "12345-01-GA_revB.pdf").read_text() == "a later issue"
    assert kept.read_text() == "mine" and (dest / "12345-01-01M.DXF").exists(), "nothing is deleted"


def test_a_machine_with_no_drop_off_folder_keeps_none_and_none_is_made(tmp_path, monkeypatch):
    monkeypatch.delenv("SDI_PACK_DROPOFF_DIR", raising=False)
    got = D.save(_staged(tmp_path), "A Customer", "12345-01-GA", tmp_path / "repo")
    assert not got["saved"] and "no drop-off folder" in got["why"]
    assert not (tmp_path / "repo").exists()


def test_it_can_be_pointed_elsewhere_or_switched_off(tmp_path, monkeypatch):
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", str(other))
    assert D.save(_staged(tmp_path), "A Customer", "12345-01-GA", tmp_path / "repo")["saved"]
    assert (other / "A Customer" / "12345-01-GA" / "12345-01-GA_revB.pdf").exists()
    monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", "off")
    assert D.root(tmp_path / "repo") is None


def test_a_drop_off_that_cannot_be_written_never_stops_the_job(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    (drop / "A Customer").write_text("a file where the client folder should be")
    got = D.save(_staged(tmp_path), "A Customer", "12345-01-GA", tmp_path / "repo")
    assert got["saved"] is False and got["why"]


def test_the_folder_names_are_the_safe_ones_the_service_files_under(tmp_path, monkeypatch):
    drop = _drop(tmp_path, monkeypatch)
    D.save(_staged(tmp_path), "M&S", "12345/01", tmp_path / "repo", safe=lambda t: str(t).replace("/", "-"))
    assert (drop / "M&S" / "12345-01").is_dir()


def test_the_service_drops_the_pack_when_the_job_is_made_and_the_suite_never_writes_here():
    src = (BACKEND / "estimate_routes.py").read_text(encoding="utf-8")
    at = src.index("pack_dropoff.save(folder, client, drawing, _REPO_ROOT, safe=safe_segment)")
    assert src.index("staged = staging.stage(_sources, client=client, drawing=drawing)") < at
    assert src.index('_pack_manifest = Path(folder) / "pack_manifest.json"') < at, "the manifest is filed first, so it is kept too"
    assert 'monkeypatch.setenv("SDI_PACK_DROPOFF_DIR", "off")' in (ROOT / "tests" / "conftest.py").read_text()


def test_client_folders_under_the_drop_off_are_never_committed():
    out = subprocess.run(["git", "check-ignore", "chatgptdropoff/A Customer/12345-01-GA/x.SLDPRT"],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, "drawings are customer data"
