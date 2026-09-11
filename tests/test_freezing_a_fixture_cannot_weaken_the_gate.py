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


# The date every fixture below claims, so the identity gate has something true to verify
# against. A record with no processed_at is REFUSED, which is why the helper carries one.
SYN_STAMP = "2026-09-07T14:17:00+00:00"
SYN_DATE = SYN_STAMP[:10]


def _record(page_text: str = "", stamp: str = SYN_STAMP) -> dict:
    """A small but real-shaped record: one routed part with a blank and a material."""
    return {
        "processed_at": stamp,
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
                                       "accepted_on": SYN_DATE})
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
                     "accepted_on": SYN_DATE,
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
                                          "accepted_on": SYN_DATE}) == 0

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
        "accepted_on": SYN_DATE, "source_path": "x"}), encoding="utf-8")
    with pytest.raises(AssertionError, match="provenance names job"):
        tfr._frozen_summary(job_dir)


# ── the baseline must BE the run it says it is ─────────────────────────────────────────


def _dated(record: dict, stamp: str) -> dict:
    out = json.loads(json.dumps(record))
    out["processed_at"] = stamp
    return out


def test_a_record_whose_own_date_contradicts_the_asserted_one_is_refused(tmp_path, monkeypatch):
    """THE DEFECT THIS EXISTS FOR, AND IT REACHED A COMMITTED FIXTURE. The tool took
    --accepted-on straight from the command line and wrote it into provenance without ever
    looking at the record. The 7332-01 fixture was labelled "the 14:17 pack, 7 Sep" while the
    record inside carried processed_at of 10 September 18:59 — a different run, wearing the
    accepted baseline's numbers. Typing an older date does not make the input that run, and a
    baseline whose label and content disagree is worse than no baseline: every later comparison
    is against something other than what it claims and nobody can tell."""
    replay = tmp_path / "replay"
    job = replay / "SYN-JOB"
    job.mkdir(parents=True)
    (job / "accepted_facts.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    source.write_text(json.dumps(_dated(_record(), "2026-09-10T18:59:00+00:00")),
                      encoding="utf-8")

    rc = frz.freeze("SYN-JOB", source,
                    {"accepted_run": "the 14:17 pack, 7 Sep", "accepted_by": "J Gray",
                     "accepted_on": "2026-09-07"})
    assert rc == 3, "a contradicted provenance must stop the freeze"
    assert not (job / "summary.json").exists(), "and write nothing at all"
    assert not (job / "provenance.json").exists()


def test_a_matching_date_freezes_normally(tmp_path, monkeypatch):
    replay = tmp_path / "replay"
    job = replay / "SYN-JOB"
    job.mkdir(parents=True)
    (job / "accepted_facts.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    source.write_text(json.dumps(_dated(_record(), "2026-09-07T14:17:00+00:00")),
                      encoding="utf-8")
    assert frz.freeze("SYN-JOB", source,
                      {"accepted_run": "the 14:17 pack", "accepted_by": "J Gray",
                       "accepted_on": "2026-09-07"}) == 0
    prov = json.loads((job / "provenance.json").read_text(encoding="utf-8"))
    assert prov["accepted_on"] == "2026-09-07"
    assert prov["record_says_about_itself"]["processed_at"].startswith("2026-09-07")


def test_accepting_a_newer_run_records_its_own_date_not_the_one_typed(tmp_path, monkeypatch):
    """If 10 September IS intentionally the new baseline, that is a legitimate decision — but it
    is recorded as 10 September. It is never labelled 7 September."""
    replay = tmp_path / "replay"
    job = replay / "SYN-JOB"
    job.mkdir(parents=True)
    (job / "accepted_facts.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    source.write_text(json.dumps(_dated(_record(), "2026-09-10T18:59:00+00:00")),
                      encoding="utf-8")
    assert frz.freeze("SYN-JOB", source,
                      {"accepted_run": "the v0020 run", "accepted_by": "J Gray",
                       "accepted_on": "2026-09-07"},
                      accept_new_baseline=True) == 0
    prov = json.loads((job / "provenance.json").read_text(encoding="utf-8"))
    assert prov["accepted_on"] == "2026-09-10", "the record's own date wins"
    assert "NEW baseline" in prov["baseline_change"]


