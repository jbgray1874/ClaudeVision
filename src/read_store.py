"""A read made once is kept, keyed on everything that would change its answer (D-554).

James Gray, 20 Oct 2026: "can we not re use / cache file or otherwise store enough data to
prevent from re running all the same processes in full for every drawing set ... to prevent a
full llm re-run also if we've already passed a drawing to the llm, unless there had been a
coding change or something else requiring it."

THE RAW READING, NOT ITS INTERPRETATION. What a reader is slow at is READING — OCR over a
page, a local vision model over a sheet, a paid model over a pack. What it is fast at is making
sense of what it read. So a store holds the reading, and the interpretation is made again on
every run by whatever code is current: a parser fix, a new rule, a bridge repaired reach every
stored read the next time it is used, with no new read. (The vision BOM store and the concept
store already work this way — they re-parse the stored response — and the whole-pack LLM store
now does too.)

THE KEY IS THE QUESTION. Two reads are the same read when the same bytes were read by the same
code under the same settings, so the key hashes all three:
  - the content: the document's bytes, not its name or path — a redrawn sheet under the same
    filename is a new read; the same sheet copied to a new folder is not;
  - the reader's code: a fingerprint of the reader function's source AND everything it reaches
    in this codebase (fingerprint_code) — a change to a helper three calls down misses, a
    change to an unrelated module does not, and nobody has to remember to bump a version;
  - the settings: the environment knobs and library versions the reader answers under.
A key that leaves one of these out gives back yesterday's answer to today's question, which
is worse than slow.

THE STORE NEVER COSTS THE RUN. A store that cannot be read computes; one that cannot be written
says so once and returns what it computed; the reader's own failure is the run's and is raised
once, untouched. SDI_READ_REFRESH=1 (set by --fresh-read) consults nothing kept and keeps the
new read. SDI_READ_STORE_DIR relocates the store; by default it lives beside the engine under
cache/<store>/, like the LLM stores, on the machine that ran the read.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import inspect
import json
import os
import re
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

SCHEMA = "read_store.v1"
_TRUE = {"1", "true", "yes", "on"}
_SRC_ROOT = Path(__file__).resolve().parent
_FINGERPRINTS: Dict[Tuple[int, ...], str] = {}
_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
_ATTR = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)")
_PLAIN = (str, bytes, int, float, bool, type(None))


# ── where ───────────────────────────────────────────────────────────────────────────────

def store_dir(store: str) -> Path:
    raw = os.environ.get("SDI_READ_STORE_DIR", "").strip()
    if raw:
        return Path(raw) / store
    try:
        import config
        return Path(config.BASE_DIR) / "cache" / store
    except Exception:                                        # noqa: BLE001
        return _SRC_ROOT.parent / "cache" / store


def refresh_asked() -> bool:
    return os.environ.get("SDI_READ_REFRESH", "").strip().lower() in _TRUE


# ── the reader's code, fingerprinted ───────────────────────────────────────────────────

def _in_src(obj: Any) -> bool:
    try:
        f = inspect.getsourcefile(obj) or inspect.getfile(obj)
    except Exception:                                        # noqa: BLE001
        return False
    if not f:
        return False
    try:
        return str(Path(f).resolve()).startswith(str(_SRC_ROOT) + os.sep)
    except Exception:                                        # noqa: BLE001
        return False


def _stable_repr(value: Any) -> str:
    """repr with sets sorted and patterns spelt out, so the same value fingerprints the same
    in every process."""
    if isinstance(value, (set, frozenset)):
        return "{" + ", ".join(sorted(_stable_repr(v) for v in value)) + "}"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_stable_repr(k)}: {_stable_repr(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        inner = ", ".join(_stable_repr(v) for v in value)
        return f"[{inner}]" if isinstance(value, list) else f"({inner})"
    if isinstance(value, re.Pattern):
        return f"re.compile({value.pattern!r}, {int(value.flags)})"
    return repr(value)


def _closure_sources(root: Any, seen: set, out: List[str], depth: int = 0,
                     label: str = "") -> None:
    """Append the source of `root` and of every function, class or constant IN THIS CODEBASE
    that it names, recursively — so a change anywhere a reader reaches changes the fingerprint,
    and a change anywhere it does not reach leaves it alone."""
    if depth > 16 or root is None:
        return
    if isinstance(root, ModuleType):
        if not _in_src(root):
            return
        ident = ("module", root.__name__)
        if ident in seen:
            return
        seen.add(ident)
        try:
            out.append(f"module {root.__name__}\n{inspect.getsource(root)}")
        except Exception:                                    # noqa: BLE001
            out.append(f"module {root.__name__} <no source>")
        # The functions and classes it imports from sibling modules are part of what it does.
        for name, val in sorted(vars(root).items()):
            if (inspect.isfunction(val) or inspect.isclass(val)) and _in_src(val) \
                    and inspect.getmodule(val) is not root:
                _closure_sources(val, seen, out, depth + 1)
        return
    if inspect.isfunction(root) or inspect.isclass(root):
        if not _in_src(root):
            return
        ident = ("object", root.__module__, root.__qualname__)
        if ident in seen:
            return
        seen.add(ident)
        try:
            src = inspect.getsource(root)
        except Exception:                                    # noqa: BLE001
            out.append(f"{root.__module__}.{root.__qualname__} <no source>")
            return
        out.append(f"{root.__module__}.{root.__qualname__}\n{src}")
        mod = inspect.getmodule(root)
        g = dict(vars(mod)) if mod is not None else {}
        # module.attribute: a sibling module's function or constant, by name.
        for m, attr in sorted(set(_ATTR.findall(src))):
            target = g.get(m)
            if isinstance(target, ModuleType) and _in_src(target) and hasattr(target, attr):
                _closure_sources(getattr(target, attr), seen, out, depth + 1,
                                 label=f"{target.__name__}.{attr}")
        # bare names: this module's own helpers, imported helpers, module-level constants.
        for name in sorted(set(_IDENT.findall(src))):
            if name == root.__name__ or name not in g:
                continue
            val = g[name]
            if isinstance(val, ModuleType):
                continue                     # a module is reached through its attributes, above
            _closure_sources(val, seen, out, depth + 1,
                             label=f"{getattr(mod, '__name__', '?')}.{name}")
        return
    # A constant: its VALUE is the thing the reader depends on.
    if label and (isinstance(root, _PLAIN) or isinstance(root, (list, tuple, dict, set,
                                                                frozenset, re.Pattern))):
        ident = ("const", label)
        if ident in seen:
            return
        seen.add(ident)
        out.append(f"{label} = {_stable_repr(root)}")


def fingerprint_code(*roots: Any) -> str:
    """A short hash of the source of every root and of everything in this codebase it reaches
    — functions, classes, module constants, sibling modules' helpers. Cached per process."""
    key = tuple(id(r) for r in roots)
    hit = _FINGERPRINTS.get(key)
    if hit:
        return hit
    seen: set = set()
    out: List[str] = []
    for r in roots:
        _closure_sources(r, seen, out, label=getattr(r, "__name__", "") or "")
    h = hashlib.sha256()
    for s in sorted(out):
        h.update(s.encode("utf-8", "replace"))
        h.update(b"\x00")
    fp = h.hexdigest()[:16]
    _FINGERPRINTS[key] = fp
    return fp


