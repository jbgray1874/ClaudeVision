"""Real saved jobs, wherever they are kept.

WHY THIS IS NOT A GLOB IN ONE TEST. tests/fixtures/jobs/ was built to be replayed and has held
zero jobs since the day it was written, so every structural rule in this suite is asserted
against records the author of the rule also wrote. A dict written by the person who wrote the
rule cannot disagree with it about the shape of a record, and three times in a row on 11350
that is exactly what went wrong. "The side panel prices correctly" is a sample of one; a
hand-written fixture is a sample of none.

TWO PLACES, ONE READER. Job records carry client names, drawing numbers and prices, and
whether those belong in git is a commercial decision, not an engineering one. Supporting both
means the decision changes a path and not a test:

    tests/fixtures/jobs/*.json          in-repo, for a private repo the team is happy with
    $SDI_JOB_CORPUS/*.json              a share, for client pricing kept out of git

Both are read. Neither is required — an empty corpus passes, exactly as it does today, because
a suite that cannot run without client data is a suite nobody outside can run at all.

THE SHAPE IS FOUND, NOT ASSUMED. A saved job is written by whichever version of the engine
produced it, and older ones are the valuable ones precisely because nobody wrote them with
today's rules in mind. A reader that knows one shape reports "no parts" on every job of
another, and the seeding then looks like a broken harness rather than a document worth
reading. So the holders are searched, and a document that yields nothing says which keys it
DOES have.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

IN_REPO = Path(__file__).resolve().parent / "fixtures" / "jobs"
CORPUS_ENV = "SDI_JOB_CORPUS"

# The LLM extract is a different document with a different shape; it is not a job. Same rule
# the diagnostics use, for the same reason.
_NOT_A_JOB = ("llm_extract",)


def roots() -> List[Path]:
    out = [IN_REPO]
    extra = os.environ.get(CORPUS_ENV, "").strip()
    if extra:
        out.append(Path(extra))
    return out


def paths() -> List[Path]:
    """Every saved job on offer, in a stable order so a failure names the same file twice."""
    found: List[Path] = []
    for root in roots():
        if not root.is_dir():
            continue
        for p in sorted(root.glob("*.json")):
            if any(token in p.name.lower() for token in _NOT_A_JOB):
                continue
            found.append(p)
    return found


def jobs() -> Iterator[Tuple[Path, Dict[str, Any]]]:
    for path in paths():
        try:
            doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError) as exc:
            # NOT SKIPPED IN SILENCE. A corpus file nobody can read is a corpus file that is
            # not testing anything, and looking like it is.
            raise AssertionError(f"{path.name} is in the corpus and cannot be read: {exc}")
        if isinstance(doc, dict):
            yield path, doc


def _first_list(holder: Any, key: str) -> List[Dict[str, Any]]:
    if isinstance(holder, dict):
        value = holder.get(key)
        if isinstance(value, list) and value:
            return [v for v in value if isinstance(v, dict)]
    return []


def raw_parts(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The part records as the pipeline built them, before costing projected them.

    These are what the merge and route rules read, so these are what a replay must feed them.
    """
    for holder, key in ((doc.get("manufacturing_writeup"), "parts"),
                        (doc, "parts"),
                        (doc.get("estimate_summary"), "parts")):
        got = _first_list(holder, key)
        if got:
            return got
    return []


def costed_parts(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The costed projection — part_estimates, wherever this document keeps them."""
    for holder in (doc.get("estimate_summary"), doc):
        got = _first_list(holder, "part_estimates")
        if got:
            return got
    return []


def what_this_document_holds(doc: Dict[str, Any]) -> str:
    """For a failure message. A corpus file that yields no parts is either the wrong kind of
    document or a shape nobody has taught this reader, and naming its keys is the difference
    between a two-minute answer and an afternoon."""
    keys = sorted(k for k in doc if isinstance(k, str))[:14]
    return f"top-level keys: {', '.join(keys) or '(none)'}"
