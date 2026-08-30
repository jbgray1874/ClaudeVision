"""Clear the LLM caches for ONE drawing pack, so the next run is a real read.

WHY THIS EXISTS. The first LLM-only run through the page reported:

    [bom-vision] 0 page(s) sent to the model, 22 from cache, 0 not selected
    [llm-full-extract] reusing the cached read for this pack

Not one call went to Grok. The run proved the plumbing and measured nothing about the model,
which is the opposite of what an LLM-only run is for. The caches are doing exactly their job
-- 2085 returned a route with welding on one run and without it on the next, and the unit cost
halved, which is why they exist -- but a MEASUREMENT of the model has to actually ask it.

WHY NOT JUST DELETE THE FOLDER. Both caches are shared across every job this machine has ever
read. Emptying them to re-read one pack throws away every other pack's settled answer and buys
back a bill and an afternoon. Nothing in either filename says which job it belongs to: both are
content hashes.

SO EACH CACHE IS MATCHED THE ONLY WAY IT HONESTLY CAN BE.

  vision_bom  -- keyed on the page IMAGE, but every entry RECORDS the pdf_name it came from.
                 Matched on that, against the actual PDFs in the pack folder. Exact.

  llm_extract -- keyed on the document text, the model and the prompt, and records nothing.
                 So the key is RECOMPUTED here from the same inputs the engine uses. If the
                 file is there, it is this pack's, by construction.

THE INFERENCE ENTRIES CANNOT BE ATTRIBUTED AND THIS SAYS SO. Their key includes the BOM and
the missing-detail list as they stood mid-run; nothing outside a run can reproduce that. They
are reported as unattributable rather than guessed at, and --everything is offered for the one
case where that matters. A tool that quietly deleted more than it could name would be worse
than one that leaves something behind.

REPORTS BY DEFAULT, DELETES ON --apply, like the other tools in this folder.

    python tools/diagnose/clear_llm_cache.py --job "\\\\sdi-dc01\\...\\Dyson\\10575-02"
    python tools/diagnose/clear_llm_cache.py --job "..." --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))

# THE DIRECTORIES THIS TOOL IS ALLOWED TO DELETE FROM. Not a style point: the paths come from
# env vars (SDI_LLM_EXTRACT_CACHE_DIR relocates one of them), and a misconfigured variable
# pointing at a share is the difference between clearing a cache and clearing a job folder.
_ALLOWED_DIR_NAMES = {"vision_bom", "llm_extract"}


def _pack_pdfs(job: Path) -> List[Path]:
    if not job.exists():
        raise SystemExit(f"No such folder: {job}")
    if job.is_file():
        return [job]
    return sorted(p for p in job.iterdir()
                  if p.is_file() and p.suffix.lower() == ".pdf")


def _vision_entries(names: Set[str]) -> Tuple[List[Path], int, str]:
    """Cache files whose recorded pdf_name is one of this pack's PDFs."""
    try:
        from _bom_vision_reader import DEFAULT_CACHE_DIR
    except Exception as exc:                     # pragma: no cover - import guard
        return [], 0, f"could not read the vision cache ({type(exc).__name__}: {exc})"
    d = Path(DEFAULT_CACHE_DIR)
    if not d.is_dir():
        return [], 0, f"no vision cache at {d}"
    hits, total = [], 0
    for f in sorted(d.glob("*.json")):
        total += 1
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            # A CORRUPT ENTRY IS NOT THIS PACK'S BY DEFAULT. The reader already re-fetches on
            # one, so it costs a call and nothing else; deleting other people's unreadable
            # files is not this tool's job.
            continue
        if str(entry.get("pdf_name") or "").strip().lower() in names:
            hits.append(f)
    return hits, total, ""


