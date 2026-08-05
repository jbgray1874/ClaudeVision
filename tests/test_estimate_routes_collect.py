"""What the estimating endpoint files to the share.

The one thing this must never do is file SOME of a run's output. A folder on
the Estimating share holding the HTML report and no workbook looks finished,
and the missing spreadsheet is not discovered by the person who ran it — it is
discovered by the estimator who goes looking for it a week later.

That is exactly what the first version did. It matched output filenames against
the job FOLDER's name, on the assumption that main.py builds every output name
from it. It does not:

    workbook   xlsx_output.write_estimate_xlsx   from the job NUMBER  12422-24
    quote      client_quote_html                 from the job STEM    12422-24-GA_End Cap_RevB

One matcher, two conventions — so the reports were filed and the workbook was
silently left in output\\estimates.

The fix is to stop guessing at names: snapshot the output tree before the run
and take whatever is new or rewritten afterwards. That is an observation rather
than an assumption, and it keeps working when the engine learns to emit a file
nobody has thought of yet.

    python -m pytest tests/test_estimate_routes_collect.py -q
"""

from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "sdi-intelligence-backend"


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    """A stand-in engine checkout with the two output folders the service watches."""
    (tmp_path / "output" / "estimates").mkdir(parents=True)
    (tmp_path / "output" / "json").mkdir(parents=True)

    # config.py wants a real .env; the collector needs only these two names.
    stub = types.ModuleType("config")
    stub.API_KEY = ""
    stub.FILE_ROOTS = [str(tmp_path)]
    monkeypatch.setitem(sys.modules, "config", stub)
    monkeypatch.syspath_prepend(str(BACKEND))

    er = pytest.importorskip("estimate_routes",
                             reason="fastapi/pydantic not installed in this environment")
    monkeypatch.setattr(er, "ENGINE_ROOT", tmp_path)
    return er, tmp_path


def _run(er, root, dest):
    return er.Run(run_id="t", client="Boots", drawing_number="12422-24", units=10,
                  job_folder=str(root / "12422-24-GA_End Cap_RevB"),
                  output_path=str(dest))


def test_both_naming_conventions_are_filed(engine):
    """The workbook and the quote are named differently. Both are deliverables."""
    er, root = engine
    est, js = root / "output" / "estimates", root / "output" / "json"
    dest = root / "share" / "Boots" / "12422-24"

    run = _run(er, root, dest)
    run.before = er._snapshot()
    time.sleep(0.01)

    (est / "12422-24_20260805_143000.xlsx").write_text("workbook")       # job NUMBER
    (est / "12422-24-GA_End Cap_RevB_quote.html").write_text("quote")    # job STEM
    (js / "12422-24-GA_End Cap_RevB.json").write_text("{}")

    er._collect(run)
    filed = {d["name"] for d in run.deliverables}

    assert "12422-24_20260805_143000.xlsx" in filed, (
        "the workbook was not filed — this is the original defect: an estimate "
        "folder with reports in it and no spreadsheet")
    assert "12422-24-GA_End Cap_RevB_quote.html" in filed
    assert "12422-24-GA_End Cap_RevB.json" in filed
    for name in filed:
        assert (dest / name).is_file(), f"{name} was reported but not written"


def test_a_previous_run_is_not_refiled(engine):
    """An estimates folder accumulates. Yesterday's workbook for the same drawing
    must not be filed as today's result — that is a wrong number, not a stale one."""
    er, root = engine
    est = root / "output" / "estimates"
    dest = root / "share" / "Boots" / "12422-24"

    stale = est / "12422-24_20260804_090000.xlsx"
    stale.write_text("yesterday")
    yesterday = time.time() - 86_400
    os.utime(stale, (yesterday, yesterday))

    run = _run(er, root, dest)
    run.before = er._snapshot()
    time.sleep(0.01)
    (est / "12422-24_20260805_143000.xlsx").write_text("today")

    er._collect(run)
    filed = {d["name"] for d in run.deliverables}
    assert "12422-24_20260804_090000.xlsx" not in filed
    assert "12422-24_20260805_143000.xlsx" in filed


