"""Live Orders from Sage X3, end to end, in one command. Written 20 Nov 2026.

    python run_x3.py [--pull api|ui] [--products <file>] [--boms <file>] [--routes <file>]
       (products / BOMs / routings default to products.json / boms.json / routes.json from the X3 pull - all
        straight from Sage X3; --routes <ROU.txt> still takes the old route load file)

  1. (optional) pull today's data from X3: --pull api (x3_api.py) or --pull ui (x3_ui.py, the screens)
  2. take the newest exports folder (%USERPROFILE%\\SDI_X3_exports\\<date>, or --exports)
  3. x3_source.py turns it into the Live Orders extract
  4. build_live_orders.py builds the board (.xlsx / .html) and the data contract (.json)
  5. copies the .json to <runs>\\latest.json and writes <runs>\\status.json - what the portal serves

Runs go to %USERPROFILE%\\SDI_X3_runs\\<date time> (or --runs / LIVE_ORDERS_RUNS). Read-only towards X3.
Schedule it in Windows Task Scheduler (see README). Exit code 0 = built, 1 = failed (status.json says why).
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
INTEGRATION = HERE.parent.parent / "integration"
EXPORTS = Path(os.environ.get("X3_EXPORT_DIR", Path.home() / "SDI_X3_exports"))
RUNS = Path(os.environ.get("LIVE_ORDERS_RUNS", Path.home() / "SDI_X3_runs"))
# Production's folder: the workbooks they open, view and edit (James, 20 Nov). Use the network path - a scheduled
# task or service doesn't see mapped drives. K: = \\sdi-dc01\shareddata$\Shared
SHARE = os.environ.get("LIVE_ORDERS_SHARE", r"\\sdi-dc01\shareddata$\Shared\Operations\Reporting\LiveOrders")


TRANSACTIONS = ["works_orders", "wo_products", "wo_materials", "stock", "so_lines", "po_lines"]   # every run
MASTER = ["products", "boms", "routes"]                                                               # once a day


def newest_workbook(folder):
    """The latest generated workbook - the one Production work in. By the time in its name, not the file date, so
    opening an old one from the history doesn't make it 'newest'. Excel's ~$ lock files are ignored."""
    if not folder or not Path(folder).exists():
        return None
    books = sorted(p for p in Path(folder).glob("SDI_Live_Orders_*.xlsx") if not p.name.startswith("~$"))
    return books[-1] if books else None


def publish(files, folder):
    """Save this run into Production's folder as a new pair - SDI_Live_Orders_<date>_<time>.xlsx (to open and edit)
    and .json (the portal's views). Nothing is ever overwritten: that folder is the history (James, 20 Nov)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now()
    stem = f"SDI_Live_Orders_{now:%Y-%m-%d_%H%M}"
    if any(folder.glob(stem + ".*")):
        stem = f"SDI_Live_Orders_{now:%Y-%m-%d_%H%M%S}"
    out = {}
    for f in files:
        dst = folder / (stem + f.suffix)
        shutil.copyfile(f, dst)
        out[f.suffix.lstrip(".")] = str(dst)
    return out


def run_streamed(cmd, timeout_s):
    """Run the pull, passing its lines straight through (the portal shows the latest one while it runs - 20 Nov:
    with the output held until the end the page said only "Generating..."). Returns (exit code, last 2000 chars).
    Data sets already written stay in today's exports folder, so a pull stopped part-way resumes on the next run."""
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([cmd[0], "-u"] + cmd[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env)
    t0, tail = time.time(), ""
    for line in p.stdout:
        print(line, end="", flush=True)
        tail = (tail + line)[-2000:]
        if time.time() - t0 > timeout_s:
            p.kill()
            return -9, tail + f"\nstopped after {timeout_s / 3600:.1f} h"
    return p.wait(), tail


def pull_failures(day, out):
    """What failed in the pull, in X3's own words: api_log.json for the day, or a crash's last line."""
    msgs = []
    try:
        log = json.loads((Path(day) / "api_log.json").read_text())
        if dt.datetime.fromisoformat(log["at"]) > dt.datetime.now() - dt.timedelta(hours=4):
            msgs = [f"{r['name']}: {r.get('error', '')[:200]}" for r in log["runs"] if not r.get("ok")]
            msgs += [f"{r['name']}: {n}" for r in log["runs"] if r.get("ok") for n in r.get("notes") or []]
    except (OSError, ValueError, KeyError):
        pass
    if "Traceback" in out:                                     # the pull itself crashed
        msgs.append("pull crashed: " + [l for l in out.strip().splitlines() if l.strip()][-1][:300])
    return msgs


def master_file(name, src, max_hours):
    """products / boms: from this pull if there, else the newest earlier pull - fresh enough if under max_hours."""
    here = next((src / f"{name}{e}" for e in (".json", ".csv") if (src / f"{name}{e}").exists()), None)
    if here:
        return here, True
    cands = sorted(EXPORTS.glob(f"*/{name}.json")) + sorted(EXPORTS.glob(f"*/{name}.csv"))
    if not cands:
        return None, False
    f = max(cands, key=lambda p: p.stat().st_mtime)
    return f, (dt.datetime.now().timestamp() - f.stat().st_mtime) / 3600 < max_hours


def newest_exports(root):
    days = sorted((p for p in Path(root).iterdir() if p.is_dir()), key=lambda p: p.name) if Path(root).exists() else []
    if not days:
        raise SystemExit(f"No exports in {root}: run  python x3_api.py pull  or  python x3_ui.py export  first")
    return days[-1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--products", help="default: products.json from the pull (X3 API)")
    ap.add_argument("--boms", help="default: boms.json from the pull (X3 API)")
    ap.add_argument("--routes", help="default: routes.json from the pull (X3 routings); or a route load file (.txt)")
    ap.add_argument("--costs")
    ap.add_argument("--carry")
    ap.add_argument("--pull", choices=["api", "ui"])
    ap.add_argument("--exports", help="an exports folder (default: the newest under X3_EXPORT_DIR)")
    ap.add_argument("--runs", default=str(RUNS))
    ap.add_argument("--keep", type=int, default=60, help="runs to keep (oldest removed)")
    ap.add_argument("--master-hours", type=float, default=24, help="re-pull products / BOMs when older than this")
    ap.add_argument("--full", action="store_true", help="re-pull products / BOMs / routings now as well")
    ap.add_argument("--pull-hours", type=float, default=4, help="stop the pull after this long (default 4 h)")
    ap.add_argument("--share", default=SHARE, help="Production's workbook folder (LIVE_ORDERS_SHARE); '' = don't publish")
    a = ap.parse_args(argv)

    runs = Path(a.runs)
    runs.mkdir(parents=True, exist_ok=True)
    status = dict(ok=False, started=dt.datetime.now().isoformat(timespec="seconds"))
    try:
        if a.pull:
            script = INTEGRATION / ("x3_api/x3_api.py" if a.pull == "api" else "x3_ui/x3_ui.py")
            cmd = [sys.executable, str(script), "pull" if a.pull == "api" else "export"]
            if a.pull == "api":                         # transactions every run; products / BOMs once a day
                today = EXPORTS / dt.date.today().isoformat()
                stale = [m for m in MASTER if a.full or not master_file(m, today, a.master_hours)[1]]
                cmd += TRANSACTIONS + stale
                status["master_refreshed"] = stale
            code, out = run_streamed(cmd, a.pull_hours * 3600)
            status["pull"] = dict(cmd=" ".join(cmd[1:]), code=code, out=out)
            status["pull_failed"] = pull_failures(EXPORTS / dt.date.today().isoformat(), out)
            if code not in (0, 1):                              # 1 = some data sets failed; carry on with the rest
                raise SystemExit(f"pull failed ({code}): {out[-400:]}")
        src = Path(a.exports) if a.exports else newest_exports(EXPORTS)
        out = runs / dt.datetime.now().strftime("%Y-%m-%d_%H%M")
        out.mkdir(parents=True, exist_ok=True)
        for k in ("products", "boms", "routes"):                # master data: this pull, else the newest earlier one
            if not getattr(a, k):
                f, _ = master_file(k, src, a.master_hours)
                if not f:
                    why = "; ".join(status.get("pull_failed") or [])
                    raise SystemExit(f"No {k} from Sage X3" + (f" - the pull said: {why}" if why else
                                     f": no {k}.json in any pull (run  x3_api.py pull {k}  or name a file)"))
                setattr(a, k, str(f))
        status["master_data"] = dict(products=a.products, boms=a.boms, routes=a.routes)
        from x3_source import to_extract
        extract = out / "X3_extract.txt"
        status["exports"] = str(src)
        status["adapter"] = to_extract(src, extract)
        if not a.carry:                                   # Production's notes: from the workbook they last edited
            last = newest_workbook(a.share) if a.share else None
            a.carry = str(last) if last else None
        status["carried_from"] = a.carry
        from build_live_orders import build
        res = build(extract, out, a.products, a.boms, a.routes, None, 14, a.costs, a.carry)
        j = next(out / f for f in res["files"] if f.endswith(".json"))
        shutil.copyfile(j, runs / "latest.json")
        if a.share:
            status["published"] = publish([out / f for f in res["files"] if f.endswith((".xlsx", ".json"))], a.share)
        status.update(ok=True, run=str(out), json=str(j), meta=res["meta"])
        if status.get("pull_failed"):                     # built, but on some of yesterday's data - say so
            status["warning"] = "note from the pull: " + "; ".join(status["pull_failed"])
        old = sorted(p for p in runs.iterdir() if p.is_dir())[:-a.keep] if a.keep else []
        for p in old:
            shutil.rmtree(p, ignore_errors=True)
    except (Exception, SystemExit) as e:                          # noqa: BLE001 - recorded for the portal
        status["error"] = str(e) or e.__class__.__name__
        if isinstance(e, ModuleNotFoundError):                     # 20 Nov: the portal's Python had no openpyxl
            status["error"] += (f' - install it for every account (the portal service is not you), in PowerShell as '
                                f'administrator:  "{sys.executable}" -s -m pip install {e.name}')
        status["trace"] = traceback.format_exc()[-1500:]
    status["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    (runs / "status.json").write_text(json.dumps(status, indent=1, default=str))
    print(json.dumps({k: status.get(k) for k in ("ok", "exports", "run", "carried_from", "published", "meta", "warning", "error")},
                     indent=1, default=str))
    for l in status.get("adapter", []):
        print(" ", l)
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
