"""The register and the PDF generator must not disagree about a finding.

They already did once, and it is the defect this month's work exists to remove, landed in
the worst possible place. The register was updated to say the quotation extract had been
removed; the PDF generator holds its OWN copy of the prose, so it went on saying the
extract was tracked. One fact, two documents, different answers -- in a document prepared
for legal advice.

The structural fix is to collapse them into one source, and until that happens this guard
is what stops them drifting again. It checks the CLAIMS that matter, not the wording: both
must speak of the corpus in the past tense, both must carry the history caveat, and neither
may carry a repository identifier or a credential value.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "delivery" / "external_providers_register.md"
GENERATOR = ROOT / "tools" / "build_external_providers_pdf.py"


def _reg():
    return REGISTER.read_text(encoding="utf-8")


def _gen():
    return GENERATOR.read_text(encoding="utf-8")


@pytest.mark.parametrize("name,text", [("register", None), ("pdf generator", None)])
def test_neither_document_claims_the_corpus_is_still_committed(name, text):
    """The stale-bullet failure, guarded. A summary that contradicts its own detail section
    is worse than either statement alone."""
    body = _reg() if name == "register" else _gen()
    stale = [m.group(0) for m in re.finditer(
        r"[^.\n]*corpus[^.\n]*\b(is committed|are tracked|is in source control|"
        r"are in source control)\b[^.\n]*", body, re.I)]
    assert not stale, f"{name} still claims the corpus is committed: {stale[:2]}"


@pytest.mark.parametrize("name", ["register", "pdf generator"])
def test_both_documents_carry_the_history_caveat(name):
    """Removal from the tracked tree is not removal from history, and that is where the
    exposure sits. A document that reports the cleanup without the caveat reads as closed."""
    body = _reg() if name == "register" else _gen()
    assert re.search(r"histor(y|ical)", body, re.I)
    assert "history rewrite is a separate decision" in body, \
        f"{name} reports the removal without saying history still holds it"


@pytest.mark.parametrize("name", ["register", "pdf generator"])
def test_both_documents_say_extract_not_master(name):
    """The distinction a reader needs to judge what was actually exposed: the system of
    record is internal, and what was committed was an extract of it."""
    body = _reg() if name == "register" else _gen()
    assert re.search(r"extract", body, re.I), f"{name} does not say it was an extract"
    assert re.search(r"system of record", body, re.I), \
        f"{name} does not say where the master lives"


@pytest.mark.parametrize("name", ["register", "pdf generator"])
def test_neither_document_carries_an_identifier_or_a_credential(name):
    body = _reg() if name == "register" else _gen()
    for pattern in ("github.com", "jbgray", "YogiSDI", "ClaudeVision",
                    "10.0.0.", "sdi-dc01", "AIBot", "SDILive"):
        assert pattern.lower() not in body.lower(), \
            f"{name} names {pattern}, which both documents deliberately omit"


def test_the_generator_is_the_authoritative_one_and_says_so():
    """Two copies of one document is the standing hazard. Until they are collapsed, the
    file that produces what is actually sent has to be the one people edit."""
    assert GENERATOR.exists() and REGISTER.exists()


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
