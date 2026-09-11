"""requirements.txt declared the contract and nothing enforced it.

Launching the engine on a box whose environment had lost two packages produced, in this order:

    *** UDEF/SDILive COULD NOT BE REACHED — RuntimeError: pyodbc is required for PricingService
    [timing]   extract_pdf_summary   0.0s  STARTED AND NEVER FINISHED
    RuntimeError: pdfplumber is not installed.

Three symptoms of one fact — two core-required packages were absent — arriving after sixteen
files had been found and one had started, none of them naming the command that fixes it.
requirements.txt had listed both as core-required all along.

These tests cover the preflight that closes it, and two properties matter more than the checking
itself: the required list is DERIVED from requirements.txt rather than duplicated, and a package
that requirements.txt requires but the preflight cannot import-check is reported as UNCHECKED
rather than passing silently.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import dependency_preflight as dp                                        # noqa: E402


# ── the required list comes from requirements.txt ──────────────────────────────────────


def test_the_required_list_is_read_from_requirements_not_hardcoded():
    """A second hand-written list would drift from the first, and a dependency added to one and
    not the other is exactly the silent gap this module is about."""
    required = dp.required_distributions()
    assert required, "nothing was parsed — the heading match has broken"
    for expected in ("pdfplumber", "pyodbc", "openpyxl", "ezdxf"):
        assert expected in required, expected


def test_the_optional_block_is_not_treated_as_required():
    """requirements.txt carries a commented optional section; pulling numpy or qdrant-client
    into the required set would stop every machine that sensibly lacks them."""
    required = dp.required_distributions()
    for optional in ("numpy", "opencv-python", "pytesseract", "qdrant-client",
                     "sentence-transformers"):
        assert optional not in required, optional


def test_a_trailing_comment_is_not_part_of_the_package_name():
    """Every line in that file carries an inline comment explaining the dependency."""
    assert all("#" not in name and " " not in name
               for name in dp.required_distributions())


def test_an_unparseable_requirements_file_yields_nothing_rather_than_raising(tmp_path):
    assert dp.required_distributions(tmp_path / "absent.txt") == []


def test_a_reformatted_heading_would_be_caught_by_the_emptiness_check(tmp_path):
    """The heading is matched on its words, so the file can be reflowed. If it is ever renamed,
    the required list empties — which the first test above fails on rather than quietly
    checking nothing."""
    path = tmp_path / "requirements.txt"
    path.write_text("# Some Other Heading\npdfplumber\n", encoding="utf-8")
    assert dp.required_distributions(path) == []


# ── platform markers ──────────────────────────────────────────────────────────────────


def test_pywin32_is_required_on_windows_and_not_elsewhere(tmp_path):
    """A Linux CI run must not be told it is missing a package it must not have."""
    path = tmp_path / "requirements.txt"
    path.write_text("# Core pipeline (required)\n"
                    "pdfplumber\n"
                    "pywin32; sys_platform == \"win32\"\n", encoding="utf-8")
    required = dp.required_distributions(path)
    assert ("pywin32" in required) == (sys.platform == "win32")


def test_an_unrecognised_marker_is_not_grounds_to_skip_a_check(tmp_path):
    """Guessing at a marker language we do not use would be worse than not supporting it: the
    safe direction is to check the package, not to assume it is irrelevant."""
    path = tmp_path / "requirements.txt"
    path.write_text("# Core pipeline (required)\n"
                    "somepkg; python_version >= \"3.9\"\n", encoding="utf-8")
    assert "somepkg" in dp.required_distributions(path)


def test_a_version_pin_is_stripped_from_the_name(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("# Core pipeline (required)\npdfplumber>=0.10.0\nPillow==10.0\n",
                    encoding="utf-8")
    assert dp.required_distributions(path) == ["pdfplumber", "Pillow"]


# ── every required package can actually be checked ────────────────────────────────────


def test_every_required_distribution_has_an_import_name():
    """THE GUARD THAT KEEPS THIS HONEST. `pip install PyMuPDF` gives `import fitz`; the mapping
    cannot be derived from the name. A required package with no mapping is UNCHECKED, and an
    unchecked package reads exactly like a satisfied one — so adding a dependency without saying
    how to import it fails here rather than silently going unverified."""
    unmapped = [d for d in dp.required_distributions() if d not in dp.IMPORT_NAME]
    assert not unmapped, (
        f"requirements.txt requires {unmapped} and dependency_preflight.IMPORT_NAME has no "
        f"import name for them, so they would never be verified")


def test_every_mapped_module_has_a_stated_consequence():
    """"pdfplumber is missing" is better than a traceback; "and without it no PDF text can be
    read" tells the reader whether they can proceed at all."""
    missing = [m for m in dp.IMPORT_NAME.values() if not dp.CONSEQUENCE.get(m)]
    assert not missing, f"no consequence stated for {missing}"


