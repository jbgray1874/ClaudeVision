"""What was selected must be what gets priced, and a re-run must not inherit last time's pack.

Selection used to mean almost nothing. The page's picks were used to derive a common parent
folder and then discarded; the runner was handed the folder and ran `--job <folder>`, which
reads everything in it. Three drawings chosen out of twelve produced an estimate built from
twelve, and no document said so.

So the list is staged into one folder per client and job. These tests cover the two things that
would hurt if they were wrong: that the folder ends up holding EXACTLY the current list, and
that the delete which makes that true cannot escape the staging root.
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
    """The module with a stub config — the real one wants a .env and a mapped K: drive."""
    stub = types.ModuleType("config")
    stub.STAGING_ROOT = str(tmp_path / "SDIIntelligenceAISheet")
    monkeypatch.setitem(sys.modules, "config", stub)
    spec = importlib.util.spec_from_file_location("staging", _BACKEND / "staging.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pdf(p: Path, body: bytes = b"%PDF-1.4 drawing") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return p


# ── what lands in the folder ────────────────────────────────────────────────────────────

def test_only_the_selected_drawings_are_staged(staging, tmp_path):
    """The defect this exists to fix: three chosen out of twelve must price three."""
    pack = tmp_path / "pack"
    for n in range(1, 13):
        _pdf(pack / f"12392-02-{n:02d}.pdf")

    chosen = [str(pack / "12392-02-01.pdf"), str(pack / "12392-02-05.pdf"),
              str(pack / "12392-02-09.pdf")]
    res = staging.stage(chosen, client="Boots", drawing="12392-02")

    staged = sorted(p.name for p in Path(res["folder"]).iterdir())
    assert staged == ["12392-02-01.pdf", "12392-02-05.pdf", "12392-02-09.pdf"]
    assert res["copied_count"] == 3


def test_a_folder_is_walked_so_adding_a_job_folder_still_works(staging, tmp_path):
    pack = tmp_path / "11650-04"
    _pdf(pack / "ga.pdf")
    _pdf(pack / "PDFs" / "detail.pdf")
    (pack / "notes.docx").write_bytes(b"x")

    res = staging.stage([str(pack)], client="MandS", drawing="11650-04")
    assert sorted(p.name for p in Path(res["folder"]).iterdir()) == ["detail.pdf", "ga.pdf"]
    assert any("notes.docx" in s["path"] for s in res["skipped"]), \
        "a non-drawing is named, not silently dropped"


def test_two_sources_merge_into_one_pack(staging, tmp_path):
    """The case that was refused outright before: a Document Manager extract and the share.

    Two parent folders meant "those drawings come from 2 different job folders" and no run.
    Staging gives them one folder, which is the whole point.
    """
    share = tmp_path / "share" / "12392-02"
    dm = tmp_path / "dmout" / "12392-02"
    _pdf(share / "ga.pdf", b"%PDF share")
    _pdf(share / "bracket.pdf")
    _pdf(dm / "ga.pdf", b"%PDF from DM, newer")
    _pdf(dm / "panel.pdf")

    res = staging.stage([str(share), str(dm)], client="Boots", drawing="12392-02")
    folder = Path(res["folder"])
    assert sorted(p.name for p in folder.iterdir()) == ["bracket.pdf", "ga.pdf", "panel.pdf"]
    # Same name, later wins — the rule the page applies when a DM copy lands on a share copy.
    assert (folder / "ga.pdf").read_bytes() == b"%PDF from DM, newer"


# ── the re-run ──────────────────────────────────────────────────────────────────────────

def test_a_rerun_replaces_the_pack_and_does_not_inherit_it(staging, tmp_path):
    """THE POINT OF CLEARING. A drawing taken off the list must not still be priced.

    Without this a re-run adds to the folder, so the second estimate quietly includes a
    drawing the estimator deliberately removed — and the sheet looks entirely normal.
    """
    pack = tmp_path / "pack"
    _pdf(pack / "a.pdf"); _pdf(pack / "b.pdf"); _pdf(pack / "c.pdf")

    first = staging.stage([str(pack / "a.pdf"), str(pack / "b.pdf"), str(pack / "c.pdf")],
                          client="Boots", drawing="12422")
    assert first["copied_count"] == 3 and first["replaced_count"] == 0

    second = staging.stage([str(pack / "a.pdf"), str(pack / "c.pdf")],
                           client="Boots", drawing="12422")
    assert second["replaced_count"] == 3, "the previous pack was cleared, not added to"
    assert sorted(p.name for p in Path(second["folder"]).iterdir()) == ["a.pdf", "c.pdf"]


def test_a_different_job_gets_its_own_folder(staging, tmp_path):
    _pdf(tmp_path / "x" / "a.pdf")
    one = staging.stage([str(tmp_path / "x" / "a.pdf")], client="Boots", drawing="12422")
    two = staging.stage([str(tmp_path / "x" / "a.pdf")], client="Boots", drawing="11650")
    assert one["folder"] != two["folder"]
    assert Path(one["folder"]).is_dir() and Path(two["folder"]).is_dir()


def test_the_same_job_for_two_clients_does_not_collide(staging, tmp_path):
    _pdf(tmp_path / "x" / "a.pdf")
    a = staging.stage([str(tmp_path / "x" / "a.pdf")], client="Boots", drawing="12422")
    b = staging.stage([str(tmp_path / "x" / "a.pdf")], client="Tesco", drawing="12422")
    assert a["folder"] != b["folder"]


# ── the delete, which is the dangerous part ─────────────────────────────────────────────

def test_the_delete_refuses_to_leave_the_staging_root(staging, tmp_path):
    """A path partly derived from user input, deleting files on a live share. It must not be
    possible to walk out of the root, however the folder was arrived at."""
    outside = tmp_path / "somebody-elses-work"
    outside.mkdir()
    (outside / "precious.pdf").write_bytes(b"do not delete")

    with pytest.raises(staging.StagingError):
        staging._clear_folder(outside)
    assert (outside / "precious.pdf").exists()


def test_the_delete_refuses_the_root_itself(staging, tmp_path):
    """Clearing the root would wipe every job's staged pack at once."""
    root = Path(staging.staging_root())
    root.mkdir(parents=True, exist_ok=True)
    (root / "OtherJob").mkdir()
    with pytest.raises(staging.StagingError):
        staging._clear_folder(root)
    assert (root / "OtherJob").exists()


