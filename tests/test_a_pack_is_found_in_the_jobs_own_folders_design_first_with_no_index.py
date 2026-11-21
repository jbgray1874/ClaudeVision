"""A PACK IS FOUND IN THE JOB'S OWN FOLDERS, DESIGN FIRST, WITH NO INDEX (JG, 15 Nov 2026).

"forget the index ... we need to look up the drawing files from design and prototype."

A drawing index that did not hold the Design area offered the resolver only Prototype copies.
Two tracker rows were priced from 13 PDFs and 14 DXFs while the job's Design Technical folder
held 11 assemblies, 13 parts and two drawings reported missing. The tracker batch and the AI
runner now find a pack from the job number: Design is looked in, then Prototype, both now, and
the resolver's own rules choose. An area or folder that cannot be read holds the row.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import drawing_index as di  # noqa: E402
import pack_resolver as pr  # noqa: E402
import tti_pricer as tp  # noqa: E402
from test_tti_pricer_prices_each_row_and_fills_ai_cost import FakePortal, _args  # noqa: E402
from test_the_tracker_batch_runs_the_rows_named_on_their_own_briefs_and_never_lists_the_share_in_silence import _tracker  # noqa: E402

GA = "12181-00-GA"


def _share(tmp_path: Path, design=True, prototype=True, design_holds_ga=True):
    d_root = tmp_path / "Design" / "Customers" / "TTi"
    p_root = tmp_path / "Prototype" / "TTi"
    d_root.mkdir(parents=True)
    p_root.mkdir(parents=True)
    if design:
        tech = d_root / "12181 - Sander Demo" / "12181-Technical"
        (tech / "12181-01 Wooden Frame").mkdir(parents=True)
        if design_holds_ga:
            (tech / "12181-00-GA.SLDASM").write_text("asm")
            (tech / "12181-00-GA_SANDER DEMO_REV A.PDF").write_text("ga")
        (tech / "12181-01 Wooden Frame" / "12181-01-01J.SLDPRT").write_text("part")
        (d_root / "12181 - Sander Demo" / "12181-Creative" / "Maps").mkdir(parents=True)
    (d_root / "12353 - Another Job" / "12353-Technical").mkdir(parents=True)
    (d_root / "12353 - Another Job" / "12353-Technical" / "12353-13-GA.pdf").write_text("other")
    (d_root / "1218 - Short Number").mkdir()
    if prototype:
        job = p_root / "Milwaukee Rome 2026" / "12181 - Sander Demo [Rome 2026]"
        job.mkdir(parents=True)
        (job / "12181-00-GA_SANDER DEMO_REV A.PDF").write_text("ga")
        (job / "12181-03-01M_2.5mm.dxf").write_text("flat")
        nested = p_root / "MW Amsterdam 2027" / "Carpentry" / "12181 - Sander Demo [Rome 2026]"
        nested.mkdir(parents=True)
        (nested / "12181-00-GA_SANDER DEMO_REV A.PDF").write_text("ga")
    return d_root, p_root


@pytest.fixture
def share(tmp_path, monkeypatch):
    def make(**kw):
        d, p = _share(tmp_path, **kw)
        monkeypatch.setenv("SDI_TTI_DESIGN_ROOT", str(d))
        monkeypatch.setenv("SDI_TTI_PROTOTYPE_ROOT", str(p))
        monkeypatch.setenv("SDI_DRAWING_INDEX", str(tmp_path / "no index" / "index.json.gz"))
        monkeypatch.setenv("SDI_TTI_INDEX", str(tmp_path / "no own index" / "index.json.gz"))
        monkeypatch.delenv("SDI_DRIVE_MAP", raising=False)
        monkeypatch.delenv("SDI_PACK_FOLDER_SECONDS", raising=False)
        pr.forget_job_folders()
        return d, p
    yield make
    pr.forget_job_folders()


def _names(rows):
    return sorted(f[0].name for r in rows for f in r[1])


def test_design_and_prototype_are_both_listed_now_and_design_comes_first(share):
    d, p = share()
    rows, said, first = pr.rows_for_job_now(GA, tp.job_areas())
    names = _names(rows)
    assert "12181-00-GA.SLDASM" in names and "12181-01-01J.SLDPRT" in names, "the Design models were not found"
    assert "12181-03-01M_2.5mm.dxf" in names, "the Prototype copy was not offered as well"
    assert str(rows[0][0]).startswith(str(d)), "Design is offered first"
    assert all(f.startswith(str(d)) for f in first) and first
    assert "Design: 1 folder(s) for job 12181 listed now" in said and "sldasm" in said
    assert "Prototype: 2 folder(s) for job 12181" in said, "a job under a trade folder was missed"
    assert not [n for n in names if n.startswith("12353")], "another job's folder was listed"


def test_no_index_exists_and_none_is_asked_for(share, monkeypatch):
    share()
    monkeypatch.setattr(pr, "folders_for", lambda *a, **k: pytest.fail("the drawing index was asked"))
    monkeypatch.setattr(tp, "area_listings", lambda *a, **k: pytest.fail("the areas were listed whole"))
    monkeypatch.setattr(tp, "list_folders", lambda *a, **k: pytest.fail("the areas were walked"))
    seen = {}

    def _resolve(drawing, rows, **kw):
        seen["rows"] = rows
        return {"status": "not found"}
    monkeypatch.setattr(pr, "resolve", _resolve)
    tp._DIRECT[:] = [True]
    try:
        tp.pack_for(GA, [("design", []), ("prototype", [])], "TTI")
    finally:
        tp._DIRECT.clear()
    assert "12181-00-GA.SLDASM" in _names(seen["rows"])


def test_a_design_folder_that_does_not_hold_the_drawing_is_said_and_prototype_stands(share):
    share(design_holds_ga=False)
    rows, said, _first = pr.rows_for_job_now(GA, tp.job_areas())
    assert "Design: 1 folder(s) for job 12181 listed now" in said
    assert "holds NO file named for the drawing; Prototype" in said
    assert "Prototype: 2 folder(s) for job 12181 listed now" in said and said.endswith("holds a file named for the drawing")
    assert "12181-00-GA_SANDER DEMO_REV A.PDF" in _names(rows)


def test_work_that_is_only_in_prototype_is_found_there_after_design_was_looked_in(share):
    share(design=False)
    rows, said, first = pr.rows_for_job_now(GA, tp.job_areas())
    assert said.startswith("Design: no folder for job 12181, looked at now; Prototype: 2 folder(s)")
    assert rows and first == set()


def test_a_job_number_does_not_take_a_longer_numbers_folder(share):
    share()
    rows, said, _f = pr.rows_for_job_now("1218-01-GA", tp.job_areas())
    assert not [n for n in _names(rows) if n.startswith("12181")]
    assert "Design: 1 folder(s) for job 1218 listed now" in said


def test_a_design_area_that_cannot_be_read_holds_the_row(share, tmp_path):
    _d, p = share()
    with pytest.raises(pr.PackCheckStalled, match="Design area could not be read"):
        pr.rows_for_job_now(GA, [("Design", tmp_path / "not" / "there"), ("Prototype", p)])


def test_a_folder_inside_the_job_that_cannot_be_read_holds_the_row(share, monkeypatch):
    share()
    real = di._list
    monkeypatch.setattr(di, "_list", lambda f: None if Path(f).name == "12181-01 Wooden Frame" else real(f))
    with pytest.raises(pr.PackCheckStalled, match="could not be read .*12181-01 Wooden Frame"):
        pr.rows_for_job_now(GA, tp.job_areas())


def test_a_share_that_does_not_answer_in_time_holds_the_row(share, monkeypatch):
    share()
    monkeypatch.setenv("SDI_PACK_FOLDER_SECONDS", "1")
    real = di._list

    def slow(f):
        if Path(f).name == "12181-Technical":
            time.sleep(3)
        return real(f)
    monkeypatch.setattr(di, "_list", slow)
    with pytest.raises(pr.PackCheckStalled, match="did not finish within 1 s"):
        pr.rows_for_job_now(GA, tp.job_areas())


def test_the_batch_takes_this_route_unless_the_index_is_asked_for_by_name(share, tmp_path, monkeypatch, capsys):
    share()
    sheet = _tracker(tmp_path, [(GA, "Sander demo", "", "", 3)])
    monkeypatch.setenv("SDI_TTI_INPUTS", str(tmp_path / "inputs"))
    monkeypatch.setattr(tp, "area_listings", lambda *a, **k: pytest.fail("the index route was taken"))
    monkeypatch.setattr(pr, "resolve", lambda *a, **k: {"status": "not found"})
    a = _args(sheet, dry_run=True)
    a.use_index = False
    tp.run_batch(a, portal=FakePortal(), status_path=None, sleep=lambda s: None)
    assert "No index is used" in capsys.readouterr().out


def test_the_same_lookup_is_there_for_the_other_entry_points(share, monkeypatch, tmp_path):
    d, p = share()
    monkeypatch.setenv("SDI_DRAWING_INDEX_ROOTS", f"{d.parent}|{p.parent}")
    monkeypatch.setattr(pr, "folders_for", lambda *a, **k: pytest.fail("the drawing index was asked"))
    rows, said, lookup = pr.folders_now(GA)
    assert callable(lookup) and "12181-00-GA.SLDASM" in _names(rows)
    assert said.startswith("Design: 1 folder(s) for job 12181 listed now")


def test_the_row_says_what_kinds_of_file_its_pack_holds():
    assert tp._formats(["a.PDF", "b.pdf", "c.SLDASM", "d.dxf", "e.dxf", "f.dxf"]) == {"dxf": 3, "pdf": 2, "sldasm": 1}


# ── the AI runner: Design primary, TTI/explicit bespoke Prototype supplements ────────────
def _ai_runner(tmp_path, monkeypatch, design=True, prototype=True):
    """A share with the client's folder under a customers folder, as the Design area is."""
    import live_enquiry_runner as ler
    d, p = _share(tmp_path, design=design, prototype=prototype)
    monkeypatch.setenv("SDI_DRAWING_INDEX_ROOTS", f"{d.parent}|{p.parent}")
    monkeypatch.setenv("SDI_DRAWING_INDEX", str(tmp_path / "no index" / "index.json.gz"))
    monkeypatch.delenv("SDI_PACK_FOLDER_SECONDS", raising=False)
    pr.forget_job_folders()
    monkeypatch.setattr(pr, "folders_for", lambda *a, **k: pytest.fail("the drawing index was asked"))
    live = tmp_path / "Live Enquiry"
    live.mkdir()
    return ler, ler.DesignShare(live), ler.EnquiryRow(row=3, customer="TTI", drawing=GA)


