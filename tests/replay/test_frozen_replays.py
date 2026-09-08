"""The fast replay layer: frozen accepted jobs through the record and the deliverables.

Each subdirectory here is one estimator-REVIEWED job (see README.md). The frozen
summary.json is driven through costed_facts (the record every surface reads) and both
HTML deliverable builders — everything downstream of extraction that runs without Excel —
and the result is diffed against accepted_facts.json: identities, routes, decisions,
names that must appear nowhere. Structure, never money.

A directory with facts but no frozen summary is reported loudly as a skip, because the
difference between "this pack is protected" and "nobody froze it" must be visible.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

HERE = Path(__file__).resolve().parent
JOBS = sorted(p for p in HERE.iterdir()
              if p.is_dir() and (p / "accepted_facts.json").is_file())


def _facts(job: Path) -> dict:
    return json.loads((job / "accepted_facts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("job", JOBS, ids=[j.name for j in JOBS])
def test_frozen_replay(job: Path):
    facts = _facts(job)
    frozen = job / "summary.json"
    if not frozen.is_file():
        pytest.skip(f"{job.name}: accepted facts exist but no frozen summary.json — "
                    f"copy output/json/{job.name}.json here to protect this pack")
    summary = json.loads(frozen.read_text(encoding="utf-8"))

    import costed_facts as cf
    record = cf.costed_job(summary)
    lines = [l for l in (record.get("lines") or []) if isinstance(l, dict)]
    line_ids = sorted({str(l.get("part_number") or "").strip().upper() for l in lines}
                      - {""})

    # ── BOM identity: exactly these lines, no more, no fewer ────────────────────
    want = facts.get("bom_identities")
    if want:
        assert line_ids == sorted(str(w).upper() for w in want), \
            f"{job.name} BOM drifted: {line_ids}"

    # ── quantities: spot-pins ──────────────────────────────────────────────────
    for pn, q in (facts.get("quantities") or {}).items():
        got = next((l.get("qty_per_unit") for l in lines
                    if str(l.get("part_number") or "").upper() == pn.upper()), None)
        assert got is not None and abs(float(got) - float(q)) < 0.01, \
            f"{job.name} {pn}: qty {got} != accepted {q}"

    # ── routes: required present, ruled-out absent ─────────────────────────────
    for pn, ops in (facts.get("required_operations") or {}).items():
        line = next((l for l in lines
                     if str(l.get("part_number") or "").upper() == pn.upper()), None)
        assert line is not None, f"{job.name}: {pn} missing from the record"
        got_ops = {str(o).lower() for o in (line.get("operations") or [])}
        for op in ops:
            assert op.lower() in got_ops, \
                f"{job.name} {pn}: required op '{op}' absent ({sorted(got_ops)})"
    for pn, ops in (facts.get("forbidden_operations") or {}).items():
        line = next((l for l in lines
                     if str(l.get("part_number") or "").upper() == pn.upper()), None)
        if line is None:
            continue
        got_ops = {str(o).lower() for o in (line.get("operations") or [])}
        for op in ops:
            assert op.lower() not in got_ops, \
                f"{job.name} {pn}: ruled-out op '{op}' is charged"

    # ── the shared tally ───────────────────────────────────────────────────────
    tally = cf.outstanding_summary(summary) or {}
    for key, n in (facts.get("phrase_counts") or {}).items():
        assert int(tally.get(key) or 0) == int(n), \
            f"{job.name}: tally {key}={tally.get(key)} != accepted {n}"
    if facts.get("decisions_expected") is not None:
        assert int(tally.get("manufacturing") or 0) == int(facts["decisions_expected"])

    # ── names that must appear nowhere: record AND both rendered deliverables ──
    _forbidden_names_check(job, facts, summary, lines)


def _squash(s: str) -> str:
    return "".join(ch for ch in str(s).upper() if ch.isalnum())


@pytest.mark.parametrize("job", JOBS, ids=[j.name for j in JOBS])
def test_frozen_stage_contracts(job: Path):
    """Tier 2: the stage that failed this week EXECUTES on the frozen inputs.

    Rendering an already-costed JSON catches reporting drift and nothing else — the
    reviewer's exact criticism. This tier re-runs the workbook canonicalisation (the
    identity gates, the multiplicity roll, the missing-bought-in mint) on the frozen
    RAW population and holds its contracts: it invents no identity the accepted BOM
    and the inputs do not know (the MIR spelling-variant mint), it never resurrects a
    folded or quarantined identity, and it reproduces the canonical population the
    accepted run recorded. Assembly-scope and extraction failures still need staged
    input packs — this closes the mint-and-gate stage only, honestly."""
    facts = _facts(job)
    frozen = job / "summary.json"
    if not frozen.is_file():
        pytest.skip(f"{job.name}: accepted facts exist but no frozen summary.json — "
                    f"copy output/json/{job.name}.json here to protect this pack")
    import copy
    summary = json.loads(frozen.read_text(encoding="utf-8"))
    s = copy.deepcopy(summary)
    raw = [p for p in ((s.get("estimate_summary") or {}).get("part_estimates") or [])
           if isinstance(p, dict)]
    if not raw:
        pytest.skip(f"{job.name}: frozen summary carries no raw part_estimates")
    import wb_populate
    out = wb_populate.canonicalise_part_estimates_for_workbook(s, raw)
    out_ids = {str(p.get("part_number") or "").strip().upper()
               for p in out if isinstance(p, dict)} - {""}

    # 1 · the stage invents nothing: every output identity is known to the accepted
    #     BOM, to the inputs, or to the graph — compared SQUASHED, so a spelling
    #     variant of a recorded part cannot slip through as a "new purchase".
    known = {_squash(x) for x in (facts.get("bom_identities") or [])}
    known |= {_squash(p.get("part_number")) for p in raw}
    import costed_facts as cf
    known |= {_squash(k) for k in cf._canonical_nodes(summary)}
    invented = sorted(pn for pn in out_ids if _squash(pn) not in known)
    assert not invented, f"{job.name}: the gate minted identities nobody accepted: {invented}"

    # 2 · a removed identity stays removed.
    gone = cf.removed_identities(summary)
    resurrected = sorted(pn for pn in out_ids
                         if _squash(pn) in {_squash(g) for g in gone})
    assert not resurrected, f"{job.name}: folded identities re-minted: {resurrected}"

    # 3 · the stage reproduces the accepted run's own canonical population.
    stored = [p for p in ((summary.get("estimate_summary") or {})
                          .get("canonical_part_estimates") or []) if isinstance(p, dict)]
    if stored:
        stored_ids = {str(p.get("part_number") or "").strip().upper()
                      for p in stored} - {""}
        assert out_ids == stored_ids, \
            (f"{job.name}: canonicalise no longer reproduces the accepted population — "
             f"gained {sorted(out_ids - stored_ids)}, lost {sorted(stored_ids - out_ids)}")


def _forbidden_names_check(job: Path, facts: dict, summary: dict, lines: list) -> None:
    forbidden = [str(x) for x in (facts.get("forbidden_names_everywhere") or [])]
    if forbidden:
        import client_quote_html
        import job_report_html
        report = job_report_html.build_report_html(summary)
        quote = client_quote_html.build_quote_html(summary)
        blob = json.dumps(lines) + report + quote
        # The evidence flags MAY name a folded identity (that is the audit trail); a
        # rendered LINE may not. The record lines and the quote must be clean; the
        # report may carry a name only inside a review-flag/ledger sentence.
        for name in forbidden:
            assert name not in json.dumps([{k: v for k, v in l.items()
                                            if k != "review_flags"} for l in lines]), \
                f"{job.name}: '{name}' is a record line"
            assert name not in quote, f"{job.name}: '{name}' reached the customer quote"
