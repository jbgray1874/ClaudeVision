"""Three runs of one job were costed drawings-only, and the log said the same seven words
every time: "no SOLIDWORKS extract found beside these drawings".

That sentence is true of two completely different situations and actionable in only one.

    A JOB WITH NO MODELS. Nothing to read, nothing to do, the estimate is as good as it gets.
    A JOB WHOSE MODELS WERE NOT SELECTED. The strongest source in the building — modelled
    material, gauge, flat blank, full-depth BOM quantities — was sitting in the folder the
    drawings came out of, and the pack arrived without it because the estimator picked
    drawings, which is what the picker is for.

12349-02 was the second one, three times. Thirty-four drawings were selected out of a folder
that also holds the SLDPRT and SLDASM files of every part on them; the models were never on the
list, so they were never staged, so the runner — which has SOLIDWORKS and generates the extract
itself when models are in the job folder — had nothing to read and said so in words that read
like the first situation.

TWO THINGS ARE FIXED HERE, AND NEITHER OF THEM GUESSES.

The extract is looked for ONE LEVEL UP as well as down. A job routinely keeps drawings and
models in sibling folders, and the analyser writes its extract beside the MODELS; searching
only downward from the drawings folder could never find it. Upward is one level and an exact
filename — never an rglob of a parent, which on an estimating share is the whole client.

And when a pack arrives with neither an extract nor a model, staging LOOKS, and the run log
says which of the two situations this is: the count, the folder, and the one click that fixes
it. Nothing is staged that was not selected — that rule is the reason this module exists.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "sdi-intelligence-backend"


@pytest.fixture()
def staging(tmp_path, monkeypatch):
    stub = types.ModuleType("config")
    stub.STAGING_ROOT = str(tmp_path / "SDIIntelligenceAISheet")
    monkeypatch.setitem(sys.modules, "config", stub)
    spec = importlib.util.spec_from_file_location("staging", _BACKEND / "staging.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pdf(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4 drawing")
    return p


def _model(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00SLDPRT")
    return p


# ── the models nobody selected ───────────────────────────────────────────────────────────

def test_the_models_beside_the_selection_are_counted_not_staged(staging, tmp_path):
    """THE 12349-02 CASE. Drawings picked out of a folder that also holds the models."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "12349-02-69-GA.PDF")
    for n in ("01A", "03M", "04M"):
        _model(pack / f"12349-02-69-{n}.SLDPRT")
    _model(pack / "12349-02-69-100.SLDASM")

    res = staging.stage([str(pack / "12349-02-69-GA.PDF")], client="Fanatics",
                        drawing="12349-02")

    assert res["native_unselected_count"] == 4
    assert str(pack) in res["native_unselected_folders"]
    _drawings = sorted(p.name for p in Path(res["folder"]).iterdir()
                       if p.suffix.lower() != ".json")
    assert _drawings == ["12349-02-69-GA.PDF"], \
        "selection means selection — no drawing is staged that was not chosen"
    assert not any(p.suffix.lower() in staging.NATIVE_SUFFIXES
                   for p in Path(res["folder"]).iterdir()), \
        "the models stay where they live; only their address travels"


def test_a_job_that_genuinely_has_no_models_says_nothing(staging, tmp_path):
    pack = tmp_path / "12422"
    _pdf(pack / "ga.pdf")
    res = staging.stage([str(pack)], client="Boots", drawing="12422")
    assert res["native_unselected_count"] == 0
    assert res["native_unselected_folders"] == []


def test_models_that_were_selected_are_staged_and_not_reported_as_missed(staging, tmp_path):
    """Select the folder and the models come too — the runner reads them itself."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    _model(pack / "12349-02-69-03M.SLDPRT")

    res = staging.stage([str(pack)], client="Fanatics", drawing="12349-02")

    assert res["native_staged"] == ["12349-02-69-03M.SLDPRT"]
    assert res["native_unselected_count"] == 0, \
        "they are in the pack; there is nothing to tell anyone"


def test_an_extract_that_travelled_ends_the_question(staging, tmp_path):
    """With Layer 0 already applying there is no second-guessing to do, and no rglob to pay
    for."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    _model(pack / "12349-02-69-03M.SLDPRT")
    (pack / "_sw_native_extract.json").write_text('{"parts": []}', encoding="utf-8")

    res = staging.stage([str(pack / "ga.pdf")], client="Fanatics", drawing="12349-02")

    assert res["sidecars"] == ["_sw_native_extract.json"]
    assert res["native_unselected_count"] == 0