def test_a_record_with_no_timestamp_cannot_be_attributed_and_is_refused(tmp_path, monkeypatch):
    """Absence of evidence is not evidence of the asserted date."""
    replay = tmp_path / "replay"
    job = replay / "SYN-JOB"
    job.mkdir(parents=True)
    (job / "accepted_facts.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    source.write_text(json.dumps(_record(stamp="")), encoding="utf-8")
    assert frz.freeze("SYN-JOB", source,
                      {"accepted_run": "r", "accepted_by": "b",
                       "accepted_on": "2026-09-07"}) == 3


def test_verify_provenance_explains_itself_rather_than_just_saying_no():
    ok, date, why = frz.verify_provenance(
        _dated(_record(), "2026-09-10T18:59:00+00:00"), "2026-09-07")
    assert ok is False
    assert date == "2026-09-10"
    assert "2026-09-10" in why and "2026-09-07" in why
    assert "--source" in why, "and names the way out"


# ── two identical errors are not proof ────────────────────────────────────────────────


def test_an_errored_fingerprint_stage_refuses_every_reduction(tmp_path, monkeypatch):
    """_fingerprint turns a stage exception into the STRING "ERROR ...". Two such strings compare
    equal, so a stage that fails on the full record and fails identically on a reduced one reads
    as "fingerprint identical" — and data would come out on the strength of two failures agreeing
    with each other."""
    replay = tmp_path / "replay"
    job = replay / "SYN-JOB"
    job.mkdir(parents=True)
    (job / "accepted_facts.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)

    real = frz._fingerprint

    def broken(summary):
        out = real(summary)
        out["route_decisions"] = "ERROR RuntimeError: the stage did not run"
        return out

    monkeypatch.setattr(frz, "_fingerprint", broken)
    source = tmp_path / "rec.json"
    source.write_text(json.dumps(_dated(_record(page_text="X" * 200_000),
                                        "2026-09-07T14:17:00+00:00")), encoding="utf-8")
    assert frz.freeze("SYN-JOB", source,
                      {"accepted_run": "r", "accepted_by": "b",
                       "accepted_on": "2026-09-07"}, reduce_content=True) == 0
    prov = json.loads((job / "provenance.json").read_text(encoding="utf-8"))
    assert prov["fixture"]["dropped"] == [], "nothing may be dropped on a failed fingerprint"
    assert "REFUSED" in prov["fixture"]["reduction"]
    assert "route_decisions" in prov["fixture"]["fingerprint_stages_that_errored"]


def test_the_error_detector_sees_every_stage():
    assert frz._fingerprint_errors({"a": "ERROR X", "b": "fine", "c": "ERROR Y"}) == ["a", "c"]
    assert frz._fingerprint_errors({"a": "fine"}) == []


# ── content reduction is opt-in; compact is the default ───────────────────────────────


def test_content_is_not_reduced_unless_asked(tmp_path, monkeypatch):
    """Compact formatting is safe arithmetic. Removing content is a claim about what every
    reader needs, now and later, and it is worth far less than a correct baseline."""
    replay = tmp_path / "replay"
    job = replay / "SYN-JOB"
    job.mkdir(parents=True)
    (job / "accepted_facts.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    big = _dated(_record(page_text="X" * 200_000), "2026-09-07T14:17:00+00:00")
    source.write_text(json.dumps(big), encoding="utf-8")

    assert frz.freeze("SYN-JOB", source, {"accepted_run": "r", "accepted_by": "b",
                                          "accepted_on": "2026-09-07"}) == 0
    frozen = json.loads((job / "summary.json").read_text(encoding="utf-8"))
    assert len(frozen["pages"][0]["text"]) == 200_000, "the page text is still there"
    prov = json.loads((job / "provenance.json").read_text(encoding="utf-8"))
    assert prov["fixture"]["dropped"] == []
    assert "--reduce" in prov["fixture"]["reduction"]


def test_the_source_checksum_is_recorded_so_the_original_stays_verifiable(tmp_path, monkeypatch):
    """Fingerprint equality proves equivalence for the checks that exist today, not for a future
    reader. The full record has to stay archived, and its checksum is what ties this fixture to
    it."""
    import hashlib
    replay = tmp_path / "replay"
    job = replay / "SYN-JOB"
    job.mkdir(parents=True)
    (job / "accepted_facts.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    payload = json.dumps(_dated(_record(), "2026-09-07T14:17:00+00:00"))
    source.write_text(payload, encoding="utf-8")
    assert frz.freeze("SYN-JOB", source, {"accepted_run": "r", "accepted_by": "b",
                                          "accepted_on": "2026-09-07"}) == 0
    prov = json.loads((job / "provenance.json").read_text(encoding="utf-8"))
    assert prov["fixture"]["source_sha256"] == hashlib.sha256(
        payload.encode("utf-8")).hexdigest()


def test_the_record_identity_is_written_into_provenance(tmp_path, monkeypatch):
    """So a reader can see what the record says about itself beside what a person asserted —
    the two being compared is the whole point."""
    replay = tmp_path / "replay"
    job = replay / "SYN-JOB"
    job.mkdir(parents=True)
    (job / "accepted_facts.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(frz, "REPLAY", replay)
    source = tmp_path / "rec.json"
    rec = _dated(_record(), "2026-09-07T14:17:00+00:00")
    rec["schema"] = "v4"
    source.write_text(json.dumps(rec), encoding="utf-8")
    assert frz.freeze("SYN-JOB", source, {"accepted_run": "r", "accepted_by": "b",
                                          "accepted_on": "2026-09-07"}) == 0
    prov = json.loads((job / "provenance.json").read_text(encoding="utf-8"))
    assert prov["record_says_about_itself"]["schema"] == "v4"


# ── choosing the source by reading the records, not by typing a path ──────────────────


def test_find_reports_each_record_with_the_date_it_says_it_ran(tmp_path, monkeypatch, capsys):
    """The question "which of these is the accepted run?" is answered by the records
    themselves. Asking somebody to type a path they have to go and hunt for invites exactly the
    mistake the identity gate now refuses: the nearest plausible file, labelled with the date we
    wished it had."""
    monkeypatch.setattr(frz, "ROOT", tmp_path)
    out = tmp_path / "output" / "json"
    out.mkdir(parents=True)
    (out / "7332-01.json").write_text(
        json.dumps(_dated(_record(), "2026-09-10T18:59:00+00:00")), encoding="utf-8")
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "7332-01_accepted.json").write_text(
        json.dumps(_dated(_record(), "2026-09-07T14:17:00+00:00")), encoding="utf-8")

    assert frz.find_candidates("7332-01") == 0
    text = capsys.readouterr().out
    assert "2026-09-10T18:59:00+00:00" in text
    assert "2026-09-07T14:17:00+00:00" in text
    assert "7332-01_accepted.json" in text
    # newest first, so the two are never confused by position
    assert text.index("2026-09-10") < text.index("2026-09-07")
    # and the overwriteable one is called out
    assert "rewritten by the next run" in text


def test_find_says_so_rather_than_failing_when_there_is_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(frz, "ROOT", tmp_path)
    assert frz.find_candidates("NOSUCH") == 1
    assert "no saved record found" in capsys.readouterr().out


def test_find_names_a_record_with_no_timestamp_instead_of_hiding_it(tmp_path, monkeypatch,
                                                                   capsys):
    """A record that cannot be attributed must be visible in the list — it is a candidate
    somebody might otherwise pick by accident."""
    monkeypatch.setattr(frz, "ROOT", tmp_path)
    out = tmp_path / "output" / "json"
    out.mkdir(parents=True)
    (out / "7332-01.json").write_text(json.dumps(_record(stamp="")), encoding="utf-8")
    assert frz.find_candidates("7332-01") == 0
    assert "NO processed_at" in capsys.readouterr().out


def test_find_survives_an_unreadable_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(frz, "ROOT", tmp_path)
    out = tmp_path / "output" / "json"
    out.mkdir(parents=True)
    (out / "7332-01.json").write_text("{ not json", encoding="utf-8")
    assert frz.find_candidates("7332-01") == 0
    assert "unreadable" in capsys.readouterr().out


def test_find_needs_none_of_the_acceptance_flags():
    """Listing what exists must never demand answers about a record you have not seen yet."""
    assert frz.main(["NOSUCH-JOB", "--find"]) in (0, 1)


def test_freezing_without_the_acceptance_flags_points_at_find(capsys):
    rc = frz.main(["NOSUCH-JOB"])
    assert rc == 2
    assert "--find" in capsys.readouterr().out


def test_no_documented_command_contains_a_powershell_redirect_placeholder():
    """TWICE I handed over a command containing <placeholder>. PowerShell treats < as a reserved
    redirect operator and fails to parse the line before python sees it, so the instruction was
    simply unrunnable. Every example in the tool and the replay README is a real path."""
    for path in (ROOT / "tools" / "freeze_replay_fixture.py",
                 ROOT / "tests" / "replay" / "README.md"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "freeze_replay_fixture.py" not in line:
                continue
            assert "<" not in line, f"{path.name}: unrunnable in PowerShell -> {line.strip()}"
