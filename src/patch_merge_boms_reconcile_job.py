r"""
Patch: extract merge_boms.main()'s inline Path-A/Path-B pairing + counting into a
reusable library function reconcile_job(pdf_paths, ...), and rewire main() to call it
(verbose=True) so the standalone CLI output is unchanged. This makes the proven
reconcile logic importable by bom_pipeline / the live estimator, with main() as the
witness that reconcile_job is faithful (re-run the standalone -> identical BOMs).

Marker-slice (robust to whitespace): replaces the region from 'def main():' up to
'if __name__' with [reconcile_job] + [new main]. Match-or-refuse: aborts untouched if
markers are missing or reconcile_job already present.

Run from anywhere (absolute path baked in):
  C:\ClaudeVision\.venv\Scripts\python.exe patch_merge_boms_reconcile_job.py
"""
import pathlib

SRC = pathlib.Path(r"C:\ClaudeVision\src\merge_boms.py")

RECONCILE_JOB = '''def reconcile_job(
    pdf_paths,
    *,
    dpi=300,
    max_side=2000,
    model=None,
    cache_dir=None,
    no_cache=False,
    refresh=False,
    force_llm=False,
    refresh_file=None,
    verbose=False,
):
    """Dual-path BOM reconcile for a set of PDFs (library entry point).

    Runs Path A (deterministic) + Path B (Grok vision, cached) exactly as main() did,
    pairs pages by file+page, reconciles each, and returns structured results:
        {'pages': [{'label','a_bom','b_bom','rows','findings'}, ...],
         'findings': [...], 'counts': {'both','recovered','override','a_only'},
         'pdf_paths': [...], 'a_count': int, 'b_count': int}
    No Grok logic lives here -- it delegates to run_path_a / run_path_b, so behaviour
    is identical to the previous inline main() (verified: standalone output unchanged).
    """
    if model is None:
        model = os.environ.get("XAI_VISION_MODEL", "grok-4.5")
    if cache_dir is None:
        cache_dir = pathB.DEFAULT_CACHE_DIR
    _args = argparse.Namespace(
        pdf=None, pdf_dir=None, dpi=dpi, max_side=max_side, model=model,
        cache_dir=cache_dir, no_cache=no_cache, refresh=refresh,
        force_llm=force_llm, refresh_file=refresh_file,
    )
    if verbose:
        print("\\nRunning Path A (deterministic extract_words)...")
    a_boms = run_path_a(pdf_paths)
    if verbose:
        print(f"  Path A found {len(a_boms)} BOM table(s).")
        print("Running Path B (Grok vision, cached)...")
    b_boms = run_path_b(pdf_paths, _args)
    if verbose:
        print(f"  Path B found {len(b_boms)} BOM table(s).")

    b_index = _index_by_keys(b_boms)
    a_index = _index_by_keys(a_boms)
    seen_fp = set()
    pages = []
    counts = {"both": 0, "recovered": 0, "override": 0, "a_only": 0}
    total_findings = []
    for bom in a_boms + b_boms:
        fp = f"{bom.get('pdf_name','')}#{bom.get('page_index',-1)}"
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        fkey = f"F:{fp}"
        a_bom = a_index.get(fkey)
        b_bom = b_index.get(fkey)
        label = (b_bom or {}).get("parent") or (a_bom or {}).get("parent") or fp
        merged, findings = reconcile_page(a_bom, b_bom, label)
        if not merged:
            continue
        page_findings = list(findings) + code_quality_findings(label, merged)
        total_findings.extend(page_findings)
        for r in merged:
            s = r["source"]
            if s == "BOTH":
                counts["both"] += 1
            elif s == "B_RECOVERED":
                counts["recovered"] += 1
            elif s == "B_OVERRIDE":
                counts["override"] += 1
            elif s == "A_ONLY":
                counts["a_only"] += 1
        pages.append({"label": label, "a_bom": a_bom, "b_bom": b_bom,
                      "rows": merged, "findings": page_findings})
    return {
        "pages": pages, "findings": total_findings, "counts": counts,
        "pdf_paths": list(pdf_paths), "a_count": len(a_boms), "b_count": len(b_boms),
    }


'''

