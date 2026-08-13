"""What the RUNNER files to the share.

The runner is the machine that actually has the files, so it is the machine that
files them. The one thing it must never do is file SOME of a run's output: a
folder on the Estimating share holding the HTML report and no workbook looks
finished, and the missing spreadsheet is not discovered by the person who ran it
— it is discovered by the estimator who goes looking for it a week later.

That is exactly what the first version did. It matched output filenames against
the job FOLDER's name, on the assumption that main.py builds every output name
from it. It does not:

    workbook   xlsx_output.write_estimate_xlsx   from the job NUMBER
    quote      client_quote_html                 from the job STEM

One matcher, two conventions. The fix is to stop guessing at names: snapshot the
output tree before the run and take whatever is new or rewritten afterwards.

These tests import the runner directly. It defers `requests` to inside its
polling loop precisely so everything that DECIDES something can be tested with
no network and no server anywhere near it.

    python -m pytest tests/test_estimate_runner.py -q
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

RUNNER_DIR = Path(__file__).resolve().parents[1] / "tools" / "runner"


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    """A stand-in engine checkout with the two output folders the runner watches."""
    (tmp_path / "output" / "estimates").mkdir(parents=True)
    (tmp_path / "output" / "json").mkdir(parents=True)
    monkeypatch.syspath_prepend(str(RUNNER_DIR))
    import sdi_estimate_runner as runner
    return runner, tmp_path


def test_both_naming_conventions_are_filed(engine):
    """The workbook and the quote are named differently. Both are deliverables."""
    runner, root = engine
    est, js = root / "output" / "estimates", root / "output" / "json"
    dest = root / "share" / "Boots" / "12422-24"

    before = runner.snapshot(root)
    time.sleep(0.01)
    (est / "12422-24_20260805_143000.xlsx").write_text("workbook")       # job NUMBER
    (est / "12422-24-GA_End Cap_RevB_quote.html").write_text("quote")    # job STEM
    (js / "12422-24-GA_End Cap_RevB.json").write_text("{}")

    filed = {d["name"] for d in runner.collect(root, dest, before, [], "12422-24")}

    assert "12422-24_20260805_143000.xlsx" in filed, (
        "the workbook was not filed — the original defect: an estimate folder "
        "with reports in it and no spreadsheet")
    assert "12422-24-GA_End Cap_RevB_quote.html" in filed
    assert "12422-24-GA_End Cap_RevB.json" in filed
    for name in filed:
        assert (dest / name).is_file(), f"{name} was reported but not written"


def test_a_previous_run_is_not_refiled(engine):
    """An estimates folder accumulates. Yesterday's workbook for the same drawing
    must not be filed as today's result — that is a wrong number, not a stale one."""
    runner, root = engine
    est = root / "output" / "estimates"
    dest = root / "share" / "Boots" / "12422-24"

    stale = est / "12422-24_20260804_090000.xlsx"
    stale.write_text("yesterday")
    yesterday = time.time() - 86_400
    os.utime(stale, (yesterday, yesterday))

    before = runner.snapshot(root)
    time.sleep(0.01)
    (est / "12422-24_20260805_143000.xlsx").write_text("today")

    filed = {d["name"] for d in runner.collect(root, dest, before, [], "12422-24")}
    assert "12422-24_20260804_090000.xlsx" not in filed
    assert "12422-24_20260805_143000.xlsx" in filed


def test_only_deliverables_are_filed(engine):
    """The output tree holds working files too. The share is not a scratch folder."""
    runner, root = engine
    est = root / "output" / "estimates"
    dest = root / "share" / "Boots" / "12422-24"

    before = runner.snapshot(root)
    time.sleep(0.01)
    (est / "12422-24_20260805_143000.xlsx").write_text("workbook")
    (est / "page_3.png").write_text("working file")

    filed = {d["name"] for d in runner.collect(root, dest, before, [], "12422-24")}
    assert "page_3.png" not in filed
    assert "12422-24_20260805_143000.xlsx" in filed


def test_the_console_is_filed_with_the_estimate(engine):
    """A number on a share with no account of how it was produced cannot be checked."""
    runner, root = engine
    dest = root / "share" / "Boots" / "12422-24"
    log = ["$ main.py --job ... --order-qty 10 --deliverables"]

    runner.collect(root, dest, runner.snapshot(root), log, "12422-24")

    transcript = dest / "12422-24_run.log"
    assert transcript.is_file()
    text = transcript.read_text(encoding="utf-8")
    assert "--order-qty 10" in text
    assert "[collect]" in text, "the transcript must include the filing result itself"


