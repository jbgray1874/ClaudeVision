"""A staged pack holds the drawings that were selected. The models stay where they live, and
the engine now goes to them.

THE FAILURE THIS ENDS. Staging exists so that what was selected is what gets priced, and it
does that by copying the selection into one folder and pointing the engine at that folder. The
SolidWorks connector looks for models in the folder it was given. An estimator selects
drawings — that is what the picker is for — so the pack contains no models, so the connector
finds none, so the run reports a job with no SolidWorks. 12349-02 was costed from drawings
alone three times in one evening with a complete set of models one folder away.

THE ANSWER IS NOT TO COPY THE MODELS. Away from their own folder an assembly loses the
references that resolve its components; a pack becomes tens of megabytes across a share on
every re-run; and it asks an estimator to know which files the costing engine happens to need.
So staging writes the ADDRESS of the models into the pack, and the connector analyses them in
place — writing the extract into the job folder, so everything downstream is unchanged.

A HINT, NEVER AN INSTRUCTION. A missing, unreadable or malformed pointer file leaves the
connector doing exactly what it did before it existed. A pointer naming a folder with no models
in it is not followed. And a job whose models really are in the pack never consults it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from source_connectors import solidworks as sw                          # noqa: E402


def _model(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00SLDPRT")
    return p


def _pointer(pack: Path, *folders: Path) -> Path:
    pack.mkdir(parents=True, exist_ok=True)
    p = pack / sw.MODEL_SOURCES_FILENAME
    p.write_text(json.dumps({"models_folders": [str(f) for f in folders],
                             "model_count": 1}), encoding="utf-8")
    return p


@pytest.fixture()
def analyser_calls(monkeypatch):
    """Record what the analyser would have been pointed at, and write nothing."""
    calls = []

    def _fake(folder, analyser=None, python_exe=None, out_path=None, produced=None):
        calls.append({"folder": str(folder), "out": str(out_path) if out_path else None})
        return None

    monkeypatch.setattr(sw, "_run_analyser", _fake)
    return calls


# ── the address is read, and the models are analysed where they are ──────────────────────

def test_the_analyser_is_pointed_at_the_folder_the_models_are_in(analyser_calls, tmp_path):
    pack = tmp_path / "staged" / "12349-02"
    pack.mkdir(parents=True)
    (pack / "ga.pdf").write_bytes(b"%PDF")
    models = tmp_path / "design" / "12349-02"
    _model(models / "12349-02-69-03M.SLDPRT")
    _pointer(pack, models)

    sw.native_extract_for_job(folder=pack, run=True)

    assert len(analyser_calls) == 1
    assert analyser_calls[0]["folder"] == str(models)


def test_the_extract_still_lands_in_the_job_folder(analyser_calls, tmp_path):
    """Everything downstream reads it from there. Reading the models elsewhere must not move
    the artefact."""
    pack = tmp_path / "staged" / "12349-02"
    pack.mkdir(parents=True)
    models = tmp_path / "design"
    _model(models / "a.SLDPRT")
    _pointer(pack, models)

    sw.native_extract_for_job(folder=pack, run=True)

    assert analyser_calls[0]["out"] == str(pack / sw.EXTRACT_FILENAME)


def test_the_record_says_where_the_geometry_came_from(analyser_calls, tmp_path):
    pack = tmp_path / "staged" / "12349-02"
    pack.mkdir(parents=True)
    models = tmp_path / "design"
    _model(models / "a.SLDPRT")
    _pointer(pack, models)

    job = sw.native_extract_for_job(folder=pack, run=True)
    assert job.meta.get("models_analysed_from") == str(models)


def test_models_in_the_pack_are_read_where_they_are(analyser_calls, tmp_path):
    """Select the folder and the models come with it. The pointer is not consulted at all."""
    pack = tmp_path / "staged" / "12349-02"
    _model(pack / "12349-02-69-03M.SLDPRT")
    _pointer(pack, tmp_path / "somewhere-else")

    job = sw.native_extract_for_job(folder=pack, run=True)

    assert analyser_calls[0]["folder"] == str(pack)
    assert "models_analysed_from" not in job.meta


# ── a hint that cannot be trusted changes nothing ────────────────────────────────────────

def test_no_pointer_leaves_the_old_behaviour_exactly(analyser_calls, tmp_path):
    pack = tmp_path / "staged" / "12349-02"
    pack.mkdir(parents=True)
    (pack / "ga.pdf").write_bytes(b"%PDF")

    sw.native_extract_for_job(folder=pack, run=True)
    assert analyser_calls[0]["folder"] == str(pack)


def test_a_pointer_to_a_folder_with_no_models_is_not_followed(analyser_calls, tmp_path):
    pack = tmp_path / "staged" / "12349-02"
    pack.mkdir(parents=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    _pointer(pack, empty)

    sw.native_extract_for_job(folder=pack, run=True)
    assert analyser_calls[0]["folder"] == str(pack)


def test_the_first_folder_that_actually_has_models_wins(analyser_calls, tmp_path):
    pack = tmp_path / "staged" / "12349-02"
    pack.mkdir(parents=True)
    empty, real = tmp_path / "empty", tmp_path / "real"
    empty.mkdir()
    _model(real / "a.SLDPRT")
    _pointer(pack, empty, real)

    sw.native_extract_for_job(folder=pack, run=True)
    assert analyser_calls[0]["folder"] == str(real)


def test_a_malformed_pointer_is_ignored_not_raised(tmp_path):
    pack = tmp_path / "staged" / "12349-02"
    pack.mkdir(parents=True)
    for body in ("not json at all", "[]", '{"models_folders": "a string"}',
                 '{"models_folders": [null, 7, ""]}', "{}"):
        (pack / sw.MODEL_SOURCES_FILENAME).write_text(body, encoding="utf-8")
        assert sw.model_source_folders(pack) == [], body


def test_a_pointer_naming_a_folder_that_is_not_there_is_dropped(tmp_path):
    """A drive that is not mapped on the runner, or a folder since renamed."""
    pack = tmp_path / "staged" / "12349-02"
    pack.mkdir(parents=True)
    _pointer(pack, tmp_path / "gone")
    assert sw.model_source_folders(pack) == []


# ── with the analyser off, the models are still known about ──────────────────────────────

def test_models_elsewhere_and_no_extract_is_reported_not_silent(tmp_path, monkeypatch):
    """SDI_SW_RUN_ANALYSER=0 consumes an extract and never invokes COM. That must not turn a
    job with a known set of models into one that says nothing about SolidWorks — which is the
    exact silence the pointer exists to break."""
    pack = tmp_path / "staged" / "12349-02"
    pack.mkdir(parents=True)
    models = tmp_path / "design"
    _model(models / "a.SLDPRT")
    _model(models / "b.SLDASM")
    _pointer(pack, models)

    job = sw.native_extract_for_job(folder=pack, run=False)

    assert job.meta.get("native_present_but_unread") is True
    assert job.meta.get("native_files_present") == 2
    assert str(models) in str(job.meta.get("native_unread_reason"))


def test_a_job_with_no_models_anywhere_still_says_nothing(tmp_path):
    pack = tmp_path / "staged" / "12422"
    pack.mkdir(parents=True)
    (pack / "ga.pdf").write_bytes(b"%PDF")

    job = sw.native_extract_for_job(folder=pack, run=False)
    assert not job.meta.get("native_present_but_unread")


# ── the two halves of the name are one name ──────────────────────────────────────────────

def test_staging_and_the_engine_agree_on_the_filename():
    """Written by the service, read by the engine, and the two do not import each other."""
    src = (ROOT / "sdi-intelligence-backend" / "staging.py").read_text(encoding="utf-8")
    assert f'MODEL_SOURCES_FILENAME = "{sw.MODEL_SOURCES_FILENAME}"' in src
