"""Who is allowed to write an arbitrated fact, enumerated — so a new writer cannot arrive quietly.

EVERY EXPENSIVE DEFECT THIS ENGINE HAS PRODUCED IS THE SAME SHAPE: two pieces of code answering
one question, and nothing failing until they disagreed on a real job.

    parts per sheet     K38 stamped on the record, J51 charged in the cost path
    the stock key       material resolved by one rule, gauge by another, landing on PETG@2.2
    the filename        a private material vocabulary that had never heard of PETG
    can we price it     one table asked, silence treated as an answer for all of them
    the handed pair     a rule wired to a call site no job uses

None of those was found by a test. Every one was found on a live job, after a wrong number had
been read by somebody, and the cheapest of them cost an afternoon.

THE ARBITRATED FACTS HAVE ONE SANCTIONED WRITER: `source_precedence.apply_field`. It is the
only thing that weighs a source against what is already there, records what it displaced, and
leaves the disagreement where a person can see it. A direct assignment bypasses all three.

SOME BYPASSES ARE LEGITIMATE and the codebase already says so in-line:

    part["quantity"] = quantity   # precedence: direct-write ok — sanitises the part's own value

That comment IS the registry entry. It was simply never enforced, so it recorded the careful
writes and said nothing about the careless ones. This turns it into a gate.

WHAT THIS CATCHES AND WHAT IT DOES NOT. It catches a NEW piece of code writing an arbitrated
fact without declaring why. It does not catch a rule wired to a call site nothing uses — that
one writes nothing at all, and needs the other guard shape (`every caller of X also calls Y`),
which lives with the rule it protects. Neither subsumes the other and both are worth having.
"""
from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import source_precedence as sp  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src")

# The datums arbitration owns, and the keys recording where each came from. Read from
# _SOURCE_FIELDS rather than retyped: a fourth arbitrated field added there is guarded here
# the same day, which is the only way a registry stays true.
FIELDS = sorted(set(sp._SOURCE_FIELDS) | set(sp._SOURCE_FIELDS.values()))
_ASSIGN = re.compile(r'\[\s*["\'](' + "|".join(map(re.escape, FIELDS)) + r')["\']\s*\]\s*=(?!=)')
_MARKER = "precedence: direct-write ok"

# WRITES THAT EXIST TODAY AND ARE NOT YET DECLARED. Held as a list rather than fixed in one
# pass, because each needs reading: some are not part records at all (a column index, a report
# header, an order quantity on the summary) and some are the real thing. Naming them stops the
# count growing while they are worked through — the same way the plaintext-password debt is
# held. Removing one from this list and marking it in the source is a two-line change.
_KNOWN_UNDECLARED = {
    ("costed_facts.py", "merged"),          # a costed copy, not the part record
    ("document_builder.py", "record"),      # stamps quantity_source on a record it just made
    ("extract_bom_to_sql.py", "mapping"),   # a column index, not a quantity
    ("main.py", "summary"),                 # the ORDER quantity, not a part's
    ("parity_check.py", "out"),             # a report header
    ("reconciliation.py", "reconciled"),    # an estimator override, applied deliberately
    ("route_compiler.py", "record"),        # a route node's qty from the BOM tree
    ("wb_populate.py", "item"),             # a spreadsheet row, not the part
}

# Files that are not the pipeline: superseded copies kept for reference, and scratch probes.
_NOT_THE_PIPELINE = ("estimator1.py", "estimator_old.py")


def _writes():
    """Every direct assignment to an arbitrated fact in the pipeline, with its receiver."""
    out = []
    for path in sorted(glob.glob(os.path.join(SRC, "*.py"))):
        name = os.path.basename(path)
        if not os.path.isfile(path) or name.startswith("_") or name in _NOT_THE_PIPELINE:
            continue
        for i, line in enumerate(
                open(path, encoding="utf-8", errors="replace").read().splitlines(), 1):
            m = _ASSIGN.search(line)
            if not m:
                continue
            recv = line.strip().split("[", 1)[0].strip()
            out.append({"file": name, "line": i, "receiver": recv,
                        "declared": _MARKER in line, "text": line.strip()[:100]})
    return out


# ── the gate ─────────────────────────────────────────────────────────────────────────

def test_no_new_writer_of_an_arbitrated_fact_arrives_undeclared():
    """THE WHOLE POINT. A direct assignment bypasses the one thing that weighs sources, records
    what it displaced, and leaves the disagreement visible. Doing that may be right — and if it
    is, it takes one comment to say so."""
    offenders = [w for w in _writes()
                 if not w["declared"] and (w["file"], w["receiver"]) not in _KNOWN_UNDECLARED]
    assert not offenders, (
        "these write an arbitrated fact without going through source_precedence.apply_field "
        "and without declaring why. Either submit through the resolver, or mark the line "
        "`# " + _MARKER + " — <reason>` if the bypass is genuinely correct:\n  "
        + "\n  ".join(f"{w['file']}:{w['line']}  {w['text']}" for w in offenders))


def test_the_registry_does_not_name_writes_that_are_gone():
    """A stale allowlist is worse than none: it reads as reviewed debt and is actually a list
    of places somebody already fixed, quietly widening the gate for their replacements."""
    live = {(w["file"], w["receiver"]) for w in _writes() if not w["declared"]}
    stale = _KNOWN_UNDECLARED - live
    assert not stale, (
        "these are on the known list and no longer exist — remove them so the list stays "
        "true: " + ", ".join(f"{f}:{r}" for f, r in sorted(stale)))


def test_the_declared_bypasses_all_give_a_reason():
    """"direct-write ok" on its own is a rubber stamp. The value of the marker is the sentence
    after it, which is what a reviewer weighs."""
    thin = [w for w in _writes() if w["declared"]
            and len(w["text"].split(_MARKER, 1)[-1].strip(" —-")) < 12]
    assert not thin, (
        "a bypass declared without saying why: " + "; ".join(w["text"] for w in thin))


def test_the_guarded_fields_are_read_from_the_resolver_not_retyped():
    """A fourth arbitrated field added to _SOURCE_FIELDS must be guarded the same day. A list
    copied into this file would be right until the moment it mattered."""
    assert set(sp._SOURCE_FIELDS) <= set(FIELDS)
    assert "normalized_material" in FIELDS and "material_source" in FIELDS


def test_the_scan_actually_finds_the_writes_it_is_guarding():
    """The gate above passes trivially if the regex matches nothing. There ARE sanctioned
    bypasses in this codebase; if none is found, the scan is broken rather than the code
    clean."""
    ws = _writes()
    assert len(ws) >= 8, f"the scan found only {len(ws)} direct writes — it is not looking"
    assert any(w["declared"] for w in ws), "no declared bypass found; the marker is not read"
