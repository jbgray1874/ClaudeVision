"""Clearing one pack's cache must clear that pack's, and nothing else's.

WHY IT EXISTS. The first LLM-only run through the page sent NOTHING to the model —
"0 page(s) sent to the model, 22 from cache" and "reusing the cached read for this pack". It
proved the plumbing and measured nothing about Grok, which is the whole purpose of that button.

WHY IT IS DANGEROUS. Both caches are shared across every job this machine has read, and
neither filename says which job it belongs to — they are content hashes. The lazy version of
this tool empties the directory, which costs every other pack's settled answer, a bill and an
afternoon. So the two matching rules are the substance of the thing and are what this file
guards:

  vision_bom  -- every entry records the pdf_name it came from; matched against the PDFs
                 actually in the pack folder.
  llm_extract -- records nothing, so the key is recomputed from the same inputs the engine
                 uses. Present means this pack's, by construction.

AND WHAT IT CANNOT DO IS STATED RATHER THAN GUESSED. The inference entries are keyed on a
mid-run BOM that nothing outside a run can reproduce. They are left alone and counted out loud.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "diagnose"))
sys.path.insert(0, str(ROOT / "src"))

import clear_llm_cache as tool                                          # noqa: E402


@pytest.fixture()
def pack(tmp_path):
    job = tmp_path / "10575-02"
    job.mkdir()
    for n in ("10575-01-GA - V1 Cordless Vacuum Display [Rev D].PDF",
              "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF"):
        (job / n).write_bytes(b"%PDF-1.4\n")
    # The pack folder holds far more than PDFs — the DXFs, the models, the extract sidecar.
    (job / "10575-01-001_MS_1.2mm_Rev D.DXF").write_text("0\nSECTION\n")
    (job / "_sw_native_extract.json").write_text("{}")
    return job


def _vision_dir(tmp_path, monkeypatch, entries):
    d = tmp_path / "cache" / "vision_bom"
    d.mkdir(parents=True)
    for i, pdf_name in enumerate(entries):
        (d / f"{i:064x}.json").write_text(json.dumps(
            {"schema_version": 1, "pdf_name": pdf_name, "page_index": i,
             "raw_response": "", "parsed": {}}), encoding="utf-8")
    monkeypatch.setattr(tool, "_vision_entries", tool._vision_entries)
    import _bom_vision_reader
    monkeypatch.setattr(_bom_vision_reader, "DEFAULT_CACHE_DIR", str(d))
    return d


def test_it_takes_this_packs_pages_and_leaves_the_other_jobs(tmp_path, monkeypatch, pack):
    """THE WHOLE POINT. Two of these five entries are this pack's."""
    d = _vision_dir(tmp_path, monkeypatch, [
        "10575-01-GA - V1 Cordless Vacuum Display [Rev D].PDF",
        "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF",
        "10412-01-GA - Somebody Else's Job.PDF",
        "9981-03-GA - Another Job Entirely.PDF",
        "10575-99-GA - A Job That Merely Starts The Same.PDF",
    ])
    names = {p.name.lower() for p in tool._pack_pdfs(pack)}
    hits, total, note = tool._vision_entries(names)
    assert total == 5
    assert len(hits) == 2, "matched the wrong number of entries: " + repr(
        [h.name for h in hits])
    survivors = {json.loads(f.read_text())["pdf_name"] for f in d.glob("*.json")
                 if f not in hits}
    assert "10412-01-GA - Somebody Else's Job.PDF" in survivors
    assert "10575-99-GA - A Job That Merely Starts The Same.PDF" in survivors, (
        "a prefix match on the job number would take this one too — 10575-99 is not 10575-02, "
        "and the pack's own sheets are 10575-01 and 10575-02, so no prefix rule can be right")


def test_only_pdfs_in_the_folder_count_as_the_pack(pack):
    """The DXFs, the models and the extract sidecar sit in the same folder and are not what
    the vision reader was given."""
    got = {p.name for p in tool._pack_pdfs(pack)}
    assert len(got) == 2, got
    assert not any(n.lower().endswith((".dxf", ".json")) for n in got)


def test_a_single_pdf_is_a_pack_of_one(pack):
    one = pack / "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF"
    assert tool._pack_pdfs(one) == [one]


def test_a_corrupt_entry_is_left_alone(tmp_path, monkeypatch, pack):
    """The reader already re-fetches on one, so it costs a call and nothing else. Deleting
    files it cannot read is not this tool's decision to make."""
    d = _vision_dir(tmp_path, monkeypatch, ["10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF"])
    (d / "beef.json").write_text("{not json", encoding="utf-8")
    names = {p.name.lower() for p in tool._pack_pdfs(pack)}
    hits, _, _ = tool._vision_entries(names)
    assert all(h.name != "beef.json" for h in hits)


# ── nothing is deleted without being asked ───────────────────────────────────

def test_it_reports_and_deletes_nothing_by_default(tmp_path, monkeypatch, pack, capsys):
    d = _vision_dir(tmp_path, monkeypatch, [
        "10575-02-GA - V2 Upright Vacuum Display [Rev D].PDF"])
    before = set(d.glob("*.json"))
    tool.main(["--job", str(pack)])
    assert set(d.glob("*.json")) == before, "it deleted without --apply"
    assert "Nothing has been removed" in capsys.readouterr().out


def test_apply_deletes_and_says_how_many(tmp_path, monkeypatch, pack, capsys):
    d = _vision_dir(tmp_path, monkeypatch, [
        "10575-01-GA - V1 Cordless Vacuum Display [Rev D].PDF",
        "10412-01-GA - Somebody Else's Job.PDF",
    ])
    tool.main(["--job", str(pack), "--apply"])
    left = [json.loads(f.read_text())["pdf_name"] for f in d.glob("*.json")]
    assert left == ["10412-01-GA - Somebody Else's Job.PDF"], left
    assert "Deleted 1 file" in capsys.readouterr().out


def test_it_will_not_delete_outside_a_cache_directory(tmp_path):
    """The cache paths come from environment variables — SDI_LLM_EXTRACT_CACHE_DIR relocates
    one of them. A variable pointing at a share is the difference between clearing a cache and
    clearing a job folder, and this tool takes a list of paths and unlinks them."""
    victim = tmp_path / "Estimating" / "10575-02-GA.PDF"
    victim.parent.mkdir(parents=True)
    victim.write_text("a real drawing")
    gone, failed = tool._delete([victim])
    assert gone == 0 and victim.exists(), "it deleted a file outside the caches"
    assert failed and "refused" in failed[0]


def test_the_allowed_directories_are_the_two_caches():
    assert tool._ALLOWED_DIR_NAMES == {"vision_bom", "llm_extract"}
