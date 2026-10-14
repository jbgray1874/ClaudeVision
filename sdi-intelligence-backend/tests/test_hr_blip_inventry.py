"""
Tests for the Blip -> InVentry presence load (hr_blip_inventry.py).

Focused on the guards: this file decides what InVentry shows as the fire
evacuation list, so the failure that matters is publishing an under-reported
on-site list. No network, no InVentry, no credentials.

    python -m pytest tests -q
"""
import csv
import datetime
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_blip_inventry as loader  # noqa: E402
import hr_config as cfg  # noqa: E402


def _iso(minutes_ago=0):
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)
    return when.isoformat()


def _person(first="John", surname="Smith", email="john.smith@wearesdi.com", start="2026-05-29T07:45:00Z"):
    return {
        "id": "EMP001",
        "first_name": first,
        "surname": surname,
        "email": email,
        "clocking": {"start": start},
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Point the loader at a temp snapshot dir, output folder and watched folder."""
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    output = tmp_path / "HRSystemsOutput"
    output.mkdir()
    watched = tmp_path / "InVentryImports" / "brighthr_onsite.csv"
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(snapshots))
    monkeypatch.setattr(cfg, "HR_OUTPUT_DIR", str(output))
    monkeypatch.setattr(cfg, "INVENTRY_ONSITE_CSV_PATH", str(watched))
    monkeypatch.setattr(cfg, "BLIP_MAX_STALE_MINUTES", 15)

    def write_snapshot(on_site, status="ok", age_minutes=1, query_failures=0):
        payload = {
            "summary": {
                "timestamp": _iso(age_minutes),
                "employees_checked": 192,
                "on_site": len(on_site),
                "query_failures": query_failures,
                "status": status,
            },
            "on_site": on_site,
        }
        (snapshots / "blip_latest.json").write_text(json.dumps(payload), encoding="utf-8")

    def write_output_file(people, status="ok", age_minutes=1, stamp="20260814T090000Z"):
        """The portal-exposed on-site file: email stripped, names only."""
        payload = {
            "generated": _iso(age_minutes),
            "query_type": "point_in_time",
            "employees_checked": 192,
            "on_site": len(people),
            "status": status,
            "staff_on_site": [
                {"first_name": p["first_name"], "surname": p["surname"],
                 "clocked_in": p.get("clocking", {}).get("start", "")}
                for p in people
            ],
        }
        (output / f"blip_onsite_{stamp}.json").write_text(json.dumps(payload), encoding="utf-8")

    def write_roster(people):
        """The roster snapshot hr_pull.py writes — this one has emails."""
        payload = {"timestamp": _iso(60), "active": len(people), "records": people}
        (snapshots / "latest.json").write_text(json.dumps(payload), encoding="utf-8")

    return type("Env", (), {
        "snapshots": snapshots,
        "output": output,
        "watched": watched,
        "write_snapshot": staticmethod(write_snapshot),
        "write_output_file": staticmethod(write_output_file),
        "write_roster": staticmethod(write_roster),
    })


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- happy path


def test_writes_on_site_list_to_watched_folder(env):
    env.write_snapshot([_person(), _person("Aisha", "Khan", "aisha.khan@wearesdi.com")])

    summary = loader.run_blip_load()

    assert summary["status"] == "ok"
    assert summary["written"] == 2
    rows = read_csv(env.watched)
    assert rows[0]["First Name"] == "John"
    assert rows[0]["Surname"] == "Smith"
    assert rows[0]["Email Address"] == "john.smith@wearesdi.com"
    assert rows[0]["Signed In"] == "2026-05-29T07:45:00Z"


def test_no_temp_file_left_behind(env):
    """InVentry sweeps this folder — a stray .tmp would be picked up."""
    env.write_snapshot([_person()])

    loader.run_blip_load()

    assert env.watched.exists()
    assert not list(env.watched.parent.glob("*.tmp"))


def test_record_with_no_name_is_skipped(env):
    """With no name there is nothing for InVentry to match on at all."""
    env.write_snapshot([_person(), _person(first="", surname="")])

    summary = loader.run_blip_load()

    assert summary["written"] == 1
    assert summary["skipped"] == 1
    assert any("skipped" in w for w in summary["warnings"])


def test_record_missing_email_is_still_written_name_only(env):
    """Leaving someone off the fire roll is worse than a row without an email."""
    env.write_snapshot([_person(), _person("Dave", "Wilson", email="")])

    summary = loader.run_blip_load()

    assert summary["written"] == 2
    assert summary["name_only"] == 1
    assert any("name alone" in w for w in summary["warnings"])
    assert read_csv(env.watched)[1]["Email Address"] == ""


# -------------------------------------------------------------------- guards


def test_degraded_snapshot_is_refused(env):
    """Failed Blip queries mean people on site may be missing from the list."""
    env.write_snapshot([_person()], status="degraded", query_failures=17)

    summary = loader.run_blip_load()

    assert summary["status"] == "aborted"
    assert not env.watched.exists()
    assert "incomplete" in summary["warnings"][0]


def test_stale_snapshot_is_refused(env):
    env.write_snapshot([_person()], age_minutes=45)

    summary = loader.run_blip_load()

    assert summary["status"] == "aborted"
    assert "stale" in summary["warnings"][0]
    assert not env.watched.exists()


def test_zero_on_site_with_query_failures_is_refused(env):
    """A broken token looks exactly like an empty building."""
    env.write_snapshot([], query_failures=192)

    summary = loader.run_blip_load()

    assert summary["status"] == "aborted"
    assert not env.watched.exists()


def test_zero_on_site_from_a_clean_run_is_published(env):
    """An empty building at 3am is real — publish it, with a header row."""
    env.write_snapshot([], query_failures=0)

    summary = loader.run_blip_load()

    assert summary["status"] == "ok"
    assert summary["written"] == 0
    assert read_csv(env.watched) == []
    assert env.watched.read_text(encoding="utf-8").startswith("First Name,Surname")


def test_force_overrides_the_guards(env):
    env.write_snapshot([_person()], status="degraded", age_minutes=90, query_failures=17)

    summary = loader.run_blip_load(force=True)

    assert summary["status"] == "ok"
    assert summary["written"] == 1


def test_missing_snapshot_raises_rather_than_writing_an_empty_file(env):
    with pytest.raises(RuntimeError, match="No Blip snapshot"):
        loader.run_blip_load()
    assert not env.watched.exists()


# ------------------------------------------------------------------- dry run


def test_dry_run_never_touches_the_watched_folder(env):
    env.write_snapshot([_person()])

    summary = loader.run_blip_load(dry_run=True)

    assert summary["dry_run"] is True
    assert not env.watched.exists()
    written = list(env.snapshots.glob("dryrun_onsite_*.csv"))
    assert len(written) == 1
    assert read_csv(written[0])[0]["First Name"] == "John"


# ------------------------------------------- the portal's on-site JSON source


def test_loads_the_portal_exposed_on_site_file(env):
    """The 'site signed in' JSON the Files view shows — staff_on_site shape."""
    env.write_output_file([_person(), _person("Aisha", "Khan")])

    summary = loader.run_blip_load(source="output")

    assert summary["status"] == "ok"
    assert summary["written"] == 2
    assert summary["source"].endswith("blip_onsite_20260814T090000Z.json")
    assert read_csv(env.watched)[0]["First Name"] == "John"


def test_newest_output_file_wins(env):
    env.write_output_file([_person()], stamp="20260814T080000Z")
    env.write_output_file([_person(), _person("Aisha", "Khan")], stamp="20260814T093000Z")

    summary = loader.run_blip_load(source="output")

    assert summary["source"].endswith("20260814T093000Z.json")
    assert summary["written"] == 2


def test_emails_stripped_from_the_output_file_are_recovered_from_the_roster(env):
    env.write_output_file([_person(), _person("Aisha", "Khan")])
    env.write_roster([
        {"first_name": "John", "surname": "Smith", "email": "john.smith@wearesdi.com"},
        {"first_name": "Aisha", "surname": "Khan", "email": "aisha.khan@wearesdi.com"},
    ])

    summary = loader.run_blip_load(source="output")

    assert summary["emails_recovered"] == 2
    assert summary["name_only"] == 0
    rows = read_csv(env.watched)
    assert rows[0]["Email Address"] == "john.smith@wearesdi.com"
    assert rows[1]["Email Address"] == "aisha.khan@wearesdi.com"


def test_duplicate_names_are_not_matched_to_an_email(env):
    """Two John Smiths: a wrong email on a fire roll is worse than a blank."""
    env.write_output_file([_person()])
    env.write_roster([
        {"first_name": "John", "surname": "Smith", "email": "john.smith@wearesdi.com"},
        {"first_name": "John", "surname": "Smith", "email": "j.smith2@wearesdi.com"},
    ])

    summary = loader.run_blip_load(source="output")

    assert summary["emails_recovered"] == 0
    assert summary["name_only"] == 1
    assert read_csv(env.watched)[0]["Email Address"] == ""


def test_output_file_without_a_roster_still_publishes_names(env):
    env.write_output_file([_person()])

    summary = loader.run_blip_load(source="output")

    assert summary["status"] == "ok"
    assert summary["written"] == 1
    assert summary["name_only"] == 1


def test_degraded_output_file_is_refused_too(env):
    env.write_output_file([_person()], status="degraded")

    summary = loader.run_blip_load(source="output")

    assert summary["status"] == "aborted"
    assert not env.watched.exists()


def test_explicit_path_source(env, tmp_path):
    env.write_output_file([_person()], stamp="20260814T070000Z")
    path = env.output / "blip_onsite_20260814T070000Z.json"

    summary = loader.run_blip_load(source=str(path))

    assert summary["written"] == 1


def test_missing_output_file_is_a_clear_error(env):
    with pytest.raises(RuntimeError, match="Who's clocked in"):
        loader.run_blip_load(source="output")


def test_unrecognised_json_shape_is_rejected(env):
    (env.output / "blip_onsite_20260814T060000Z.json").write_text(
        json.dumps({"something": "else"}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Unrecognised on-site JSON"):
        loader.run_blip_load(source="output")


# -------------------------------------------------------------------- status


def test_status_file_records_the_load_for_the_portal_panel(env):
    env.write_snapshot([_person()])

    loader.run_blip_load()

    status = json.loads((env.snapshots / "hr_status.json").read_text(encoding="utf-8"))
    assert status["blip_load"]["written"] == 1
    assert status["blip_load"]["status"] == "ok"
