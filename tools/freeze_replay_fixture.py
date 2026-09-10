"""Freeze an accepted run into tests/replay/<job>/ — slimmed, but only provably so.

RUN THIS ON THE BOX. It turns an accepted output/json/<job>.json into the two files the replay
gate needs, and it keeps the fixture small enough that committing one per pack is not a
permanent cost to the repository:

    python tools\\freeze_replay_fixture.py 7332-01 ^
        --accepted-run "the 14:17 pack, 7 Sep" ^
        --accepted-by "J Gray" --accepted-on 2026-09-07 ^
        --unit 80.09 --material 40.89 --labour 33.59 --quantity 6

WHY A SLIMMED FIXTURE IS SAFE HERE, AND HOW THAT IS ESTABLISHED RATHER THAN ASSUMED. A fixture
quietly missing a field the gate needs would weaken the gate while every push still reported
green — a smaller file that has stopped gating, which is the failure mode this whole harness
exists to prevent. So nothing is dropped because it looks unimportant.

The tool computes a STRUCTURAL FINGERPRINT by running the same reads all three tiers run — the
costed lines, the outstanding tally, both RENDERED deliverables, the workbook canonicalisation,
the compiled route decisions and the re-costed material figures — against the complete record,
then against each candidate reduction. A reduction is accepted ONLY if its fingerprint is
byte-identical. Anything refused is named, so "this is big and we are keeping it" is a visible
decision rather than a silent one.

TWO THINGS HERE WERE WRONG IN THE FIRST VERSION AND ARE WORTH KEEPING ON THE RECORD, because
both produced confident output that was false:

  · It guessed where the weight lived, with a hardcoded list of keys ("text", "raw_text",
    "page_text", ...). On the real 7332-01 record not one matched: it attempted no reduction at
    all and reported "dropped: nothing" on a 7.8 MB file. Heavy paths are now MEASURED.
  · It wrote the fixture with indent=1, turning that 7.8 MB record into an 11.5 MB fixture — a
    tool for keeping files small that made one 47% bigger, which is the single number it exists
    to move. Output is now compact.

And the fingerprint itself had a hole its own test found: drawn only from the costed record, it
approved dropping every part's review_flags and the whole `pages` list, because no costed-line
field changed. Tier 1 RENDERS both deliverables and the forbidden-names check reads that HTML —
the flags ARE the audit trail it reads. Both builders were verified deterministic before being
relied on; if one ever embeds a clock, every reduction is refused rather than wrongly taken,
which is the right way round to fail.

The fingerprint is written beside the fixture as fingerprint.json, so the next freeze of the
same pack can show what moved.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

REPLAY = ROOT / "tests" / "replay"

# WHERE THE WEIGHT IS, IS DISCOVERED — NOT GUESSED. The first version carried a hardcoded list
# of keys it expected the bulk to live under ("text", "raw_text", "page_text", ...). On the real
# 7332-01 record not one of them matched: the tool attempted no reduction at all and reported
# "dropped: nothing" on a 7.8 MB file. A guess about another team's data shape is not a
# reduction strategy, so the record is now walked and the heaviest paths are found by measuring.
MIN_CANDIDATE_BYTES = 50_000      # below this a path is not worth a fingerprint run
MAX_CANDIDATES = 20               # bounded: each candidate costs one full re-fingerprint


def _encode(obj: Any) -> bytes:
    """Compact and key-sorted. Compact because the FIXTURE IS THE POINT: the first version
    wrote indent=1 and turned a 7.8 MB record into an 11.5 MB fixture — a tool for keeping
    files small that made one 47% bigger. Sorted so two freezes of one pack diff."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _size(obj: Any) -> int:
    return len(_encode(obj))


def _heavy_paths(record: Any) -> List[Tuple[str, int]]:
    """[(path, bytes)] for every subtree big enough to be worth dropping, heaviest first.

    Paths are normalised with list indices collapsed — "pages[].page_analysis" rather than
    "pages[7].page_analysis" — so one candidate covers the same field on all 25 pages. A
    parent and its children both appear; the caller drops largest-first and skips anything
    already inside something it removed.
    """
    totals: Dict[str, int] = {}

    def walk(node: Any, path: str, depth: int) -> None:
        if depth > 6:
            return
        if isinstance(node, str):
            if len(node) >= 1_000:
                totals[path] = totals.get(path, 0) + len(node)
            return
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else str(key)
                if isinstance(value, (dict, list)) and _size(value) >= MIN_CANDIDATE_BYTES:
                    totals[child] = totals.get(child, 0) + _size(value)
                walk(value, child, depth + 1)
            return
        if isinstance(node, list):
            for item in node:
                walk(item, f"{path}[]", depth + 1)

    walk(record, "", 0)
    return sorted(((p, n) for p, n in totals.items() if n >= MIN_CANDIDATE_BYTES),
                  key=lambda pair: -pair[1])


