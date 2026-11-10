#!/usr/bin/env python3
"""New drawing packs on the design share, flagged as candidate jobs (JG, 9 Nov 2026).

An hourly sweep of the design share's client folders (SDI_DESIGN_SWEEP_ROOT, default \\\\sdi-dc01\\CAD\\Design\\Customers April 08 Onwards, which is W:) that
finds drawing-pack folders and lists the NEW ones on the control panel as candidate jobs to
discuss with design. It runs on the estimating machine, which holds the share rights, and
reports to the service the way the self-running watcher does; the service only shows it.

    python src/design_sweep.py --once            one sweep, report, stop
    python src/design_sweep.py                   sweep every SDI_DESIGN_SWEEP_MINUTES (60)
    python src/design_sweep.py --once --dry-run  sweep and print; ledger and service untouched

WHAT A CLIENT FOLDER IS. A folder directly under the root whose name carries no run of four or
more digits (a folder named with a drawing number is a pack, never a customer; the Live Enquiry
rule), and is not a system or archive folder.

WHAT A PACK IS. Under a client folder, down to SDI_DESIGN_SWEEP_DEPTH levels (3): a folder whose
name opens with a job number (three or more digits), or that holds drawing or model files
directly (.pdf .dxf .dwg .sldprt .sldasm .slddrw .step .stp). The sweep does not go inside a
pack. Archive, old, superseded and backup folders are skipped.

WHAT IS NEW. The ledger (SDI_DESIGN_SWEEP_LEDGER) keeps every pack seen, with a fingerprint of
its files (names, sizes, modified times). The FIRST sweep records what is already there as the
baseline and flags nothing, so the panel is not flooded with every old job; after that a pack
not seen before is "new" and one whose files changed is "changed". A candidate stays listed for
SDI_DESIGN_SWEEP_KEEP_DAYS (14) or until someone dismisses it on the panel. A pack whose job
number already has an AI estimate filed under SDI_ESTIMATE_OUTPUT_ROOT is marked so.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

SCHEMA = "design_sweep.v1"
DRAWING_EXT = {".pdf", ".dxf", ".dwg", ".sldprt", ".sldasm", ".slddrw", ".step", ".stp"}
SKIP_WORDS = re.compile(r"\b(archive|archived|old|superseded|backup|back up|obsolete|recycle)\b|^[._~$]",
                        re.IGNORECASE)
JOB_LEAD = re.compile(r"^\s*(\d{3,})")


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# The client folders (Boots, TTI and the rest) sit directly under this one (JG, 9 Nov 2026).
DEFAULT_ROOT = r"\\sdi-dc01\CAD\Design\Customers April 08 Onwards"  # W:

def _to_unc(path: str, env: Dict[str, str]) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from drive_map import to_unc
    return to_unc(path, env)


def settings(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    e = env if env is not None else os.environ
    here = Path(__file__).resolve().parents[1]
    return {
        "root": Path(_to_unc(e.get("SDI_DESIGN_SWEEP_ROOT") or DEFAULT_ROOT, e)),
        "depth": max(1, int(e.get("SDI_DESIGN_SWEEP_DEPTH") or 3)),
        "minutes": max(5, int(e.get("SDI_DESIGN_SWEEP_MINUTES") or 60)),
        "keep_days": max(1, int(e.get("SDI_DESIGN_SWEEP_KEEP_DAYS") or 14)),
        "ledger": Path(e.get("SDI_DESIGN_SWEEP_LEDGER") or (here / "output" / "design_sweep" / "ledger.json")),
        "estimates": Path(e.get("SDI_ESTIMATE_OUTPUT_ROOT") or ""),
        "show_changed": str(e.get("SDI_DESIGN_SWEEP_SHOW_CHANGED") or "").strip().lower()
                        in ("1", "true", "yes", "on"),
    }


def is_client_folder(name: str) -> bool:
    return bool(name) and not re.search(r"\d{4,}", name) and not SKIP_WORDS.search(name)


def job_of(name: str) -> str:
    """The job number a folder name opens with; a year folder ("2026") is not one."""
    if re.fullmatch(r"\s*(19|20)\d{2}\s*", name or ""):
        return ""
    m = JOB_LEAD.match(name or "")
    return m.group(1) if m else ""


def _drawing_files(folder: Path) -> List[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in DRAWING_EXT)
    except OSError:
        return []


def fingerprint(folder: Path, limit: int = 500) -> Dict[str, Any]:
    """Names, sizes and modified times of the pack's files (its own and one level down)."""
    rows: List[str] = []
    newest = 0.0
    try:
        for p in sorted(folder.rglob("*")):
            if len(rows) >= limit:
                break
            if not p.is_file() or p.suffix.lower() not in DRAWING_EXT:
                continue
            if len(p.relative_to(folder).parts) > 2:
                continue
            st = p.stat()
            newest = max(newest, st.st_mtime)
            rows.append(f"{p.relative_to(folder).as_posix()}:{st.st_size}:{int(st.st_mtime)}")
    except OSError:
        pass
    return {"sha1": hashlib.sha1("\n".join(rows).encode("utf-8")).hexdigest(), "files": len(rows),
            "newest": newest}