def test_an_unmapped_requirement_is_reported_as_unchecked_not_passed(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("# Core pipeline (required)\nsomething-nobody-mapped\n", encoding="utf-8")
    result = dp.check(path)
    assert result["unmapped"] == ["something-nobody-mapped"]
    assert result["ok"] is False, "unchecked must not read as satisfied"


# ── fatal versus degrading ────────────────────────────────────────────────────────────


def test_pdfplumber_is_fatal_because_its_absence_provably_raises():
    """extract_with_pdfplumber raises and the scan dies inside page extraction. That is the
    failure that prompted this module."""
    assert "pdfplumber" in dp.FATAL


def test_the_fatal_set_is_small_and_evidence_based():
    """Stopping the run for every missing required package would be its own overreach: a box
    without openai reads every BOM with one reader instead of two, which is far better than
    nothing. A package joins FATAL when a failure proves it belongs."""
    assert dp.FATAL <= {"pdfplumber"}, (
        "FATAL has grown — each addition needs a failure that proves the absence stops the "
        "run, not a judgement that the package looks important")
    for degrading in ("pyodbc", "openai", "xlrd"):
        assert degrading not in dp.FATAL


def test_a_fatal_absence_stops_the_run(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("# Core pipeline (required)\npdfplumber\n", encoding="utf-8")
    result = dp.check(path)
    if not result["missing"]:
        pytest.skip("pdfplumber is installed here, so its absence cannot be exercised")
    assert result["can_run"] is False
    assert dp.report(result, log=lambda *a: None) is False


def test_a_degrading_absence_lets_the_run_continue(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("# Core pipeline (required)\npyodbc\n", encoding="utf-8")
    result = dp.check(path)
    if not result["missing"]:
        pytest.skip("pyodbc is installed here")
    assert result["can_run"] is True, "a run without catalogue prices is still worth having"
    assert result["ok"] is False, "but the environment is not complete and must say so"
    assert dp.report(result, log=lambda *a: None) is True


def test_the_report_names_the_install_command(capsys):
    result = {"ok": False, "can_run": False,
              "fatal": [{"distribution": "pdfplumber", "module": "pdfplumber",
                         "consequence": "no PDF text"}],
              "degrading": [], "missing": [], "unmapped": [],
              "checked": [], "requirements": "requirements.txt"}
    dp.report(result)
    text = capsys.readouterr().out
    assert "pip install pdfplumber" in text
    assert "pip install -r requirements.txt" in text
    assert "BEFORE the scan" in text


def test_a_complete_environment_says_so_briefly(capsys):
    result = {"ok": True, "can_run": True, "fatal": [], "degrading": [], "missing": [],
              "unmapped": [], "checked": ["a", "b"], "requirements": "requirements.txt"}
    assert dp.report(result) is True
    assert "2 required package(s) present" in capsys.readouterr().out


# ── what the run records about its own environment ────────────────────────────────────


def test_the_environment_description_names_every_missing_package_and_its_consequence():
    """Same principle as money_provenance: a console warning nobody kept is not a record. An
    estimate produced without pyodbc is costed from fallbacks, and a reader months later has no
    other way to know."""
    result = {"ok": False, "can_run": True, "fatal": [], "missing": [
        {"distribution": "pyodbc", "module": "pyodbc", "consequence": "prices MISSING"}],
        "degrading": [], "unmapped": ["oddity"], "checked": [], "requirements": "r.txt"}
    described = dp.describe_environment(result)
    assert described["complete"] is False
    assert described["missing"] == [{"package": "pyodbc", "consequence": "prices MISSING"}]
    assert described["unverified"] == ["oddity"]
    assert "without the packages listed above" in described["why_it_matters"]


def test_a_complete_environment_is_described_as_complete():
    result = {"ok": True, "can_run": True, "fatal": [], "degrading": [], "missing": [],
              "unmapped": [], "checked": ["a"], "requirements": "r.txt"}
    described = dp.describe_environment(result)
    assert described["complete"] is True
    assert described["missing"] == []


# ── wired in, and the messages that were bare ─────────────────────────────────────────


def test_the_preflight_runs_before_any_scanning():
    """Discovering this sixteen files in is the defect. It must sit at the top of main()."""
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8", errors="ignore")
    assert "import dependency_preflight as _dp" in source
    assert "raise SystemExit(2)" in source
    preflight_at = source.index("import dependency_preflight as _dp")
    scan_at = source.index("summary, output_paths = scan_file(")
    assert preflight_at < scan_at, "the preflight must precede the scan"


def test_the_run_records_its_environment_on_the_estimate():
    source = (ROOT / "src" / "main.py").read_text(encoding="utf-8", errors="ignore")
    assert "SDI_ENVIRONMENT_DESCRIPTION" in source
    assert '_mp_doc["environment"]' in source


def test_the_pdfplumber_failure_names_the_fix():
    """It read "pdfplumber is not installed." and arrived as a traceback, leaving the reader to
    work out that requirements.txt lists it and one pip command restores it."""
    source = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8", errors="ignore")
    assert "pip install pdfplumber" in source
    assert "core-required" in source


def test_the_pyodbc_failure_names_the_fix_and_the_driver():
    """The ODBC driver is a separate install from the Python package, and a machine with one and
    not the other fails identically."""
    source = (ROOT / "src" / "pricing_service.py").read_text(encoding="utf-8", errors="ignore")
    assert "pip install pyodbc" in source
    assert "ODBC Driver 18" in source