def test_a_sibling_named_like_the_root_is_not_inside_it(staging, tmp_path):
    """...\\SDIIntelligenceAISheetOLD must not pass as inside ...\\SDIIntelligenceAISheet.

    A naive startswith check says it does, and that is a delete in somebody's archive.
    """
    root = Path(staging.staging_root())
    sibling = Path(str(root) + "OLD")
    sibling.mkdir(parents=True, exist_ok=True)
    (sibling / "archive.pdf").write_bytes(b"keep")

    with pytest.raises(staging.StagingError):
        staging._clear_folder(sibling)
    assert (sibling / "archive.pdf").exists()


# ── refusals that are worth the words ───────────────────────────────────────────────────

def test_a_selection_with_no_drawings_says_so(staging, tmp_path):
    (tmp_path / "readme.txt").write_bytes(b"x")
    with pytest.raises(staging.StagingError) as exc:
        staging.stage([str(tmp_path / "readme.txt")], client="Boots", drawing="12422")
    assert "readme.txt" in str(exc.value), "name what was rejected, not just the count"


def test_a_wildly_large_selection_is_refused_before_it_copies(staging, tmp_path, monkeypatch):
    """Usually a folder chosen a level too high. Better to refuse than to spend ten minutes
    filling a share with somebody else's jobs."""
    monkeypatch.setattr(staging, "MAX_FILES", 3)
    pack = tmp_path / "toobig"
    for n in range(6):
        _pdf(pack / f"d{n}.pdf")
    with pytest.raises(staging.StagingError) as exc:
        staging.stage([str(pack)], client="Boots", drawing="12422")
    assert "level too high" in str(exc.value)
    assert not (Path(staging.staging_root()) / "Boots" / "12422").exists() or \
        not any((Path(staging.staging_root()) / "Boots" / "12422").iterdir()), \
        "nothing is copied when the selection is refused"


# ── the SolidWorks extract must travel with the job ─────────────────────────────────────
#
# THE REGRESSION THIS PINS. Staging pointed the engine at a folder that did not contain
# _sw_native_extract.json, and the SolidWorks connector is self-gating on that file. Layer 0 —
# modelled material, gauge, flat blank, full-depth BOM quantities, the strongest source in the
# building — stopped applying. Silently: with no models in the staged folder either,
# "models present but unread" could not fire, so the job read as a genuinely drawings-only one.

def test_the_solidworks_extract_is_staged_with_the_drawings(staging, tmp_path):
    pack = tmp_path / "10575-02"
    _pdf(pack / "ga.pdf")
    (pack / "_sw_native_extract.json").write_text('{"parts": []}', encoding="utf-8")

    res = staging.stage([str(pack)], client="Dyson", drawing="10575-02")
    staged = {p.name for p in Path(res["folder"]).iterdir()}
    assert "_sw_native_extract.json" in staged, \
        "without it the SolidWorks layer silently stops applying"
    assert res["sidecars"] == ["_sw_native_extract.json"]


def test_the_extract_follows_even_when_only_drawings_were_selected(staging, tmp_path):
    """An estimator picks drawings. They have no reason to know the extract exists, and
    picking three PDFs must not quietly disable the model read."""
    pack = tmp_path / "10575-02"
    _pdf(pack / "a.pdf"); _pdf(pack / "b.pdf")
    (pack / "_sw_native_extract.json").write_text('{"parts": []}', encoding="utf-8")

    res = staging.stage([str(pack / "a.pdf")], client="Dyson", drawing="10575-02")
    assert "_sw_native_extract.json" in {p.name for p in Path(res["folder"]).iterdir()}


def test_the_extract_is_not_reported_as_an_unrecognised_file(staging, tmp_path):
    """It was listed as 'not staged: _sw_native_extract.json — not a drawing file (.json)',
    which reads as though it had been considered and rejected."""
    pack = tmp_path / "10575-02"
    _pdf(pack / "ga.pdf")
    (pack / "_sw_native_extract.json").write_text("{}", encoding="utf-8")
    res = staging.stage([str(pack)], client="Dyson", drawing="10575-02")
    assert not any("_sw_native_extract" in s["path"] for s in res["skipped"])


def test_a_solidworks_drawing_file_is_staged(staging, tmp_path):
    """.slddrw is one of the engine's own native extensions, alongside .sldprt and .sldasm.
    Leaving it out made a job with a SolidWorks drawing look like a job without one."""
    pack = tmp_path / "10575-02"
    _pdf(pack / "ga.pdf")
    (pack / "10575-02-GA.SLDDRW").write_bytes(b"\x00")
    res = staging.stage([str(pack)], client="Dyson", drawing="10575-02")
    assert "10575-02-GA.SLDDRW" in {p.name for p in Path(res["folder"]).iterdir()}


def test_no_extract_means_no_sidecar_and_no_pretending(staging, tmp_path):
    pack = tmp_path / "12422"
    _pdf(pack / "ga.pdf")
    res = staging.stage([str(pack)], client="Boots", drawing="12422")
    assert res["sidecars"] == [] and res["sidecars_count"] == 0
