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

Every roll call is kept, from its first tick: present is ticked, absent is
everyone else who was on the list while it was being ticked. The app keeps
its own copy, and a spreadsheet of each goes in HR's folder.
"""
import datetime
import json
import os
import re
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

    managers = (snapshot or {}).get("managers") or {}
    for p in inventry_on_site or []:
        e = slot(p["name"], "inventry")
        e["inventry"] = {"since": p.get("since", ""), "by": p.get("by", "")}
        e.setdefault("manager", managers.get(" ".join(p["name"].lower().split()), ""))

    forgotten = 0
    for r in (snapshot or {}).get("on_site") or []:
        name = f"{r.get('first_name', '')} {r.get('surname', '')}".strip() or "?"
        start = (r.get("clocking") or {}).get("start", "")
        t = _parse(start)
        if limit and t is not None and (now - t).total_seconds() / 3600 > limit:
            forgotten += 1
            continue
        e = slot(name, "brighthr")
        e["brighthr"] = {"since": start}
        if r.get("manager"):
            e["manager"] = r["manager"]
        e.setdefault("manager", "")

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


def tick(key: str, ticked: bool, by: str, people=None) -> dict:
    """people: the list on screen at this tick, kept with the roll call so the
    ones nobody ticked are recorded as absent."""
    with _lock:
        s = state()
        if ticked:
            s["ticks"][key] = {"by": by, "at": _now().isoformat()}
        else:
            s["ticks"].pop(key, None)
        if not s.get("started"):
            s["started"], s["started_by"] = _now().isoformat(), by
        _save(s)
        rid = _remember(s, people)
    _schedule_export(rid)
    return s


def start_new(by: str) -> dict:
    with _lock:
        s = {"started": _now().isoformat(), "started_by": by, "ticks": {}}
        _save(s)
        return s


# ── each roll call, kept ────────────────────────────────────────────────────
# A roll call runs from "Start a new roll call" (or its first tick) to the
# next one. It is saved at every tick, so nobody has to remember to save it in
# an evacuation. The list is taken at the ticks and never afterwards: a drill
# left open is not rewritten by whoever is in the building next week.

RUN_ID = re.compile(r"^\d{8}-\d{6}$")
EXPORT_DELAY_SECONDS = 5
_export_lock = threading.Lock()
_export_due = {}


def run_id(started):
    t = _parse(started) if started else None
    return t.astimezone(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S") if t else None


def _runs_dir() -> Path:
    return Path(cfg.HR_SNAPSHOT_DIR) / "rollcalls"


def _load_run(rid):
    if not rid or not RUN_ID.match(str(rid)):
        return None
    try:
        rec = json.loads((_runs_dir() / f"{rid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def _save_run(rec: dict) -> None:
    p = _runs_dir() / f"{rec['id']}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _remember(s: dict, people) -> str:
    """Keep this roll call as it stands. Called inside _lock."""
    rid = run_id(s["started"])
    rec = _load_run(rid) or {"id": rid, "started": s["started"],
                             "started_by": s.get("started_by"), "people": {}}
    for p in people or []:
        rec["people"].setdefault(p["key"], {k: p[k] for k in ("name", "manager", "inventry", "brighthr")
                                            if p.get(k)})
    rec["ticks"] = s["ticks"]
    rec["updated"] = _now().isoformat()
    _save_run(rec)
    return rid


def _name_from_key(key: str) -> str:
    return key.rsplit("#", 1)[0].title()


def summarise(rec: dict) -> dict:
    """Present (ticked) and absent (everyone else on the list), by name."""
    people = dict(rec.get("people") or {})
    ticks = rec.get("ticks") or {}
    present, absent = [], []
    for key in set(people) | set(ticks):
        p = people.get(key) or {}
        row = {"name": p.get("name") or _name_from_key(key), "manager": p.get("manager", ""),
               "inventry": p.get("inventry"), "brighthr": p.get("brighthr")}
        t = ticks.get(key)
        if t:
            present.append(dict(row, ticked_by=t.get("by", ""), ticked_at=t.get("at", "")))
        else:
            absent.append(row)
    present.sort(key=lambda r: r["name"].lower())
    absent.sort(key=lambda r: r["name"].lower())
    return {"id": rec.get("id"), "started": rec.get("started"), "started_by": rec.get("started_by"),
            "updated": rec.get("updated"), "present": present, "absent": absent,
            "present_count": len(present), "absent_count": len(absent),
            "count": len(present) + len(absent), "spreadsheet": rec.get("spreadsheet"),
            "spreadsheet_saved": rec.get("spreadsheet_saved"),
            "spreadsheet_problem": rec.get("spreadsheet_problem")}


def runs(limit: int = 60) -> list:
    """The saved roll calls, newest first, without their names."""
    out = []
    for p in sorted(_runs_dir().glob("*.json"), reverse=True)[:limit]:
        rec = _load_run(p.stem)
        if rec:
            sm = summarise(rec)
            out.append({k: v for k, v in sm.items() if k not in ("present", "absent")})
    return out


def saved(rid):
    rec = _load_run(rid)
    return summarise(rec) if rec else None


# ── the spreadsheet in HR's folder ──────────────────────────────────────────
# Written a few seconds after the ticks, in the background: a network share
# that stalls must never stall a tick in an evacuation. What happened is kept
# with the roll call, so the screen can say if the folder could not be reached.

def folder() -> str:
    """The folder as people know it (K:\\...)."""
    return cfg.HR_ROLLCALL_DIR or os.path.join(cfg.HR_OUTPUT_DIR, "Roll calls")


def _server_path(path: str) -> str:
    """A mapped letter as the share it stands for: a service has no K:."""
    import config
    p = str(path).strip()
    unc = (getattr(config, "DRIVE_MAP", {}) or {}).get(p[0].upper()) \
        if len(p) >= 2 and p[1] == ":" else None
    if not unc:
        return p
    rest = p[2:].lstrip("\\/")
    return unc + ("\\" + rest if rest else "")


def _local(iso) -> str:
    t = _parse(iso) if iso else None
    return t.astimezone().strftime("%d/%m/%Y %H:%M") if t else ""


def _schedule_export(rid) -> None:
    with _export_lock:
        if rid in _export_due:
            return
        t = threading.Timer(EXPORT_DELAY_SECONDS, export, (rid,))
        t.daemon = True
        _export_due[rid] = t
    t.start()


def _write_sheet(sm: dict, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Roll call"
    ws.append(["Fire roll call"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Started", _local(sm["started"]), f"by {sm['started_by']}" if sm["started_by"] else ""])
    ws.append(["Last tick", _local(sm["updated"])])
    ws.append(["Present", sm["present_count"], f"of {sm['count']}"])
    ws.append(["Absent", sm["absent_count"]])
    ws.append(["Present: ticked as accounted for. Absent: on the roll call and not ticked."])
    ws.append([])
    ws.append(["Status", "Name", "Manager", "Ticked by", "Ticked at", "On InVentry since",
               "Clocked in on BrightHR"])
    head = ws.max_row
    for cell in ws[head]:
        cell.font = Font(bold=True)
    colour = {"Absent": PatternFill("solid", fgColor="F8CBAD"),
              "Present": PatternFill("solid", fgColor="C6EFCE")}
    # Absent first: on a fire roll call they are the names that matter.
    for status, rows in (("Absent", sm["absent"]), ("Present", sm["present"])):
        for r in rows:
            ws.append([status, r["name"], r.get("manager", ""), r.get("ticked_by", ""),
                       _local(r.get("ticked_at")), _local((r.get("inventry") or {}).get("since")),
                       _local((r.get("brighthr") or {}).get("since"))])
            ws.cell(ws.max_row, 1).fill = colour[status]
    ws.freeze_panes = ws.cell(head + 1, 1)
    ws.auto_filter.ref = f"A{head}:G{max(ws.max_row, head)}"
    for col, width in zip("ABCDEFG", (10, 28, 24, 22, 17, 18, 22)):
        ws.column_dimensions[col].width = width
    tmp = path.with_suffix(".tmp")
    wb.save(tmp)
    os.replace(tmp, path)


def export(rid) -> dict:
    """Write, or rewrite, this roll call's spreadsheet in HR's folder."""
    with _export_lock:
        _export_due.pop(rid, None)
    rec = _load_run(rid)
    if not rec:
        return {}
    shown = folder()
    name, problem = rec.get("spreadsheet_name"), None
    try:
        target = Path(_server_path(shown))
        target.mkdir(parents=True, exist_ok=True)
        if not name:
            t = _parse(rec["started"]).astimezone()
            name = f"Roll call {t:%Y-%m-%d %H-%M}.xlsx"
            if (target / name).exists():                # another roll call in the same minute
                name = f"Roll call {t:%Y-%m-%d %H-%M-%S}.xlsx"
        _write_sheet(summarise(rec), target / name)
    except PermissionError as exc:
        problem = (f"The spreadsheet could not be saved in {shown}: {exc}. It may be open in "
                   f"Excel, or the server may not be allowed to write there. The roll call itself "
                   f"is saved in the app.")
    except Exception as exc:                            # noqa: BLE001 - said on screen, never lost
        problem = (f"The spreadsheet could not be saved in {shown}: {exc}. The roll call itself "
                   f"is saved in the app.")
    if problem:
        try:
            import hr_blip
            hr_blip._log(f"ROLL CALL {rid}: {problem}")
        except Exception:                               # noqa: BLE001
            pass
    with _lock:
        rec = _load_run(rid) or rec
        if name:
            rec["spreadsheet_name"] = name
        if problem:
            rec["spreadsheet_problem"] = problem
        else:
            rec.pop("spreadsheet_problem", None)
            rec["spreadsheet"] = os.path.join(shown, name)
            rec["spreadsheet_saved"] = _now().isoformat()
        _save_run(rec)
    return rec
