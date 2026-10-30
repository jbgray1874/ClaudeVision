"""An extract behind the code is re-read even when the models never changed — the old-jobs fix.

The freshness check only asked 'are the models newer than the extract?'. On an OLD job the models
are from 2019/2025 and the extract is from whenever it was last taken, so the models are never
newer and the extract is reused for ever — which means an analyser CODE improvement (the weldment
tube read, material provenance) never reaches an old job until someone deletes the cache by hand.
For a tool whose whole purpose is pricing old jobs, that is backwards.

The extract now carries a schema_version, and the freshness check re-runs the analyser when the
extract's version is behind what the estimate needs (_MIN_EXTRACT_SCHEMA_VERSION) — regardless of
file dates. A code fix reaches an old job automatically on the next run. An unreadable or
unversioned extract reads as version 0 and is re-run, the safe direction.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "solidworks"))

from source_connectors import solidworks as sw  # noqa: E402
import sw_native_analyse as swa  # noqa: E402


def _write(dirpath, name, payload):
    p = Path(dirpath) / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_the_analyser_and_the_consumer_agree_on_the_version():
    """The producer's stamped version is at least what the consumer requires — they must not
    drift, or the consumer would re-run for ever (too low) or trust a stale extract (too high)."""
    assert swa.EXTRACT_SCHEMA_VERSION >= sw._MIN_EXTRACT_SCHEMA_VERSION


def test_an_old_unversioned_extract_forces_a_re_extract():
    """THE OLD-JOB CASE. A v2/unversioned extract reads as version 0 and is re-run even though it
    exists and the models are ancient."""
    d = tempfile.mkdtemp()
    old = _write(d, "_sw_native_extract.json",
                 {"schema": "sw_native_extract.v2", "_manifest": {}, "records": []})
    assert sw._extract_schema_version(old) == 0
    assert sw._should_run(old, d) is True


def test_a_current_extract_is_reused_when_the_models_did_not_change():
    """A v3 extract with models no newer than it is reused — the version gate only forces a
    re-run when the extract is BEHIND, never on every run."""
    d = tempfile.mkdtemp()
    cur = _write(d, "_sw_native_extract.json",
                 {"schema": "sw_native_extract.v3", "schema_version": 3,
                  "_manifest": {"schema_version": 3}, "records": []})
    assert sw._extract_schema_version(cur) == sw._MIN_EXTRACT_SCHEMA_VERSION
    # No model files in the temp dir, so nothing is newer than the extract -> reuse.
    assert sw._should_run(cur, d) is False


def test_a_missing_extract_runs():
    d = tempfile.mkdtemp()
    assert sw._should_run(Path(d) / "nope.json", d) is True


def test_a_corrupt_extract_reads_as_version_zero_and_re_runs():
    """An unreadable extract must not be trusted — version 0 forces the safe path, a re-read."""
    d = tempfile.mkdtemp()
    bad = Path(d) / "_sw_native_extract.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    assert sw._extract_schema_version(bad) == 0
    assert sw._should_run(bad, d) is True


def test_the_version_can_be_read_from_either_the_top_or_the_manifest():
    """Robust to where the stamp sits — the analyser writes it in both the payload and the
    manifest, and either is accepted."""
    d = tempfile.mkdtemp()
    top = _write(d, "top.json", {"schema_version": 3, "records": []})
    man = _write(d, "man.json", {"_manifest": {"schema_version": 3}, "records": []})
    assert sw._extract_schema_version(top) == 3
    assert sw._extract_schema_version(man) == 3
