"""Live Orders from Sage X3, end to end, in one command. Written 20 Nov 2026.

    python run_x3.py --routes <ROU.txt> [--products <file>] [--boms <file>] [--pull api|ui]
       (products / BOMs default to products.json / boms.json in the same X3 pull)

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
MASTER = ["products", "boms"]                                                                         # once a day


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
    ap.add_argument("--routes", required=True, help="the route load file (.txt) until X3 routings are mapped")
    ap.add_argument("--costs")
    ap.add_argument("--carry")
    ap.add_argument("--pull", choices=["api", "ui"])
    ap.add_argument("--exports", help="an exports folder (default: the newest under X3_EXPORT_DIR)")
    ap.add_argument("--runs", default=str(RUNS))
    ap.add_argument("--keep", type=int, default=60, help="runs to keep (oldest removed)")
    ap.add_argument("--master-hours", type=float, default=24, help="re-pull products / BOMs when older than this")
    ap.add_argument("--full", action="store_true", help="re-pull products / BOMs now as well")
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
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            status["pull"] = dict(cmd=" ".join(cmd[1:]), code=r.returncode, out=(r.stdout + r.stderr)[-2000:])
            if r.returncode not in (0, 1):                      # 1 = some data sets failed; carry on with the rest
                raise SystemExit(f"pull failed ({r.returncode}): {(r.stdout + r.stderr)[-400:]}")
        src = Path(a.exports) if a.exports else newest_exports(EXPORTS)
        out = runs / dt.datetime.now().strftime("%Y-%m-%d_%H%M")
        out.mkdir(parents=True, exist_ok=True)
        for k in ("products", "boms"):                          # master data: this pull, else the newest earlier one
            if not getattr(a, k):
                f, _ = master_file(k, src, a.master_hours)
                if not f:
                    raise SystemExit(f"No --{k} given and no {k}.json in any pull: run  x3_api.py pull {k}  or name a file")
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
        old = sorted(p for p in runs.iterdir() if p.is_dir())[:-a.keep] if a.keep else []
        for p in old:
            shutil.rmtree(p, ignore_errors=True)
    except (Exception, SystemExit) as e:                          # noqa: BLE001 - recorded for the portal
        status["error"] = str(e) or e.__class__.__name__
        status["trace"] = traceback.format_exc()[-1500:]
    status["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    (runs / "status.json").write_text(json.dumps(status, indent=1, default=str))
    print(json.dumps({k: status.get(k) for k in ("ok", "exports", "run", "carried_from", "published", "meta", "error")},
                     indent=1, default=str))
    for l in status.get("adapter", []):
        print(" ", l)
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