def test_the_ai_runner_finds_the_design_pack_from_the_job_number_with_no_index(tmp_path, monkeypatch):
    ler, source, row = _ai_runner(tmp_path, monkeypatch)
    seen = {}

    def _resolve(drawing, rows, **kw):
        seen["names"] = _names(rows)
        seen["folders"] = [str(r[0]) for r in rows]
        return {"status": "not found"}
    monkeypatch.setattr(pr, "resolve", _resolve)
    source.find(row)
    assert "12181-00-GA.SLDASM" in seen["names"] and "12181-01-01J.SLDPRT" in seen["names"]
    assert any("Prototype" in f for f in seen["folders"]), "TTI's Prototype supplement was not offered"
    pr.forget_job_folders()


def test_the_ai_runner_does_not_take_a_non_tti_pack_that_is_only_in_prototype(tmp_path, monkeypatch):
    ler, source, row = _ai_runner(tmp_path, monkeypatch, design=False)
    row.customer = 'Other customer'
    monkeypatch.delenv('SDI_PACK_PROTOTYPE_JOBS', raising=False)
    monkeypatch.setattr(pr, "resolve", lambda *a, **k: pytest.fail("a Prototype pack was offered to the resolver"))
    assert source.find(row) is None, "the Live Enquiry folder's own reason must stand"
    pr.forget_job_folders()


def test_the_ai_runner_holds_the_row_when_the_design_area_cannot_be_read(tmp_path, monkeypatch):
    ler, source, row = _ai_runner(tmp_path, monkeypatch)
    monkeypatch.setenv("SDI_DRAWING_INDEX_ROOTS", f"{tmp_path / 'gone'}|{tmp_path / 'Prototype'}")
    pr.forget_job_folders()
    got = source.find(row)
    assert got is not None and got.status == "held"
    assert "could not be checked" in got.reason and "Design area could not be read" in got.reason
    pr.forget_job_folders()
