"""Client quotation data must not be tracked in the repository.

104,386 records were: customer names, job numbers, sell prices, cost breakdowns, rebate
fractions, derived overhead divisors, and the names of the 39 estimators who prepared them
-- 488 customers, 2006 to 2036. No CAD, no drawing, no model; commercially it is worse,
because it is what SDI charged, to whom, at what margin.

They bought nothing. NOTHING READS THEM AT ESTIMATE TIME. They are an intermediate
artefact: corpus_ingest.py writes one from the K: spreadsheets, and the two ingest scripts
read it ONCE to load SQL Server and the vector store -- both taking the path as an argument
and defaulting to a relative corpus.jsonl, never to anything committed. The engine's
corpus-derived constants live in config.py with the corpus named in a comment as their
provenance; the file itself is never opened.

This guard is not about disk space. A .gitignore rule is one edit away from being reverted
by someone who wants a file to travel between machines -- which is exactly how it happened
the first time, via an explicit "!corpus/*.jsonl" exception that put them back after the
blanket rule had excluded them.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return [l for l in out.stdout.splitlines() if l.strip()]


def test_no_jsonl_corpus_is_tracked():
    bad = [f for f in _tracked() if f.endswith(".jsonl")]
    assert not bad, f"client quotation data is back in source control: {bad}"


def test_the_gitignore_exception_has_not_returned():
    """The exact mechanism that put them there. A blanket *.jsonl rule with a targeted
    un-ignore beneath it reads as tidy and re-admits the whole corpus.

    RULES ONLY, NOT COMMENTS. The first version searched the whole file and failed on the
    comment that explains which rule was removed -- prose naming a rule is not the rule,
    and a guard that forces the file to stop explaining itself makes the file worse. This
    is the third time that trap has been hit in this codebase; it is always the same fix.
    """
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    rules = [l.strip() for l in gi.splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    assert not [r for r in rules if r.startswith("!") and "corpus" in r], \
        "an un-ignore exception has re-admitted the client corpora"
    assert "*.jsonl" in rules, "the blanket jsonl rule has gone"
    assert "corpus/" in rules, "the corpus directory is not excluded"


def test_no_spreadsheet_of_client_pricing_is_tracked():
    """The same question asked of the other shape this data arrives in."""
    bad = [f for f in _tracked()
           if f.lower().endswith((".xls", ".xlsx", ".xlsm", ".mdb", ".accdb"))]
    assert not bad, f"client pricing workbooks are tracked: {bad}"


def test_the_engine_does_not_read_a_committed_corpus():
    """The reason removal is safe, asserted rather than assumed. If a future change makes
    the estimate path depend on a corpus file, this fails and the decision gets retaken
    deliberately instead of by a broken run."""
    hits = []
    for p in list((ROOT / "src").glob("*.py")) + list((ROOT / "tools").rglob("*.py")):
        if "_archive" in str(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in re.finditer(r"^.*(?:open\(|read_text|json\.load)\s*\(?[^\n]*corpus[^\n]*"
                             r"\.jsonl.*$", text, re.M | re.I):
            line = m.group(0).strip()
            if line.startswith("#") or line.startswith('"'):
                continue
            hits.append(f"{p.name}: {line[:90]}")
    # The ingest scripts take a --jsonl argument; they do not name a committed path.
    assert not hits, ("something now opens a corpus file by name -- removing it from "
                      f"source control would break this: {hits}")


def test_the_env_file_is_not_tracked():
    """Filed alongside because it is the same defect with a different payload, entered the
    repository in the SAME commit, and has the same cure: ignore rules do nothing to a file
    that is already tracked.

    THE MARKER THAT USED TO BE HERE, and why it is gone. This was a strict xfail recording
    sdi-intelligence-backend/.env as a known live exposure, with the instruction that whoever
    untracked it should delete the marker. It worked exactly as designed: the file was untracked
    and this test turned from xfail into an error naming itself.

    Its reasoning said untracking must not come FIRST, because rotation is the cure and deletion
    is only tidying. That still holds and none of it is retracted. What changed is the ordering
    it was warning about: the next morning's job was "change the SDI live database password and
    put it into .env only", and with .env tracked, "into .env only" would have committed the NEW
    password on the next commit that touched the file — rotating a credential straight back into
    the exposure it was being rotated out of. Untracking had to happen before that, not after.

    SO SAY PLAINLY WHAT IS AND IS NOT FIXED. Untracking removes the file from the index, not from
    history. Every password committed to this repository is still in it and still readable by
    anyone who has ever had a clone; making the repository private did not undo that. The live SQL
    login and the BrightHR client secret were exposed for four months and are exposed still. This
    test stops the NEXT secret being added. Rotation is what ends the current one, and the strict
    xfail in test_a_setting_we_read_is_a_setting_that_exists.py stays failing until it happens.

    The other warning it carried is operational and is real: untracking deletes the file from
    every other working copy on the next pull, taking the service down until someone restores it.
    Every machine must copy its .env aside BEFORE pulling this and put it back afterwards."""
    tracked = _tracked()
    live = [f for f in tracked
            if f.endswith(".env") and ".example" not in f and "/env/" not in f]
    assert not live, (
        f"a live credentials file is tracked: {live}. Rotate the secrets FIRST -- removing "
        "the file does not remove it from history, so rotation is the cure and deletion is "
        "only tidying.")


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
