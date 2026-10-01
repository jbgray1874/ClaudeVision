"""
Tests for the Blip output file write.

The failure that prompted these: the write to HR_OUTPUT_DIR is non-fatal, so
when the share was unreachable the run still reported OK and simply omitted the
file. Nothing in the portal said why the output directory had not updated.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_blip  # noqa: E402
import hr_config as cfg  # noqa: E402

SUMMARY = {"timestamp": "2026-09-21T08:00:00+00:00", "employees_checked": 192,
           "on_site": 1, "status": "ok"}
ON_SITE = [{"first_name": "John", "surname": "Smith", "email": "j@wearesdi.com",
            "clocking": {"start": "2026-09-21T07:45:00Z"}}]


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(snapshots))
    return snapshots


def test_writes_the_browsable_file_and_strips_email(dirs, tmp_path, monkeypatch):
    out = tmp_path / "HRSystemsOutput"
    monkeypatch.setattr(cfg, "HR_OUTPUT_DIR", str(out))

    path, error = hr_blip._write_output_file(ON_SITE, SUMMARY)

    assert error is None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["staff_on_site"][0]["first_name"] == "John"
    assert "email" not in payload["staff_on_site"][0]      # PII stripped


def test_unreachable_output_dir_reports_a_reason_instead_of_failing_silently(dirs, monkeypatch):
    # A drive letter that does not exist is what a service sees for K:.
    monkeypatch.setattr(cfg, "HR_OUTPUT_DIR", "K:\\IT\\HRSystemsOutput")
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("not found")))

    path, error = hr_blip._write_output_file(ON_SITE, SUMMARY)

    assert path is None
    assert error and "Could not write to HR_OUTPUT_DIR" in error


def test_mapped_drive_failure_names_the_cause_and_the_fix(dirs, monkeypatch):
    monkeypatch.setattr(cfg, "HR_OUTPUT_DIR", "K:\\IT\\HRSystemsOutput")
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("not found")))

    _, error = hr_blip._write_output_file(ON_SITE, SUMMARY)

    assert "mapped drive" in error
    assert "UNC path" in error


def test_a_local_copy_is_kept_when_the_share_is_unreachable(dirs, monkeypatch):
    monkeypatch.setattr(cfg, "HR_OUTPUT_DIR", "K:\\IT\\HRSystemsOutput")
    real_mkdir = Path.mkdir

    def only_fail_for_k(self, *a, **k):
        if str(self).startswith("K:"):
            raise OSError("not found")
        return real_mkdir(self, *a, **k)

    monkeypatch.setattr(Path, "mkdir", only_fail_for_k)

    _, error = hr_blip._write_output_file(ON_SITE, SUMMARY)

    fallbacks = list(dirs.glob("blip_onsite_*.json"))
    assert len(fallbacks) == 1
    assert "A local copy was written" in error
    assert json.loads(fallbacks[0].read_text(encoding="utf-8"))["on_site"] == 1


def test_unset_output_dir_is_reported_too(dirs, monkeypatch):
    monkeypatch.setattr(cfg, "HR_OUTPUT_DIR", "")

    path, error = hr_blip._write_output_file(ON_SITE, SUMMARY)

    assert path is None
    assert "not set" in error


@pytest.mark.parametrize("path,expected", [
    ("K:\\IT\\HRSystemsOutput", True),
    ("C:\\SDIIntelligence", True),
    ("\\\\sdi-dc01\\shareddata$\\Shared\\IT", False),
    ("/mnt/share", False),
])
def test_mapped_drive_detection(path, expected):
    assert hr_blip._looks_like_mapped_drive(path) is expected
