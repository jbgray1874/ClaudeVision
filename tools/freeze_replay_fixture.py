"""Freeze an accepted run into tests/replay/<job>/ — the right run, and provably slimmed.

RUN THIS ON THE BOX. Start by asking what records exist, rather than hunting for a path:

    python tools\\freeze_replay_fixture.py 7332-01 --find

That lists every saved record for the job with the date EACH ONE SAYS it ran. Pick the accepted
one and freeze it:

    python tools\\freeze_replay_fixture.py 7332-01 --source output\\archive\\7332-01_accepted.json ^
        --accepted-run "the 14:17 pack, 7 Sep" ^
        --accepted-by "J Gray" --accepted-on 2026-09-07 ^
        --unit 80.09 --material 40.89 --labour 33.59 --quantity 6

(Every example here is a real path, never a <placeholder>: PowerShell treats < as a redirect
operator and fails to parse the line before python ever sees it.)

THE FIRST THING THIS DOES IS CHECK THE RECORD IS THE RUN YOU SAY IT IS, AND IT LEADS BECAUSE IT
IS THE MOST IMPORTANT THING HERE. The first version took --accepted-on, --accepted-run and the
accepted numbers from the command line and wrote them into provenance without ever opening the
record. The 7332-01 fixture produced that way was labelled "the 14:17 pack, 7 Sep" while the
record inside it carried processed_at of 10 September 18:59 — a different run, wearing the
accepted baseline's numbers. Nothing lied; the tool transcribed an assertion and presented it as
provenance.

A baseline whose label and content disagree is worse than no baseline: every later comparison
runs against something other than what it claims and nobody can tell. So the record's own
processed_at, which json_normaliser stamps at run time and is therefore evidence rather than
assertion, is compared against the asserted date, and a mismatch STOPS the freeze with nothing
written. Typing an older date does not make the input that run. If a newer run genuinely is the
new baseline that is a legitimate decision — pass --accept-new-baseline and the record's own
date is recorded, never the one typed.

Note also that output/json/<job>.json is REWRITTEN by the next run of that job. A provenance
entry pointing there names a path whose contents will not be what was frozen, so the tool warns
and you should pass --source pointing at an archived copy.

CONTENT REDUCTION IS OPT-IN (--reduce). Compact formatting is safe arithmetic and is always
applied; removing content is a claim about what every reader needs, now and later, and it is
worth far less than a correct baseline. Saving megabytes comes a distant second to the fixture
being the run it says it is.

WHY A SLIMMED FIXTURE IS SAFE WHEN YOU DO ASK FOR IT. A fixture quietly missing a field the gate
needs would weaken the gate while every push still reported green — a smaller file that has
stopped gating, which is the failure mode this whole harness exists to prevent. So nothing is
dropped because it looks unimportant.

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

AND EQUALITY PROVES EQUIVALENCE FOR TODAY'S CHECKS ONLY. A reader added next month may need a
field this fingerprint never looked at. That is why the source's sha256 and byte count go into
provenance: the full record must stay archived, and the fixture is a convenience derived from it
rather than a replacement for it. If any fingerprint stage ERRORS, no reduction is attempted at
all — two identical error strings are two failures agreeing with each other, not evidence that
removing data is safe.

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
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


def _record_identity(record: Dict[str, Any]) -> Dict[str, Any]:
    """What the RECORD says about itself: when it ran, and anything version-shaped.

    `processed_at` is stamped by json_normaliser at run time, so it is evidence rather than
    assertion — it says when this run happened whatever anybody types on the command line.
    """
    out: Dict[str, Any] = {"processed_at": record.get("processed_at") or "",
                           "schema": record.get("schema") or ""}
    for key, value in record.items():
        if isinstance(value, (str, int, float)) and "version" in str(key).lower():
            out[str(key)] = value
    for holder in ("run", "meta", "metadata"):
        block = record.get(holder)
        if isinstance(block, dict):
            for key, value in block.items():
                if isinstance(value, (str, int, float)) and (
                        "version" in str(key).lower() or "processed" in str(key).lower()
                        or str(key).lower() in ("run_id", "started_at", "finished_at")):
                    out[f"{holder}.{key}"] = value
    return out


def verify_provenance(record: Dict[str, Any], asserted_on: str) -> Tuple[bool, str, str]:
    """(does the record's own timestamp support the asserted acceptance date, its date, why).

    THE DEFECT THIS EXISTS FOR. The first version of this tool took --accepted-on, --accepted-run
    and the accepted numbers straight from the command line and wrote them into provenance
    without ever looking at the record. The 7332-01 fixture was therefore labelled "the 14:17
    pack, 7 Sep" while the record it contained carried processed_at of 10 September 18:59 — a
    different run entirely, stamped with the accepted baseline's numbers. Nothing was lying;
    the tool simply transcribed an assertion and presented it as provenance.

    A baseline whose label and content disagree is worse than no baseline: every later
    comparison is against something other than what it claims, and nobody can tell. So the
    record's own stamp is now compared against the asserted date, and a mismatch stops the
    freeze. Typing an older date does not make the input that run.
    """
    stamp = str(record.get("processed_at") or "").strip()
    if not stamp:
        return False, "", ("the record carries no processed_at, so nothing here can confirm "
                           "which run it is")
    record_date = stamp[:10]
    asserted = str(asserted_on or "").strip()[:10]
    if not asserted:
        return False, record_date, "no --accepted-on given"
    if record_date == asserted:
        return True, record_date, ""
    return False, record_date, (
        f"the record says it ran on {record_date} ({stamp}) but --accepted-on says {asserted}. "
        f"These are different runs. Either point --source at the archived JSON of the run that "
        f"was actually accepted, or — if this newer run IS the new baseline — review it and pass "
        f"its own date with --accept-new-baseline")


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


def _fingerprint_errors(fingerprint: Dict[str, Any]) -> List[str]:
    """Which stages did not actually run.

    WHY THIS GATES THE REDUCTION. _fingerprint() turns a stage exception into the STRING
    "ERROR TypeError: ...". Two such strings compare equal, so a stage that fails on the full
    record and fails identically on a reduced one reads as "fingerprint identical" — and data
    would be removed on the strength of two failures agreeing with each other. Two identical
    errors are not evidence that removing data is safe. Any errored stage now stops reduction
    outright and is recorded, so the fixture is full and the reason is on the file.
    """
    return sorted(key for key, value in fingerprint.items()
                  if isinstance(value, str) and value.startswith("ERROR"))


def freeze(job: str, source: Path, provenance: Dict[str, Any],
           force_full: bool = False, reduce_content: bool = False,
           accept_new_baseline: bool = False) -> int:
    target_dir = REPLAY / job
    if not target_dir.is_dir():
        print(f"!! {target_dir} does not exist — is '{job}' the right job name?")
        return 2
    if not (target_dir / "accepted_facts.json").is_file():
        print(f"!! {target_dir}/accepted_facts.json is missing. The accepted STRUCTURE is an "
              f"estimator-reviewed file and this tool will not invent one.")
        return 2

    source_bytes = source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    full = json.loads(source_bytes.decode("utf-8"))
    full_bytes = _size(full)
    print(f"   source: {source}  ({len(source_bytes) / 1_048_576:.1f} MB on disk, "
          f"{full_bytes / 1_048_576:.1f} MB compact)")
    print(f"   sha256: {source_sha}")
    # output/json/<job>.json is REWRITTEN by the next run of that job, so a provenance entry
    # pointing at it names a path whose contents will not be what was frozen.
    if source.parent.name == "json" and source.parent.parent.name == "output":
        print(f"   !! this is the overwriteable run output, not an archive. The next run of "
              f"{job} replaces it, so source_path will point at different content. Archive the "
              f"accepted record and pass --source that copy.")

    # ── IDENTITY BEFORE ANYTHING ELSE ──────────────────────────────────────────
    identity = _record_identity(full)
    print(f"   the record says about itself:")
    for key in sorted(identity):
        if identity[key] not in ("", None):
            print(f"       {key} = {identity[key]}")
    ok, record_date, why = verify_provenance(full, provenance.get("accepted_on", ""))
    if not ok and not accept_new_baseline:
        print()
        print(f"!! REFUSING TO FREEZE — the record does not match the provenance asserted.")
        print(f"   {why}")
        print()
        print(f"   A baseline whose label and content disagree is worse than no baseline: every")
        print(f"   later comparison is against something other than what it claims, and nobody")
        print(f"   can tell. Nothing has been written.")
        return 3
    if not ok and accept_new_baseline:
        print(f"   --accept-new-baseline: recording this run's OWN date ({record_date}), not "
              f"the one asserted")
        provenance["accepted_on"] = record_date
        provenance["baseline_change"] = (
            f"Accepted as a NEW baseline. The record ran on {record_date}; it is not the "
            f"earlier accepted run.")

    print("   computing the structural fingerprint of the complete record ...")
    base = _fingerprint(full)
    base_digest = _digest(base)
    print(f"   fingerprint {base_digest[:16]}  "
          f"({len(base.get('lines') or [])} costed lines, "
          f"{len(base.get('route_decisions') or [])} route decisions)")
    errors = _fingerprint_errors(base)
    for key in errors:
        print(f"   !! stage '{key}' ERRORED on the full record: {base[key]}")

    chosen, dropped_paths, refused_paths = full, [], []
    reduction_note = "none attempted — content is reduced only with --reduce"
    if force_full:
        reduction_note = "none attempted (--full)"
        print("   --full given: no reduction attempted")
    elif errors:
        reduction_note = (f"REFUSED: stage(s) {errors} errored, so fingerprint equality would "
                          f"only mean two failures agreed")
        print(f"   reduction REFUSED: a stage errored, so equal fingerprints would only prove "
              f"two failures agree. Freezing the full record.")
    elif not reduce_content:
        print("   compact formatting only. Pass --reduce to attempt content reduction "
              "(each dropped path is fingerprint-verified and named).")
    else:
        chosen, dropped_paths, refused_paths = reduce_record(full, base_digest)
        reduction_note = "fingerprint-verified path removal"

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
    provenance["record_says_about_itself"] = identity
    provenance["fixture"] = {
        "reduction": reduction_note,
        "dropped": dropped_paths,
        "kept_because_a_tier_reads_it": refused_paths,
        "fingerprint_stages_that_errored": errors,
        "source_sha256": source_sha,
        "source_bytes_on_disk": len(source_bytes),
        "full_record_bytes": full_bytes,
        "fixture_bytes": final_bytes,
        "structural_fingerprint": base_digest,
        "_note": ("Any path dropped was dropped only because the structural fingerprint of the "
                  "reduced record is byte-identical to the complete record's, over all three "
                  "tiers INCLUDING both rendered deliverables. Nothing was dropped on the "
                  "reasoning that it 'is not read'. Fingerprint equality proves equivalence "
                  "for the checks that exist TODAY and not for a future reader, which is why "
                  "source_sha256 is recorded: keep the full record archived."),
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


def find_candidates(job: str, extra_roots: Sequence[Path] = ()) -> int:
    """List every saved record for this job with the date IT says it ran, newest first.

    WHY THIS IS A MODE OF THE TOOL RATHER THAN AN INSTRUCTION TO GO LOOKING. The question "which
    of these is the accepted run?" is answered by the records themselves — each one carries the
    processed_at its own run stamped. Asking somebody to type a path they have to go and hunt
    for invites exactly the mistake this tool now refuses: the nearest plausible file, labelled
    with the date we wished it had. Run this, read the dates, then pass the one you mean.

    Nothing here decides which record is accepted. It reports what exists and what each one
    says about itself; choosing is a person's job and recording that choice is the freeze.
    """
    roots = [ROOT / "output" / "json", ROOT / "output", ROOT / "archive",
             ROOT / "output" / "archive", ROOT / "tests" / "replay" / job]
    roots.extend(Path(r) for r in extra_roots)
    seen: Dict[Path, None] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.json")):
            if job.lower().replace("-", "") in path.name.lower().replace("-", ""):
                seen.setdefault(path.resolve(), None)

    if not seen:
        print(f"   no saved record found for {job} under:")
        for root in roots:
            print(f"       {root}{'' if root.is_dir() else '   (does not exist)'}")
        print("   Pass --search with another directory to look there as well.")
        return 1

    rows: List[Tuple[str, Path, int, int]] = []
    for path in seen:
        try:
            raw = path.read_bytes()
            record = json.loads(raw.decode("utf-8"))
        except Exception as err:                                         # noqa: BLE001
            rows.append((f"unreadable: {type(err).__name__}", path, 0, 0))
            continue
        if not isinstance(record, dict):
            rows.append(("not a record (not an object)", path, len(raw), 0))
            continue
        parts = (record.get("estimate_summary") or {}).get("part_estimates") or []
        rows.append((str(record.get("processed_at") or "NO processed_at"),
                     path, len(raw), len(parts) if isinstance(parts, list) else 0))

    rows.sort(key=lambda r: r[0], reverse=True)
    print(f"   saved records for {job}, newest first by what each one says about itself:")
    print()
    for stamp, path, size, parts in rows:
        print(f"   {stamp:34s} {size / 1_048_576:6.1f} MB  {parts:3d} parts")
        print(f"   {'':34s} {path}")
    print()
    print("   Pick the one that was ACCEPTED and pass it with --source. A record whose date is")
    print("   not the accepted date will be refused unless you pass --accept-new-baseline,")
    print("   which records that run's own date rather than the one you type.")
    overwriteable = [p for _s, p, _z, _n in rows
                     if p.parent.name == "json" and p.parent.parent.name == "output"]
    if overwriteable:
        print()
        print("   NOTE: these are rewritten by the next run of this job, so archive a copy")
        print("   before freezing and point --source at the archive:")
        for path in overwriteable:
            print(f"       {path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job", help="the job name, matching the tests/replay/<job> directory")
    ap.add_argument("--find", action="store_true",
                    help="list every saved record for this job with the date it says it ran, "
                         "and exit. Use this to choose --source instead of guessing a path")
    ap.add_argument("--search", action="append", default=[], metavar="DIR",
                    help="an extra directory for --find to search (repeatable)")
    ap.add_argument("--source", default="",
                    help="path to the accepted record (default output/json/<job>.json)")
    # Not argparse-required, because --find needs none of them. Checked below instead, so
    # "list what exists" never demands answers about a record you have not seen yet.
    ap.add_argument("--accepted-run", default="",
                    help='which run this is, e.g. "the 14:17 pack, 7 Sep"')
    ap.add_argument("--accepted-by", default="", help="who signed it off")
    ap.add_argument("--accepted-on", default="", help="YYYY-MM-DD")
    ap.add_argument("--unit", type=float, default=None, help="accepted unit price")
    ap.add_argument("--material", type=float, default=None, help="accepted material")
    ap.add_argument("--labour", type=float, default=None, help="accepted labour")
    ap.add_argument("--quantity", type=int, default=None, help="quantity it was settled at")
    ap.add_argument("--notes", default="", help="anything a reader would have to ask")
    ap.add_argument("--reduce", action="store_true",
                    help="attempt fingerprint-verified content reduction. OFF by default: "
                         "compact formatting is safe arithmetic, removing content is a claim "
                         "about what every reader needs and is worth far less than a correct "
                         "baseline")
    ap.add_argument("--full", action="store_true",
                    help="never reduce, whatever else is passed")
    ap.add_argument("--accept-new-baseline", action="store_true",
                    help="the record is a NEWER run than --accepted-on and you are deliberately "
                         "making it the baseline. Its own date is recorded, not the one typed")
    args = ap.parse_args(argv)

    if args.find:
        print(f"== records found for {args.job} ==")
        return find_candidates(args.job, [Path(d) for d in args.search])

    missing = [flag for flag, value in (("--accepted-run", args.accepted_run),
                                        ("--accepted-by", args.accepted_by),
                                        ("--accepted-on", args.accepted_on))
               if not str(value).strip()]
    if missing:
        print(f"!! {', '.join(missing)} required to freeze. To see what records exist and the "
              f"date each one says it ran, run:\n"
              f"       python tools/freeze_replay_fixture.py {args.job} --find")
        return 2

    source = Path(args.source) if args.source else (ROOT / "output" / "json" / f"{args.job}.json")
    if not source.is_file():
        print(f"!! {source} not found. To see what records exist for this job:\n"
              f"       python tools/freeze_replay_fixture.py {args.job} --find")
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
    return freeze(args.job, source, provenance, force_full=bool(args.full),
                  reduce_content=bool(args.reduce) and not bool(args.full),
                  accept_new_baseline=bool(args.accept_new_baseline))


if __name__ == "__main__":
    raise SystemExit(main())
