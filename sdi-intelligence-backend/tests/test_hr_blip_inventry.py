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
    """Point the loader at a temp snapshot dir and watched folder."""
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    watched = tmp_path / "InVentryImports" / "brighthr_onsite.csv"
    monkeypatch.setattr(cfg, "HR_SNAPSHOT_DIR", str(snapshots))
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

    return type("Env", (), {
        "snapshots": snapshots,
        "watched": watched,
        "write_snapshot": staticmethod(write_snapshot),
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


def test_records_missing_name_or_email_are_skipped(env):
    """InVentry matches on name + email, so a partial row cannot be linked."""
    env.write_snapshot([_person(), _person("Dave", "Wilson", email="")])

    summary = loader.run_blip_load()

    assert summary["written"] == 1
    assert summary["skipped"] == 1
    assert any("skipped" in w for w in summary["warnings"])


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


# -------------------------------------------------------------------- status


def test_status_file_records_the_load_for_the_portal_panel(env):
    env.write_snapshot([_person()])

    loader.run_blip_load()

    status = json.loads((env.snapshots / "hr_status.json").read_text(encoding="utf-8"))
    assert status["blip_load"]["written"] == 1
    assert status["blip_load"]["status"] == "ok"
