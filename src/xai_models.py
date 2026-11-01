#!/usr/bin/env python3
"""The Grok models the engine calls, named once, and a check that this account has them (D-612).

    python src\\xai_models.py

JG, 1 Nov 2026: "we need to upgrade the model so we get the best possible llm as we know we use
this a lot... is it in the .env file? must be in config.py? as I only have the XAI_API_KEY."

It was in neither, which was the problem. "grok-4.3" was written into a dozen modules, each with
its own default, and two of them still fell back to grok-2, which xAI no longer serves. Changing
the model meant finding every copy; missing one meant two models reading the same job.

ONE SETTING. config.py names the models (XAI_MODEL, XAI_VISION_MODEL, XAI_IMAGE_MODEL) and .env
can override them for one machine. Every caller asks this module, so a change is one line.

    SDI_XAI_MODEL=grok-4.3          in .env goes back to the previous model
    SDI_XAI_VISION_MODEL=...        the drawing reads only, if they must differ
    SDI_XAI_IMAGE_MODEL=...         the quote's artist's impression

A REFUSED MODEL IS SAID ONCE, LOUDLY. When xAI answers that it does not know the model, every
Grok call on the machine fails the same way. The old grok-2 setting failed like that for a whole
session with nothing printed, and the note scan was silently dead. Now the first refusal prints
what was asked, what xAI said, and the command that lists the account's models.

THE CHECK. Run directly, this asks xAI for the account's models (free: no tokens) and says, per
setting, whether the account has it and whether the drawing-read model takes pictures. Exit 0
when every setting is served, 1 when one is not, 2 when xAI could not be asked.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

TEXT_DEFAULT = "grok-4.7"
IMAGE_DEFAULT = "grok-imagine-image-2.0"
_API = "https://api.x.ai/v1"
_REFUSED: set = set()


def _config() -> Any:
    try:
        import config                                                # noqa: WPS433
        return config
    except Exception:                                                # noqa: BLE001
        return None


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def text_model() -> str:
    """Prices, the note scan, the walkthrough's answers: every text-only Grok call."""
    cfg = _config()
    return str(getattr(cfg, "XAI_MODEL", "") or _env("SDI_XAI_MODEL", "XAI_MODEL")
               or TEXT_DEFAULT).strip()


def vision_model() -> str:
    """The drawing reads: the BOM read, the concept read, the whole-pack read."""
    cfg = _config()
    return str(getattr(cfg, "XAI_VISION_MODEL", "")
               or _env("SDI_XAI_VISION_MODEL", "XAI_VISION_MODEL") or text_model()).strip()


def image_model() -> str:
    """The quote's artist's impression."""
    cfg = _config()
    return str(getattr(cfg, "XAI_IMAGE_MODEL", "") or _env("SDI_XAI_IMAGE_MODEL")
               or IMAGE_DEFAULT).strip()


def looks_like_model_refusal(status: Optional[int], detail: str) -> bool:
    """xAI's answer when the model named is not one this account can use."""
    text = str(detail or "").lower()
    if status not in (None, 400, 403, 404):
        return False
    return "model" in text and any(w in text for w in (
        "not found", "does not exist", "not exist", "unknown", "invalid", "not available",
        "no access", "not supported", "deprecated", "retired"))


def note_refusal(model: str, status: Optional[int], detail: str) -> bool:
    """Print once per model when xAI refuses it. True when it was a model refusal."""
    if not looks_like_model_refusal(status, detail):
        return False
    if model not in _REFUSED:
        _REFUSED.add(model)
        print(f"   [xai] xAI REFUSED THE MODEL {model!r}"
              f"{f' (HTTP {status})' if status else ''}: {str(detail)[:200]}. Every Grok call "
              f"using it fails until it is a model this account has. "
              f"Run  python src\\xai_models.py  to list them; set SDI_XAI_MODEL in .env "
              f"(SDI_XAI_MODEL=grok-4.3 is the previous model).", flush=True)
    return True


