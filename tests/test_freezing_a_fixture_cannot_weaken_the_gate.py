"""A slimmed fixture must answer IDENTICALLY to the record it came from.

The replay packs are large — mostly transcribed page text, which on a 25-page pack is the whole
drawing set. Committing one multi-megabyte record per pack is a permanent cost to the
repository, so tools/freeze_replay_fixture.py drops what it can.

The hazard in doing that is the one this whole harness exists to prevent. "Page text is not
read by the replay tiers" is true until somebody adds a reader, and a fixture quietly missing a
field the gate needs would weaken the gate while every push still reported green — a slimmer
file that has stopped gating. So the tool never drops anything on that reasoning: it computes a
structural fingerprint by CALLING the code all three tiers call, and accepts a reduction only
if the reduced record's fingerprint is byte-identical.

These tests hold that contract in both directions: a harmless reduction is taken, and a
reduction that changes any answer is refused even though it would have saved more.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import freeze_replay_fixture as frz                                      # noqa: E402


def _record(page_text: str = "") -> dict:
    """A small but real-shaped record: one routed part with a blank and a material."""
    return {
        "pages": [{"page_number": 1, "source_pdf_name": "j.pdf",
                   "text": page_text or ("LOREM IPSUM DRAWING NOTES " * 40),
                   "page_analysis": {"dimensions": {"all_dimensions_mm": [100, 50]}}}],
        "document_analysis": {"bom_rows": [
            {"part_number": "SYN-001", "description": "Synthetic plate",
             "quantity": 2, "material_text": "Steel, Mild 2mm"}]},
        "estimate_summary": {"part_estimates": [
            {"part_number": "SYN-001", "quantity": 2,
             "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 2.0,
             "blank_length_mm": 100.0, "blank_width_mm": 50.0}]},
    }


def test_the_fingerprint_is_stable_for_one_record():
    """If it were not, every reduction would look different and nothing could ever be dropped."""
    record = _record()
    assert frz._digest(frz._fingerprint(record)) == frz._digest(frz._fingerprint(record))


def test_the_heaviest_paths_are_measured_not_guessed():
    """THE FIRST VERSION CARRIED A HARDCODED KEY LIST and on the real 7332-01 record not one key
    matched: it attempted no reduction at all and reported "dropped: nothing" on a 7.8 MB file.
    A guess about where another team's data keeps its weight is not a reduction strategy."""
    record = _record(page_text="X" * 200_000)
    paths = dict(frz._heavy_paths(record))
    assert paths, "a 200 KB string must be found"
    # both the leaf and the subtree containing it are offered; the caller drops largest-first
    assert "pages[].text" in paths, sorted(paths)
    assert paths["pages[].text"] >= 200_000
    assert paths.get("pages", 0) >= paths["pages[].text"], "the parent subtree is also offered"


def test_a_path_a_renderer_reads_is_refused_by_name_not_quietly_taken():
    """MY OWN TEST CAUGHT THIS ONE. Before the rendered deliverables joined the fingerprint, the
    reducer dropped every part's review_flags and the whole pages list, because no costed-line
    field changed. Tier 1 RENDERS both deliverables and the forbidden-names check reads the
    rendered HTML — the flags are the audit trail it reads. A fingerprint drawn only from the
    costed record is blind to everything a renderer reads and nothing else does."""
    record = _record()
    record["estimate_summary"]["part_estimates"][0]["review_flags"] = ["Y" * 80_000]
    base = frz._digest(frz._fingerprint(record))
    _reduced, dropped, refused = frz.reduce_record(record, base, log=lambda *a: None)
    flags = "estimate_summary.part_estimates[].review_flags"
    assert flags not in dropped, "the audit trail the renderer prints must not be dropped"
    assert flags in refused or not any(
        d.startswith("estimate_summary") for d in dropped), (
        f"dropped={dropped} refused={refused}")


