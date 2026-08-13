r"""where_did_this_fact_come_from.py — which source set this datum, what it beat, and on what build.

WHY THIS EXISTS. 11650-04's side panels came out as two handed pairs that disagreed with their
own bases:

    11650-04-01A         ABS   2.2mm  GBP 175.01/sheet
    11650-04-01A-HANDED  ABS   2.0mm  GBP 244.97/sheet     material inherited, gauge did not
    11650-04-03A         ABS   2.2mm  GBP 175.01/sheet
    11650-04-03A-HANDED  PETG  2.0mm  GBP 114.98/sheet     neither inherited

Material and thickness are written by the SAME loop through the SAME resolver, so one moving
without the other is not a possible outcome of that loop — which means the question is not
"why did the loop behave differently", it is "did the loop run at all, on this build". Nothing
on the record or the console answered that, so the next fix was about to be aimed by guesswork.

why_this_price.py answers "why is this line this price". This answers the question underneath
it: for each datum the price turns on, WHO said it, what rank that source holds, what it
overwrote, and whether anything independent disagreed. Plus the commit the engine was running,
because "the fix is not live" and "the fix does not work" look identical on a spreadsheet and
lead opposite ways.

    python tools\diagnose\where_did_this_fact_come_from.py 11650-04-01A-HANDED
    python tools\diagnose\where_did_this_fact_come_from.py 11650-04-01A 11650-04-01A-HANDED --json <path>
    python tools\diagnose\where_did_this_fact_come_from.py --mirrors      # every handed part in the job

IT KNOWS NO FIELD NAMES IT DOES NOT HAVE TO. The fields it reports are the ones
source_precedence arbitrates, read from that module — not a list typed here that goes stale the
first time a fourth field joins them. The source keys are asked of source_precedence too,
because three of them are NOT "<field>_source" and a reader that assumed the convention would
report "no source" for material, quantity and thickness — the three that matter most.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import source_precedence as sp  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]

# EVERY DATUM THE RESOLVER ARBITRATES, TAKEN FROM THE RESOLVER. Typed out here it would go
# stale the first time a fourth field joined them, and the tool would then print a complete-
# looking report with one of them missing -- an absence reported as a clean answer, in the tool
# built to stop exactly that.
_ARBITRATED = list(sp._SOURCE_FIELDS)
_GEOMETRY = ["blank_length_mm", "blank_width_mm", "overall_length_mm", "overall_width_mm",
             "cut_length_mm", "hole_count", "fold_count"]


def _newest_job_json(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit)
    import config
    candidates: List[str] = []
    for pattern in ("json/*.json", "estimates/*.json"):
        candidates += glob.glob(str(Path(config.OUTPUT_DIR) / pattern))
    candidates = [c for c in candidates if "llm_extract" not in os.path.basename(c).lower()]
    if not candidates:
        raise SystemExit(f"No job JSON under {config.OUTPUT_DIR}. Pass --json <path>.")
    return Path(max(candidates, key=os.path.getmtime))


def _parts(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """part_estimates, wherever this document keeps them. Some writers stamp the estimate on
    the root and some inside estimate_summary; a reader that looks in one place reports
    "no such part" on every job of the other shape."""
    for holder in (doc.get("estimate_summary"), doc):
        if isinstance(holder, dict):
            pes = holder.get("part_estimates")
            if isinstance(pes, list) and pes:
                return [p for p in pes if isinstance(p, dict)]
    return []


def _engine_build() -> str:
    """Which commit this checkout is on, and whether it is dirty.

    THE POINT OF THE WHOLE TOOL, ON ONE LINE. A fix that is not deployed and a fix that does
    not work produce the same spreadsheet. This is printed even when it cannot be determined,
    because an unknown build stated is worth more than an assumed one.
    """
    def _git(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(["git", "-C", str(_REPO), *args],
                                 capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    sha = _git("rev-parse", "--short", "HEAD")
    if not sha:
        return "engine build: UNKNOWN (not a git checkout, or git unavailable)"
    subject = _git("log", "-1", "--format=%s") or ""
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    dirty = _git("status", "--porcelain")
    state = " + UNCOMMITTED CHANGES" if dirty else ""
    return f"engine build: {sha} on {branch}{state}\n              {subject}"


def _rows_for(part: Dict[str, Any], fields: List[str]) -> List[str]:
    out: List[str] = []
    for field in fields:
        value = sp.value_of(part, field)
        if value is sp.MISSING:
            value_txt = "-- not set --"
        else:
            value_txt = str(value)
        source = sp.source_of(part, field) or ""
        rank = sp.rank(source) if source else 0
        # An absent source is not a source named "": say which, because rank 0 from a source
        # nobody recorded and rank 0 from a source nobody recognises are different bugs.
        if not source:
            src_txt = "(no source recorded)"
        else:
            src_txt = f"{sp.display_name(source)}  rank {rank}"
            if sp.was_measured(source):
                src_txt += "  [measured]"
        out.append(f"    {field:<28} {value_txt:<22} {src_txt}")
        for entry in sp.displaced_values(part, field):
            out.append(f"        displaced: {str(entry.get('value')):<18} "
                       f"by/from {entry.get('source') or '?'}"
                       + (f"  — {entry.get('note')}" if entry.get("note") else ""))
        against = sp.corroboration_against(part, field)
        if against.get("count"):
            out.append(f"        AGAINST IT: {against['count']} independent source(s) said "
                       f"{against['value']} — {', '.join(against['sources'])}")
    return out


def _mirror_evidence(part: Dict[str, Any]) -> List[str]:
    """Anything on this record that says a mirror rule touched it.

    Found by walking the record for keys that mention mirroring, not by naming the three keys
    the rule happens to write today. A tool that named them would report "no mirror provenance"
    the moment the rule started recording it somewhere else — which is precisely the failure it
    is here to rule out.
    """
    hits: List[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                here = f"{path}.{k}" if path else str(k)
                if "mirror" in str(k).lower() and not isinstance(v, (dict, list)):
                    hits.append(f"    {here} = {v}")
                walk(v, here)
        elif isinstance(node, list):
            for i, v in enumerate(node[:50]):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and "mirror" in node.lower() and len(node) < 200:
            hits.append(f"    {path} = {node}")

    walk(part, "")
    return hits


def _report(part: Dict[str, Any]) -> str:
    pn = part.get("part_number") or "(unnamed)"
    roles = part.get("page_roles") or []
    roles = roles if isinstance(roles, list) else [roles]
    me = part.get("material_estimate") if isinstance(part.get("material_estimate"), dict) else {}
    stock = me.get("stock_estimate") if isinstance(me.get("stock_estimate"), dict) else {}

    lines = [f"\n{'=' * 78}", f"{pn}", f"{'=' * 78}",
             f"  page_roles: {', '.join(str(r) for r in roles) or '(none)'}",
             f"  cost_method: {me.get('cost_method') or '(none)'}"
             f"   parts/sheet: {me.get('parts_per_sheet') or stock.get('parts_per_sheet')}"
             f"   rule: {me.get('nesting_rule') or stock.get('nesting_rule') or '(none)'}",
             "",
             "  ARBITRATED FACTS — who said it, and what they beat:"]
    lines += _rows_for(part, _ARBITRATED)
    lines += ["", "  GEOMETRY:"]
    lines += _rows_for(part, _GEOMETRY)

    evidence = _mirror_evidence(part)
    lines += ["", "  MIRROR PROVENANCE:"]
    if evidence:
        lines += evidence
    else:
        # AN ABSENCE, REPORTED AS AN ABSENCE. "Nothing found" and "the rule did not run" are
        # the same observation here, and saying which is not this tool's job — saying that
        # neither can be ruled out is.
        lines += ["    NOTHING on this record says a mirror rule touched it.",
                  "    Either apply_mirror_geometry never fired for this part, or it fired and",
                  "    recorded nothing. Check the source ranks above: a field carrying",
                  "    'mirror_of_measured' was inherited; one carrying 'llm_extract' or no",
                  "    source at all was read (or guessed) independently of its base."]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("part_numbers", nargs="*", help="part numbers to explain")
    ap.add_argument("--json", dest="json_path", default=None, help="job JSON (default: newest)")
    ap.add_argument("--mirrors", action="store_true",
                    help="every part whose number carries a hand, plus the base it mirrors")
    args = ap.parse_args(argv)

    path = _newest_job_json(args.json_path)
    doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    parts = _parts(doc)

    print(_engine_build())
    print(f"job JSON:     {path}")
    print(f"parts:        {len(parts)}")

    wanted = [str(p).strip().upper() for p in args.part_numbers]
    if args.mirrors:
        # THE ENGINE'S OWN ANSWER to "is this a hand, and of what". A second opinion here would
        # be a second convention, and a tool that disagreed with the merge about which parts
        # are handed would be diagnosing a different job.
        from part_code_conventions import mirror_base
        for p in parts:
            pn = str(p.get("part_number") or "")
            base = mirror_base(pn)
            if base:
                for name in (pn, base):
                    if name.upper() not in wanted:
                        wanted.append(name.upper())
        if not wanted:
            print("\nNo part in this job carries a hand suffix.")
            return 0

    if not wanted:
        ap.error("name at least one part, or pass --mirrors")

    index = {str(p.get("part_number") or "").strip().upper(): p for p in parts}
    missing = [w for w in wanted if w not in index]
    for w in wanted:
        if w in index:
            print(_report(index[w]))
    if missing:
        # NOT SILENCE. A part number that is not in the job is an answer, and it is often THE
        # answer — a handed part the merge never created looks exactly like one it did.
        print(f"\nNOT IN THIS JOB: {', '.join(missing)}")
        print("  Nothing costed these, so nothing can explain them. If a hand is missing here")
        print("  and present on the spreadsheet, the two came from different runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