def test_an_archive_folder_is_not_the_live_design(staging, tmp_path):
    """The same exclusion the analyser applies when it decides what to read — otherwise the
    count offered to the estimator includes models no run would ever open."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    _model(pack / "OLD" / "12349-02-69-03M.SLDPRT")
    _model(pack / "Superseded" / "12349-02-69-04M.SLDPRT")
    _model(pack / "~$locked.sldprt")

    res = staging.stage([str(pack / "ga.pdf")], client="Fanatics", drawing="12349-02")
    assert res["native_unselected_count"] == 0


def test_a_cad_folder_is_not_an_old_one(staging, tmp_path):
    """"folder" contains "old". The tokens are matched as whole words on both sides of this
    comparison, and the consumer's list has the same bug fixed the same way."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    _model(pack / "CAD Folder" / "12349-02-69-03M.SLDPRT")

    res = staging.stage([str(pack / "ga.pdf")], client="Fanatics", drawing="12349-02")
    assert res["native_unselected_count"] == 1


def test_the_two_exclusion_lists_have_not_drifted(staging):
    """This service does not import the engine, so the rule exists twice. Two copies of one
    exclusion list is a defect that shows up as a number quietly disagreeing with itself."""
    src = (_ROOT / "src" / "source_connectors" / "solidworks.py").read_text(encoding="utf-8")
    for token in staging._EXCLUDED_DIR_TOKENS:
        assert f'"{token}"' in src, token
    for phrase in staging._EXCLUDED_DIR_PHRASES:
        assert f'"{phrase}"' in src, phrase
    assert staging.NATIVE_SUFFIXES == (".sldprt", ".sldasm", ".slddrw")


# ── the files SolidWorks leaves behind when somebody has a model open ────────────────────

def test_a_lock_file_is_not_staged_as_a_drawing(staging, tmp_path):
    """"~$12349-02-69-GA.SLDASM" carries a model's extension and is a few bytes saying who
    has it open. Six of them reached one pack, where they inflate the model count and invite
    the analyser to open something that is not a document."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    _model(pack / "12349-02-69-GA.SLDASM")
    for junk in ("~$12349-02-69-GA.SLDASM", "~$12349-02-69-01A.SLDPRT"):
        (pack / junk).write_bytes(b"\x00")

    res = staging.stage([str(pack)], client="Fanatics", drawing="12349-02")

    staged = {p.name for p in Path(res["folder"]).iterdir()}
    assert not any(n.startswith("~") for n in staged)
    assert res["native_staged"] == ["12349-02-69-GA.SLDASM"]


def test_it_says_why_rather_than_dropping_them_silently(staging, tmp_path):
    """A lock file in the pack means somebody had that model open when it was picked — and a
    borrowed document can be read with unsaved changes the fingerprint cannot see."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    (pack / "~$12349-02-69-GA.SLDASM").write_bytes(b"\x00")

    res = staging.stage([str(pack)], client="Fanatics", drawing="12349-02")
    reasons = " ".join(s["reason"] for s in res["skipped"])
    assert "lock file" in reasons and "had that document open" in reasons


def test_a_lock_file_does_not_count_as_a_model_beside_the_drawings(staging, tmp_path):
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    (pack / "~$12349-02-69-GA.SLDASM").write_bytes(b"\x00")
    res = staging.stage([str(pack / "ga.pdf")], client="Fanatics", drawing="12349-02")
    assert res["native_unselected_count"] == 0


# ── and the pack carries their address, so the runner reads them in place ────────────────

def test_the_pack_is_told_where_the_models_are(staging, tmp_path):
    """The runner has SOLIDWORKS. Given the address it analyses them where they live and
    writes the extract into the job folder — no models copied, no JSON moved by hand."""
    import json
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    _model(pack / "12349-02-69-03M.SLDPRT")

    res = staging.stage([str(pack / "ga.pdf")], client="Fanatics", drawing="12349-02")

    pointer = Path(res["folder"]) / staging.MODEL_SOURCES_FILENAME
    assert pointer.is_file()
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    assert payload["models_folders"] == [str(pack)]
    assert payload["model_count"] == 1


def test_no_address_is_written_when_there_is_nothing_to_point_at(staging, tmp_path):
    pack = tmp_path / "12422"
    _pdf(pack / "ga.pdf")
    res = staging.stage([str(pack)], client="Boots", drawing="12422")
    assert not (Path(res["folder"]) / staging.MODEL_SOURCES_FILENAME).exists()