def test_a_reduction_still_preserves_the_fingerprint_exactly():
    """Whatever the reducer does take, the contract is unchanged: byte-identical."""
    record = _record(page_text="X" * 200_000)
    base = frz._digest(frz._fingerprint(record))
    reduced, dropped, _refused = frz.reduce_record(record, base, log=lambda *a: None)
    assert frz._digest(frz._fingerprint(reduced)) == base
    if dropped:
        assert frz._size(reduced) < frz._size(record), "a drop must actually save bytes"


def test_the_fingerprint_covers_the_rendered_deliverables():
    keys = set(frz._fingerprint(_record()))
    assert {"report_html", "quote_html"} <= keys
    for key in ("report_html", "quote_html"):
        value = frz._fingerprint(_record())[key]
        assert not str(value).startswith("ERROR"), f"{key}: {value}"


def test_both_builders_are_deterministic_so_a_reduction_can_be_judged():
    """If either embedded a clock, every reduction would be refused — which is the right way
    round to fail, but it would mean no fixture ever shrank, and that should be visible here
    rather than discovered as a mysteriously large fixture."""
    record = _record()
    first = frz._fingerprint(record)
    second = frz._fingerprint(record)
    assert first["report_html"] == second["report_html"]
    assert first["quote_html"] == second["quote_html"]


def test_the_fixture_is_written_compact_and_never_larger_than_the_record():
    """The defect this fixes: the first version wrote indent=1 and turned the real 7.8 MB
    7332-01 record into an 11.5 MB fixture — a tool for keeping files small that made one 47%
    bigger, which is the single number it exists to move."""
    record = _record(page_text="X" * 50_000)
    assert b"\n" not in frz._encode(record), "compact: no newlines"
    assert frz._size(record) < len(json.dumps(record, indent=1).encode("utf-8"))


def test_a_reduction_that_changes_an_answer_is_detected():
    """THE GUARD ON THE GUARD. A fingerprint that cannot tell a damaged record from a slimmed
    one would approve every reduction, and the tool's whole safety argument rests on it. Here
    the part's material is removed — a change the costing stage must notice."""
    record = _record()
    damaged = json.loads(json.dumps(record))
    damaged["estimate_summary"]["part_estimates"][0].pop("normalized_material")
    assert frz._digest(frz._fingerprint(damaged)) != frz._digest(frz._fingerprint(record)), \
        "the fingerprint cannot distinguish a record that lost its material"


def test_the_fingerprint_notices_a_changed_quantity():
    record = _record()
    other = json.loads(json.dumps(record))
    other["estimate_summary"]["part_estimates"][0]["quantity"] = 9
    assert frz._digest(frz._fingerprint(other)) != frz._digest(frz._fingerprint(record))


def test_the_fingerprint_notices_a_dropped_part():
    record = _record()
    other = json.loads(json.dumps(record))
    other["estimate_summary"]["part_estimates"] = []
    assert frz._digest(frz._fingerprint(other)) != frz._digest(frz._fingerprint(record))


def test_the_fingerprint_covers_all_three_tiers():
    """A fingerprint drawn only from tier 1 would let a reduction break routing or costing
    silently — the exact criticism that rendering a costed record is not a replay."""
    keys = set(frz._fingerprint(_record()))
    assert {"lines", "tally"} <= keys, "tier 1: the costed record and the tally"
    assert "canonicalised" in keys, "tier 2: the workbook canonicalisation"
    assert {"route_decisions", "material_recosted"} <= keys, "tier 3: routing and costing"


def test_freezing_refuses_to_invent_an_accepted_structure(tmp_path, monkeypatch):
    """accepted_facts.json is estimator-reviewed. A tool that wrote one would be manufacturing
    the very thing the gate checks against."""
    replay = tmp_path / "replay"
    (replay / "NEWJOB").mkdir(parents=True)
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    source.write_text(json.dumps(_record()), encoding="utf-8")
    rc = frz.freeze("NEWJOB", source, {"accepted_run": "r", "accepted_by": "b",
                                       "accepted_on": "2026-01-01"})
    assert rc == 2
    assert not (replay / "NEWJOB" / "summary.json").exists()
    assert not (replay / "NEWJOB" / "accepted_facts.json").exists()


