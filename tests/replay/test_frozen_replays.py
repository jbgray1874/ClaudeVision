"""The fast replay layer: frozen accepted jobs through the record and the deliverables.

Each subdirectory here is one estimator-REVIEWED job (see README.md). The frozen
summary.json is driven through costed_facts (the record every surface reads) and both
HTML deliverable builders — everything downstream of extraction that runs without Excel —
and the result is diffed against accepted_facts.json: identities, routes, decisions,
names that must appear nowhere. Structure, never money.

A MISSING FIXTURE IS A FAILURE, NOT A SKIP. It used to skip with a loud message, and the
message was not loud: four skips inside a 4,600-test run is indistinguishable from four
passes, so both frozen packs sat unprotected for weeks while every push reported green. The
difference between "this pack is protected" and "nobody froze it" has to be a red result.

Set SDI_REPLAY_ALLOW_MISSING=1 to downgrade that to a skip. That is for working locally on a
checkout without the packs; CI must never set it, which is why it is an explicit opt-out
rather than a default.

AND A FROZEN RECORD MUST SAY WHERE IT CAME FROM. A summary.json with no provenance is an
unlabelled number: nobody can tell the accepted run from whichever run last passed, which is
precisely the substitution the accepted baseline exists to prevent.
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

ALLOW_MISSING = os.environ.get("SDI_REPLAY_ALLOW_MISSING", "").strip() not in ("", "0")

# What a provenance file has to answer. Not bureaucracy: each of these is a question somebody
# asked about a baseline this year and nobody could answer from the file.
PROVENANCE_FIELDS = ("job", "accepted_run", "accepted_by", "accepted_on", "source_path")


def _facts(job: Path) -> dict:
    return json.loads((job / "accepted_facts.json").read_text(encoding="utf-8"))


def _frozen_summary(job: Path) -> dict:
    """The frozen record, or a FAILURE saying exactly what to copy where.

    Also enforces provenance, because an unattributed baseline cannot be audited: "the run the
    estimator signed off" and "whichever run last passed" look identical on disk.
    """
    frozen = job / "summary.json"
    if not frozen.is_file():
        message = (
            f"{job.name}: accepted facts exist but NO frozen summary.json — this pack is "
            f"NOT protected. On the box:\n"
            f"    copy output\\json\\{job.name}.json  tests\\replay\\{job.name}\\summary.json\n"
            f"from the run the estimator signed off, write "
            f"tests/replay/{job.name}/provenance.json, and commit both.")
        if ALLOW_MISSING:
            pytest.skip(message + "\n(skipped: SDI_REPLAY_ALLOW_MISSING is set)")
        pytest.fail(message)

    prov_path = job / "provenance.json"
    assert prov_path.is_file(), (
        f"{job.name}: summary.json is frozen with no provenance.json beside it. A baseline "
        f"nobody can attribute is not a baseline. Required fields: "
        f"{', '.join(PROVENANCE_FIELDS)}")
    prov = json.loads(prov_path.read_text(encoding="utf-8"))
    missing = [f for f in PROVENANCE_FIELDS if not str(prov.get(f) or "").strip()]
    assert not missing, f"{job.name}: provenance.json is missing {missing}"
    assert str(prov.get("job")).strip().upper() == job.name.upper(), (
        f"{job.name}: provenance names job {prov.get('job')!r} — a record filed under the "
        f"wrong job is worse than none")
    return json.loads(frozen.read_text(encoding="utf-8"))


def canonical_decisions(summary: dict) -> list:
    """Every OperationDecision the canonical route recorded, wherever this pipeline keeps it.

    Both spellings and both nestings are read because the record has used both: costed_facts
    reads `canonical_route_shadow`, the compiler writes it into estimate_summary, and a record
    may carry `canonical_route` instead. Picking one and missing the other is how a route that
    IS recorded reads as absent.
    """
    out: list = []
    for holder in (summary or {}), ((summary or {}).get("estimate_summary") or {}):
        if not isinstance(holder, dict):
            continue
        for key in ("canonical_route_shadow", "canonical_route"):
            payload = holder.get(key)
            if isinstance(payload, dict):
                for decision in (payload.get("decisions") or []):
                    if isinstance(decision, dict) and decision not in out:
                        out.append(decision)
    return out


def required_ops_for(summary: dict, part_number: str) -> set:
    """Operations the canonical route REQUIRES of this part.

    WHY THE ROUTE AND NOT THE COSTED LINE. costed_job() derives a line's `operations` from the
    workbook rows that carry decision ids, so on a record whose rows carry none the list comes
    back EMPTY even though the route recorded tubebend on 7332-01-002. The gate would then
    reject a structurally correct record — the pin would be testing whether decision ids
    reached the sheet, not whether the route was compiled.

    Those are two different assertions and the gate now makes them separately: a REQUIRED
    operation is asserted against the route, which is the authority on routing, and a FORBIDDEN
    one against what is actually charged, which is the authority on money.

    AND ONLY `required` COUNTS. An unverified or refused decision must never satisfy a
    required-operation pin: "the compiler considered tubebend" is not "the route bends the
    tube". Status is read strictly — a decision with no status at all does not qualify either,
    because absence is not a claim.
    """
    want = str(part_number).strip().upper()
    ops: set = set()
    for decision in canonical_decisions(summary):
        if str(decision.get("status") or "").strip().lower() != "required":
            continue
        targets = {str(decision.get("part_number") or "").strip().upper(),
                   str(decision.get("target_id") or "").strip().upper()}
        targets |= {str(p).strip().upper() for p in (decision.get("participants") or [])}
        if want in targets - {""}:
            op = str(decision.get("operation") or "").strip().lower()
            if op:
                ops.add(op)
    return ops


def assert_accepted_structure(job_name: str, facts: dict, lines: list,
                              summary: dict = None) -> None:
    """Every structural pin in accepted_facts.json, held against a costed record's lines.

    SEPARATED FROM THE FIXTURE ON PURPOSE. While both packs sat unfrozen these checks could
    not be executed at all, so a pin could be added and never once run — the same silent-skip
    problem one level up. Lifted out, each one is provable against a synthetic record (see
    tests/test_the_replay_gate_is_a_gate.py) independently of whether any pack is frozen.
    """
    line_ids = sorted({str(l.get("part_number") or "").strip().upper() for l in lines} - {""})

    def _find(pn):
        return next((l for l in lines
                     if str(l.get("part_number") or "").upper() == str(pn).upper()), None)

    # ── BOM identity: exactly these lines, no more, no fewer ────────────────────
    want = facts.get("bom_identities")
    if want:
        assert line_ids == sorted(str(w).upper() for w in want), \
            f"{job_name} BOM drifted: {line_ids}"

    # ── quantities: spot-pins ──────────────────────────────────────────────────
    for pn, q in (facts.get("quantities") or {}).items():
        line = _find(pn)
        got = line.get("qty_per_unit") if line else None
        assert got is not None and abs(float(got) - float(q)) < 0.01, \
            f"{job_name} {pn}: qty {got} != accepted {q}"

    # ── routes: required DERIVED by the route, ruled-out not CHARGED ────────────
    for pn, ops in (facts.get("required_operations") or {}).items():
        line = _find(pn)
        assert line is not None, f"{job_name}: {pn} missing from the record"
        charged = {str(o).lower() for o in (line.get("operations") or [])}
        # The line's OWN route_operations first — costed_facts now publishes what the route
        # requires beside what is charged, so the record answers this itself. The summary read
        # stays as a fallback for records frozen before that field existed.
        routed = {str(o).lower() for o in (line.get("route_operations") or [])}
        if not routed and summary is not None:
            routed = required_ops_for(summary, pn)
        got_ops = charged | routed
        for op in ops:
            assert op.lower() in got_ops, (
                f"{job_name} {pn}: required op '{op}' is neither routed nor charged — "
                f"route requires {sorted(routed)}, line carries {sorted(charged)}")
    for pn, ops in (facts.get("forbidden_operations") or {}).items():
        line = _find(pn)
        if line is None:
            continue
        got_ops = {str(o).lower() for o in (line.get("operations") or [])}
        for op in ops:
            assert op.lower() not in got_ops, \
                f"{job_name} {pn}: ruled-out op '{op}' is charged"

    # ── operations no line anywhere may carry ──────────────────────────────────
    # Per-part forbids miss the case that actually happened: a finish reappearing on a
    # DIFFERENT part than the one it was ruled off. On 7332 the plated and Harrods-1 finishes
    # were read as powder, and pinning powder off part 002 alone would not have caught it
    # landing on 101 or 008 instead.
    for op in (facts.get("forbidden_operations_anywhere") or []):
        guilty = sorted(str(l.get("part_number")) for l in lines
                        if op.lower() in {str(o).lower() for o in (l.get("operations") or [])})
        assert not guilty, \
            f"{job_name}: '{op}' is ruled out for this job but is charged on {guilty}"

    # ── material has to actually reach the line ────────────────────────────────
    # NOT a rate pin: rates move and this layer never pins money. It pins PRESENCE — a leg
    # costed with no material contribution at all is the failure that produced GBP 0 lines,
    # and it is invisible to an identity or route check because the line is present and
    # routed.
    for pn in (facts.get("material_charged") or []):
        line = _find(pn)
        assert line is not None, f"{job_name}: {pn} is missing, so nothing is charged for it"
        charged = line.get("charged_unit_gbp")
        money = charged if charged is not None else line.get("engine_unit_gbp")
        assert money is not None and float(money) > 0.0, (
            f"{job_name} {pn}: material contribution is {money!r} — the line exists and is "
            f"routed, but no material money reaches it")

    # ── no child minted under a part to stand in for its stock ─────────────────
    # The failure shape: rather than charging the leg's own tube, the engine mints a child
    # node beneath it to carry the stock, and the money lands twice or on a node no estimator
    # has ever seen. Expressed generically as "this parent gains no descendants", so it holds
    # whatever the minted child would have been called.
    for parent in (facts.get("no_minted_children") or []):
        stem = _squash(parent)
        children = sorted(str(l.get("part_number")) for l in lines
                          if _squash(l.get("part_number")) != stem
                          and _squash(l.get("part_number")).startswith(stem))
        assert not children, \
            f"{job_name}: {parent} gained minted child line(s) {children}"


@pytest.mark.parametrize("job", JOBS, ids=[j.name for j in JOBS])
def test_frozen_replay(job: Path):
    facts = _facts(job)
    summary = _frozen_summary(job)

    import costed_facts as cf
    record = cf.costed_job(summary)
    lines = [l for l in (record.get("lines") or []) if isinstance(l, dict)]

    assert_accepted_structure(job.name, facts, lines, summary=summary)

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
    summary = _frozen_summary(job)
    import copy
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


@pytest.mark.parametrize("job", JOBS, ids=[j.name for j in JOBS])
def test_frozen_routing_and_costing_re_execute(job: Path):
    """Tier 3: the ROUTING and MATERIAL COSTING code runs again on the frozen inputs.

    Tiers 1 and 2 between them render an already-costed record and re-run the workbook
    canonicalisation. Neither re-derives a route or a material price, so a change inside
    route_compiler or estimator could alter what a leg costs and both tiers would still pass on
    the frozen numbers — exactly the criticism that "rendering previously calculated results"
    is not a replay.

    This tier calls compile_job_route on the frozen part population and estimate_material on
    each part, and holds what those two stages are responsible for:

      · a route the accepted facts REQUIRE is still compiled from the inputs, and one they
        rule out is still refused — re-derived, not read back
      · a part the accepted facts say carries material still prices above zero when costed
        from scratch
      · no operation the job rules out anywhere is minted by the compiler

    It does NOT pin a rate. Prices move; the contract is that the stage still produces one.
    """
    facts = _facts(job)
    summary = _frozen_summary(job)
    parts = [p for p in ((summary.get("estimate_summary") or {}).get("part_estimates") or [])
             if isinstance(p, dict)]
    if not parts:
        pytest.fail(f"{job.name}: frozen summary carries no raw part_estimates to re-route")

    import copy
    import route_compiler

    doc = summary.get("document_analysis") or {}
    compiled = route_compiler.compile_job_route(
        copy.deepcopy(parts),
        llm_extract=summary.get("llm_extract") or {},
        bom_rows=doc.get("bom_rows") or [],
    )
    decisions = [d for d in (compiled.get("decisions") or []) if isinstance(d, dict)]

    def _ops_for(pn: str) -> set:
        want = str(pn).strip().upper()
        return {str(d.get("operation") or "").lower() for d in decisions
                if str(d.get("part_number") or d.get("target_id") or "").strip().upper() == want
                and str(d.get("status") or "").lower() not in
                ("not_applicable", "refused", "excluded")}

    for pn, ops in (facts.get("required_operations") or {}).items():
        got = _ops_for(pn)
        for op in ops:
            assert op.lower() in got, (
                f"{job.name} {pn}: the compiler no longer DERIVES required op '{op}' from the "
                f"frozen inputs (got {sorted(got)}) — the record may still carry it")
    for pn, ops in (facts.get("forbidden_operations") or {}).items():
        got = _ops_for(pn)
        for op in ops:
            assert op.lower() not in got, \
                f"{job.name} {pn}: the compiler now derives ruled-out op '{op}'"
    for op in (facts.get("forbidden_operations_anywhere") or []):
        guilty = sorted({str(d.get("part_number") or d.get("target_id") or "")
                         for d in decisions
                         if str(d.get("operation") or "").lower() == op.lower()
                         and str(d.get("status") or "").lower() not in
                         ("not_applicable", "refused", "excluded")})
        assert not guilty, f"{job.name}: the compiler mints ruled-out '{op}' on {guilty}"

    # ── material re-costed from scratch, not read back ─────────────────────────
    import estimator
    for pn in (facts.get("material_charged") or []):
        part = next((p for p in parts
                     if str(p.get("part_number") or "").upper() == str(pn).upper()), None)
        assert part is not None, f"{job.name}: {pn} absent from the frozen part population"
        fresh = estimator.estimate_material(copy.deepcopy(part)) or {}
        unit = fresh.get("unit_material_cost_gbp")
        assert unit is not None and float(unit) > 0.0, (
            f"{job.name} {pn}: re-costing the frozen part yields {unit!r} — the stored record "
            f"carries material money that the costing stage no longer produces")