def test_a_rerun_cannot_overwrite_an_earlier_estimate(engine):
    """The quote is named from the job STEM with no timestamp, so in a flat folder
    a second run replaced the report belonging to the first run's workbook — and
    the workbook, being timestamped, stayed. An estimator opening the older
    spreadsheet then got a report for a different estimate, with nothing saying so.

    One folder per run. Nothing is ever overwritten. The folder names come from
    the server, so they are mirrored here rather than imported — what is under
    test is that collect() writes into whatever distinct folder it is given."""
    runner, root = engine
    est = root / "output" / "estimates"
    drawing_folder = root / "share" / "Boots" / "12422-24"

    for stamp, workbook in (("2026-08-05 10-00-00 (10 off)", "12422-24_20260805_100000.xlsx"),
                            ("2026-08-05 11-00-00 (10 off)", "12422-24_20260805_110000.xlsx")):
        dest = drawing_folder / stamp
        before = runner.snapshot(root)
        time.sleep(0.01)
        (est / workbook).write_text(f"workbook for {stamp}")
        # Same name every run — this is the file that used to be clobbered.
        (est / "12422-24-GA_End Cap_RevB_quote.html").write_text(f"quote for {stamp}")
        runner.collect(root, dest, before, [], "12422-24")

    runs = sorted(p for p in drawing_folder.iterdir() if p.is_dir())
    assert len(runs) == 2, f"expected one folder per run, got {[p.name for p in runs]}"

    for folder, workbook in ((runs[0], "12422-24_20260805_100000.xlsx"),
                             (runs[1], "12422-24_20260805_110000.xlsx")):
        assert (folder / workbook).is_file(), f"{workbook} missing from {folder.name}"
        quote = folder / "12422-24-GA_End Cap_RevB_quote.html"
        assert quote.read_text() == f"quote for {folder.name}", (
            f"{folder.name} holds a quote from a different run — this is the defect")

    assert runs[0].name < runs[1].name, "folder name order must be time order"


def test_nothing_written_is_said_out_loud(engine):
    """A gate nobody asks reports nothing. If the engine exits 0 and writes no
    deliverable, the page must say so rather than showing an empty success."""
    runner, root = engine
    log = []
    runner.collect(root, root / "share" / "Boots" / "12422-24",
                   runner.snapshot(root), log, "12422-24")
    assert any("NOTHING was copied" in line for line in log)


def test_the_engine_is_driven_exactly_as_a_person_would(engine):
    """--deliverables is not a flag the caller can forget: the page promises a
    complete set every time, so it is not optional in the command."""
    runner, root = engine
    cmd = runner.engine_command(root, root / "nope.exe", root / "job", 10, "Boots")
    assert "--deliverables" in cmd
    assert cmd[cmd.index("--order-qty") + 1] == "10"
    assert cmd[cmd.index("--customer") + 1] == "Boots"
    assert cmd[0] == "python", "a missing engine python must fall back to PATH, not crash"


# ── one runner per machine ───────────────────────────────────────────────────
def test_a_second_runner_on_this_machine_refuses_and_names_the_first(engine):
    """Two runners on one desktop fight over one Excel and one SOLIDWORKS
    session, and the service cannot tell them apart because the runner id is
    deliberately stable per machine. Six were found running at once."""
    runner, root = engine

    held = runner.claim_the_machine(root)
    assert held is not None

    with pytest.raises(SystemExit) as exit_info:
        runner.claim_the_machine(root)

    said = str(exit_info.value)
    assert "already running on this machine" in said
    assert f"pid {os.getpid()}" in said, "it must name WHICH process, not just that one exists"
    assert "sdi_estimate_runner" in said, "and give the command to find strays"


def test_the_lock_is_released_when_the_holder_lets_go(engine):
    """The lock is an OS lock, not a pid file, precisely so it survives nothing:
    Ctrl+C, a crash, a closed window, a laptop that slept. A pid file outlives
    all of those and then refuses to start the runner you actually want."""
    runner, root = engine
    first = runner.claim_the_machine(root)
    first.close()                                   # as process exit would
    second = runner.claim_the_machine(root)         # must not raise
    assert second is not None
    second.close()


def test_writing_the_identity_does_not_fight_the_lock(engine):
    """The first version locked byte 0 and then wrote the holder's identity to
    byte 0 through the same handle, and died on the flush with Permission
    denied. The lock byte sits far past anything written."""
    runner, root = engine
    assert runner._LOCK_BYTE > runner._IDENTITY_BYTES, (
        "the locked byte must be outside the region the identity is written to")
    held = runner.claim_the_machine(root)           # would raise if they overlapped
    lock_file = root / "output" / ".runner.lock"
    text = lock_file.read_bytes()[:runner._IDENTITY_BYTES].decode().strip()
    assert f"pid {os.getpid()}" in text
    held.close()