LISTING_LIMIT = 300


def listing(folder: Path, limit: int = LISTING_LIMIT, depth: int = 4) -> Dict[str, Any]:
    """Every file in a candidate pack, for Grid Control's file view (JG, 10 Nov 2026: "some sort
    of a file explorer view of the files in the new design folders"). Read here because the
    sweep has the user's rights on the share and the service has none. Relative path, size,
    modified time and whether it is a drawing file; at most `limit`, the rest counted."""
    out: List[Dict[str, Any]] = []
    more = 0
    try:
        for p in sorted(folder.rglob("*")):
            try:
                rel = p.relative_to(folder)
                if len(rel.parts) > depth or any(SKIP_WORDS.search(x) for x in rel.parts[:-1]):
                    continue
                if not p.is_file():
                    continue
                if len(out) >= limit:
                    more += 1
                    continue
                st = p.stat()
                out.append({"path": rel.as_posix(), "size": st.st_size, "modified": _iso(st.st_mtime),
                            "drawing": p.suffix.lower() in DRAWING_EXT})
            except OSError:
                continue
    except OSError:
        pass
    return {"files": out, "more": more}


def find_packs(root: Path, depth: int = 3) -> Iterable[Dict[str, Any]]:
    """Every pack folder under every client folder."""
    try:
        clients = sorted(p for p in root.iterdir() if p.is_dir() and is_client_folder(p.name))
    except OSError as exc:
        raise RuntimeError(f"the design share {root} could not be read: {exc}") from None
    for client in clients:
        stack = [(client, 0)]
        while stack:
            folder, level = stack.pop()
            try:
                subs = sorted((p for p in folder.iterdir() if p.is_dir() and not SKIP_WORDS.search(p.name)),
                              reverse=True)
            except OSError:
                continue
            for sub in subs:
                if job_of(sub.name) or _drawing_files(sub):
                    yield {"client": client.name, "folder": str(sub), "name": sub.name, "job": job_of(sub.name)}
                elif level + 1 < depth:
                    stack.append((sub, level + 1))


def estimated_jobs(root: Path) -> Set[str]:
    """Job numbers that already have an AI estimate filed (<root>\\<client>\\<drawing>)."""
    out: Set[str] = set()
    if not str(root) or not root.is_dir():
        return out
    try:
        for c in root.iterdir():
            if c.is_dir():
                for d in c.iterdir():
                    j = job_of(d.name)
                    if d.is_dir() and j:
                        out.add(j)
    except OSError:
        pass
    return out