def test_only_deliverables_are_filed(engine):
    """The output tree holds working files too. The share is not a scratch folder."""
    er, root = engine
    est = root / "output" / "estimates"
    dest = root / "share" / "Boots" / "12422-24"

    run = _run(er, root, dest)
    run.before = er._snapshot()
    time.sleep(0.01)
    (est / "12422-24_20260805_143000.xlsx").write_text("workbook")
    (est / "page_3.png").write_text("working file")

    er._collect(run)
    filed = {d["name"] for d in run.deliverables}
    assert "page_3.png" not in filed
    assert "12422-24_20260805_143000.xlsx" in filed


def test_the_console_is_filed_with_the_estimate(engine):
    """A number on a share with no account of how it was produced cannot be checked."""
    er, root = engine
    dest = root / "share" / "Boots" / "12422-24"
    run = _run(er, root, dest)
    run.before = er._snapshot()
    run.line("$ main.py --job ... --order-qty 10 --deliverables")

    er._collect(run)
    transcript = dest / "12422-24_run.log"
    assert transcript.is_file()
    text = transcript.read_text(encoding="utf-8")
    assert "--order-qty 10" in text
    assert "[collect]" in text, "the transcript must include the filing result itself"


def test_a_rerun_cannot_overwrite_an_earlier_estimate(engine):
    """The quote is named from the job STEM with no timestamp, so in a flat folder
    a second run replaced the report belonging to the first run's workbook — and
    the workbook, being timestamped, stayed. An estimator opening the older
    spreadsheet then got a report for a different estimate with nothing saying so.

    One folder per run. Nothing is ever overwritten."""
    er, root = engine
    est = root / "output" / "estimates"
    drawing_folder = root / "share" / "Boots" / "12422-24"

    first_at = 1_760_000_000.0
    second_at = first_at + 3_600          # an hour later, same drawing

    for at, workbook in ((first_at, "12422-24_20260805_100000.xlsx"),
                         (second_at, "12422-24_20260805_110000.xlsx")):
        dest = drawing_folder / er.run_folder_name(at, 10)
        run = er.Run(run_id="t", client="Boots", drawing_number="12422-24", units=10,
                     job_folder=str(root / "12422-24-GA_End Cap_RevB"),
                     output_path=str(dest), started_at=at)
        run.before = er._snapshot()
        time.sleep(0.01)
        (est / workbook).write_text(f"workbook for {at}")
        # Same name every run — this is the file that used to be clobbered.
        (est / "12422-24-GA_End Cap_RevB_quote.html").write_text(f"quote for {at}")
        er._collect(run)

    runs = sorted(p for p in drawing_folder.iterdir() if p.is_dir())
    assert len(runs) == 2, f"expected one folder per run, got {[p.name for p in runs]}"

    for at, folder, workbook in ((first_at, runs[0], "12422-24_20260805_100000.xlsx"),
                                 (second_at, runs[1], "12422-24_20260805_110000.xlsx")):
        assert (folder / workbook).is_file(), f"{workbook} missing from {folder.name}"
        quote = folder / "12422-24-GA_End Cap_RevB_quote.html"
        assert quote.read_text() == f"quote for {at}", (
            f"{folder.name} holds a quote from a different run — this is the defect")

    assert runs[0].name < runs[1].name, "folder name order must be time order"


def test_the_run_folder_names_the_quantity(engine):
    """Two estimates of one drawing at different quantities are different
    estimates, and the quantity is the one thing a timestamp cannot tell you."""
    er, _ = engine
    at = 1_760_000_000.0
    assert er.run_folder_name(at, 10) != er.run_folder_name(at, 180)
    assert "(10 off)" in er.run_folder_name(at, 10)
    assert "(180 off)" in er.run_folder_name(at, 180)


def test_nothing_written_is_said_out_loud(engine):
    """A gate nobody asks reports nothing. If the engine exits 0 and writes no
    deliverable, the page must say so rather than showing an empty success."""
    er, root = engine
    dest = root / "share" / "Boots" / "12422-24"
    run = _run(er, root, dest)
    run.before = er._snapshot()

    er._collect(run)
    assert any("NOTHING was copied" in line for line in run.log)