def test_an_unexpected_failure_never_stops_the_runner(engine, monkeypatch, capsys):
    """THE GUARD MUST NOT BECOME THE PROBLEM. This one has twice stopped the one
    runner somebody wanted: once by locking the byte it then wrote to, once by
    failing to read a byte another handle held. A definite "somebody else has
    this" is refused; anything else at all warns and carries on."""
    runner, root = engine

    def explode(*_a, **_k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(runner.os, "open", explode)

    assert runner.claim_the_machine(root) is None, "it must return, not raise"
    assert "could not take the single-runner lock" in capsys.readouterr().out


def test_the_refusal_survives_the_platform_branch(engine):
    """Two questions kept apart: which locking API this platform has, and whether
    the lock succeeded. Answering both in one try/except put fcntl.flock inside
    the except ImportError handler, so the error it raises when another process
    holds the lock escaped the sibling except OSError — and the refusal quietly
    became a fail-open."""
    runner, root = engine
    held = runner.claim_the_machine(root)
    assert held is not None

    # RE-LOCKING YOUR OWN HANDLE IS NOT A TEST OF ANYTHING, and asserting it
    # succeeded encoded one platform's semantics as if they were the rule. POSIX
    # flock is re-entrant per descriptor, so this returned True on Linux and the
    # assertion looked meaningful; Windows byte-range locks are not re-entrant, so
    # the same call correctly returns False and the test failed on the only
    # platform the runner runs on. The claim below — that a SECOND handle is
    # refused — is the one that matters, and it is true on both.

    import os as _os
    second = _os.fdopen(_os.open(str(root / "output" / ".runner.lock"),
                                 _os.O_RDWR | _os.O_CREAT), "r+b")
    try:
        assert runner._take_lock(second) is False, (
            "a second handle must be refused, not fail open")
    finally:
        second.close(); held.close()


def test_reading_the_identity_never_reaches_the_locked_byte(engine, monkeypatch):
    """THE LOCK WAS BREAKING THE READ IT EXISTS TO ENABLE, on Windows only.

    The identity sits at byte 0 and the lock at byte 4096, which looks like ample
    separation and is not: a BUFFERED read of 256 bytes issues a raw read of
    io.DEFAULT_BUFFER_SIZE — 8192 — so it spans the locked byte every time. POSIX
    flock is advisory and blocks nothing, so every test passed here while the
    refusal on Windows could not name the pid and said "another process" instead.
    The one thing an estimator needs from that message is which window to close.

    The outcome is indistinguishable on the platform these tests run on, so this
    asserts the MECHANISM instead. Note which assertion does the work: a buffered
    implementation fills through FileIO.readinto at C level and never calls
    os.read at all, so `assert asked` is what fails if this is reverted. The size
    check is a second line on the raw path, not the primary guard — a monkeypatch
    of os.read cannot observe the very reads that caused the defect.
    """
    runner, root = engine
    held = runner.claim_the_machine(root)
    assert held is not None

    asked = []
    real_read = runner.os.read
    monkeypatch.setattr(runner.os, "read",
                        lambda fd, n: (asked.append(n), real_read(fd, n))[1])

    runner._read_identity(root / "output" / ".runner.lock")

    assert asked, "the identity must actually be read"
    assert max(asked) <= runner._IDENTITY_BYTES, (
        f"a read of {max(asked)} bytes reaches past byte {runner._LOCK_BYTE} and is "
        f"refused by a mandatory lock; it must ask for at most "
        f"{runner._IDENTITY_BYTES}")


def test_the_refusal_names_the_holder_while_the_lock_is_held(engine):
    """The user-visible property the size guard above protects: with the lock
    genuinely held, the identity is still readable and the message still says who."""
    runner, root = engine
    held = runner.claim_the_machine(root)
    assert held is not None
    said = runner._read_identity(root / "output" / ".runner.lock")
    assert f"pid {os.getpid()}" in said, said


# ── the lease survives a phase that prints nothing ───────────────────────────
class _FakeProc:
    """An engine that says one thing, then works in silence, then finishes.

    That is not a contrived shape — it is the real one. The 11650 pack prints steadily
    through extraction and BOM reconciliation and then goes quiet for minutes driving
    Excel and SOLIDWORKS over COM, which is the most expensive part of the run.
    """

    def __init__(self, quiet_for):
        self._quiet_for = quiet_for
        self._alive = True
        self.returncode = 0

    @property
    def stdout(self):
        def _lines():
            yield "   [bom] 28 line(s)\n"
            time.sleep(self._quiet_for)          # the silence that killed two runs
            self._alive = False
            yield "  Order quantity set to 45\n"
        return _lines()

    def poll(self):
        return None if self._alive else 0

    def wait(self):
        self._alive = False
        return 0


class _FakeRequests:
    def __init__(self):
        self.progress = []
        self.completed = []

    def post(self, url, json=None, headers=None, timeout=None):
        (self.completed if url.endswith("/complete") else self.progress).append(json)

        class _R:
            @staticmethod
            def raise_for_status():
                return None
        return _R()


def _run_with_a_quiet_engine(runner, root, monkeypatch, quiet_for=0.45):
    monkeypatch.setattr(runner, "_BEAT_SECONDS", 0.02)
    monkeypatch.setattr(runner, "_SAY_QUIET_AFTER", 0.05)
    monkeypatch.setattr(runner.subprocess, "Popen",
                        lambda *a, **k: _FakeProc(quiet_for))
    req = _FakeRequests()
    job = {"run_id": "r1", "client": "Boots", "units": 45, "drawing_number": "11650-00",
           "job_folder": str(root), "output_path": str(root / "share" / "Boots")}
    runner._execute(req, "http://x/api/estimate", {}, job, root,
                    Path("python"), "rnr-1")
    return req


def test_a_silent_engine_keeps_its_lease(engine, monkeypatch):
    """THE DEFECT THAT DISCARDED TWO GOOD RUNS OF 11650, AT 180s AND 181s.

    The lease was renewed by the act of PRINTING, so a phase that works hard and says
    nothing was indistinguishable from a machine that had gone to sleep. The service
    failed the run, threw away several minutes of correct work, and told the operator to
    check whether the laptop had closed.

    The engine here emits one line, goes quiet for many beats, then finishes. Every post
    during that silence is a lease renewal that would not have happened before.
    """
    runner, root = engine
    req = _run_with_a_quiet_engine(runner, root, monkeypatch)

    # POSTS INSIDE THE SILENCE, not posts in total. A bare count passes on the three the
    # engine's own two lines already produce, so it survived deleting the heartbeat thread
    # outright -- a test that cannot fail on the defect it names.
    def _at(needle):
        for i, post in enumerate(req.progress):
            if any(needle in line for line in (post.get("lines") or [])):
                return i
        raise AssertionError(f"{needle!r} was never posted at all")

    during = _at("Order quantity") - _at("[bom]") - 1
    assert during >= 2, (
        f"{during} progress post(s) between the last thing the engine said and the next — "
        f"the lease is still being renewed by the act of printing, so a quiet phase runs "
        f"the clock out and a working run is discarded")


def test_the_silence_is_reported_rather_than_hidden(engine, monkeypatch):
    """The original design worried that a timer would keep a WEDGED run looking alive,
    and that worry is right. It is answered by saying how long the quiet has run, so a
    wedge is visible on the page instead of being papered over by a heartbeat."""
    runner, root = engine
    req = _run_with_a_quiet_engine(runner, root, monkeypatch)
    said = " ".join(line for post in req.progress for line in (post.get("lines") or []))
    assert "no output for" in said, (
        "a run that goes quiet for minutes now holds its lease and says nothing about "
        "it — that is how a wedged engine would look healthy for ever")


def test_the_beat_stops_when_the_engine_does(engine, monkeypatch):
    """A heartbeat that outlives the process it reports on is the thing the original
    design was protecting against, and it must stay protected against: the beat is
    conditional on proc.poll(), so a crashed engine still times out on schedule."""
    runner, root = engine
    req = _run_with_a_quiet_engine(runner, root, monkeypatch, quiet_for=0.1)
    before = len(req.progress)
    time.sleep(0.2)                                   # many beats, if any were still running
    assert len(req.progress) == before, "the heartbeat is still beating after the engine ended"
    assert req.completed, "the run never reported its outcome"


def test_the_beat_cannot_be_configured_slower_than_the_lease(engine):
    """A runner beating less often than the lease it renews is the same defect with
    different numbers, and it would arrive silently through an env var nobody re-read."""
    runner, _ = engine
    lease = int(os.getenv("SDI_RUNNER_LEASE_SECONDS", "180"))
    assert runner._BEAT_SECONDS * 2 < lease, (
        f"beat every {runner._BEAT_SECONDS}s against a {lease}s lease leaves no margin "
        f"for a slow post and a retry")