def load_ledger(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("schema") == SCHEMA:
            return data
    except (OSError, ValueError):
        pass
    return {"schema": SCHEMA, "packs": {}, "sweeps": 0, "baseline_at": None}


def sweep(cfg: Dict[str, Any], ledger: Dict[str, Any], now: Optional[float] = None,
          walker=find_packs, fingerprinter=fingerprint, estimated: Optional[Set[str]] = None) -> Dict[str, Any]:
    """One sweep: update the ledger in place and return the report for the panel."""
    now = now if now is not None else _now()
    first = not ledger.get("packs") and not ledger.get("baseline_at")
    packs: Dict[str, Any] = ledger.setdefault("packs", {})
    est = estimated if estimated is not None else estimated_jobs(cfg["estimates"])
    errors: List[str] = []
    seen: Set[str] = set()
    clients: Set[str] = set()
    try:
        found = list(walker(cfg["root"], cfg["depth"]))
    except RuntimeError as exc:
        found, errors = [], [str(exc)]
    for f in found:
        key = os.path.normcase(f["folder"])
        seen.add(key)
        clients.add(f["client"])
        fp = fingerprinter(Path(f["folder"]))
        old = packs.get(key)
        if old is None:
            packs[key] = dict(f, first_seen=now, last_seen=now, fingerprint=fp["sha1"], files=fp["files"],
                              newest=fp["newest"], status="baseline" if first else "new", flagged_at=None if first else now)
        else:
            old.update(last_seen=now, client=f["client"], name=f["name"], job=f["job"])
            if fp["sha1"] != old.get("fingerprint"):
                # A NEW JOB'S FOLDER IS MADE BEFORE ITS DRAWINGS ARRIVE (JG, 10 Nov 2026: "we need
                # to find NEW folders, not changes"). A folder that held no drawings when last
                # seen and holds some now is a new pack, not a changed one.
                became = "new" if not int(old.get("files") or 0) else "changed"
                if old.get("status") == "new" and old.get("flagged_at"):
                    became = "new"                 # still the new pack it was flagged as
                old.update(fingerprint=fp["sha1"], files=fp["files"], newest=fp["newest"],
                           status=became, flagged_at=now if became != old.get("status")
                           or not old.get("flagged_at") else old["flagged_at"])
    for key, p in packs.items():
        p["present"] = key in seen
    ledger["sweeps"] = int(ledger.get("sweeps") or 0) + 1
    if first:
        ledger["baseline_at"] = now
    keep = cfg["keep_days"] * 86400
    candidates = []
    # A FOLDER MADE AFTER THE FIRST SWEEP IS NEW, whatever the sweep saw of it first (a folder
    # created empty just before a sweep, then filled, was recorded "changed"). Its creation time
    # on the share says so; looked at only for packs marked changed.
    base_at = float(ledger.get("baseline_at") or 0)
    for key, p in packs.items():
        if p.get("status") == "changed" and p.get("present") and base_at:
            try:
                if base_at < os.stat(p["folder"]).st_ctime <= now:
                    p["status"] = "new"
            except OSError:
                pass
    # NEW FOLDERS ONLY, UNLESS ASKED (SDI_DESIGN_SWEEP_SHOW_CHANGED=1 lists changed packs too).
    shown = ("new", "changed") if cfg.get("show_changed") else ("new",)
    for key, p in packs.items():
        if p.get("status") in shown and p.get("present") and p.get("flagged_at") \
                and now - float(p["flagged_at"]) <= keep:
            candidates.append({"folder": p["folder"], "client": p["client"], "name": p["name"], "job": p["job"],
                               "status": p["status"], "files": p.get("files"),
                               "flagged_at": _iso(float(p["flagged_at"])),
                               "first_seen": _iso(float(p["first_seen"])),
                               "estimated": bool(p.get("job") and p["job"] in est),
                               "listing": listing(Path(p["folder"]))})
    candidates.sort(key=lambda c: c["flagged_at"], reverse=True)
    return {"schema": SCHEMA, "swept_at": _iso(now), "root": str(cfg["root"]), "every_minutes": cfg["minutes"],
            "next_at": _iso(now + cfg["minutes"] * 60), "baseline": first, "clients": len(clients),
            "packs": len(found), "candidates": candidates, "errors": errors,
            "baseline_at": _iso(float(ledger["baseline_at"])) if ledger.get("baseline_at") else None}


def save_ledger(path: Path, ledger: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def report_to(servers: List[str], api_key: str, report: Dict[str, Any]) -> List[str]:
    """POST the report to every service; the problems, if any."""
    import urllib.request
    problems = []
    for s in servers:
        req = urllib.request.Request(s.rstrip("/") + "/api/estimate/design-sweep/report",
                                     data=json.dumps(report).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        if api_key:
            req.add_header("X-SDI-Key", api_key)
        try:
            with urllib.request.urlopen(req, timeout=30):
                pass
        except Exception as exc:                                         # noqa: BLE001
            problems.append(f"{s}: {exc}")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--server", default=os.getenv("SDI_SERVER", "http://10.0.0.5:8071"))
    ap.add_argument("--api-key", default=os.getenv("SDI_API_KEY", ""))
    ap.add_argument("--log", default="", help="append the sweep's lines to this file")
    ap.add_argument("--no-index", action="store_true", help="do not refresh the drawing index")
    args = ap.parse_args(argv)
    if args.log:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = open(args.log, "a", encoding="utf-8", buffering=1)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import config  # noqa: F401  (loads .env)
    except Exception:                                                    # noqa: BLE001
        pass
    cfg = settings()
    servers = [x.strip() for x in str(args.server or "").split(",") if x.strip()]
    while True:
        ledger = load_ledger(cfg["ledger"])
        report = sweep(cfg, ledger)
        print(f"[design-sweep] {report['swept_at']} {report['root']}: {report['clients']} client folder(s), "
              f"{report['packs']} pack(s), {len(report['candidates'])} candidate(s)"
              + (" (baseline: nothing flagged on the first sweep)" if report["baseline"] else "")
              + (f"; errors: {report['errors']}" if report["errors"] else ""), flush=True)
        if args.dry_run:
            for c in report["candidates"][:50]:
                print(f"   {c['status']:<8} {c['client']} / {c['name']}", flush=True)
            return 0
        save_ledger(cfg["ledger"], ledger)
        # THE DRAWING INDEX rides on the same hourly beat (src/drawing_index.py): the TTI pricer
        # and anything else finding a drawing by number reads it instead of walking the share.
        if not args.no_index:
            try:
                import drawing_index as di
                icfg = di.settings()
                report["index"] = di.refresh(icfg["roots"], icfg["path"], icfg["depth"], full_days=icfg["full_days"],
                                             recent_days=icfg["recent_days"])
                if report["index"].get("skipped"):
                    print(f"[design-sweep] drawing index not refreshed: {report['index']['skipped']}", flush=True)
                last = report["index"].get("last") or {}
                print(f"[design-sweep] drawing index: {report['index']['folders']} folder(s), "
                      f"{report['index']['drawings']} drawing(s); listed {last.get('listed')}, reused "
                      f"{last.get('reused')} in {last.get('seconds')} s", flush=True)
            except Exception as exc:                                     # noqa: BLE001
                report["index"] = {"error": str(exc)}
                print(f"[design-sweep] the drawing index was not refreshed: {exc}", flush=True)
        for p in report_to(servers, args.api_key, report):
            print(f"[design-sweep] the service did not take the report: {p}", flush=True)
        if args.once:
            return 1 if report["errors"] else 0
        for _ in range(cfg["minutes"]):
            time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
