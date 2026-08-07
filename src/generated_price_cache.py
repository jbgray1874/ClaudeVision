r"""A generated price that changes every run is not a price. This makes it one.

An AI market estimate for the same part came back £35.62, £95.62, £75.62 and £85.62 on
four consecutive runs of one job. That is why the workbook refused to put it in the price
column: not because the number was uncertain — an estimator can work with an uncertain
number — but because the unit cost moved by sixty pounds while nothing about the job
changed. Two people reading the same estimate on the same day would disagree about what
it said.

Uncertainty and instability are different faults with different remedies. Uncertainty is
declared: say where the number came from and how much to trust it, and an estimator can
weigh it. Instability cannot be declared away, and it is the one that makes a system
untrustworthy — the same question answered differently each time it is asked.

So the estimate is asked for ONCE per distinct specification and stored. The same part on
the same drawing gets the same number tomorrow, next week, and on the estimator's machine
as well as this one. It changes when the SPEC changes, when the model or prompt changes,
or when somebody deliberately refreshes it — never on its own.

The cache is content-addressed and inspectable: one JSON file per specification, holding
the spec it answered, the answer, and when it was taken. Nothing is hidden in it, and
deleting a file simply asks the question again.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# Bump when the prompt or the meaning of the stored answer changes, so old entries are
# not silently reused against a question they were never asked.
CACHE_VERSION = "1"

# The fields that make one price question different from another. Anything not in here
# does not change the answer, and including it would fragment the cache into single-use
# entries — which is the same as having no cache while still looking like one.
_SPEC_KEYS = (
    "material", "description", "thickness_mm", "part_code", "finish",
    "colour", "quantity", "length_mm", "width_mm", "weight_kg", "operations",
)


def default_cache_dir() -> str:
    try:
        import config
        return str(config.BASE_DIR / "cache" / "generated_prices")
    except Exception:
        return str(Path(__file__).resolve().parents[1] / "cache" / "generated_prices")


def _canonical(spec: Dict[str, Any]) -> str:
    """The specification, reduced to the form two runs of the same job both produce.

    Values are normalised — case, surrounding whitespace, and a float that is really an
    integer — because "MILD STEEL" and "Mild Steel " are the same question, and a cache
    that thinks otherwise asks the model twice and gets two answers.
    """
    out: Dict[str, Any] = {}
    for key in _SPEC_KEYS:
        value = (spec or {}).get(key)
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, (list, tuple)):
            out[key] = sorted(str(v).strip().upper() for v in value if str(v).strip())
        elif isinstance(value, float) and value.is_integer():
            out[key] = int(value)
        elif isinstance(value, (int, float)):
            out[key] = value
        else:
            out[key] = " ".join(str(value).split()).upper()
    return json.dumps(out, sort_keys=True, ensure_ascii=False)


def cache_key(spec: Dict[str, Any], provider: str, model: str) -> str:
    h = hashlib.sha256()
    h.update(_canonical(spec).encode("utf-8"))
    h.update(b"\x00")
    h.update(str(provider or "").encode("utf-8"))
    h.update(b"\x00")
    h.update(str(model or "").encode("utf-8"))
    h.update(b"\x00")
    h.update(CACHE_VERSION.encode("utf-8"))
    return h.hexdigest()[:32]


def cached_estimate(
    spec: Dict[str, Any],
    provider: str,
    model: str,
    compute: Callable[[], Dict[str, Any]],
    *,
    cache_dir: Optional[str] = None,
    use_cache: bool = True,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Return a generated price for `spec`, asking `compute()` only when it is not held.

    The returned dict carries two extra keys the caller can report:
        price_is_reproducible  True when this number will come back the same next run
        price_first_taken      when the stored answer was originally obtained

    A failed computation is never stored. An estimate we could not obtain must be
    retried, not remembered as an absence.
    """
    directory = cache_dir or default_cache_dir()
    key = cache_key(spec, provider, model)
    path = os.path.join(directory, key + ".json")

    if use_cache and not refresh and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                entry = json.load(fh)
            result = dict(entry.get("result") or {})
            if result.get("found"):
                result["price_is_reproducible"] = True
                result["price_from_cache"] = True
                result["price_first_taken"] = entry.get("created_utc")
                return result
        except Exception:
            pass  # a corrupt entry is a cache miss, not a failure

    result = dict(compute() or {})
    if not result.get("found"):
        # Do not store. Tomorrow's run should ask again rather than inherit today's
        # network problem as though it were a fact about the part.
        result["price_is_reproducible"] = False
        return result

    stamped = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if use_cache:
        try:
            os.makedirs(directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({
                    "cache_version": CACHE_VERSION,
                    "provider": provider,
                    "model": model,
                    "spec": json.loads(_canonical(spec)),
                    "created_utc": stamped,
                    "result": result,
                }, fh, indent=2, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  [generated-price cache write failed: {exc}]")
            result["price_is_reproducible"] = False
            return result

    result["price_is_reproducible"] = bool(use_cache)
    result["price_from_cache"] = False
    result["price_first_taken"] = stamped
    return result