def library_versions(*names: str) -> Dict[str, Optional[str]]:
    """The installed version of each distribution, or None — a reader under a new OCR or PDF
    library may read differently, so the version is part of the settings."""
    from importlib import metadata
    out: Dict[str, Optional[str]] = {}
    for n in names:
        ver = None
        for candidate in (n, n.lower(), n.replace("-", "_")):
            try:
                ver = metadata.version(candidate)
                break
            except Exception:                                # noqa: BLE001
                continue
        out[n] = ver
    return out


# ── the key ─────────────────────────────────────────────────────────────────────────────

def _chunks(content: Union[bytes, bytearray, Iterable[bytes]]) -> Sequence[bytes]:
    if isinstance(content, (bytes, bytearray)):
        return [bytes(content)]
    return [bytes(c) for c in content]


def content_sha256(content: Union[bytes, bytearray, Iterable[bytes]]) -> str:
    h = hashlib.sha256()
    for c in _chunks(content):
        h.update(c)
        h.update(b"\x00")
    return h.hexdigest()


def key(store: str, *, content: Union[bytes, bytearray, Iterable[bytes]], fingerprint: str,
        context: Optional[Dict[str, Any]] = None) -> str:
    h = hashlib.sha256()
    h.update(store.encode("utf-8"))
    h.update(b"\x00")
    h.update(content_sha256(content).encode("ascii"))
    h.update(b"\x00")
    h.update(str(fingerprint).encode("utf-8"))
    h.update(b"\x00")
    h.update(json.dumps(context or {}, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()


# ── the entries ─────────────────────────────────────────────────────────────────────────

def _path(store: str, k: str) -> Path:
    return store_dir(store) / f"{k}.json"


def get(store: str, k: str) -> Optional[Dict[str, Any]]:
    """The kept entry for this key, or None — also None when a fresh read was asked for."""
    if refresh_asked():
        return None
    p = _path(store, k)
    try:
        if not p.exists():
            return None
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return None                      # a corrupt entry is a miss, and is rewritten below
    if isinstance(obj, dict) and obj.get("schema") == SCHEMA and "raw" in obj:
        return obj
    return None


def _build() -> Optional[str]:
    try:
        import engine_build
        return (engine_build.describe() or {}).get("commit")
    except Exception:                                        # noqa: BLE001
        return None


def put(store: str, k: str, raw: Any, *, components: Dict[str, Any],
        source: str = "") -> Optional[Path]:
    """Keep an entry, whole or not at all (write beside, then rename). Returns the path, or
    None after saying once why nothing was kept."""
    p = _path(store, k)
    entry = {"schema": SCHEMA, "store": store, "key": k,
             "created_utc": _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
             "build": _build(), "source": source, "components": components, "raw": raw}
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entry, fh, ensure_ascii=False, default=str)
        os.replace(tmp, p)
        return p
    except Exception as exc:                                 # noqa: BLE001
        try:
            tmp.unlink()
        except Exception:                                    # noqa: BLE001
            pass
        print(f"   [read-store] {store}: could not keep the read for {source or k[:12]} "
              f"({type(exc).__name__}: {exc}) — this run has it; the next will read again",
              flush=True)
        return None


def _count(store: str, hit: bool) -> None:
    try:
        import run_timing
        run_timing.reuse(store, hit)
    except Exception:                                        # noqa: BLE001
        pass


def reuse(store: str, *, content: Union[bytes, bytearray, Iterable[bytes]], fingerprint: str,
          compute: Callable[[], Any], context: Optional[Dict[str, Any]] = None,
          keep: Optional[Callable[[Any], bool]] = None,
          thin: Optional[Callable[[Any], Any]] = None, source: str = "") -> Dict[str, Any]:
    """The reading for this question: given back from the store when it holds one, else made by
    `compute` and kept. Returns {'raw', 'hit', 'key', 'path', 'created_utc', 'build'}.

    `keep(raw)` may say a reading is not worth keeping (a local model that never answered); it
    is still used this run. `thin(raw)` is what to keep when the stored form should be smaller
    than the used one. Store trouble never costs the run; compute's own exception is raised
    once, untouched."""
    k: Optional[str] = None
    hit: Optional[Dict[str, Any]] = None
    try:
        k = key(store, content=content, fingerprint=fingerprint, context=context)
        hit = get(store, k)
    except Exception:                                        # noqa: BLE001
        hit = None
    if hit is not None:
        _count(store, True)
        return {"raw": hit["raw"], "hit": True, "key": k, "path": str(_path(store, k)),
                "created_utc": hit.get("created_utc"), "build": hit.get("build")}
    raw = compute()                 # outside every try: its failure is the run's, not the store's
    _count(store, False)
    path: Optional[Path] = None
    if k is not None:
        try:
            worth = True if keep is None else bool(keep(raw))
        except Exception:                                    # noqa: BLE001
            worth = False
        if worth:
            try:
                stored = thin(raw) if thin is not None else raw
                path = put(store, k, stored, source=source,
                           components={"content_sha256": content_sha256(content),
                                       "fingerprint": fingerprint, "context": context or {}})
            except Exception:                                # noqa: BLE001
                path = None
    return {"raw": raw, "hit": False, "key": k, "path": str(path) if path else None,
            "created_utc": None, "build": None}