def test_a_freeze_writes_the_summary_the_provenance_and_the_fingerprint(tmp_path, monkeypatch):
    replay = tmp_path / "replay"
    job_dir = replay / "SYN-JOB"
    job_dir.mkdir(parents=True)
    (job_dir / "accepted_facts.json").write_text(
        json.dumps({"quantities": {"SYN-001": 2}, "material_charged": ["SYN-001"]}),
        encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    source.write_text(json.dumps(_record()), encoding="utf-8")

    rc = frz.freeze("SYN-JOB", source,
                    {"accepted_run": "the synthetic run", "accepted_by": "a test",
                     "accepted_on": "2026-01-01",
                     "accepted_numbers": {"unit_gbp": 1.23}})
    assert rc == 0
    summary = json.loads((job_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["estimate_summary"]["part_estimates"][0]["part_number"] == "SYN-001"

    prov = json.loads((job_dir / "provenance.json").read_text(encoding="utf-8"))
    # every field the gate requires, filled
    from test_the_replay_gate_is_a_gate import PROVENANCE_FIELDS
    assert all(str(prov.get(f) or "").strip() for f in PROVENANCE_FIELDS), prov
    assert prov["job"] == "SYN-JOB"
    # and it records WHAT was dropped and on what evidence
    assert "structural_fingerprint" in prov["fixture"]
    assert prov["fixture"]["fixture_bytes"] <= prov["fixture"]["full_record_bytes"]
    assert (job_dir / "fingerprint.json").is_file()


def test_a_frozen_fixture_then_satisfies_the_gate_loader(tmp_path, monkeypatch):
    """End to end: what the tool writes is what the strict loader accepts. Otherwise the two
    halves agree on paper and disagree in the run."""
    replay = tmp_path / "replay"
    job_dir = replay / "SYN-JOB"
    job_dir.mkdir(parents=True)
    (job_dir / "accepted_facts.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    source.write_text(json.dumps(_record()), encoding="utf-8")
    assert frz.freeze("SYN-JOB", source, {"accepted_run": "r", "accepted_by": "b",
                                          "accepted_on": "2026-01-01"}) == 0

    sys.path.insert(0, str(ROOT / "tests" / "replay"))
    import test_frozen_replays as tfr
    loaded = tfr._frozen_summary(job_dir)          # must not raise, must not skip
    assert loaded["estimate_summary"]["part_estimates"][0]["part_number"] == "SYN-001"


def test_the_loader_rejects_what_the_tool_would_never_write(tmp_path):
    """A summary dropped in by hand with no provenance — the path that produced unlabelled
    baselines before the tool existed."""
    sys.path.insert(0, str(ROOT / "tests" / "replay"))
    import test_frozen_replays as tfr
    job_dir = tmp_path / "HANDMADE"
    job_dir.mkdir()
    (job_dir / "accepted_facts.json").write_text("{}", encoding="utf-8")
    (job_dir / "summary.json").write_text(json.dumps(_record()), encoding="utf-8")
    with pytest.raises(AssertionError, match="no provenance.json"):
        tfr._frozen_summary(job_dir)


def test_a_provenance_naming_the_wrong_job_is_rejected(tmp_path):
    """A record filed under the wrong job is worse than none."""
    sys.path.insert(0, str(ROOT / "tests" / "replay"))
    import test_frozen_replays as tfr
    job_dir = tmp_path / "7332-01"
    job_dir.mkdir()
    (job_dir / "accepted_facts.json").write_text("{}", encoding="utf-8")
    (job_dir / "summary.json").write_text(json.dumps(_record()), encoding="utf-8")
    (job_dir / "provenance.json").write_text(json.dumps({
        "job": "10975-02", "accepted_run": "r", "accepted_by": "b",
        "accepted_on": "2026-01-01", "source_path": "x"}), encoding="utf-8")
    with pytest.raises(AssertionError, match="provenance names job"):
        tfr._frozen_summary(job_dir)
