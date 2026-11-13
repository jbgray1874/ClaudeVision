"""NO PRICE CACHE CARRIES A RATE FROM ONE JOB TO ANOTHER (reviewer, 13 Nov 2026).

"Clearing price caches between tests addresses test contamination. Separately confirm that
production cache keys cannot carry an inappropriate rate between jobs."

Two kinds of cache exist. The estimator's own caches live in memory for one process, and
each estimate is its own process. The generated-price cache is on disk and is shared between
jobs on purpose: it is keyed on the whole specification, so only the same question gets the
same answer.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import generated_price_cache as G  # noqa: E402

RUNNER = (ROOT / "tools" / "runner" / "sdi_estimate_runner.py").read_text(encoding="utf-8")
ESTIMATOR = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
CACHES = sorted(set(re.findall(r"^(_[A-Z_]*(?:CACHE|_ROWS|_META)[A-Z_]*)\s*:\s*Dict", ESTIMATOR, re.M)))


def test_each_estimate_is_its_own_process():
    assert 'str(Path(engine_root) / "src" / "main.py")' in RUNNER
    assert "subprocess.Popen(" in RUNNER
    assert not re.search(r"^\s*import estimator\b|^\s*from estimator import", RUNNER, re.M), \
        "the runner never loads the estimator into its own long-lived process"


def test_the_estimators_caches_are_memory_only():
    assert len(CACHES) >= 5
    for name in CACHES:
        for writer in ("json.dump", "pickle.dump", "write_text", "shelve"):
            for line in ESTIMATOR.splitlines():
                assert not (name in line and writer in line), f"{name} is written to disk: {line.strip()}"


def test_the_sheet_rate_key_holds_material_gauge_product_and_specification():
    at = ESTIMATOR.index("_cache_key = ((_token, _t_key,")
    block = ESTIMATOR[at:at + 400]
    assert "_ref_probes" in block and '_spec["key"]' in block
    assert "_rate_key = (str(material).upper(), round(float(_thk), 1) if _thk else None," in ESTIMATOR


SPEC = {"material": "MFC", "description": "SIDE PANEL", "thickness_mm": 18.0, "part_code": "P-01",
        "finish": "WHITE", "colour": "W1000", "quantity": 4, "length_mm": 800.0, "width_mm": 400.0,
        "weight_kg": None, "operations": ["cnc_routing", "edge_banding"]}


def test_the_shared_cache_answers_only_the_same_question():
    base = G.cache_key(SPEC, "xai", "grok")
    assert G.cache_key(dict(SPEC), "xai", "grok") == base
    assert G.cache_key(dict(SPEC, material=" mfc "), "xai", "grok") == base, "spelling is not a new question"
    for field, other in (("material", "MDF"), ("thickness_mm", 25.0), ("finish", "OAK"), ("colour", "H1145"),
                         ("quantity", 68), ("length_mm", 810.0), ("width_mm", 410.0), ("part_code", "P-02"),
                         ("description", "BASE"), ("operations", ["cnc_routing"]), ("weight_kg", 3.2)):
        assert G.cache_key(dict(SPEC, **{field: other}), "xai", "grok") != base, field
    assert G.cache_key(SPEC, "xai", "another-model") != base
    assert G.cache_key(SPEC, "other", "grok") != base


def test_every_field_the_price_question_uses_is_in_the_key():
    assert set(G._SPEC_KEYS) == set(SPEC)
