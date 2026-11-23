r"""A row whose archive path passes Windows' 260-character limit is still filed, not a crash.

Row 29's second attempt (23 Nov 2026): the unpriced covering e-mail's path on K came to 264
characters, the atomic write's temporary name pushed it further, Windows answered
FileNotFoundError, and the whole queue stopped. Long paths are now written and read in
Windows' extended-length form (\\?\UNC\...); short paths and every path off Windows are
untouched.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import tti_concept_batch as b  # noqa: E402

LONG = "x" * 260


def test_a_long_unc_or_drive_path_takes_the_extended_form_and_short_ones_do_not():
    unc = "\\\\sdi-dc01\\shareddata$\\" + LONG
    assert b.winsafe(unc, windows=True) == "\\\\?\\UNC\\sdi-dc01\\shareddata$\\" + LONG
    drive = "C:\\" + LONG
    assert b.winsafe(drive, windows=True) == "\\\\?\\C:\\" + LONG
    assert b.winsafe("C:\\k\\v.json", windows=True) == "C:\\k\\v.json"
    already = "\\\\?\\UNC\\s\\" + LONG
    assert b.winsafe(already, windows=True) == already
    assert b.winsafe(unc, windows=False) == unc


def test_atomic_goes_through_the_safe_form_for_the_folder_and_the_target(tmp_path, monkeypatch):
    crossed = []
    def spy(p, windows=None):
        crossed.append(str(p))
        return str(p)
    monkeypatch.setattr(b, "winsafe", spy)
    b.atomic(tmp_path / "deep" / "f.json", b"x")
    assert (tmp_path / "deep" / "f.json").read_bytes() == b"x"
    assert str(tmp_path / "deep") in crossed          # the folder it makes and writes in
    assert str(tmp_path / "deep" / "f.json") in crossed   # the target it renames onto


def test_the_archive_reads_its_verification_through_the_safe_form(tmp_path, monkeypatch):
    crossed = []
    real = b.winsafe
    def spy(p, windows=None):
        crossed.append(str(p))
        return real(p, windows)
    monkeypatch.setattr(b, "winsafe", spy)
    arc = b.Archive(tmp_path / "c", tmp_path / "k")
    name = "TTI-C-" + "8484cc0233aa3f2f2cff-R2/unpriced/4a1540d19e54/" + "e" * 80 + ".html"
    arc.put(name, b"the covering e-mail")
    for root in ("c", "k"):
        assert (tmp_path / root / name).read_bytes() == b"the covering e-mail"
        assert str(tmp_path / root / name) in crossed
