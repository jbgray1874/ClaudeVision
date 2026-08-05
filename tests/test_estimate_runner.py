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
