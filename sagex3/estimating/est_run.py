"""One estimate -> Sage X3 run, for the SDI Intelligence portal's Estimate → X3 page (20 Nov 2026).

    python est_run.py <estimate.xls|xlsx> <run_folder> [--products FILE] [--parent CODE] [--category FGML]
                      [--sheet-material CR4] [--rev-in-code] [--by NAME]

Writes into <run_folder>/out:
    <part>_ZSDIITM.txt / _YA00408BOM.txt / _ZSDIROU2.txt   the X3 load files (and their .xlsx)
    <part>_estimate_to_SageX3.xlsx                          the write-up workbook (est_workbook.py)
    <part>_CHECKS.xlsx                                      the converter's own check workbook
and <run_folder>/run.json - everything the page shows (no X3 product list in it).
With --publish (the portal passes EST_SHARE): a READY run's three load files and the write-up are also saved in
<publish>\<part>_<YYYY-MM-DD_HHMM>\ - K:\Operations\Reporting\SageEstimates, where they are loaded from (James,
20 Nov) - with run.json, so the page's Saved estimates list can reopen it. A NOT READY run isn't saved there: its
files mustn't be loaded. Nothing is ever overwritten.

The X3 product list: --products, else EST_PRODUCTS, else the newest products.json from the X3 pull
(X3_EXPORT_DIR, default %USERPROFILE%\\SDI_X3_exports) - the live list, refreshed daily with Live Orders.
Nothing is written to Sage X3. Exit 0 = ran (READY or NOT READY is in run.json), 1 = couldn't run (error in run.json).
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def find_products(explicit=None):
    for p in (explicit, os.environ.get("EST_PRODUCTS")):
        if p and Path(p).is_file():
            return Path(p)
    root = Path(os.environ.get("X3_EXPORT_DIR", Path.home() / "SDI_X3_exports"))
    cands = sorted(root.glob("*/products.json"), key=lambda p: p.stat().st_mtime) if root.exists() else []
    if not cands:
        raise SystemExit(f"No X3 product list: no products.json under {root} (run a Live Orders Regenerate, which pulls "
                         f"products daily) and EST_PRODUCTS isn't set")
    return cands[-1]


def publish(out, names, folder, folder_user, code):
    """Copy a READY run's files into <folder>\<part>_<date>_<time>\ (seconds added if that minute is taken)."""
    import est_workbook
    now = dt.datetime.now()
    base = Path(folder)
    base.mkdir(parents=True, exist_ok=True)
    name = f"{est_workbook.stem_of(code)}_{now:%Y-%m-%d_%H%M}"
    if (base / name).exists():
        name = f"{est_workbook.stem_of(code)}_{now:%Y-%m-%d_%H%M%S}"
    dest = base / name
    dest.mkdir()
    for n in names:
        shutil.copyfile(out / n, dest / n)
    shown = f"{folder_user.rstrip(chr(92))}\\{name}" if folder_user else str(dest)
    return {"folder": shown, "name": name, "files": names, "path": str(dest)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("estimate")
    ap.add_argument("run_folder")
    ap.add_argument("--products")
    ap.add_argument("--parent")
    ap.add_argument("--category", default="FGML")
    ap.add_argument("--sheet-material", default="CR4")
    ap.add_argument("--rev-in-code", action="store_true")
    ap.add_argument("--by", default="")
    ap.add_argument("--publish", default="", help="folder to save READY runs in (network path)")
    ap.add_argument("--publish-user", default="", help="the same folder as people see it (K:\\...)")
    a = ap.parse_args(argv)
    run = Path(a.run_folder)
    out = run / "out"
    info = dict(ok=False, started=dt.datetime.now().isoformat(timespec="seconds"), estimate=Path(a.estimate).name,
                by=a.by, options=dict(parent=a.parent or "", category=a.category, sheet_material=a.sheet_material,
                                      rev_in_code=a.rev_in_code))
    try:
        import est_to_x3
        import est_workbook
        products = find_products(a.products)
        info["products"] = dict(file=str(products), as_at=dt.datetime.fromtimestamp(products.stat().st_mtime)
                                .isoformat(timespec="minutes"))
        res = est_to_x3.build(a.estimate, out, products, a.parent or None, a.category, a.rev_in_code, a.sheet_material)
        d = res["detail"]
        book = out / f"{est_workbook.stem_of(res['code'])}_estimate_to_SageX3.xlsx"
        est_workbook.write(res, book)
        d.pop("x3", None)                                  # the whole product list: not for the page
        info.update(ok=True, code=res["code"], new=res["new"], ready=res["stop"] == 0, bom=res["bom"], ops=res["ops"],
                    stop=res["stop"], warn=res["warn"], checks=res["checks"], workbook=book.name,
                    load_files=d["load_files"], files=sorted(p.name for p in out.iterdir() if p.is_file()),
                    head={k: v for k, v in d["head"].items()}, existing=d.get("existing"),
                    bom_rows=d["bom_rows"], rou_rows=d["rou_rows"], itm_row=d["itm_row"],
                    bom_read=[{k: v for k, v in b.items() if k != "sheet"} | ({"sheet": list(b["sheet"])} if b.get("sheet") else {})
                              for b in d["bom"]],
                    ops_read=d["ops"])
        if a.publish and info["ready"]:
            try:
                info["published"] = publish(out, [*d["load_files"], book.name], a.publish, a.publish_user, res["code"])
            except OSError as e:                               # the run stands; the page says it wasn't saved
                info["publish_error"] = f"Not saved to {a.publish_user or a.publish}: {e}"
    except (Exception, SystemExit) as e:                       # noqa: BLE001 - recorded for the page
        info["error"] = str(e) or e.__class__.__name__
        if isinstance(e, ModuleNotFoundError):
            info["error"] += (f' - install it for every account, in PowerShell as administrator:  "{sys.executable}" '
                              f'-s -m pip install {e.name}')
        info["trace"] = traceback.format_exc()[-1500:]
    info["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    run.mkdir(parents=True, exist_ok=True)
    (run / "run.json").write_text(json.dumps(info, indent=1, default=str), encoding="utf-8")
    pub = info.get("published")
    if pub:                                    # the saved folder carries its own summary, so the page can reopen it
        try:                                   # from K: alone - "load up previously generated files" (James, 20 Nov)
            keep = {k: v for k, v in info.items() if k != "trace"}
            (Path(pub["path"]) / "run.json").write_text(json.dumps(keep, indent=1, default=str), encoding="utf-8")
        except OSError as e:
            info["publish_error"] = f"Files saved, but not the run summary: {e}"
            (run / "run.json").write_text(json.dumps(info, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: info.get(k) for k in ("ok", "code", "ready", "bom", "ops", "stop", "warn", "workbook", "error")},
                     default=str))
    return 0 if info["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
