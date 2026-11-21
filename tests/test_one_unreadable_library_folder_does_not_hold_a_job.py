"""ONE UNREADABLE LIBRARY FOLDER DOES NOT HOLD A JOB (21 Nov 2026).

Row 139 (12132-01-GA) was held overnight: the live library search hit a service's temporary
folder deep in the Design area (".ArchiveServiceTemp...") that raised PermissionError, and the
whole search stopped as "library area could not be read". A folder below the area's root is now
skipped and recorded on the evidence, so a drawing missed there is not taken as proof it does not
exist. An unreadable area root still stops the check. Invented folders.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_resolver as pr  # noqa: E402
from live_library_lookup import LiveLibraryLookup  # noqa: E402


def _put(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("drawing")
    return path


def _deny(monkeypatch, bad):
    real = os.scandir

    def scandir(p):
        if Path(p) == bad:
            raise PermissionError(13, "Access is denied", str(p))
        return real(p)
    monkeypatch.setattr(os, "scandir", scandir)


def test_an_unreadable_sub_folder_is_skipped_and_said(tmp_path, monkeypatch):
    design = tmp_path / "Design"
    want = _put(design / "Shared library" / "Holders" / "5100-GA.pdf")
    bad = design / "Workshop" / ".ServiceTemp-x"
    bad.mkdir(parents=True)
    _deny(monkeypatch, bad)
    lookup = LiveLibraryLookup([("Design", design)])
    assert [f[0] for f in lookup("5100-GA")] == [want]
    said = lookup.evidence[-1]["unreadable_folders"]
    assert said and ".ServiceTemp-x" in said[0] and "PermissionError" in said[0]


def test_an_unreadable_area_root_still_stops_the_check(tmp_path, monkeypatch):
    design = tmp_path / "Design"
    design.mkdir()
    _deny(monkeypatch, design)
    with pytest.raises(pr.PackCheckStalled):
        LiveLibraryLookup([("Design", design)])("5100-GA")