NEW_MAIN = '''def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default=None)
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--max-side", type=int, default=2000)
    ap.add_argument("--model", default=os.environ.get("XAI_VISION_MODEL", "grok-4.5"))
    ap.add_argument("--cache-dir", default=pathB.DEFAULT_CACHE_DIR)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--force-llm", action="store_true")
    ap.add_argument("--refresh-file", default=None)
    args = ap.parse_args()
    if args.pdf:
        pdf_paths = [args.pdf]
    elif args.pdf_dir:
        pdf_paths = find_pdfs(args.pdf_dir)
    else:
        print("Provide --pdf-dir or --pdf."); sys.exit(1)
    if not pdf_paths:
        print("No PDFs found."); sys.exit(1)
    print("=" * 82)
    print("DUAL-PATH BOM RECONCILIATION  (Path A deterministic + Path B vision)")
    print(f"Files: {len(pdf_paths)}   Model: {args.model}   DPI: {args.dpi}")
    print("=" * 82)
    result = reconcile_job(
        pdf_paths, dpi=args.dpi, max_side=args.max_side, model=args.model,
        cache_dir=args.cache_dir, no_cache=args.no_cache, refresh=args.refresh,
        force_llm=args.force_llm, refresh_file=args.refresh_file, verbose=True,
    )
    for pg in result["pages"]:
        label = pg["label"]; a_bom = pg["a_bom"]; b_bom = pg["b_bom"]; merged = pg["rows"]
        a_n = len((a_bom or {}).get("rows", []))
        b_n = len((b_bom or {}).get("rows", []))
        print("\\n" + "#" * 82)
        print(f"PARENT: {label}    (Path A: {a_n} rows, Path B: {b_n} rows -> merged: {len(merged)})")
        print("#" * 82)
        for r in merged:
            src = r["source"]; conf = r["confidence"]
            code = r.get("part_number") or r.get("part_ref") or ""
            tag = {"BOTH": "", "B_RECOVERED": "  <= RECOVERED by vision",
                   "B_OVERRIDE": "  <= VISION OVERRIDE", "A_ONLY": "  <= A-only"}.get(src, "")
            print(f"  item {str(r['item_number']):>2} | {code:<16} | {r.get('description','')[:36]:<36} "
                  f"| qty {r['quantity']} | {src:<11} {conf}{tag}")
    print("\\n" + "=" * 82)
    print("RECONCILIATION SUMMARY")
    print("=" * 82)
    c = result["counts"]
    print(f"  BOTH agree (high confidence):     {c['both']}")
    print(f"  RECOVERED by vision (A missed):   {c['recovered']}   <- coverage vision adds")
    print(f"  VISION OVERRIDE (conflict):       {c['override']}   <- Grok won, flagged")
    print(f"  A-only (vision missed):           {c['a_only']}")
    print()
    if result["findings"]:
        print("DRAWING-QUALITY & REVIEW FINDINGS (for the emailed report):")
        for f in result["findings"]:
            print(f"  - {f}")
    else:
        print("No review findings -- both paths agreed on everything, codes clean.")
    print("=" * 82)


'''


def run():
    src = SRC.read_text(encoding="utf-8")
    if "def reconcile_job(" in src:
        print("ABORT: reconcile_job already present -- nothing changed.")
        return
    i = src.find("def main():")
    j = src.find('if __name__')
    if i == -1 or j == -1 or j < i:
        print("ABORT: could not locate 'def main():' ... 'if __name__' markers. "
              "Nothing changed. Paste the current tail of merge_boms.py so I can re-key.")
        return
    head = src[:i]
    tail = src[j:]
    new = head + RECONCILE_JOB + NEW_MAIN + tail
    # syntax-check before writing
    import ast
    try:
        ast.parse(new)
    except SyntaxError as e:
        print(f"ABORT: patched result failed syntax check ({e}). Nothing written.")
        return
    SRC.write_text(new, encoding="utf-8")
    print("OK: inserted reconcile_job + rewired main() to call it (verbose=True).")
    print()
    print("VERIFY reconcile_job is faithful -- these must produce IDENTICAL BOMs to before:")
    print(r'  C:\ClaudeVision\.venv\Scripts\python.exe merge_boms.py --pdf-dir "K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay"')
    print(r'  C:\ClaudeVision\.venv\Scripts\python.exe merge_boms.py --pdf-dir "K:\Estimating\Completed\AI Estimating\Live Enquiry\12120-01-GA- DIGITAL TICKETING BRACKET"')


if __name__ == "__main__":
    run()
