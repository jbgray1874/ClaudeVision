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



def test_the_snapshot_names_whose_lookup_failed(dirs, monkeypatch):
    """The push needs WHO, not just how many, to tell unknown from absent."""
    monkeypatch.setattr(cfg, "HR_OUTPUT_DIR", "")
    monkeypatch.setattr(hr_blip, "_get_token", lambda: "t")
    monkeypatch.setattr(hr_blip, "_current_staff", lambda token: ([
        {"id": "BH-1", "first_name": "John", "surname": "Smith", "email": "j@wearesdi.com"},
        {"id": "BH-2", "first_name": "Pat", "surname": "Example", "email": "p@wearesdi.com"},
    ], None))

    def query(token, employee_id, from_dt, throttle=None):
        if employee_id == "BH-1":
            return [{"start": "2026-10-14T07:00:00Z"}], True
        return [], False                                   # BH-2's lookup fails

    monkeypatch.setattr(hr_blip, "_query_one", query)
    hr_blip.run_blip()

    snap = json.loads((dirs / "blip_latest.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in snap["on_site"]] == ["BH-1"]
    assert [p["id"] for p in snap["query_failed"]] == ["BH-2"]


# ── who gets asked about ──────────────────────────────────────────────────────
# A person clocked in on Blip but missing from the staff list is never asked
# about, so never appears on site. The list used to be a saved file that only a
# manual pull refreshed, and it dropped anyone without an email address.

def _brighthr(monkeypatch, raw=None, error=None):
    import hr_brighthr as bh
    def fetch(token):
        if error:
            raise bh.BrightHRError(error)
        return raw
    monkeypatch.setattr(bh, "fetch_employees", fetch)


def test_staff_without_an_email_are_still_asked_about(monkeypatch):
    _brighthr(monkeypatch, raw=[
        {"id": "BH-1", "firstName": "Jo", "lastName": "Office", "email": "jo@wearesdi.com"},
        {"id": "BH-2", "firstName": "Sam", "lastName": "Warehouse"},           # no email
        {"id": "BH-3", "firstName": "Lee", "lastName": "Leaver", "isTerminated": True},
    ])

    staff, warning = hr_blip._current_staff("t")

    assert [e["id"] for e in staff] == ["BH-1", "BH-2"]                        # not the leaver
    assert warning is None


def test_a_new_starter_is_asked_about_without_a_manual_pull(dirs, monkeypatch):
    # The saved list predates them; BrightHR's own list does not.
    (dirs / "latest.json").write_text(json.dumps({"records": [
        {"id": "BH-1", "first_name": "Jo", "surname": "Office", "email": "jo@wearesdi.com"}]}),
        encoding="utf-8")
    _brighthr(monkeypatch, raw=[
        {"id": "BH-1", "firstName": "Jo", "lastName": "Office", "email": "jo@wearesdi.com"},
        {"id": "BH-9", "firstName": "New", "lastName": "Starter", "email": "new@wearesdi.com"},
    ])

    staff, _ = hr_blip._current_staff("t")

    assert "BH-9" in [e["id"] for e in staff]


def test_if_brighthr_s_staff_list_fails_the_saved_list_is_used_and_said(dirs, monkeypatch):
    (dirs / "latest.json").write_text(json.dumps({"records": [
        {"id": "BH-1", "first_name": "Jo", "surname": "Office", "email": "jo@wearesdi.com"}]}),
        encoding="utf-8")
    _brighthr(monkeypatch, error="429 Too Many Requests")

    staff, warning = hr_blip._current_staff("t")

    assert [e["id"] for e in staff] == ["BH-1"]
    assert "saved list" in warning and "429" in warning


def test_the_fallback_warning_reaches_the_run_summary(dirs, monkeypatch):
    monkeypatch.setattr(cfg, "HR_OUTPUT_DIR", "")
    monkeypatch.setattr(hr_blip, "_get_token", lambda: "t")
    monkeypatch.setattr(hr_blip, "_current_staff", lambda token: (
        [{"id": "BH-1", "first_name": "Jo", "surname": "Office", "email": ""}],
        "BrightHR's staff list could not be read (x); checked the saved list of 1 instead"))
    monkeypatch.setattr(hr_blip, "_query_one", lambda *a, **k: ([], True))

    summary = hr_blip.run_blip()

    assert any("saved list" in w for w in summary["warnings"])
