"""
The fire roll call: everyone who should be in the building, with shared ticks.

Two sources, because either alone misses people: InVentry's on-site list
(including anyone signed in at reception) and BrightHR's clocked-in list from
the latest check (including anyone InVentry cannot match, and everyone when
InVentry is not answering). Clockings open past BLIP_MAX_CLOCKIN_AGE_HOURS are
forgotten clock-outs, not people in the building, and are left out.

Ticks live in one file on the server, so every marshal's phone sees every
other marshal's ticks, with who ticked and when. "Start a new roll call"
clears them. Nothing here writes to InVentry or BrightHR.
"""
import datetime
import json
import os
import threading
from pathlib import Path

import hr_config as cfg

_lock = threading.Lock()


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(ts):
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def build(inventry_on_site, snapshot, now=None, max_age_hours=None):
    """The roll call entries, one per person, merged by name.

    inventry_on_site: [{"name", "since", "by"}] or None when InVentry is down.
    snapshot: the latest BrightHR check (blip_latest.json) or None.

    Two people with the same name stay two entries: the n-th of a name in one
    source pairs with the n-th in the other, so a namesake is never merged away.
    """
    now = now or _now()
    limit = cfg.BLIP_MAX_CLOCKIN_AGE_HOURS if max_age_hours is None else max_age_hours
    entries = {}

    def slot(name, source):
        base = " ".join(name.lower().split()) or "?"
        i = 0
        while (key := f"{base}#{i}") in entries and source in entries[key]:
            i += 1
        e = entries.setdefault(key, {"key": key, "name": name})
        return e

    for p in inventry_on_site or []:
        slot(p["name"], "inventry")["inventry"] = {"since": p.get("since", ""), "by": p.get("by", "")}

    forgotten = 0
    for r in (snapshot or {}).get("on_site") or []:
        name = f"{r.get('first_name', '')} {r.get('surname', '')}".strip() or "?"
        start = (r.get("clocking") or {}).get("start", "")
        t = _parse(start)
        if limit and t is not None and (now - t).total_seconds() / 3600 > limit:
            forgotten += 1
            continue
        slot(name, "brighthr")["brighthr"] = {"since": start}

    people = sorted(entries.values(), key=lambda e: (e["name"].lower(), e["key"]))
    return people, forgotten


# ── shared ticks ────────────────────────────────────────────────────────────

def _path() -> Path:
    return Path(cfg.HR_SNAPSHOT_DIR) / "rollcall.json"


def state() -> dict:
    try:
        s = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(s.get("ticks"), dict):
            return s
    except (OSError, ValueError):
        pass
    return {"started": None, "started_by": None, "ticks": {}}


def _save(s: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def tick(key: str, ticked: bool, by: str) -> dict:
    with _lock:
        s = state()
        if ticked:
            s["ticks"][key] = {"by": by, "at": _now().isoformat()}
        else:
            s["ticks"].pop(key, None)
        if not s.get("started"):
            s["started"], s["started_by"] = _now().isoformat(), by
        _save(s)
        return s


def start_new(by: str) -> dict:
    with _lock:
        s = {"started": _now().isoformat(), "started_by": by, "ticks": {}}
        _save(s)
        return s