def note_exception(exc: BaseException, model: str) -> bool:
    """The same, for the OpenAI client's exceptions (they carry status_code and a message)."""
    status = getattr(exc, "status_code", None)
    return note_refusal(model, status if isinstance(status, int) else None, str(exc))


def where_from(env_names: Tuple[str, ...]) -> str:
    name = next((n for n in env_names if os.environ.get(n, "").strip()), "")
    return f".env or shell ({name})" if name else "config.py default"


def _get(path: str, key: str) -> Dict[str, Any]:
    import urllib.request                                            # noqa: WPS433
    req = urllib.request.Request(f"{_API}{path}", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _entries(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = doc.get("models") if isinstance(doc.get("models"), list) else doc.get("data")
    return [r for r in rows or [] if isinstance(r, dict) and r.get("id")]


def account_models(key: str, fetch: Any = None) -> Dict[str, Dict[str, Any]]:
    """{name: {"id", "kind", "input"}} for every model and alias the account lists."""
    fetch = fetch or _get
    found: Dict[str, Dict[str, Any]] = {}
    for path, kind in (("/language-models", "language"), ("/image-generation-models", "image")):
        try:
            rows = _entries(fetch(path, key))
        except Exception:                                            # noqa: BLE001
            continue
        for row in rows:
            entry = {"id": str(row["id"]), "kind": kind,
                     "input": [str(m) for m in row.get("input_modalities") or []]}
            for name in [row["id"], *(row.get("aliases") or [])]:
                found.setdefault(str(name), entry)
    if not found:
        for row in _entries(fetch("/models", key)):                 # the plain list, ids only
            found.setdefault(str(row["id"]), {"id": str(row["id"]), "kind": "", "input": []})
    return found


def check(key: str, fetch: Any = None) -> Tuple[int, List[str]]:
    """(exit code, lines) for the three settings against what the account serves."""
    settings = [
        ("Text (prices, notes, answers)", text_model(), ("SDI_XAI_MODEL", "XAI_MODEL"), "text"),
        ("Vision (drawing reads)", vision_model(),
         ("SDI_XAI_VISION_MODEL", "XAI_VISION_MODEL", "SDI_XAI_MODEL", "XAI_MODEL"), "image"),
        ("Image (artist's impression)", image_model(), ("SDI_XAI_IMAGE_MODEL",), ""),
    ]
    lines = [f"{label:32} {model:28} from {where_from(env)}" for label, model, env, _ in settings]
    if not key:
        return 2, lines + ["", "XAI_API_KEY is not set on this machine: nothing can be checked."]
    try:
        served = account_models(key, fetch)
    except Exception as exc:                                         # noqa: BLE001
        return 2, lines + ["", f"xAI could not be asked: {type(exc).__name__}: {str(exc)[:160]}"]
    code = 0
    lines.append("")
    for label, model, _env_names, needs in settings:
        hit = served.get(model)
        if hit is None:
            code = 1
            lines.append(f"NOT SERVED  {model}: this account does not list it. {label} calls "
                         f"will be refused.")
        elif needs and hit["input"] and needs not in hit["input"]:
            code = 1
            lines.append(f"NO {needs.upper()} INPUT  {model} is served but does not take "
                         f"{needs}s. Set a model that does for {label}.")
        else:
            alias = f" (alias of {hit['id']})" if hit["id"] != model else ""
            lines.append(f"OK          {model}{alias}")
    names = sorted({e["id"] for e in served.values()})
    lines += ["", "This account serves: " + (", ".join(names) or "nothing listed")]
    if code:
        lines.append("Fix: set SDI_XAI_MODEL (and SDI_XAI_IMAGE_MODEL) in .env to a served "
                     "model, then restart the services and the runner.")
    return code, lines


def main() -> int:
    _config()                                    # loads .env, so XAI_API_KEY is there
    code, lines = check(os.environ.get("XAI_API_KEY", "").strip())
    print("\n".join(lines), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
