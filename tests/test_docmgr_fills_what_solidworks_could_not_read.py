"""SolidWorks read some of the models and not the rest: the Document Manager reads the rest (D-706).

SCRUM-184 added the backup for a run in which the SolidWorks worker could not run at all. JG
asked for the check to hold mid-run too: a seat that drops out partway through a batch, a model
open in a designer's session, a file SolidWorks will not open. The worker still exits zero with
the files it reached, so the whole-job fallback never fired and those files stayed unread.

With SDI_SW_DOCMGR=1 the connector now asks the Document Manager for exactly the files the worker
opened and got nothing from, in the same run. Their records take the place of the failures;
every file SolidWorks did read keeps its values; the worker's extract is never rewritten, so the
next run with a healthy seat reads those files again.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "solidworks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from source_connectors import solidworks as sw          # noqa: E402
import invariants as inv                                # noqa: E402
import sw_docmgr_analyse as dm                          # noqa: E402
import test_a_docmgr_extract_backs_up_solidworks as base  # noqa: E402

A, B = "12345-01-01M", "12345-01-02M"


# ── the reader reads only the files it is asked for ──────────────────────────────────

def test_the_reader_reads_only_the_files_asked_for(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(dm.KEY_ENV, base.KEY)
    folder, app = base._job(tmp_path)
    out = tmp_path / "topup.json"
    only = folder / f"{B}.SLDPRT"
    assert dm.main([str(folder), "--out", str(out), "--only", str(only)],
                   class_factory=base.FakeFactory(app)) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert [Path(r["path"]).name for r in payload["records"]] == [f"{B}.SLDPRT"]
    assert payload["_manifest"]["only"] == [str(only)]
    assert payload["_manifest"]["generated_from"] == str(folder), \
        "the folder is still fingerprinted whole, as the SolidWorks extract's is"


def test_a_long_list_comes_from_a_file(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv(dm.KEY_ENV, base.KEY)
    folder, app = base._job(tmp_path)
    lst = tmp_path / "files.txt"
    lst.write_text(f"{folder / (A + '.SLDPRT')}\n{folder / (B + '.SLDPRT')}\n", encoding="utf-8")
    out = tmp_path / "topup.json"
    assert dm.main([str(folder), "--out", str(out), "--only-from", str(lst)],
                   class_factory=base.FakeFactory(app)) == 0
    names = sorted(Path(r["path"]).name for r in json.loads(out.read_text())["records"])
    assert names == [f"{A}.SLDPRT", f"{B}.SLDPRT"]


def test_a_file_named_by_another_drive_is_matched_by_name_and_never_guessed():
    found = [r"\\srv\share\job\12345-01-01M.SLDPRT", r"\\srv\share\job\sub\12345-01-02M.SLDPRT",
             r"\\srv\share\job\a\X.SLDPRT", r"\\srv\share\job\b\X.SLDPRT"]
    assert dm.select_only(found, [r"K:\job\12345-01-01M.SLDPRT"]) == [found[0]]
    assert dm.select_only(found, [r"K:\job\X.SLDPRT"]) == [], "two files of one name: neither"


# ── the connector fills the failures in the same run ─────────────────────────────────

def _ok(title):
    return base._com_records(title)[0] | {"path": f"{title}.SLDPRT"}


def _failed(title):
    return {"path": f"{title}.SLDPRT", "errors": ["(-2147023170, 'The remote procedure call "
                                                  "failed.')"]}


@pytest.fixture()
def two_models(tmp_path):
    folder = tmp_path / "job"
    folder.mkdir()
    for t in (A, B):
        (folder / f"{t}.SLDPRT").write_bytes(b"\x00SLDPRT")
    return folder


@pytest.fixture()
def partial_run(monkeypatch):
    """SolidWorks reads A and loses B; the Document Manager reads whatever it is asked for."""
    calls = {"com": 0, "docmgr": []}
    behaviour = {"docmgr_error": None, "docmgr_writes": True, "com_records": None}

    def _com(folder, analyser=None, python_exe=None, out_path=None, produced=None, turn=None):
        calls["com"] += 1
        recs = behaviour["com_records"] or [_ok(A), _failed(B)]
        base._write_extract(out_path, recs, folder)
        # The coverage the real analyser writes into its manifest.
        payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
        bad = [r for r in recs if r.get("errors")]
        payload["_manifest"].update({
            "files_seen": len(recs), "files_read": len(recs) - len(bad),
            "files_failed": len(bad),
            "errors": [{"path": r["path"], "errors": r["errors"]} for r in bad]})
        Path(out_path).write_text(json.dumps(payload), encoding="utf-8")
        return None                                  # a partial run still exits zero

    def _docmgr(folder, analyser=None, python_exe=None, out_path=None, produced=None,
                extra_args=None):
        args = list(extra_args or [])
        asked = (Path(args[args.index("--only-from") + 1]).read_text(encoding="utf-8")
                 .split() if "--only-from" in args else [])
        calls["docmgr"].append({"out": str(out_path), "asked": asked})
        if behaviour["docmgr_writes"] and out_path:
            recs = [base._docmgr_records(Path(p).stem)[0] for p in asked]
            base._write_extract(out_path, recs, folder, reader=dm.READER)
            payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
            payload["_manifest"]["only"] = asked
            Path(out_path).write_text(json.dumps(payload), encoding="utf-8")
        return behaviour["docmgr_error"]

    monkeypatch.setattr(sw, "_run_analyser", _com)
    monkeypatch.setattr(sw, "_run_docmgr_analyser", _docmgr)
    monkeypatch.setattr(sw, "solidworks_com_available", lambda: (True, ""))
    monkeypatch.delenv("SDI_SW_DOCMGR", raising=False)
    return calls, behaviour


def test_the_files_solidworks_lost_are_read_by_the_backup_in_the_same_run(two_models,
                                                                         partial_run,
                                                                         monkeypatch):
    calls, _ = partial_run
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    job = sw.native_extract_for_job(folder=two_models, run=True)
    assert calls["com"] == 1 and len(calls["docmgr"]) == 1
    assert calls["docmgr"][0]["asked"] == [f"{B}.SLDPRT"], "only the file SolidWorks lost"
    assert calls["docmgr"][0]["out"].endswith(sw.DOCMGR_TOPUP_FILENAME)
    assert job.meta["docmgr_topped_up"] == [f"{B}.SLDPRT"]
    assert job.meta["files_failed"] == 0 and job.meta["files_read"] == 2
    assert not job.meta["extract_errors"]
    assert job.meta["extract_reader"] == "mixed"
    assert job.part_signals[A].source == sw.SOURCE_NAME, "SolidWorks keeps what it read"
    assert job.part_signals[B].source == sw.DOCMGR_SOURCE_NAME
    assert "could not read 1 of 2" in job.meta["docmgr_backup_reason"]
    com = json.loads((two_models / sw.EXTRACT_FILENAME).read_text(encoding="utf-8"))
    assert any(r.get("errors") for r in com["records"]), \
        "the worker's extract is left as it wrote it, so a healthy seat reads B next time"


def test_the_estimate_warns_and_no_longer_blocks_on_the_lost_file(two_models, partial_run,
                                                                  monkeypatch):
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    job = sw.native_extract_for_job(folder=two_models, run=True)
    node = {"found": True, "files_read": job.meta["files_read"],
            "files_failed": job.meta["files_failed"],
            "extract_errors": job.meta["extract_errors"], **sw.extract_reader_summary(job)}
    got = {v["code"]: v for v in inv.check_native_evidence_is_current(
        {"solidworks_native": node})}
    assert "native_extract_partial" not in got
    assert got["native_extract_from_docmgr"]["severity"] == inv.WARNING
    assert f"{B}.SLDPRT" in got["native_extract_from_docmgr"]["message"]


def test_with_the_switch_off_the_lost_file_stays_lost_and_blocks(two_models, partial_run):
    calls, _ = partial_run
    job = sw.native_extract_for_job(folder=two_models, run=True)
    assert calls["docmgr"] == []
    assert job.meta["files_failed"] == 1 and "docmgr_topped_up" not in job.meta
    node = {"found": True, "files_read": job.meta["files_read"],
            "files_failed": job.meta["files_failed"],
            "extract_errors": job.meta["extract_errors"]}
    got = {v["code"]: v for v in inv.check_native_evidence_is_current(
        {"solidworks_native": node})}
    assert got["native_extract_partial"]["severity"] == inv.BLOCKING


def test_a_top_up_of_the_same_failures_is_reused(two_models, partial_run, monkeypatch):
    calls, _ = partial_run
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    sw.native_extract_for_job(folder=two_models, run=True)
    job = sw.native_extract_for_job(folder=two_models, run=True)
    assert len(calls["docmgr"]) == 1, "the same failures of the same files are not read twice"
    assert job.meta["docmgr_ran"] is False and job.meta["docmgr_topped_up"] == [f"{B}.SLDPRT"]


def test_a_backup_that_fails_leaves_the_lost_file_reported(two_models, partial_run,
                                                           monkeypatch):
    calls, behaviour = partial_run
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    behaviour["docmgr_writes"] = False
    behaviour["docmgr_error"] = "SDI_SW_DOCMGR_KEY is not set"
    job = sw.native_extract_for_job(folder=two_models, run=True)
    assert job.meta["files_failed"] == 1 and "docmgr_topped_up" not in job.meta
    assert job.meta["docmgr_error"] == "SDI_SW_DOCMGR_KEY is not set"
    assert not job.meta.get("analyser_error"), "SolidWorks itself ran; it is not its failure"


def test_a_file_solidworks_read_in_part_keeps_the_worker_values(two_models, partial_run,
                                                                monkeypatch):
    calls, behaviour = partial_run
    monkeypatch.setenv("SDI_SW_DOCMGR", "1")
    partly = _ok(B) | {"errors": ["bbox: timed out"]}
    behaviour["com_records"] = [_ok(A), partly]
    job = sw.native_extract_for_job(folder=two_models, run=True)
    assert calls["docmgr"] == [], "the backup has less to offer on that file, never more"
    assert job.part_signals[B].source == sw.SOURCE_NAME
