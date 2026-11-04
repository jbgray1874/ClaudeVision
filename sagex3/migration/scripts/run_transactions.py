"""The six YA004 opening-transaction spreadsheets from one live extract, in one command.

    python run_transactions.py <run folder> [--stock-date 20261031] [--previous <last set>]

<run folder>/extract/extract_transactions.txt is the output of rebuild/sql/extract_transactions.sql,
taken that morning (rule 1: every extract is live). The products come from the same run folder's
product build (rebuild/run.py): the transactions use exactly the codes in that product file, and a
row is held back only if its product, customer or supplier isn't in the files being loaded.

It runs the proven chain unchanged - map_bins, build_mapped_guides, populate_guides,
recode_ledgers_v7, build_mfg, build_bicy_bisy, build_sheets - in a fresh working folder
(<run>/work), with reference files generated from the run's product build in place of the old UAT
product lists. Out come YA004SMR, YA004POH, YA004SOHPJ, YA004MFG, YA004BICY and YA004BISY, each as
the mapped spreadsheet and its ; load file, in <run>/out, with RUN_SUMMARY.md (the extract's checks
and control totals, rows and held-back reasons per file) and the change report against --previous.
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "rebuild"))
from common import product_codes, read_grids, write_load  # noqa: E402
from product_suppliers import old_clean  # noqa: E402
from products import load  # noqa: E402

BASE = Path("/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad")
SET = BASE / "Current_mapped_set_2026-11-04"
# the grids populate_guides reads, in its order, with the number of columns each view returns
GRIDS = [("SOH", 20), ("POH", 15), ("SMR", 19), ("BICX", 23), ("BISX", 24)]
CHAIN = ["map_bins.py", "build_mapped_guides.py", "populate_guides.py", "recode_ledgers_v7.py", "build_mfg.py",
         "build_bicy_bisy.py", "build_sheets.py"]
OUTPUTS = [("out_sheets/YA004SMR_guide_MAPPED_clean_run.xlsx", "Data with Headings", 3),
           ("out_sheets/YA004POH_guide_MAPPED_clean_run.xlsx", "Data with Headings", 3),
           ("out_sheets/YA004SOHPJ_guide_MAPPED_clean_run.xlsx", "Data with Headings", 3),
           ("out_sheets/YA004MFG_works_orders_MAPPED_clean_run.xlsx", "Data With Headings", 3),
           ("out_mapped/YA004BICY_guide_MAPPED.xlsx", "Data with Headings", 2),
           ("out_mapped/YA004BISY_guide_MAPPED.xlsx", "Data with Headings", 2)]


def semi(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="cp850", errors="replace") as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(rows)


def data_rows(path, sheet, first):
    return [r for r in load_workbook(path, read_only=True)[sheet].iter_rows(min_row=first, values_only=True)
            if r and r[0] is not None]


def references(run, work, bom_file, route_file):
    """The product, BOM and route lists the chain checks against, from this run's product build.
    The views write product codes with the old cleansing; the chain maps old -> X3 code through
    the 'V6' (old) and 'V7' (X3) lists, so those are generated row for row from the code map."""
    item, master, _, _, _ = load(run / "extract" / "extract_products.txt")
    code, _ = product_codes(sorted(set(item) | set(master)))
    products = {r[1]: list(r[:13]) for r in data_rows(run / "out" / "ZSDIITM_products_MAPPED.xlsx",
                                                     "Data with Headings", 4)}
    old_to_x3 = {}
    for raw, x3 in code.items():
        if x3 in products:
            old_to_x3.setdefault(old_clean(raw), x3)
    for x3 in products:                                  # a code already in X3 form maps to itself
        old_to_x3.setdefault(x3, x3)
    cell = lambda v: "" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
    v6 = [[cell(v) for v in [products[x][0], old] + products[x][2:]] for old, x in sorted(old_to_x3.items())]
    v7 = [[cell(v) for v in products[x]] for _, x in sorted(old_to_x3.items())]
    for p in (work / "uploads_final" / "ZSDIITM_Cleansing.txt", work / "out_std6" / "ZSDIITM_load6_products.txt"):
        semi(p, v6)
    semi(work / "out_v7" / "ZSDIITM_load7_products.txt", v7)
    x3_to_old = {}
    for old, x in old_to_x3.items():
        x3_to_old.setdefault(x, []).append(old)
    parents = lambda f, sheet, first: sorted({o for r in data_rows(f, sheet, first) for o in x3_to_old.get(r[0], [r[0]])})
    semi(work / "out_std6" / "YA00408BOM_load6_loadable.txt", [[p] for p in parents(bom_file, "Data with Headings", 3)])
    semi(work / "out_std6" / "ZSDIROU2_load6_routes.txt", [[p] for p in parents(route_file, "ZSDROU2", 4)])
    return len(products), len(old_to_x3)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument("--stock-date", default="20261031", help="SMR Posted Date (Run 3: 20261031; go-live 20261231)")
    ap.add_argument("--company", default="C01")
    ap.add_argument("--customers", default=str(BASE / "out_run3" / "YA004BPC_customers_MAPPED.txt"))
    ap.add_argument("--suppliers", default=str(BASE / "out_run3" / "YA004BPS_suppliers_MAPPED.txt"))
    ap.add_argument("--bom", default=str(SET / "YA00408BOM_boms_MAPPED.xlsx"))
    ap.add_argument("--routes", default=str(SET / "ZSDIROU2_routes_MAPPED.xlsx"))
    ap.add_argument("--bins", default=str(BASE / "bins" / "out.txt"), help="bins_and_delivery.sql grid 1")
    ap.add_argument("--previous", default=str(SET), help="the set to compare with")
    ap.add_argument("--legacy-views", help="test only: an old views_v2 output (positional grids)")
    ap.add_argument("--legacy-wor", help="test only: an old works_orders_extract output")
    ap.add_argument("--extra", help="test only: the 27 Oct new-accounts export")
    a = ap.parse_args()
    run = Path(a.run_dir)
    work, out = run / "work", run / "out"
    if work.exists():
        shutil.rmtree(work)
    for d in ("run1", "wor", "bins", "out_mapped", "out_sheets", "out_mfg", "out_v7", "out_std6", "uploads_final"):
        (work / d).mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    # ---- the extract, in the layout the chain reads -----------------------------------------
    summary = []
    if a.legacy_views:
        shutil.copy(a.legacy_views, work / "run1" / "out.txt")
        shutil.copy(a.legacy_wor, work / "wor" / "out.txt")
        summary.append(f"Test run on old extracts: {a.legacy_views}, {a.legacy_wor}")
    else:
        g, _ = read_grids(run / "extract" / "extract_transactions.txt")
        missing = [k for k, _ in GRIDS + [("WOR", 25), ("CHECK", 0)] if k not in g]
        if missing:
            raise SystemExit(f"extract_transactions.txt: no {missing} grid - was the whole script saved?")
        for k, n in GRIDS:
            widths = Counter(len(r) for r in g[k])
            if set(widths) != {n}:
                raise SystemExit(f"{k}: rows of {dict(widths)} columns, the chain expects {n} - has the view changed?")
        blocks = [["X\t0"]] * 6 + [["\t".join(r) for r in g[k]] for k, _ in GRIDS]
        (work / "run1" / "out.txt").write_text("\n\n".join("\n".join(b) for b in blocks) + "\n", encoding="utf-8")
        (work / "wor" / "out.txt").write_text("\n".join("\t".join(r) for r in g["WOR"]) + "\n", encoding="utf-8")
        summary.append("## Extract checks\n")
        summary += [f"- {r[0]}: **{r[1]}**" for r in g["CHECK"]]
        summary.append("\n## Control totals (for the reconciliation)\n")
        summary += [f"- {r[0]}: {r[1]}" + (f", GBP {r[2]}" if len(r) > 2 and r[2] not in ("", "NULL") else "")
                    for r in g.get("TOTALS", [])]
        bad = [r for r in g["CHECK"] if "dropped" in r[0] and r[1] not in ("0", "")]
        if bad:
            summary.append("\n**STOP check: rows dropped for want of an account - " + "; ".join(f"{r[0]} {r[1]}" for r in bad)
                           + ". Only the accounts left out on purpose may be here (runbook section 9).**")
    shutil.copy(a.bins, work / "bins" / "out.txt")
    shutil.copytree(BASE / "loclist", work / "loclist")
    for d in ("uploads_tmpl5", "tmpl_t2", "out_v8"):
        os.symlink(BASE / d, work / d)
    n_products, n_codes = references(run, work, Path(a.bom), Path(a.routes))

    # ---- the chain ------------------------------------------------------------------------------
    env = dict(os.environ, MIG_BASE=str(work), STOCK_DATE=a.stock_date, COMPANY=a.company,
               CUSTOMER_FILE=a.customers, SUPPLIER_FILE=a.suppliers)
    env.pop("OUT_DIR", None)
    if a.extra:
        env["EXTRA_EXPORT"] = a.extra
    with open(work / "chain.log", "w") as log:
        for step in CHAIN:
            log.write(f"\n===== {step}\n")
            log.flush()
            r = subprocess.run([sys.executable, str(HERE / step)], env=env, stdout=log, stderr=subprocess.STDOUT)
            if r.returncode:
                raise SystemExit(f"{step} failed - see {work / 'chain.log'}")

    # ---- the six files, with their load files -------------------------------------------------
    summary.append(f"\n## Files (products from {run / 'out'}: {n_products:,} products, {n_codes:,} codes mapped)\n")
    summary.append("| File | Rows | Held back | Why held back |")
    summary.append("|---|---|---|---|")
    for rel, sheet, first in OUTPUTS:
        src = work / rel
        dst = out / src.name
        shutil.copy(src, dst)
        txt, n, _ = write_load(dst, sheet, first)
        wb = load_workbook(dst, read_only=True)
        held = []
        if "Held back" in wb.sheetnames:
            held = [r for r in wb["Held back"].iter_rows(min_row=2, values_only=True) if r and any(r)]
        reasons = Counter(str([v for v in r if v not in (None, "")][-1])[:60] for r in held)
        summary.append(f"| {dst.name} | {n:,} | {len(held):,} | " + "; ".join(f"{k} {v}" for k, v in reasons.most_common(3)) + " |")
    (out / "RUN_SUMMARY.md").write_text("# Opening transactions - run summary\n\n" + "\n".join(summary) + "\n",
                                        encoding="utf-8")
    print("\n".join(summary))
    if a.previous:
        sys.path.insert(0, str(HERE.parent / "rebuild"))
        import changes
        print()
        changes.main(a.previous, out)


if __name__ == "__main__":
    main()
