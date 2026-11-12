"""The covering note and the automatic e-mail link the WAV, or say it was not made (JG, 12 Nov 2026).

"Add a clearly labelled 'Listen to the estimate walkthrough - WAV' link to both the HTML covering
note and the automatic email body. Use a location recipients can access, not a runner-local path.
If audio generation failed, say so rather than showing a broken link." And two runs at once must
not exchange audio."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))
import estimate_walkthrough as ew  # noqa: E402

URL = "https://portal.example/estimating/walkthrough/tok123"


def _files(job, stamp, wav=True):
    names = [f"{job}_{stamp}.xlsx", f"{job}_{stamp}_covering_email.html", f"{job}_{stamp}_walkthrough.txt"]
    if wav:
        names.append(f"{job}_{stamp}_walkthrough.wav")
    return [{"name": n, "path": rf"C:\ClaudeVision\output\estimates\{n}"} for n in names]


def test_the_email_carries_a_labelled_wav_link_served_by_the_portal():
    audio = ew.audio_of(_files("6364-01", "20261111_143053"))
    note = ew.email_button({"html": "<div>note</div>", "text": "note"}, URL, audio)
    link = "https://portal.example/api/estimate/walkthrough/tok123/file/6364-01_20261111_143053_walkthrough.wav"
    assert link in note["html"] and "Listen to the estimate walkthrough &mdash; WAV" in note["html"]
    assert f"Listen to the estimate walkthrough - WAV: {link}" in note["text"]
    assert "C:\\" not in note["html"] and "output\\estimates" not in note["text"]


def test_a_run_with_words_and_no_sound_says_so_and_links_nothing_broken():
    audio = ew.audio_of(_files("6364-01", "20261111_143053", wav=False))
    assert audio == ""
    note = ew.email_button({"html": "<div>note</div>", "text": "note"}, URL, audio)
    assert "its audio could not be generated" in note["html"] and "/file/" not in note["html"]
    assert "could not be generated" in note["text"]


def test_a_run_with_no_walkthrough_keeps_the_buttons_as_they_were():
    assert ew.audio_of([{"name": "6364-01_20261111_143053.xlsx", "path": "x"}]) is None
    note = ew.email_button({"html": "<div>note</div>", "text": "note"}, URL, None)
    assert "WAV" not in note["html"] and "could not be generated" not in note["html"]


def test_the_filed_note_gains_the_same_link(tmp_path):
    f = tmp_path / "6364-01_20261111_143053_covering_email.html"
    f.write_text("<!-- subject: x -->\n<div>note</div>", encoding="utf-8")
    f.with_suffix(".txt").write_text("note", encoding="utf-8")
    assert ew.stamp_note_files([str(f)], URL, "6364-01_20261111_143053_walkthrough.wav") == [str(f)]
    assert "/file/6364-01_20261111_143053_walkthrough.wav" in f.read_text(encoding="utf-8")
    assert f.read_text(encoding="utf-8").startswith("<!-- subject: x -->")
    assert "WAV: https://portal.example/api/estimate/walkthrough/tok123/file/" in f.with_suffix(".txt").read_text(encoding="utf-8")


def test_two_runs_at_once_each_link_their_own_audio():
    """The service keeps only a run's own files (own_record), so the audio named is the run's."""
    sys.path.insert(0, str(ROOT / "src"))
    import own_record
    a, b = _files("12674-01-GA", "20261111_141715"), _files("6364-01", "20261111_143053")
    theirs = set(own_record.other_jobs_files(a + b, "6364-01"))
    mine = [f for f in a + b if f["name"] not in theirs]
    assert ew.audio_of(mine) == "6364-01_20261111_143053_walkthrough.wav"
    theirs = set(own_record.other_jobs_files(a + b, "12674-01-GA"))
    assert ew.audio_of([f for f in a + b if f["name"] not in theirs]) == "12674-01-GA_20261111_141715_walkthrough.wav"