def _full_extract_entries(pdfs: List[Path], model: str) -> Tuple[List[Path], int, int, str]:
    """The whole-pack read, found by RECOMPUTING its key from the same inputs the engine uses.

    Returns (files, total_in_dir, unattributable, note). Unattributable are every other entry
    in the directory: the inference passes, and other jobs' reads."""
    try:
        import llm_full_extract as lfe
    except Exception as exc:                     # pragma: no cover - import guard
        return [], 0, 0, f"could not read the extract cache ({type(exc).__name__}: {exc})"
    d = lfe._cache_dir()
    if d is None or not Path(d).is_dir():
        return [], 0, 0, f"no extract cache at {d}"
    d = Path(d)
    total = len(list(d.glob("*.json")))
    hits: List[Path] = []
    note = ""
    for pdf in pdfs:
        try:
            ctx = lfe.build_document_context(pdf)
        except Exception as exc:
            note = (f"the pack text could not be rebuilt ({type(exc).__name__}: {exc}) — the "
                    f"whole-pack read cannot be identified without it")
            continue
        if not ctx:
            continue
        key = lfe._cache_key("full", ctx, model, lfe._PROMPT, lfe.SYSTEM_TRANSCRIBE)
        f = d / f"{lfe._CACHE_VERSION}_{key}.json"
        if f.exists() and f not in hits:
            hits.append(f)
    return hits, total, max(total - len(hits), 0), note


def _delete(files: List[Path]) -> Tuple[int, List[str]]:
    gone, failed = 0, []
    for f in files:
        if f.parent.name not in _ALLOWED_DIR_NAMES:
            failed.append(f"{f} — refused: not inside a cache directory")
            continue
        try:
            f.unlink()
            gone += 1
        except Exception as exc:
            failed.append(f"{f} — {type(exc).__name__}: {exc}")
    return gone, failed


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Clear the vision and whole-pack LLM caches for one drawing pack.")
    ap.add_argument("--job", required=True,
                    help="the pack folder (or a single PDF) the next run will read")
    ap.add_argument("--model", default="",
                    help="the model the run will use; defaults to the engine's own default")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete. Without it nothing is removed and the files that "
                         "WOULD be are listed.")
    ap.add_argument("--everything", action="store_true",
                    help="also delete the entries that cannot be attributed to this pack — "
                         "the inference passes AND every other job's read. Rarely right.")
    args = ap.parse_args(argv)

    try:
        import llm_full_extract as lfe
        default_model = lfe.DEFAULT_MODEL
    except Exception:
        default_model = ""
    model = args.model or default_model

    job = Path(args.job)
    pdfs = _pack_pdfs(job)
    names = {p.name.lower() for p in pdfs}
    print(f"Pack   {job}")
    if not pdfs:
        print("  No PDFs in that folder — nothing in either cache belongs to it.")
        return 1
    for p in pdfs:
        print(f"  pdf  {p.name}")

    vis, vis_total, vis_note = _vision_entries(names)
    full, full_total, unattributable, full_note = _full_extract_entries(pdfs, model)

    print("")
    print(f"Vision cache   {len(vis)} of {vis_total} entr(ies) belong to this pack"
          + (f" — {vis_note}" if vis_note else ""))
    print(f"Extract cache  {len(full)} of {full_total} entr(ies) identified as this pack's "
          f"whole-pack read (model {model or 'unknown'})"
          + (f" — {full_note}" if full_note else ""))
    if unattributable:
        # SAID PLAINLY, because it is the one thing this tool cannot do. An inference entry
        # keyed on a mid-run BOM cannot be reproduced from outside a run at any price.
        print(f"               {unattributable} further entr(ies) cannot be attributed to any "
              f"pack from the cache alone (inference passes and other jobs). Left alone.")

    targets = list(vis) + list(full)
    if args.everything:
        try:
            import llm_full_extract as lfe2
            d = lfe2._cache_dir()
            if d:
                targets += [f for f in Path(d).glob("*.json") if f not in targets]
        except Exception:
            pass

    if not targets:
        print("\nNothing to clear. The next run will call the model for anything it needs.")
        return 0

    if not args.apply:
        print(f"\nWould delete {len(targets)} file(s). Nothing has been removed.")
        print("Re-run with --apply to clear them, then run the pack again — the log should "
              "show pages SENT to the model rather than read from cache.")
        return 0

    gone, failed = _delete(targets)
    print(f"\nDeleted {gone} file(s).")
    for line in failed:
        print("  NOT deleted: " + line)
    print("Run the pack again. [bom-vision] should now report pages sent to the model, and "
          "the whole-pack read should not say it is reusing a cached one.")
    return 0 if not failed else 1


if __name__ == "__main__":                        # pragma: no cover
    raise SystemExit(main())