def test_the_address_is_not_written_when_the_models_are_in_the_pack(staging, tmp_path):
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    _model(pack / "12349-02-69-03M.SLDPRT")
    res = staging.stage([str(pack)], client="Fanatics", drawing="12349-02")
    assert not (Path(res["folder"]) / staging.MODEL_SOURCES_FILENAME).exists(), \
        "they are already here; there is nowhere else to look"


# ── the extract the last run paid half an hour for ───────────────────────────────────────

def test_the_previous_runs_extract_survives_the_clear(staging, tmp_path):
    """The folder is emptied before the copy, which deleted an extract the ENGINE had
    generated into it — so every re-run of the same pack spent another half hour in
    SolidWorks. It is kept, and the engine's own fingerprint check decides whether to trust
    it."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")
    _model(pack / "a.SLDPRT")

    first = staging.stage([str(pack)], client="Fanatics", drawing="12349-02")
    # What a run does: writes its extract into the job folder it was pointed at.
    (Path(first["folder"]) / "_sw_native_extract.json").write_text(
        '{"records": [], "_manifest": {}}', encoding="utf-8")

    second = staging.stage([str(pack)], client="Fanatics", drawing="12349-02")

    assert second["extract_carried_forward"] is True
    assert (Path(second["folder"]) / "_sw_native_extract.json").is_file()


def test_an_extract_travelling_with_the_selection_wins(staging, tmp_path):
    """The kept one is a cache. One that came with the drawings is somebody's statement about
    the models, and it is the newer fact."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "ga.pdf")

    first = staging.stage([str(pack)], client="Fanatics", drawing="12349-02")
    (Path(first["folder"]) / "_sw_native_extract.json").write_text("STALE", encoding="utf-8")
    (pack / "_sw_native_extract.json").write_text("FRESH", encoding="utf-8")

    second = staging.stage([str(pack)], client="Fanatics", drawing="12349-02")

    assert second["sidecars"] == ["_sw_native_extract.json"]
    assert second["extract_carried_forward"] is False
    assert (Path(second["folder"]) / "_sw_native_extract.json").read_text(
        encoding="utf-8") == "FRESH"


def test_a_first_run_carries_nothing_forward(staging, tmp_path):
    pack = tmp_path / "12422"
    _pdf(pack / "ga.pdf")
    res = staging.stage([str(pack)], client="Boots", drawing="12422")
    assert res["extract_carried_forward"] is False


def test_the_drawings_themselves_are_still_replaced(staging, tmp_path):
    """Keeping the extract must not turn into keeping the pack. A drawing removed from the
    list must leave the folder — that rule is why the clear exists."""
    pack = tmp_path / "12349-02"
    _pdf(pack / "a.pdf"); _pdf(pack / "b.pdf")
    staging.stage([str(pack / "a.pdf"), str(pack / "b.pdf")], client="Fanatics",
                  drawing="12349-02")

    res = staging.stage([str(pack / "a.pdf")], client="Fanatics", drawing="12349-02")
    assert sorted(p.name for p in Path(res["folder"]).iterdir()
                  if p.suffix.lower() == ".pdf") == ["a.pdf"]


# ── the extract that lives with the models, one folder over ──────────────────────────────

def test_the_extract_is_found_in_the_parent_when_the_drawings_are_in_a_subfolder(
        staging, tmp_path):
    """12349-02\\PDF holds the drawings; the analyser wrote its extract at 12349-02. Looking
    only downward from the drawings folder found nothing, on a job that had everything."""
    job = tmp_path / "12349-02"
    _pdf(job / "PDF" / "ga.pdf")
    (job / "_sw_native_extract.json").write_text('{"parts": []}', encoding="utf-8")

    res = staging.stage([str(job / "PDF" / "ga.pdf")], client="Fanatics", drawing="12349-02")

    assert res["sidecars"] == ["_sw_native_extract.json"]
    assert "_sw_native_extract.json" in {p.name for p in Path(res["folder"]).iterdir()}


def test_upward_is_one_level_and_never_a_search(staging, tmp_path):
    """An extract two levels up belongs to some other job, or to the client folder. It is not
    this job's evidence and must not be dragged in."""
    root = tmp_path / "Fanatics"
    (root / "_sw_native_extract.json").parent.mkdir(parents=True, exist_ok=True)
    (root / "_sw_native_extract.json").write_text('{"parts": []}', encoding="utf-8")
    _pdf(root / "12349-02" / "PDF" / "ga.pdf")

    res = staging.stage([str(root / "12349-02" / "PDF" / "ga.pdf")], client="Fanatics",
                        drawing="12349-02")
    assert res["sidecars"] == []