def _blank_path(record: Any, path: str) -> Any:
    """A copy of the record with everything at `path` emptied (string -> "", container -> same
    empty container, so a reader that iterates it still finds the shape it expects)."""
    out = copy.deepcopy(record)
    steps = [s for s in path.replace("[]", "").split(".") if s]
    want_list = path.endswith("[]") or "[]" in path

    def descend(node: Any, index: int) -> None:
        if isinstance(node, list):
            for item in node:
                descend(item, index)
            return
        if not isinstance(node, dict) or index >= len(steps):
            return
        key = steps[index]
        if key not in node:
            return
        if index == len(steps) - 1:
            value = node[key]
            if isinstance(value, str):
                node[key] = ""
            elif isinstance(value, list):
                node[key] = []
            elif isinstance(value, dict):
                node[key] = {}
            return
        descend(node[key], index + 1)

    descend(out, 0)
    _ = want_list
    return out


def _num(value: Any) -> Optional[float]:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _fingerprint(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the three replay tiers actually assert on, in one comparable structure.

    Deliberately derived by CALLING the same code the tiers call, not by copying fields: a
    fingerprint assembled from a hand-written field list would miss exactly the field somebody
    added a reader for, which is the failure this guards against.
    """
    out: Dict[str, Any] = {}

    # tier 1 — the costed record and the shared tally
    import costed_facts as cf
    record = cf.costed_job(copy.deepcopy(summary))
    lines = [l for l in (record.get("lines") or []) if isinstance(l, dict)]
    out["lines"] = sorted(
        [{"part_number": str(l.get("part_number") or "").upper(),
          "qty_per_unit": _num(l.get("qty_per_unit")),
          "kind": str(l.get("kind") or ""),
          "operations": sorted(str(o).lower() for o in (l.get("operations") or [])),
          "charged_unit_gbp": _num(l.get("charged_unit_gbp")),
          "engine_unit_gbp": _num(l.get("engine_unit_gbp")),
          "price_firmness": str((l.get("price_origin") or {}).get("firmness") or ""),
          } for l in lines],
        key=lambda r: r["part_number"])
    tally = cf.outstanding_summary(copy.deepcopy(summary)) or {}
    out["tally"] = {k: tally.get(k) for k in sorted(tally)
                    if isinstance(tally.get(k), (int, float, str, type(None)))}
    out["removed_identities"] = sorted(str(x).upper() for x in cf.removed_identities(summary))
    out["canonical_nodes"] = sorted(str(x).upper() for x in cf._canonical_nodes(summary))

    # tier 1 also RENDERS both deliverables, and the forbidden-names check reads the rendered
    # HTML. A fingerprint drawn only from the costed record is blind to everything the renderers
    # read and nothing else does — and this was not theoretical: without these two digests the
    # reducer cheerfully dropped `pages` and every part's `review_flags`, because no costed-line
    # field changed. The flags ARE the audit trail the forbidden-names check reads. Both
    # builders were verified deterministic (same record, same digest) before being relied on;
    # if one ever embeds a clock, every reduction will be refused rather than wrongly taken,
    # which is the right way round to fail.
    for name, build in (("report_html", "job_report_html.build_report_html"),
                        ("quote_html", "client_quote_html.build_quote_html")):
        try:
            module_name, func_name = build.rsplit(".", 1)
            module = __import__(module_name)
            html = getattr(module, func_name)(copy.deepcopy(summary)) or ""
            out[name] = hashlib.sha256(str(html).encode("utf-8")).hexdigest()
        except Exception as err:                                         # noqa: BLE001
            out[name] = f"ERROR {type(err).__name__}: {err}"

    # tier 2 — the workbook canonicalisation stage
    raw = [p for p in ((summary.get("estimate_summary") or {}).get("part_estimates") or [])
           if isinstance(p, dict)]
    try:
        import wb_populate
        canon = wb_populate.canonicalise_part_estimates_for_workbook(
            copy.deepcopy(summary), copy.deepcopy(raw))
        out["canonicalised"] = sorted({str(p.get("part_number") or "").strip().upper()
                                       for p in canon if isinstance(p, dict)} - {""})
    except Exception as err:                                             # noqa: BLE001
        out["canonicalised"] = f"ERROR {type(err).__name__}: {err}"

    # tier 3 — routing re-derived, and material re-costed
    try:
        import route_compiler
        doc = summary.get("document_analysis") or {}
        compiled = route_compiler.compile_job_route(
            copy.deepcopy(raw),
            llm_extract=summary.get("llm_extract") or {},
            bom_rows=doc.get("bom_rows") or [])
        out["route_decisions"] = sorted(
            f"{str(d.get('part_number') or d.get('target_id') or '').upper()}"
            f"|{str(d.get('operation') or '').lower()}"
            f"|{str(d.get('status') or '').lower()}"
            for d in (compiled.get("decisions") or []) if isinstance(d, dict))
    except Exception as err:                                             # noqa: BLE001
        out["route_decisions"] = f"ERROR {type(err).__name__}: {err}"

    try:
        import estimator
        costs = {}
        for part in raw:
            pn = str(part.get("part_number") or "").upper()
            if not pn:
                continue
            try:
                fresh = estimator.estimate_material(copy.deepcopy(part)) or {}
                costs[pn] = _num(fresh.get("unit_material_cost_gbp"))
            except Exception as err:                                     # noqa: BLE001
                costs[pn] = f"ERROR {type(err).__name__}"
        out["material_recosted"] = {k: costs[k] for k in sorted(costs)}
    except Exception as err:                                             # noqa: BLE001
        out["material_recosted"] = f"ERROR {type(err).__name__}: {err}"

    return out


def _digest(fingerprint: Dict[str, Any]) -> str:
    blob = json.dumps(fingerprint, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ── the reduction pass ────────────────────────────────────────────────────────────────


def reduce_record(full: Dict[str, Any], base_digest: str,
                  log=print) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """(smallest record that fingerprints identically, what was dropped, what was refused).

    Greedy and cumulative, heaviest path first. Each candidate is blanked on top of what has
    already been accepted and the WHOLE fingerprint is recomputed; it is kept only if the
    digest is unchanged. So every byte removed has been shown not to alter a single thing the
    three replay tiers assert on, and a path that does matter is refused by name rather than
    quietly taken.
    """
    candidates = _heavy_paths(full)
    if not candidates:
        log("   nothing in this record is large enough to be worth dropping")
        return full, [], []

    log(f"   heaviest paths in the record (top {min(len(candidates), MAX_CANDIDATES)} of "
        f"{len(candidates)}):")
    for path, size in candidates[:MAX_CANDIDATES]:
        log(f"       {size / 1_048_576:6.2f} MB  {path}")
    if len(candidates) > MAX_CANDIDATES:
        skipped = sum(n for _, n in candidates[MAX_CANDIDATES:])
        log(f"   ... {len(candidates) - MAX_CANDIDATES} further path(s) totalling "
            f"{skipped / 1_048_576:.2f} MB NOT attempted (candidate cap)")

    current = full
    dropped: List[str] = []
    refused: List[str] = []
    for path, size in candidates[:MAX_CANDIDATES]:
        if any(path.startswith(d + ".") or path == d for d in dropped):
            continue                                  # already inside something removed
        trial = _blank_path(current, path)
        if _size(trial) >= _size(current):
            continue                                  # nothing actually came out
        if _digest(_fingerprint(trial)) == base_digest:
            current = trial
            dropped.append(path)
            log(f"   drop {path:52s} -{size / 1_048_576:5.2f} MB  fingerprint identical")
        else:
            refused.append(path)
            log(f"   KEEP {path:52s}  a tier reads this — fingerprint changed")
    return current, dropped, refused


def freeze(job: str, source: Path, provenance: Dict[str, Any],
           force_full: bool = False) -> int:
    target_dir = REPLAY / job
    if not target_dir.is_dir():
        print(f"!! {target_dir} does not exist — is '{job}' the right job name?")
        return 2
    if not (target_dir / "accepted_facts.json").is_file():
        print(f"!! {target_dir}/accepted_facts.json is missing. The accepted STRUCTURE is an "
              f"estimator-reviewed file and this tool will not invent one.")
        return 2

    full = json.loads(source.read_text(encoding="utf-8"))
    full_bytes = _size(full)
    print(f"   source: {source}  ({source.stat().st_size / 1_048_576:.1f} MB on disk, "
          f"{full_bytes / 1_048_576:.1f} MB compact)")

    print("   computing the structural fingerprint of the complete record ...")
    base = _fingerprint(full)
    base_digest = _digest(base)
    print(f"   fingerprint {base_digest[:16]}  "
          f"({len(base.get('lines') or [])} costed lines, "
          f"{len(base.get('route_decisions') or [])} route decisions)")
    for key in ("canonicalised", "route_decisions", "material_recosted"):
        if isinstance(base.get(key), str) and base[key].startswith("ERROR"):
            print(f"   !! tier reading '{key}' errored on the FULL record: {base[key]}")
            print(f"      Freezing anyway — the fixture is honest about what the code does "
                   "today — but expect that tier to fail until it is fixed.")

    chosen, dropped_paths, refused_paths = full, [], []
    if force_full:
        print("   --full given: no reduction attempted")
    else:
        chosen, dropped_paths, refused_paths = reduce_record(full, base_digest)

    # COMPACT. Not cosmetics: this is the one number the tool exists to move.
    summary_path = target_dir / "summary.json"
    summary_path.write_bytes(_encode(chosen))
    final_bytes = summary_path.stat().st_size
    saved = full_bytes - final_bytes
    verb = "saved" if saved >= 0 else "LARGER by"
    print(f"   wrote {summary_path}  ({final_bytes / 1_048_576:.2f} MB — "
          f"{verb} {abs(saved) / 1_048_576:.2f} MB vs the full record)")
    if final_bytes > 5_000_000:
        print(f"   !! this fixture is still {final_bytes / 1_048_576:.1f} MB. The refused paths "
              f"above are read by a tier, so they cannot come out without weakening the gate. "
              f"Commit it as-is; if the size becomes a problem the answer is a narrower tier, "
              f"not a quieter fixture.")

    provenance = dict(provenance)
    provenance["job"] = job
    provenance["source_path"] = str(source)
    provenance["fixture"] = {
        "dropped": dropped_paths,
        "kept_because_a_tier_reads_it": refused_paths,
        "full_record_bytes": full_bytes,
        "fixture_bytes": final_bytes,
        "structural_fingerprint": base_digest,
        "_note": ("The reduction was accepted only because the structural fingerprint of the "
                  "reduced record is byte-identical to the complete record's. Nothing was "
                  "dropped on the reasoning that it 'is not read'."),
    }
    (target_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"   wrote {target_dir / 'provenance.json'}")
    (target_dir / "fingerprint.json").write_text(
        json.dumps(base, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print(f"   wrote {target_dir / 'fingerprint.json'}  (what the next freeze is compared to)")

    print()
    print("   Now, from the repository root:")
    print(f"       git add tests/replay/{job}")
    print(f'       git commit -m "Freeze the accepted {job} record"')
    print("       git push -u origin main-2026")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job", help="the job name, matching the tests/replay/<job> directory")
    ap.add_argument("--source", default="",
                    help="path to the accepted record (default output/json/<job>.json)")
    ap.add_argument("--accepted-run", required=True,
                    help='which run this is, e.g. "the 14:17 pack, 7 Sep"')
    ap.add_argument("--accepted-by", required=True, help="who signed it off")
    ap.add_argument("--accepted-on", required=True, help="YYYY-MM-DD")
    ap.add_argument("--unit", type=float, default=None, help="accepted unit price")
    ap.add_argument("--material", type=float, default=None, help="accepted material")
    ap.add_argument("--labour", type=float, default=None, help="accepted labour")
    ap.add_argument("--quantity", type=int, default=None, help="quantity it was settled at")
    ap.add_argument("--notes", default="", help="anything a reader would have to ask")
    ap.add_argument("--full", action="store_true",
                    help="skip every reduction and freeze the complete record")
    args = ap.parse_args(argv)

    source = Path(args.source) if args.source else (ROOT / "output" / "json" / f"{args.job}.json")
    if not source.is_file():
        print(f"!! {source} not found. Pass --source with the path to the accepted record.")
        return 2

    provenance: Dict[str, Any] = {
        "accepted_run": args.accepted_run,
        "accepted_by": args.accepted_by,
        "accepted_on": args.accepted_on,
        "notes": args.notes,
    }
    money = {k: v for k, v in (("unit_gbp", args.unit), ("material_gbp", args.material),
                               ("labour_gbp", args.labour), ("quantity", args.quantity))
             if v is not None}
    if money:
        money["_note"] = ("Recorded for the Windows Excel/read-back reconciliation ONLY. The "
                          "fast replay layer pins structure and never money.")
        provenance["accepted_numbers"] = money

    print(f"== freezing {args.job} ==")
    return freeze(args.job, source, provenance, force_full=bool(args.full))


if __name__ == "__main__":
    raise SystemExit(main())
