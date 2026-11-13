r"""
sw_docmgr_analyse.py
The BACKUP reader: .SLDPRT / .SLDASM / .SLDDRW read through the SOLIDWORKS Document Manager
API, for a machine where the full SolidWorks COM API (sw_native_analyse.py) cannot run.

WHAT IT IS FOR. The production extractor needs Windows and a licensed SolidWorks seat, and a
seat is not always there: the licence is in use on somebody's desktop, the estimate is running
on a server, the analyser has been switched off on a designer's workstation. Without it a job
whose models sit beside its drawings is costed from the drawings alone. Document Manager is a
separate COM library (SwDocumentMgr) that reads the SolidWorks files themselves, headless — no
SolidWorks running, no seat, only a licence KEY issued by Dassault. docs/solidworks_integration_
design.md has always named it phase 1 for exactly this.

WHAT IT CANNOT DO, AND THE RULE THAT FOLLOWS FROM IT. It reads what was SAVED in the file. It
never rebuilds a model, so it measures nothing: no bounding box, no volume, no surface area, no
flattening of a formed part. A mass or a flat pattern exists only if SolidWorks saved one into a
property or a cut list. Every field it cannot supply is written null and named in the record's
`not_saved` list with the sentence "not saved in the file; only the SolidWorks worker measures it" — never
inferred from something nearby. A formed sheet-metal part with no saved flat pattern is marked
`needs_solidworks_worker`, because its developed blank is the one number this reader cannot
produce and the estimate must not be priced on a guess at it.

THE SAME SCHEMA. Records have exactly the shape sw_native_analyse.py writes —
{path, title, doctype, custom_properties, bbox_mm, bom, route_signals, errors, ...} — so
source_connectors.solidworks.normalize_native_extract consumes them unchanged. Two additions
mark where they came from: `"reader": "solidworks_docmgr"` on every record and in the manifest.
The consumer applies values from such a record under source `solidworks_docmgr`, ranked below
a SolidWorks COM measurement and below a DXF, so it can fill a gap and never displace either.

WHY THE MISSING FIELDS ARE NOTES AND NOT `errors`. The consumer counts a record with any entry
in `errors` as a FAILED read (files_failed, extract_incomplete). Every Document Manager record
lacks a bounding box by construction, so writing that as an error would report a complete,
successful read as a total failure. `errors` keeps its meaning — the file could not be opened
or read — and what was simply never saved goes in `not_saved` and `notes`.

THE KEY. Read from SDI_SW_DOCMGR_KEY and handed to GetApplication. It is never printed, never
logged, never written to the extract, never put on a command line (the consumer passes it to
this process through the inherited environment, not argv). Every line this tool prints and the
JSON it writes go through redact(), so an exception that happens to echo the key is cleaned
before anyone sees it.

UNVERIFIED SIGNATURES. This file was written on Linux with no SolidWorks. Every Document
Manager call is isolated in one small function in the COM SEAM section, and each says what it
assumes. The method NAMES are the documented ones; the calling convention (which arguments come
back as [out] parameters, which members pywin32 exposes as properties) is what needs checking
on a Windows machine. Tests drive everything through a fake COM object injected at main().

Usage (Windows, SOLIDWORKS Document Manager installed, SDI_SW_DOCMGR_KEY set):
  python sw_docmgr_analyse.py "<folder or model file>" [--out <json path>]
Writes _sw_docmgr_extract.json next to the target. Exit codes as sw_native_analyse.py:
0 at least one file read, 1 nothing read (or the files changed mid-run), 2 setup problem.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ONE COPY OF EVERY PURE RULE. The cut-list property names, the millimetre and count readers,
# the weldment profile parse, the discovery and exclusion rule and the fingerprint all live in
# the production extractor. A second copy here is how the two readers would come to disagree
# about what a cut list says or which folder is the live design — the defect this codebase has
# already paid for with two exclusion lists. sw_native_analyse imports COM lazily, so importing
# it here costs nothing on a machine without pywin32.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import sw_native_analyse as _nat  # noqa: E402

READER = "solidworks_docmgr"
KEY_ENV = "SDI_SW_DOCMGR_KEY"
DM_PROGID = "SwDocumentMgr.SwDMClassFactory"
EXTRACT_FILENAME = "_sw_docmgr_extract.json"
# The DATA schema is the production extractor's: the consumer's re-extract gate compares this
# number, and a backup extract must answer it the same way.
EXTRACT_SCHEMA_VERSION = _nat.EXTRACT_SCHEMA_VERSION
NOT_SAVED = "not saved in the file; only the SolidWorks worker measures it"

SW_PART, SW_ASM, SW_DRW = _nat.SW_PART, _nat.SW_ASM, _nat.SW_DRW
DOCTYPE = dict(_nat.DOCTYPE)

# SwDmDocumentOpenError, as the Document Manager documents it. UNVERIFIED numbering: the names
# are the documented ones, the integers are the documented order. Anything not listed is
# reported by its number.
_OPEN_ERRORS = {
    1: "the Document Manager could not open the file",
    2: "the file is not a SolidWorks document",
    3: "the file was not found",
    4: "the file is read-only and could not be opened read-only",
    5: "the Document Manager licence key was refused",
    6: "the file was saved by a newer SolidWorks than this Document Manager reads",
}

# Fields a Document Manager read never has, whatever was saved: they are computed by a rebuild.
_NEVER_SAVED = ("bounding box", "volume", "surface area")
# Assemblies nest; a reference loop or a pathological tree must not hang a batch.
_MAX_ASSEMBLY_DEPTH = 20


# ── the key never leaves this process ─────────────────────────────────────────────────


def reader_build() -> str:
    """This reader's identity: the first 12 hex of the SHA-256 of its own source."""
    try:
        import hashlib
        with open(os.path.abspath(__file__), "rb") as fh:
            return "sw_docmgr_analyse " + hashlib.sha256(fh.read()).hexdigest()[:12]
    except Exception:                                                # noqa: BLE001
        return "sw_docmgr_analyse (build unreadable)"

def _key_from_env() -> str:
    return (os.environ.get(KEY_ENV) or "").strip()


def _load_engine_env() -> None:
    """Run by hand, read the engine's own .env for the key, as an engine run does (D-710):
    the checkout's .env, then src\\.env. A key already in this shell wins. The key is never
    printed; only whether it was found is said."""
    if _key_from_env():
        return
    try:
        from dotenv import load_dotenv                               # noqa: PLC0415
    except ImportError:
        return
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / ".env", here.parents[2] / "src" / ".env"):
        try:
            if candidate.exists():
                load_dotenv(candidate, override=False)
                if _key_from_env():
                    return
        except OSError:
            continue


def redact(text: Any, key: Optional[str] = None) -> str:
    """`text` with the licence key removed. Applied to every printed line and the JSON.

    A Document Manager key is a long comma-separated list of product grants. The whole key and
    each grant are removed, so an error message that echoes one grant is cleaned too. Fragments
    shorter than eight characters are left alone: they cannot identify a key, and replacing
    them would mangle ordinary words."""
    s = "" if text is None else str(text)
    k = _key_from_env() if key is None else str(key or "").strip()
    if not k:
        return s
    frags = {k} | {f.strip() for f in re.split(r"[,;]", k)}
    for frag in sorted(frags, key=len, reverse=True):
        if len(frag) >= 8:
            s = s.replace(frag, f"[{KEY_ENV}]")
    return s


def _str(v: Any) -> str:
    return "" if v is None else str(v).strip()


# ── COM SEAM ──────────────────────────────────────────────────────────────────────────
#
# Every call into the Document Manager is below, one small function each, so a test can hand
# main() a fake class factory and so the calls that need checking on a Windows machine are in
# one place. "UNVERIFIED" marks a calling convention that could not be exercised here.

# NEWER INTERFACES OF THE SAME OBJECT. Under early binding pywin32 wraps a returned object in
# the interface its method DECLARES, and Document Manager grew by adding numbered interfaces
# (ISwDMDocument10 has the tables, ISwDMConfiguration16 the newer cut list). A member missing
# from the declared wrapper may be one CastTo away. UNVERIFIED: which numbered interface first
# carries each member; the candidates are tried newest first and a failed cast costs nothing.
_DOC_IFACES = ("ISwDMDocument10", "ISwDMDocument8", "ISwDMDocument5", "ISwDMDocument")
_CFG_IFACES = ("ISwDMConfiguration16", "ISwDMConfiguration5", "ISwDMConfiguration2",
               "ISwDMConfiguration")
_COMP_IFACES = ("ISwDMComponent6", "ISwDMComponent2", "ISwDMComponent")
_CUT_IFACES = ("ISwDMCutListItem2", "ISwDMCutListItem")

# HOW THIS RUN REACHED THE LIBRARY (D-711). pywin32 needs IDispatch; on JG's laptop (5 Nov 2026)
# Dispatch("SwDocumentMgr.SwDMClassFactory") answered "No such interface supported", the class
# factory having no IDispatch. comtypes binds to the interface itself, from the type library
# the Document Manager registers, so it is the second route. `types` is that generated module.
_BINDING: Dict[str, Any] = {"via": "", "types": None}


# --trace (D-713): what each call into the library answered, per file, so a reading that comes
# back empty can be traced to the call that returned nothing. None when tracing is off.
_TRACE: Optional[List[str]] = None


def _t(msg: str) -> None:
    if _TRACE is not None and len(_TRACE) < 200:
        _TRACE.append(msg)


def _shape(v: Any) -> str:
    """What a call returned, in a few words, never its content."""
    if v is None:
        return "None"
    if isinstance(v, (tuple, list)):
        return f"{type(v).__name__} of {len(v)}" + (f" ({type(v[0]).__name__})" if v else "")
    return type(v).__name__


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_com_object(v: Any) -> bool:
    """A COM object, under either binding: never called, only used."""
    if hasattr(v, "_oleobj_"):
        return True
    try:
        import comtypes  # noqa: PLC0415 — Windows only
        return isinstance(v, comtypes.IUnknown)
    except Exception:                                                    # noqa: BLE001
        return False


def _member(obj, name: str, ifaces: Sequence[str] = ()):
    """obj.<name>, or the same member reached through a newer interface of obj; None if
    neither has it. Fakes and late-bound objects answer on the first line."""
    if obj is None:
        return None
    try:
        found = getattr(obj, name)
        return found
    except Exception as exc:                                             # noqa: BLE001
        first = f"{type(exc).__name__}"
    if ifaces and _BINDING.get("via") == "comtypes" and _BINDING.get("types") is not None:
        tried = []
        for iface in ifaces:
            cls = getattr(_BINDING["types"], iface, None)
            if cls is None:
                tried.append(f"{iface}: not in the type library")
                continue
            try:
                found = getattr(obj.QueryInterface(cls), name)
                _t(f"{name}: reached through {iface}")
                return found
            except Exception as exc:                                     # noqa: BLE001
                tried.append(f"{iface}: {type(exc).__name__}")
        _t(f"{name}: not on {type(obj).__name__} ({first}); " + "; ".join(tried))
        return None
    if ifaces or first:
        _t(f"{name}: not on {type(obj).__name__} ({first})")
    if not ifaces or not getattr(_nat, "_COM_AVAILABLE", False):
        return None
    try:
        from win32com.client import CastTo  # noqa: PLC0415 — Windows only
    except Exception:                                                    # noqa: BLE001
        return None
    for iface in ifaces:
        try:
            return getattr(CastTo(obj, iface), name)
        except Exception:                                                # noqa: BLE001
            continue
    return None


def _get(obj, name: str, ifaces: Sequence[str] = ()):
    """A no-argument getter that pywin32 may expose as a method or as a property — the
    production extractor's _get0 rule — reached through _member.

    ONE DIFFERENCE FROM _get0. A property that returns a COM OBJECT (ConfigurationManager)
    hands back a pywin32 dispatch, and a dispatch is itself callable — calling it invokes the
    object's default member, which these interfaces do not have, so the read would raise and
    come back as nothing. A value carrying `_oleobj_` is a COM object and is returned as is."""
    attr = _member(obj, name, ifaces)
    if attr is None or _is_com_object(attr):
        return attr
    try:
        return attr() if callable(attr) else attr
    except Exception as exc:                                             # noqa: BLE001
        _t(f"{name}(): {type(exc).__name__}: {redact(exc)[:160]}")
        return None


def com_available() -> Tuple[bool, str]:
    """Can this Python reach a COM library at all?"""
    if os.name != "nt":
        return False, "this is not a Windows machine, and the Document Manager is a Windows COM library"
    if not getattr(_nat, "_COM_AVAILABLE", False):
        return False, (f"pywin32 is not available in this Python "
                       f"({getattr(_nat, '_COM_IMPORT_ERROR', 'import failed')})")
    return True, ""


def _comtypes_class_factory():
    """(ISwDMClassFactory, its generated type module), through comtypes: the type library is
    found from the class's own registration, its DLL first, then its registered TypeLib
    versions newest first."""
    import comtypes.client as cc  # noqa: PLC0415 — Windows only
    import winreg  # noqa: PLC0415 — Windows only
    hkcr = winreg.HKEY_CLASSES_ROOT
    clsid = winreg.QueryValue(hkcr, DM_PROGID + "\\CLSID")
    sources: List[Any] = []
    try:
        dll = winreg.QueryValue(hkcr, f"CLSID\\{clsid}\\InprocServer32")
        if dll:
            sources.append(os.path.expandvars(dll.strip().strip('"')))
    except OSError:
        pass
    try:
        tlb = winreg.QueryValue(hkcr, f"CLSID\\{clsid}\\TypeLib")
        with winreg.OpenKey(hkcr, f"TypeLib\\{tlb}") as k:
            versions, i = [], 0
            while True:
                try:
                    versions.append(winreg.EnumKey(k, i))
                    i += 1
                except OSError:
                    break

        def _ver(v: str) -> Tuple[int, int]:
            a, _, b = v.partition(".")
            try:
                return int(a, 16), int(b or "0", 16)
            except ValueError:
                return 0, 0
        sources += [(tlb,) + _ver(v) for v in sorted(versions, key=_ver, reverse=True)]
    except OSError:
        pass
    tried: List[str] = []
    for src in sources:
        try:
            mod = cc.GetModule(src)
            return cc.CreateObject(DM_PROGID, interface=mod.ISwDMClassFactory), mod
        except Exception as exc:                                         # noqa: BLE001
            tried.append(f"{src}: {exc}")
    raise RuntimeError("comtypes could not load the Document Manager's type library ("
                       + ("; ".join(tried) or "none is registered for " + DM_PROGID) + ")")


def dispatch_class_factory():
    """The ISwDMClassFactory, by pywin32 or else by comtypes (D-711).

    pywin32 early binding first: the generated wrappers return [out] parameters as tuples,
    which is what GetDocument's open-error needs; then late binding, under which open_document
    passes a by-reference VARIANT. Where the class factory has no IDispatch, neither can reach
    it, and comtypes binds to the interface from its type library. [out] parameters come back
    as tuples there too. `_BINDING` records which route answered."""
    first = ""
    try:
        import win32com.client  # noqa: PLC0415 — Windows only
        for how in (win32com.client.gencache.EnsureDispatch, win32com.client.Dispatch):
            try:
                factory = how(DM_PROGID)
                _BINDING.update(via="pywin32", types=None)
                return factory
            except Exception as exc:                                     # noqa: BLE001
                first = first or f"{type(exc).__name__}: {exc}"
    except ImportError as exc:
        first = f"pywin32 is not available ({exc})"
    try:
        import comtypes.client  # noqa: F401,PLC0415 — Windows only
    except ImportError:
        raise RuntimeError(
            f"pywin32 cannot reach it ({first}), and comtypes, the second route, is not "
            f"installed in this Python. Install it once:  .venv\\Scripts\\python.exe -m pip "
            f"install comtypes") from None
    factory, mod = _comtypes_class_factory()
    _BINDING.update(via="comtypes", types=mod)
    _enable_interface_arrays()
    return factory


def _enable_interface_arrays() -> None:
    """Let comtypes unpack an array of interface pointers (D-714).

    GetComponents and GetCutListItems return a SAFEARRAY of VT_UNKNOWN (13). comtypes maps each
    element type it unpacks through a table that, here, had no entry for 13, so both calls
    raised KeyError: 13 on the laptop (5 Nov 2026) and every assembly read as having no
    components and every cut list as absent. The entries name the plain interface pointer;
    each element is then reached through its own interface by QueryInterface, as before."""
    try:
        from ctypes import POINTER  # noqa: PLC0415
        import comtypes  # noqa: PLC0415 — Windows only
        import comtypes.automation as au  # noqa: PLC0415
        au._vartype_to_ctype.setdefault(au.VT_UNKNOWN, POINTER(comtypes.IUnknown))
        au._vartype_to_ctype.setdefault(au.VT_DISPATCH, POINTER(au.IDispatch))
    except Exception:                                                    # noqa: BLE001
        pass


def open_application(factory, key: str):
    """ISwDMClassFactory.GetApplication(LicenseKey) -> ISwDMApplication."""
    return factory.GetApplication(key)


def docmgr_version(app) -> str:
    """ISwDMApplication.GetLatestSupportedFileVersion() — the newest file version this
    Document Manager reads. Recorded in the manifest; absent is not an error. UNVERIFIED:
    exposed as a method or a property depending on binding, so read through _get0."""
    v = _get(app, "GetLatestSupportedFileVersion")
    return _str(v)


def _retval_first(r: Any) -> Any:
    """A method's outputs with its [out, retval] FIRST, whichever binding returned them (D-712).

    pywin32's early binding returns (retval, out1, out2, ...); comtypes returns the [out]
    parameters in order and the retval LAST: (out1, out2, ..., retval). On the laptop's first
    comtypes run (5 Nov 2026) GetDocument came back (result, document), the reader took the
    document pointer for the open-error number, and int() of the pointer's raw bytes failed on
    all 12 files. Every unpacking below reads through this, so one rule serves both bindings."""
    if _BINDING.get("via") == "comtypes" and isinstance(r, tuple) and len(r) > 1:
        return (r[-1],) + tuple(r[:-1])
    return r


def _is_null(obj: Any) -> bool:
    """A NULL interface pointer, as comtypes returns for "no document": not None, but empty."""
    if obj is None:
        return True
    if _BINDING.get("via") != "comtypes":
        return False
    try:
        return not bool(obj)
    except Exception:                                                    # noqa: BLE001
        return False


def open_document(app, path: str, doctype: int) -> Tuple[Any, int]:
    """ISwDMApplication.GetDocument(FullPathName, docType, allowReadOnly, out Result)
    -> (ISwDMDocument or None, SwDmDocumentOpenError).

    UNVERIFIED CALLING CONVENTION. Opened with allowReadOnly=True: this tool never writes a
    file. Under early binding the [out] Result comes back with the document as a tuple
    (doc, result); under late binding pywin32 cannot see the [out] parameter, so a by-reference
    VARIANT is passed and read back. Both forms are tried; the first that answers wins."""
    first_exc: Optional[BaseException] = None
    try:
        r = _retval_first(app.GetDocument(path, int(doctype), True))
        if isinstance(r, (tuple, list)):
            doc = r[0] if r else None
            err = r[1] if len(r) > 1 else None
            # THE DOCUMENT IS THE OBJECT, THE RESULT IS THE NUMBER (D-712), told apart by what
            # they are and not only by where they sit: a status is an int and a document
            # never is. int() is never applied to anything that is not already a number.
            if _is_int(doc) and not _is_int(err):
                doc, err = err, doc
        else:
            doc, err = r, None
        if _is_null(doc):
            doc = None
        if not _is_int(err):
            err = 0 if doc is not None else 1
        return doc, int(err)
    except Exception as exc:                                             # noqa: BLE001
        first_exc = exc
    try:
        import pythoncom  # noqa: PLC0415 — Windows only
        from win32com.client import VARIANT  # noqa: PLC0415
        holder = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        doc = app.GetDocument(path, int(doctype), True, holder)
        return doc, int(holder.value or 0)
    except Exception:                                                    # noqa: BLE001
        if first_exc is not None:
            raise first_exc
        raise


def close_document(doc) -> None:
    """ISwDMDocument.CloseDoc() — releases the file handle. Nothing is ever saved."""
    try:
        doc.CloseDoc()
    except Exception:                                                    # noqa: BLE001
        pass


def _string_list(v: Any) -> List[str]:
    if v is None or isinstance(v, (str, bytes)):
        return [str(v)] if isinstance(v, str) and v.strip() else []
    try:
        return [str(x) for x in list(v) if x is not None and str(x).strip()]
    except TypeError:
        return []


def custom_property_names(obj) -> List[str]:
    """GetCustomPropertyNames() on ISwDMDocument, ISwDMConfiguration or ISwDMCutListItem2.
    Returns an array of names, or nothing when the object holds no properties."""
    if obj is None:
        return []
    return _string_list(_get(obj, "GetCustomPropertyNames"))


def _unpack_property(r: Any) -> Tuple[Optional[str], str]:
    """(value, linked expression) from whatever shape a property getter returned.

    Early binding returns (value, [out] type, [out] linkedTo) — or (value, type) for the older
    getters; a bare string is a value with no expression. A bare number is a STATUS or a TYPE,
    never the value (the lesson sw_native_analyse learned when a status code of 1 became a
    1.0mm blank), so it is refused."""
    if r is None:
        return None, ""
    if isinstance(r, str):
        return r.strip(), ""
    r = _retval_first(r)
    if isinstance(r, (tuple, list)):
        if not r or not isinstance(r[0], str):
            return None, ""
        linked = next((x for x in r[1:] if isinstance(x, str)), "")
        return r[0].strip(), (linked or "").strip()
    return None, ""


def custom_property(obj, name: str) -> Tuple[str, str]:
    """(evaluated value, linked expression) of one custom property.

    UNVERIFIED. The getters, newest first, and the interface each belongs to:
      GetCustomPropertyValues(name)   ISwDMDocument5 / ISwDMConfiguration5 — value; [out] type,
                                      [out] linkedTo (the text expression, "SW-Material@...")
      GetCustomPropertyValue2(name)   ISwDMCutListItem2 — value; [out] type, [out] linkedTo
      GetCustomPropertyValue(name)    ISwDMCutListItem — value; [out] type, [out] linkedTo
      GetCustomProperty(name)         ISwDMDocument / ISwDMConfiguration — value; [out] type
    The VALUE is the one SolidWorks evaluated and saved; the linked expression is what tells a
    material the designer typed from one linked to the library's applied material. Returns
    ("", "") when no getter answers."""
    if obj is None:
        return "", ""
    for meth in ("GetCustomPropertyValues", "GetCustomPropertyValue2",
                 "GetCustomPropertyValue", "GetCustomProperty"):
        fn = _member(obj, meth, _DOC_IFACES + _CFG_IFACES + _CUT_IFACES)
        if fn is None or not callable(fn):
            continue
        try:
            r = fn(name)
        except Exception:                                                # noqa: BLE001
            continue
        val, linked = _unpack_property(r)
        if val is not None:
            return val, linked
    return "", ""


def configuration_manager(doc):
    """ISwDMDocument.ConfigurationManager -> ISwDMConfigurationMgr (a property)."""
    return _get(doc, "ConfigurationManager")


def configuration_names(doc) -> List[str]:
    """ISwDMConfigurationMgr.GetConfigurationNames()."""
    return _string_list(_get(configuration_manager(doc), "GetConfigurationNames"))


def active_configuration_name(doc) -> str:
    """ISwDMConfigurationMgr.GetActiveConfigurationName() — the configuration the file was
    saved in, which is the one the COM analyser reads when it opens the document."""
    return _str(_get(configuration_manager(doc), "GetActiveConfigurationName"))


def get_configuration(doc, name: str):
    """ISwDMConfigurationMgr.GetConfigurationByName(name) -> ISwDMConfiguration."""
    cm = configuration_manager(doc)
    _t(f"ConfigurationManager -> {_shape(cm)}")
    if cm is None or not name:
        return None
    try:
        cfg = cm.GetConfigurationByName(name)
        _t(f"GetConfigurationByName({name!r}) -> {_shape(cfg)}")
        return None if _is_null(cfg) else cfg
    except Exception as exc:                                             # noqa: BLE001
        _t(f"GetConfigurationByName({name!r}): {type(exc).__name__}: {redact(exc)[:160]}")
        return None


class Unreadable(RuntimeError):
    """A part of the file the reader needs and could not read: an assembly's components. The
    file is then a FAILED read, never an empty success (D-714)."""


def _answer(obj, names: Sequence[str], ifaces: Sequence[str]) -> Tuple[bool, Any]:
    """(answered, value) for the first of `names` the object answers. answered is False when
    every one is missing or raised: the library could not be asked, which is not the same as
    the library saying there is nothing."""
    for meth in names:
        fn = _member(obj, meth, ifaces)
        if fn is None:
            continue
        try:
            v = fn() if callable(fn) and not _is_com_object(fn) else fn
        except Exception as exc:                                         # noqa: BLE001
            _t(f"{meth}(): {type(exc).__name__}: {redact(exc)[:160]}")
            continue
        _t(f"{meth} -> {_shape(v)}")
        return True, v
    return False, None


def configuration_components(cfg) -> Optional[List[Any]]:
    """ISwDMConfiguration2.GetComponents() -> ISwDMComponent[] for this configuration.

    UNVERIFIED: documented as the components of the configuration; this reader assumes TOP
    LEVEL ONLY and walks sub-assemblies by opening them (walk_assembly). If a Windows check
    shows it returns every level, walk_assembly must stop recursing or counts double."""
    if cfg is None:
        _t("GetComponents: no configuration to ask")
        return None
    answered, v = _answer(cfg, ("GetComponents",), _CFG_IFACES)
    if not answered:
        return None
    if v is None or isinstance(v, (str, bytes)):
        return []
    try:
        return list(v)
    except TypeError:
        return []


def component_info(comp) -> Dict[str, Any]:
    """What one ISwDMComponent says about itself.

    UNVERIFIED member spellings: PathName (the referenced file as last saved), Name2 (instance
    name, ISwDMComponent6+; Name on older interfaces), ConfigurationName (the referenced
    configuration), DocumentType (SwDmDocumentType), IsSuppressed() (ISwDMComponent2+)."""
    name = _str(_get(comp, "Name2", _COMP_IFACES)) or _str(_get(comp, "Name", _COMP_IFACES))
    try:
        doc_type = int(_get(comp, "DocumentType", _COMP_IFACES))
    except (TypeError, ValueError):
        doc_type = None
    suppressed = _get(comp, "IsSuppressed", _COMP_IFACES)
    # EXCLUDED FROM THE PARTS LIST, where the library says so. UNVERIFIED member name: a
    # release that does not answer leaves it unknown, and the drawing's own parts list decides
    # instead (reconcile_with_drawings).
    excluded = _get(comp, "ExcludeFromBOM", _COMP_IFACES)
    _path = _str(_get(comp, "PathName", _COMP_IFACES))
    _t(f"component {type(comp).__name__}: name={name!r} path={'set' if _path else 'EMPTY'} "
       f"suppressed={suppressed!r}")
    return {
        "path": _path,
        "name": name,
        "config": _str(_get(comp, "ConfigurationName", _COMP_IFACES)),
        "doc_type": doc_type,
        "suppressed": bool(suppressed) if suppressed is not None else False,
        "excluded_from_bom": excluded is True or (isinstance(excluded, int)
                                                  and not isinstance(excluded, bool)
                                                  and excluded == 1),
    }


def cut_list_items(cfg) -> Optional[List[Any]]:
    """The configuration's saved cut list: ISwDMConfiguration16.GetCutListItems2(), or
    ISwDMConfiguration2.GetCutListItems() on older interfaces. UNVERIFIED which name a given
    Document Manager release answers; both are tried. Empty when the file saved none — a part
    that is not sheet metal, a weldment or multi-body has no cut list."""
    if cfg is None:
        _t("cut list: no configuration to ask")
        return None
    any_answered = False
    for meth in ("GetCutListItems2", "GetCutListItems"):
        answered, v = _answer(cfg, (meth,), _CFG_IFACES)
        if not answered:
            continue
        any_answered = True
        if v is None or isinstance(v, (str, bytes)):
            continue
        try:
            items = list(v)
        except TypeError:
            continue
        if items:
            return items
    return [] if any_answered else None


def cut_list_item_info(item) -> Dict[str, Any]:
    """ISwDMCutListItem: Name and Quantity (properties)."""
    try:
        qty = float(_get(item, "Quantity"))
    except (TypeError, ValueError):
        qty = None
    return {"name": _str(_get(item, "Name")), "quantity": qty}


def external_references(app, doc) -> List[str]:
    """ISwDMDocument.GetAllExternalReferences(ISwDMSearchOption) -> the files this document
    references, as their paths were last saved.

    UNVERIFIED: the search option comes from ISwDMApplication.GetSearchOptionObject(); newer
    interfaces add GetAllExternalReferences4(option, out broken, out virtual, out timestamps),
    whose first return element is the same list. Recorded for audit — the assembly BOM comes
    from the components, which carry quantities and configurations."""
    try:
        opt = app.GetSearchOptionObject()
    except Exception:                                                    # noqa: BLE001
        opt = None
    for meth in ("GetAllExternalReferences4", "GetAllExternalReferences"):
        fn = _member(doc, meth, _DOC_IFACES)
        if fn is None or not callable(fn):
            continue
        try:
            r = _retval_first(fn(opt))
        except Exception:                                                # noqa: BLE001
            continue
        if isinstance(r, tuple) and r and not isinstance(r[0], str):
            r = r[0]
        refs = _string_list(r)
        if refs:
            return refs
    return []


# SwDmTableType for a bill of materials. UNVERIFIED: the enumeration's integer values could not
# be checked here, so every small value is asked and the RESULT is filtered by shape instead
# (bom_from_table_rows keeps a table only when its header names a part column and a quantity
# column). A revision block or a general note table therefore cannot be read as a BOM whatever
# number it answers to.
_DM_TABLE_TYPE_CANDIDATES = tuple(range(0, 8))


def drawing_tables(doc) -> List[Any]:
    """Table annotations saved in a drawing: ISwDMDocument10.GetTableNames(SwDmTableType) and
    ISwDMDocument10.GetTable(name) -> ISwDMTable. UNVERIFIED (see the candidates above)."""
    seen: Dict[str, Any] = {}
    fn_names = _member(doc, "GetTableNames", _DOC_IFACES)
    fn_get = _member(doc, "GetTable", _DOC_IFACES)
    if not callable(fn_names) or not callable(fn_get):
        return []
    for t in _DM_TABLE_TYPE_CANDIDATES:
        try:
            names = _string_list(fn_names(t))
        except Exception:                                                # noqa: BLE001
            continue
        for n in names:
            if n in seen:
                continue
            try:
                tbl = fn_get(n)
            except Exception:                                            # noqa: BLE001
                tbl = None
            if tbl is not None:
                seen[n] = tbl
    return list(seen.values())


def table_rows(table) -> List[List[str]]:
    """Every cell of an ISwDMTable as rows of text, header row first.

    UNVERIFIED member names. Sizes are read from RowCount/ColumnCount or GetRowCount()/
    GetColumnCount(); cells from GetColumn(col) (a whole column) or GetCellText(row, col).
    Whichever answers is used; a table nothing can be read from yields no rows, never a guess."""
    def _count(*names) -> int:
        for n in names:
            v = _get(table, n)
            try:
                if v is not None:
                    return int(v)
            except (TypeError, ValueError):
                continue
        return 0
    rows, cols = _count("RowCount", "GetRowCount"), _count("ColumnCount", "GetColumnCount")
    if cols <= 0:
        return []
    columns: List[List[str]] = []
    get_col = _member(table, "GetColumn")
    if callable(get_col):
        for c in range(cols):
            try:
                columns.append([_str(x) for x in (get_col(c) or [])])
            except Exception:                                            # noqa: BLE001
                columns = []
                break
    if columns and any(columns):
        height = max(len(c) for c in columns)
        return [[(col[r] if r < len(col) else "") for col in columns] for r in range(height)]
    get_cell = _member(table, "GetCellText")
    if not callable(get_cell) or rows <= 0:
        return []
    out: List[List[str]] = []
    for r in range(rows):
        row = []
        for c in range(cols):
            try:
                row.append(_str(get_cell(r, c)))
            except Exception:                                            # noqa: BLE001
                row.append("")
        out.append(row)
    return out


# ── PURE: what the saved data says ────────────────────────────────────────────────────

def read_properties(obj) -> Dict[str, Dict[str, str]]:
    """{name: {"value", "linked_to"}} for every custom property on a document, configuration
    or cut-list item."""
    out: Dict[str, Dict[str, str]] = {}
    for n in custom_property_names(obj):
        v, linked = custom_property(obj, n)
        out[n] = {"value": v, "linked_to": linked}
    return out


def _values(props: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    return {k: _str((v or {}).get("value")) for k, v in (props or {}).items()}


def _prop_entry(props: Dict[str, Dict[str, str]], *aliases: str) -> Tuple[str, Dict[str, str]]:
    """(property name, entry) for the first alias that has a value — the same exact-then-
    contains matching as sw_native_analyse._prop, returning WHICH property answered so its
    linked expression can be read."""
    low = {str(k).lower().strip(): (k, v) for k, v in (props or {}).items()}
    for a in aliases:
        hit = low.get(a.lower().strip())
        if hit and _str((hit[1] or {}).get("value")):
            return hit[0], hit[1]
    for a in aliases:
        al = a.lower().strip()
        for k_low, (k, v) in low.items():
            if al in k_low and _str((v or {}).get("value")):
                return k, v
    return "", {}


# A value that is still the EXPRESSION, not its evaluation: '"SW-Material@part.SLDPRT"'. A file
# saved without the evaluated text leaves the link itself in the value field; reading that as a
# material would put a file name where a material belongs.
_UNEVALUATED_LINK = re.compile(r'^\s*"?\s*SW-[^@"]*@', re.IGNORECASE)


def _is_unevaluated_link(value: str) -> bool:
    return bool(_UNEVALUATED_LINK.match(str(value or "")))


_COUNT_KEYS = {"cut_out_count", "bend_count", "hole_count"}


def parse_cut_list(props: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """The cut-list values the production extractor reads, from saved properties.

    Same property names (_nat._CUTLIST_KEYS / _CUTLIST_TEXT_KEYS), same readers: lengths
    through _num_mm (a zero length is a failed read), counts through _num_count (a zero count
    is a statement). Matched by name, case-insensitively."""
    low = {str(k).strip().lower(): _str((v or {}).get("value")) for k, v in (props or {}).items()}
    out: Dict[str, Any] = {}
    for key, candidates in _nat._CUTLIST_KEYS.items():
        for cand in candidates:
            raw = low.get(cand.lower())
            if raw is None:
                continue
            val = _nat._num_count(raw) if key in _COUNT_KEYS else _nat._num_mm(raw)
            if val is not None:
                out[key] = val
                break
    for key, candidates in _nat._CUTLIST_TEXT_KEYS.items():
        for cand in candidates:
            raw = low.get(cand.lower())
            if raw:
                out[key] = raw
                break
    return out


def classify_cut_list(props: Dict[str, Dict[str, str]]) -> str:
    """'sheet_metal', 'weldment' or 'other' — decided by the names present, as the production
    extractor decides it. SolidWorks calls a sheet-metal FLAT and a weldment member's SOLID box
    by the same name, 'Bounding Box Length', so the kind of list is what says which one a value
    is; only a sheet-metal list's box is ever read as a blank."""
    names = [str(k).strip().lower() for k in (props or {})]
    if any("sheet metal" in n or "bend radius" in n or "flat pattern" in n for n in names):
        return "sheet_metal"
    if any(n in ("length", "angle1", "angle2") for n in names) or \
            _nat.weldment_section_from_cutlist(_values(props)):
        return "weldment"
    return "other"


_GAUGE_WORDS = re.compile(r"\b(GA|GAUGE|SWG)\b", re.IGNORECASE)


def _thickness_from_props(values: Dict[str, str]) -> Optional[float]:
    """A thickness the designer typed as a property. '16 GA' is a gauge NUMBER, not 16mm, so a
    value naming a gauge system is refused rather than read as millimetres."""
    raw = _nat._prop(values, "Thickness", "Sheet Thickness", "Gauge", "Material Thickness")
    if not raw or _GAUGE_WORDS.search(raw):
        return None
    return _nat._num_mm(raw)


def _resolve_saved_mass(raw: str, material: str, area_mm2: Optional[float],
                        thickness_mm: Optional[float]) -> Tuple[Optional[float], str]:
    """A saved Mass with its units resolved by geometry, or (None, why not).

    The same rule as the production extractor's cut-list mass: the saved figure is in the
    document's mass units (kg on some models, grams on others) and the number alone cannot say
    which. Predict the mass from blank area x thickness x density and accept the reading that
    matches. Neither matching, or nothing to predict from, leaves mass unset — a mass wrong by a
    thousand would wreck the material cost, and an honest null is recoverable."""
    try:
        m = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None, f"saved Mass {raw!r} is not a number"
    dens = _nat._density_kg_m3(material)
    if not (dens and area_mm2 and thickness_mm):
        return None, (f"saved Mass {raw!r} is present but its units cannot be checked (need "
                      f"material density, blank area and thickness)")
    pred = (area_mm2 / 1e6) * (thickness_mm / 1000.0) * dens
    for unit, kg in (("kg", m), ("g", m / 1000.0)):
        if pred > 0 and 0.6 <= kg / pred <= 1.6:
            return round(kg, 5), (f"mass {round(kg, 5)}kg from the saved Mass (read as {unit}; "
                                  f"geometry predicts {pred:.4f}kg)")
    return None, (f"saved Mass {raw!r} matches neither kg nor grams against the {pred:.4f}kg "
                  f"the geometry predicts — units unresolved, left unset")


def signals_from_saved(title: str, props: Dict[str, Dict[str, str]],
                       cut_lists: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """route_signals for one part, from saved properties and the saved cut list alone.

    `props` is the part's custom properties with the active configuration's laid over the
    file's (a configuration-specific value wins, as it does in a SolidWorks BOM); each
    `cut_lists` entry is {"name", "quantity", "props"}. Pure — no COM — so every decision here
    is proven in tests.

    The record has the production extractor's RouteSignals shape plus four keys:
      reader                           "solidworks_docmgr"
      not_saved                        the fields this reader could not supply
      needs_solidworks_worker          a formed sheet-metal part with no saved flat pattern
      needs_solidworks_worker_reason   why, in words an estimator can act on
    """
    sig = _nat.RouteSignals(part_number=title)
    notes = sig.notes
    not_saved: List[str] = list(_NEVER_SAVED)
    values = _values(props)

    # ── the cut lists: which kind each is, and the sheet-metal one's values ──────────────
    sm_list: Optional[Dict[str, Any]] = None
    sm_count = 0
    weld_lists: List[Dict[str, Any]] = []
    for cl in cut_lists or []:
        kind = classify_cut_list(cl.get("props") or {})
        if kind == "sheet_metal":
            sm_count += 1
            sm_list = sm_list or cl
        elif kind == "weldment":
            weld_lists.append(cl)
    if sm_count > 1:
        notes.append(f"{sm_count} sheet-metal bodies in the saved cut list; the first was read, "
                     f"as the SolidWorks worker reads one")
    # UNKNOWN IS NOT NO (D-714). cut_lists is None when the library could not hand the cut list
    # back at all. Whether the part is sheet metal, its bends and its blank are then unknown,
    # and say so; False and 0 would read as "not formed, no folding", which nothing here knows.
    cut_list_unread = cut_lists is None
    if cut_list_unread:
        sig.is_sheet_metal = None
        sig.bend_count = None
        sig.bend_count_cutlist = None
        not_saved.append("cut list (it could not be read)")
    cp = parse_cut_list(sm_list.get("props") or {}) if sm_list else {}
    if sm_list:
        sig.is_sheet_metal = True
        fl, fw = cp.get("flat_length"), cp.get("flat_width")
        if fl and fw:
            sig.flat_length_mm, sig.flat_width_mm = fl, fw
            sig.flat_pattern_present = True
            notes.append(
                f"flat blank {fl:g} x {fw:g}mm as SAVED in the sheet-metal cut list — not "
                f"rebuilt, and not checked against the part's envelope, which is not saved in "
                f"the file")
        sig.bend_radius_mm = cp.get("bend_radius")
        co, ci = cp.get("cut_length_outer"), cp.get("cut_length_inner")
        sig.cut_length_outer_mm, sig.cut_length_inner_mm = co, ci
        if co or ci:
            sig.cut_length_mm = round((co or 0.0) + (ci or 0.0), 2)
        sig.blank_area_mm2 = cp.get("blank_area_mm2")
        sig.bend_allowance_mm = cp.get("bend_allowance")
        sig.surface_treatment = str(cp.get("surface_treatment") or "")
        sig.sheet_gauge = str(cp.get("sheet_gauge") or "")
        if cp.get("cut_out_count") is not None:
            sig.cut_out_count = int(cp["cut_out_count"])
        if cp.get("bend_count") is not None:
            # The cut list's count is the ONLY bend count this reader has: the feature tree is
            # not readable without SolidWorks.
            sig.bend_count_cutlist = int(cp["bend_count"])
            sig.bend_count = int(cp["bend_count"])
        if cp.get("thickness"):
            sig.thickness_mm = float(cp["thickness"])
    if sig.thickness_mm is None:
        _tn, _te = _prop_entry(props, "Thickness", "Sheet Thickness", "Gauge",
                               "Material Thickness")
        _tval, _tlink = _str((_te or {}).get("value")), _str((_te or {}).get("linked_to"))
        if _tval and _tlink and not sm_list:
            # A LINKED PROPERTY'S SAVED VALUE IS NOT A THICKNESS (D-714). 12678-01-01J, an MDF
            # panel, saved Thickness = 1.5mm, linked to "Thickness@Default@...". The Document
            # Manager hands back the value as last saved and cannot re-evaluate the link;
            # SolidWorks, which can, read no thickness for it. With no sheet-metal cut list to
            # stand behind it, the value is said and not taken.
            notes.append(f"property '{_tn}' holds {_tval}, the saved value of the linked "
                         f"expression {_tlink}; the Document Manager cannot re-evaluate it and "
                         f"the part has no sheet-metal cut list, so it is not read as the "
                         f"part's thickness")
            not_saved.append("thickness (only a linked property's saved value)")
            _t(f"thickness NOT taken from property {_tn!r} = {_tval!r}: linked to {_tlink!r} "
               f"and no sheet-metal cut list")
        else:
            sig.thickness_mm = _thickness_from_props(values)
            if sig.thickness_mm is not None:
                _t(f"thickness {sig.thickness_mm:g} from property {_tn!r} = {_tval!r}"
                   + (f", linked to {_tlink!r}" if _tlink else ", typed"))
    else:
        _t(f"thickness {sig.thickness_mm:g} from the cut list")

    # ── material, and whether the designer typed it ──────────────────────────────────────
    # A property LINKED to SW-Material is the library's applied material (the appearance
    # default the waterfall ranks below the drawing); typed text is the spec. The production
    # extractor cannot see the link and treats every Material property as typed; this reader
    # can, so it says which. With no link information it behaves exactly as that one does.
    m_name, m_entry = _prop_entry(props, *_nat._MATERIAL_PROP_ALIASES)
    m_val, m_link = _str((m_entry or {}).get("value")), _str((m_entry or {}).get("linked_to"))
    if m_val and _is_unevaluated_link(m_val):
        notes.append(f"material property '{m_name}' holds an unevaluated link ({m_val}) — not "
                     f"read as a material")
        m_val = ""
    if m_val and "sw-material" not in m_link.lower() and not _nat.reads_as_material(m_val):
        # A TYPED VALUE THAT NAMES NO MATERIAL (JG, 10 Nov 2026): 12674-01-07J's Material
        # property said "SHELF", what the part is rather than what it is made of, and it was
        # taken as the designer's spec. It is set aside, said, and the cut list's material (or
        # the drawing) decides.
        notes.append(f"material property '{m_name}' says {m_val!r}, which names no material "
                     f"— not used")
        m_val, m_link = "", ""
    if not m_val:
        # The cut list's MATERIAL is a property SolidWorks generates LINKED to SW-Material, so
        # with no link information it is taken as the applied material — the lower-ranked of
        # the two readings, which is the safe direction when the evidence is silent.
        for cl in ([sm_list] if sm_list else []) + list(cut_lists or []):
            if not cl:
                continue
            c_name, c_entry = _prop_entry(cl.get("props") or {}, "MATERIAL")
            c_val = _str((c_entry or {}).get("value"))
            if c_val and not _is_unevaluated_link(c_val):
                m_val, m_link = c_val, _str((c_entry or {}).get("linked_to")) or "SW-Material"
                break
    if m_val:
        sig.material = m_val
        sig.material_source = ("applied_library" if "sw-material" in m_link.lower()
                               else "custom_property")

    # ── mass, only where it was saved and its units can be proven ────────────────────────
    mass_raw = ""
    if sm_list:
        mass_raw = _nat._prop(_values(sm_list.get("props") or {}), "Mass")
    if not mass_raw:
        mass_raw = _nat._prop(values, "Mass", "Weight")
    if mass_raw:
        area = sig.blank_area_mm2 or ((sig.flat_length_mm or 0) * (sig.flat_width_mm or 0)) or None
        sig.mass_kg, why = _resolve_saved_mass(mass_raw, sig.material, area, sig.thickness_mm)
        notes.append(why)
        if sig.mass_kg is None:
            not_saved.append("mass (saved, but in units that cannot be proven)")
    else:
        not_saved.append("mass")

    # ── weldment members ─────────────────────────────────────────────────────────────────
    for cl in weld_lists:
        sec = _nat.weldment_section_from_cutlist(_values(cl.get("props") or {}))
        if sec:
            sig.section_profile = sec
            notes.append(f"weldment_section={sec.get('profile_form')} "
                         f"{sec.get('a')}x{sec.get('b')}x{sec.get('t')} len={sec.get('length_mm')}")
            break
    if weld_lists:
        sig.has_weldment = True

    # ── a formed part with no saved flat: the one number this reader cannot produce ──────
    worker_reason = ""
    if sig.is_sheet_metal and not (sig.flat_length_mm and sig.flat_width_mm):
        not_saved.append("flat blank")
        if sig.bend_count_cutlist and sig.bend_count_cutlist > 0:
            worker_reason = (
                f"formed sheet-metal part ({sig.bend_count_cutlist} bend(s) saved in its cut "
                f"list) with no flat pattern saved in the file — its developed blank can only be "
                f"measured by the SolidWorks worker")
        elif sig.bend_count_cutlist is None:
            worker_reason = (
                "sheet-metal part with neither a flat pattern nor a bend count saved in the file "
                "— whether it is formed, and its blank, can only be read by the SolidWorks worker")
        else:
            notes.append("flat sheet-metal part (0 bends saved) with no saved blank — its blank "
                         "comes from the DXF or the drawing")
    if cut_list_unread and not worker_reason:
        worker_reason = ("its cut list could not be read through the Document Manager, so "
                         "whether it is sheet metal, its bends and its blank are unknown — the "
                         "SolidWorks worker reads them")

    # ── operations: only what the saved data evidences ───────────────────────────────────
    # No hole_machining (that is a feature-tree count) and no powder_coating (a default
    # assumption even in the production extractor). This reader says what the file says.
    if sig.is_sheet_metal:
        sig.ops_hint.append("laser_cutting")
    if (sig.bend_count or 0) > 0:
        sig.ops_hint.append("folding")
    if sig.has_weldment:
        sig.ops_hint += ["welding", "dress_welds"]
    sig.ops_hint = sorted(set(sig.ops_hint))

    notes.append(f"{', '.join(not_saved)}: {NOT_SAVED}")
    out = asdict(sig)
    out["reader"] = READER
    out["not_saved"] = not_saved
    out["needs_solidworks_worker"] = bool(worker_reason)
    out["needs_solidworks_worker_reason"] = worker_reason
    return out


def bom_from_table_rows(rows: List[List[str]]) -> List[_nat.BomLine]:
    """BOM lines from a table's rows, header first, or nothing when the table is not BOM-shaped.

    The same reading as the SolidWorks extractor's (sw_native_analyse.bom_lines_from_rows): kept
    only when the header names a part column AND a quantity column, the table-type number this
    reader asks for being unverified, so the shape is what keeps a revision block out. The PART
    NUMBER column is preferred over ITEM NO.: an item number is a balloon, not a part."""
    return _nat.bom_lines_from_rows(rows)


def _basename(p: str) -> str:
    """The file name of a path saved on Windows, read anywhere."""
    return re.split(r"[\\/]", str(p or ""))[-1]


def _stem(p: str) -> str:
    b = _basename(p)
    return os.path.splitext(b)[0].strip() if b else ""


def _doc_type_of(path_or_name: str, declared: Optional[int]) -> Optional[int]:
    """By extension first — it cannot be misread — then by the declared SwDmDocumentType."""
    ext = os.path.splitext(_basename(path_or_name))[1].lower()
    if ext in DOCTYPE:
        return DOCTYPE[ext]
    return declared if declared in (SW_PART, SW_ASM, SW_DRW) else None


def resolve_reference(stored: str, referencing_dir: Any) -> Optional[str]:
    """Where a referenced file actually is: the path as last saved, else the same file name
    beside the document that references it. That is the commonest of SolidWorks' own search
    rules, and the one that matters when a designer's drive letter is not mapped here. None
    when neither exists — the caller says so rather than guessing."""
    if not stored:
        return None
    try:
        if os.path.isfile(stored):
            return stored
    except (OSError, ValueError):
        pass
    base = _basename(stored)
    if base and referencing_dir is not None:
        cand = Path(str(referencing_dir)) / base
        try:
            if cand.is_file():
                return str(cand)
        except OSError:
            return None
    return None


# ── RECORDS ───────────────────────────────────────────────────────────────────────────

def _base_record(path: str, doctype: Optional[int]) -> Dict[str, Any]:
    return {
        "path": path,
        "title": "",
        "doctype": doctype,
        "reader": READER,
        "custom_properties": {},
        "bbox_mm": None,
        "bom": [],
        "route_signals": None,
        "errors": [],
        "notes": [],
    }


def _merged_properties(doc, cfg_name: str) -> Tuple[Dict[str, Dict[str, str]],
                                                    Dict[str, Dict[str, str]], Any]:
    """(file-level properties, the active configuration's, the configuration object)."""
    file_props = read_properties(doc)
    cfg = get_configuration(doc, cfg_name) if cfg_name else None
    cfg_props = read_properties(cfg) if cfg is not None else {}
    return file_props, cfg_props, cfg


def _child_document(app, path: str, cfg_name: str, cache: Dict
                    ) -> Tuple[Dict[str, str], Optional[List[Dict[str, Any]]], str]:
    """(merged property values, component infos when it is an assembly, error) for one
    referenced file. Opened read-only, read, closed — and cached, because an assembly that uses
    a part forty times needs it opened once."""
    key = (os.path.normcase(os.path.abspath(path)), cfg_name)
    if key in cache:
        return cache[key]
    dt = _doc_type_of(path, None) or SW_PART
    props: Dict[str, str] = {}
    comps: Optional[List[Dict[str, Any]]] = []
    err = ""
    try:
        doc, code = open_document(app, path, dt)
    except Exception as exc:                                             # noqa: BLE001
        doc, code, err = None, 1, redact(exc)
    if doc is None or code:
        err = err or _OPEN_ERRORS.get(int(code or 1), f"open error {code}")
    else:
        try:
            use_cfg = cfg_name or active_configuration_name(doc)
            fp, cp, cfg = _merged_properties(doc, use_cfg)
            props = _values({**fp, **cp})
            if dt == SW_ASM:
                _raw = configuration_components(cfg)
                if _raw is None:
                    comps = None
                    err = "its components could not be read through the Document Manager"
                else:
                    comps = [component_info(c) for c in _raw]
        except Exception as exc:                                         # noqa: BLE001
            err = redact(exc)
        finally:
            close_document(doc)
    cache[key] = (props, comps, err)
    return cache[key]


def walk_assembly(app, top_doc, top_path: str, cfg_name: str
                  ) -> Tuple[List[_nat.BomLine], List[Dict[str, Any]], List[str]]:
    """(full-depth BOM, parent->child edges, notes) for one assembly, as the production
    extractor builds them from GetComponents(False).

    The Document Manager hands back one level at a time, so sub-assemblies are opened and
    walked. Each component INSTANCE is visited, so a sub-assembly used twice contributes its
    children twice — the same full-depth roll-up the COM analyser reports. Edges are counted
    per instance where they hang ("" is a direct child of the assembly being read), exactly as
    that analyser counts them, so the consumer's hierarchy and per-parent arithmetic read both
    extracts the same way. Suppressed components are skipped, as there."""
    counts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    edges: Dict[Tuple[str, str, str], float] = {}
    edge_dt: Dict[Tuple[str, str, str], Optional[int]] = {}
    notes: List[str] = []
    cache: Dict = {}
    top_cfg = get_configuration(top_doc, cfg_name) if cfg_name else None
    _raw = configuration_components(top_cfg)
    if _raw is None:
        # OPENED IS NOT READ (D-714). An assembly whose components the library could not
        # hand back has no quantities in this read; it is a failed read, not an empty one.
        raise Unreadable(f"its components could not be read through the Document Manager "
                         f"(configuration {cfg_name or 'none'}) — the assembly's quantities "
                         f"are unknown; the SolidWorks worker reads them")
    top_comps = [component_info(c) for c in _raw]

    def _norm(p: str) -> str:
        return os.path.normcase(os.path.abspath(p))

    def visit(components: List[Dict[str, Any]], ref_dir: Any, parent: str, depth: int,
              stack: frozenset) -> None:
        for info in components:
            if info.get("suppressed"):
                continue
            if info.get("excluded_from_bom"):
                notes.append(f"component {_stem(info.get('path') or '') or info.get('name')}: "
                             f"excluded from the parts list in the model — not counted")
                continue
            stored = info.get("path") or ""
            title = _stem(stored) if stored else _nat._clean_pn(
                _str(info.get("name")).split("/")[-1])
            if not title:
                continue
            cfg = _str(info.get("config"))
            dt = _doc_type_of(stored or _str(info.get("name")), info.get("doc_type"))
            resolved = resolve_reference(stored, ref_dir)
            props: Dict[str, str] = {}
            sub: Optional[List[Dict[str, Any]]] = []
            if resolved:
                props, sub, err = _child_document(app, resolved, cfg, cache)
                if dt == SW_ASM and (err or sub is None):
                    # A SUB-ASSEMBLY NOT READ LOSES EVERYTHING UNDER IT (D-714): counting it
                    # and moving on would report the assembly complete with its children
                    # missing.
                    _why = err or "its components could not be read"
                    raise Unreadable(f"sub-assembly {title}: {_why} — the quantities below it "
                                     f"are unknown")
                if err:
                    notes.append(f"component {title}: {err} — counted, its properties not read")
            else:
                notes.append(f"component {title}: its file was not found where it was saved "
                             f"({stored or 'no path saved'}) or beside the assembly — counted, "
                             f"its properties not read")
            key = (title, cfg)
            if key not in counts:
                counts[key] = {
                    "part_number": title,
                    "description": _nat._prop(props, "Description", "Part Description", "Desc"),
                    "qty": 0.0,
                    "config": cfg,
                    "material": _nat._prop(props, "Material", "Material Description",
                                           "Material Spec", "Grade"),
                    "file_path": resolved or stored,
                    "custom_props": props,
                    "parent_part_number": parent,
                    "doc_type": dt,
                }
            counts[key]["qty"] += 1.0
            ek = (parent, title, cfg)
            edges[ek] = edges.get(ek, 0.0) + 1.0
            edge_dt[ek] = dt
            if dt == SW_ASM and resolved:
                if depth + 1 > _MAX_ASSEMBLY_DEPTH:
                    notes.append(f"sub-assembly {title}: deeper than {_MAX_ASSEMBLY_DEPTH} "
                                 f"levels — its components were not walked")
                elif _norm(resolved) in stack:
                    notes.append(f"sub-assembly {title}: references itself — not walked again")
                else:
                    visit(sub or [], Path(resolved).parent, title, depth + 1,
                          stack | {_norm(resolved)})

    visit(top_comps, Path(top_path).parent, "", 0, frozenset({_norm(top_path)}))
    lines = [_nat.BomLine(
        part_number=v["part_number"], description=v["description"], qty=v["qty"],
        config=v["config"], material=v["material"], file_path=v["file_path"],
        source="assembly_tree", custom_props=v["custom_props"],
        parent_part_number=v["parent_part_number"], doc_type=v["doc_type"])
        for v in counts.values()]
    lines.sort(key=lambda x: x.part_number.lower())
    edge_list = [{"parent": p, "child": ch, "config": cfg, "qty": q,
                  "child_doc_type": edge_dt.get((p, ch, cfg))}
                 for (p, ch, cfg), q in sorted(edges.items())]
    # One note per fact, not one per instance: a part used forty times and not found is one
    # missing file.
    return lines, edge_list, list(dict.fromkeys(notes))


def analyse_file(app, path: str) -> Dict[str, Any]:
    """One file, read from what was saved in it, in the production extractor's record shape."""
    doctype = DOCTYPE.get(Path(path).suffix.lower())
    rec = _base_record(path, doctype)
    if doctype is None:
        rec["errors"].append(f"not a SolidWorks part, assembly or drawing: {Path(path).name}")
        return rec
    try:
        doc, code = open_document(app, path, doctype)
    except Exception as exc:                                             # noqa: BLE001
        rec["errors"].append(f"open: {redact(exc)}")
        return rec
    if doc is None or code:
        rec["errors"].append(f"open: {_OPEN_ERRORS.get(int(code or 1), f'open error {code}')}")
        return rec
    try:
        title = _stem(path)
        rec["title"] = title
        cfg_names = configuration_names(doc)
        # The configuration the file was saved in; failing that, its first one — a part has
        # at least one, and reading none would report a populated file as empty.
        cfg_name = active_configuration_name(doc) or (cfg_names[0] if cfg_names else "")
        _t(f"configurations {cfg_names!r}, active {cfg_name!r}")
        rec["configurations"] = cfg_names
        rec["active_configuration"] = cfg_name
        file_props, cfg_props, cfg = _merged_properties(doc, cfg_name)
        rec["custom_properties"] = _values(file_props)
        if cfg_props:
            rec["configuration_properties"] = {cfg_name: _values(cfg_props)}
        rec["notes"].append(f"bounding box: {NOT_SAVED}")
        if doctype == SW_PART:
            items = cut_list_items(cfg)
            cut_lists: Optional[List[Dict[str, Any]]] = None
            if items is not None:
                cut_lists = []
                for item in items:
                    info = cut_list_item_info(item)
                    info["props"] = read_properties(item)
                    cut_lists.append(info)
            merged = {**file_props, **cfg_props}
            rs = signals_from_saved(title, merged, cut_lists)
            rec["route_signals"] = rs
            values = _values(merged)
            rec["bom"] = [asdict(_nat.BomLine(
                part_number=title,
                description=_nat._prop(values, "Description", "Part Description", "Desc"),
                qty=1.0, material=rs.get("material") or "",
                thickness_mm=rs.get("thickness_mm"), file_path=path, source="part_props",
                custom_props=rec["custom_properties"]))]
        elif doctype == SW_ASM:
            lines, edge_list, walk_notes = walk_assembly(app, doc, path, cfg_name)
            rec["bom"] = [asdict(b) for b in lines]
            rec["assembly_edges"] = edge_list
            rec["assembly_part_number"] = title
            rec["external_references"] = external_references(app, doc)
            rec["notes"].extend(walk_notes)
        elif doctype == SW_DRW:
            table_lines: List[_nat.BomLine] = []
            for tbl in drawing_tables(doc):
                table_lines.extend(bom_from_table_rows(table_rows(tbl)))
            table_lines.sort(key=lambda x: x.part_number.lower())
            rec["bom"] = [asdict(b) for b in table_lines]
            rec["external_references"] = external_references(app, doc)
            if not table_lines:
                rec["notes"].append("no BOM table could be read from the saved drawing")
    except Exception as exc:                                             # noqa: BLE001
        rec["errors"].append(f"read: {redact(exc)}")
    finally:
        close_document(doc)
    return rec


# ── THE DRAWING'S PARTS LIST DECIDES WHAT THE MODEL COUNTS (JG, 10 Nov 2026) ─────────────
# 12674-01-GA: the GA assembly holds 24 of 12424-02-GA, another job's assembly placed in the
# model for show, and 6 plinth feet; neither file is in the pack. SolidWorks suppresses a
# component whose file it cannot find, so it counted neither; this reader counts what was saved,
# so it counted both. The GA drawing's own parts list names the feet (a Hafele catalogue part)
# and not 12424-02-GA. Neither "missing file" nor "found file" is the rule: the released parts
# list is. So where an assembly's drawing is in the same read and carries a parts list that the
# model can be matched to, a component that the list names nowhere, and that neither sits under
# a listed assembly nor holds a listed part, is not counted; it is said, with its quantity, in
# the record's "excluded_components". Where the list cannot be matched to the model (a balloon-
# number-only list, another assembly's list) nothing is excluded and that is said too.
_CODE_RE = re.compile(r"\d[\d.\-/ ]*\d")


def _identity_keys(*texts: Any) -> set:
    """What a parts-list row or a model component can be recognised by: each text squeezed to
    letters and digits, and every catalogue-style number in it (five digits or more) as digits."""
    keys: set = set()
    for t in texts:
        s = _str(t).upper()
        if not s:
            continue
        sq = re.sub(r"[^A-Z0-9]", "", s)
        if len(sq) >= 3:
            keys.add(sq)
        for m in _CODE_RE.finditer(s):
            digits = re.sub(r"\D", "", m.group())
            if len(digits) >= 5:
                keys.add("#" + digits)
    return keys


def _line_keys(line: Dict[str, Any]) -> set:
    props = line.get("custom_props") or {}
    return _identity_keys(line.get("part_number"), line.get("description"),
                          _stem(line.get("file_path") or ""),
                          _nat._prop(props, "Part Number", "PartNo", "Part No", "Number"))


def reconcile_with_drawings(records: List[Dict[str, Any]]) -> None:
    """Hold every assembly read to its own drawing's parts list, in place (see above)."""
    drawings = [r for r in records if r.get("doctype") == SW_DRW and r.get("bom")]
    for rec in records:
        if rec.get("doctype") != SW_ASM or not rec.get("bom"):
            continue
        title = _str(rec.get("title")).upper()
        asm_name = _basename(rec.get("path") or "").upper()
        mine = [d for d in drawings
                if _str(d.get("title")).upper() == title
                or any(_basename(x).upper() == asm_name
                       for x in (d.get("external_references") or []))]
        if not mine:
            continue
        rows = [ln for d in mine for ln in (d.get("bom") or [])]
        row_keys = [_identity_keys(ln.get("part_number"), ln.get("description")) for ln in rows]
        lines = rec["bom"]
        matched = {i for i, ln in enumerate(lines)
                   if any(_line_keys(ln) & k for k in row_keys)}
        rows_found = sum(1 for k in row_keys if any(_line_keys(ln) & k for ln in lines))
        _dname = _basename(mine[0].get("path") or "") or "its drawing"
        if rows_found < max(2, (len(rows) + 1) // 2):
            rec["notes"].append(f"{_dname}'s parts list could not be matched to this assembly "
                                f"({rows_found} of {len(rows)} row(s) found in the model) — "
                                f"every component counted")
            continue
        # A listed assembly keeps everything under it; a listed part keeps every assembly above.
        pn = [_str(ln.get("part_number")) for ln in lines]
        kids: Dict[str, set] = {}
        for e in rec.get("assembly_edges") or []:
            kids.setdefault(_str(e.get("parent")), set()).add(_str(e.get("child")))
        parents: Dict[str, set] = {}
        for p_, cs in kids.items():
            for c in cs:
                parents.setdefault(c, set()).add(p_)
        listed = {pn[i] for i in matched}

        def _reach(start: set, step: Dict[str, set]) -> set:
            out, todo = set(), list(start)
            while todo:
                for nxt in step.get(todo.pop(), set()) - {""}:
                    if nxt not in out:
                        out.add(nxt)
                        todo.append(nxt)
            return out

        keep = listed | _reach(listed, kids) | _reach(listed, parents)
        gone = [ln for ln in lines if _str(ln.get("part_number")) not in keep]
        if not gone:
            continue
        gone_pn = {_str(ln.get("part_number")) for ln in gone}
        rec["bom"] = [ln for ln in lines if _str(ln.get("part_number")) in keep]
        rec["assembly_edges"] = [e for e in rec.get("assembly_edges") or []
                                 if _str(e.get("child")) not in gone_pn
                                 and _str(e.get("parent")) not in gone_pn]
        rec["excluded_components"] = [
            {"part_number": ln.get("part_number"), "qty": ln.get("qty"),
             "reason": f"not on {_dname}'s parts list, and not under or above anything it lists"}
            for ln in gone]
        rec["notes"].append(
            f"{len(gone)} component(s) not on {_dname}'s parts list and not counted: "
            + ", ".join(f"{ln.get('part_number')} x{ln.get('qty'):g}" for ln in gone))


def build_payload(records: List[Dict[str, Any]], target: str, fp_before: str, fp_after: str,
                  dm_version: str = "") -> Dict[str, Any]:
    """The extract: the production extractor's payload and manifest, plus who read it."""
    changed = bool(fp_before) and bool(fp_after) and fp_before != fp_after
    errors = [{"path": r.get("path"), "errors": r.get("errors")}
              for r in records if isinstance(r, dict) and r.get("errors")]
    ok = [r for r in records if isinstance(r, dict) and not r.get("errors") and r.get("title")]
    return {
        "schema": f"sw_native_extract.v{EXTRACT_SCHEMA_VERSION}",
        "schema_version": EXTRACT_SCHEMA_VERSION,
        "reader": READER,
        "_manifest": {
            "schema_version": EXTRACT_SCHEMA_VERSION,
            "reader": READER,
            "native_files_fingerprint": fp_after,
            "fingerprint_before": fp_before,
            "changed_during_extraction": changed,
            "generated_from": _nat._fingerprint_scope(target),
            "solidworks_version": "",
            "document_manager_version": dm_version,
            "extractor_schema": f"sw_native_extract.v{EXTRACT_SCHEMA_VERSION}",
            # The Document Manager reads the FILE, never anybody's open session: there is no
            # such thing as a borrowed document here, and unsaved work is invisible to it.
            "read_from_open_documents": [],
            "geometry_supplied": False,
            "not_saved": f"{', '.join(_NEVER_SAVED)}, and any mass or flat pattern a file did "
                         f"not save: {NOT_SAVED}",
            "files_seen": len(records),
            "files_read": len(ok),
            # Which reader wrote this and when, as the SolidWorks reader records (12 Nov 2026).
            "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reader_build": reader_build(),
            "files_failed": len(errors),
            "errors": errors[:200],
        },
        "records": records,
    }


def write_extract(payload: Dict[str, Any], out_json: str, key: Optional[str] = None) -> str:
    """Atomic write, through redact(), falling back to the working directory when the target
    is a read-only share — as the production extractor does. Returns where it went."""
    text = redact(json.dumps(payload, indent=2, default=str), key)

    def _write(path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)

    try:
        _write(out_json)
        return out_json
    except OSError as exc:
        fallback = os.path.join(os.getcwd(), EXTRACT_FILENAME)
        print(redact(f"\nWARNING: could not write to {out_json} ({exc})", key), flush=True)
        _write(fallback)
        return fallback


def _path_key(p: Any) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p or "").strip())))


def select_only(paths: Sequence[str], only: Sequence[str]) -> List[str]:
    """The discovered model files the caller asked for. Matched by full path, then by file
    name: the SolidWorks extract may name a file by a mapped drive where this run sees the
    share. A name that matches more than one discovered file takes none of them, never a
    guess."""
    by_path = {_path_key(p): p for p in paths}
    def _name(p: Any) -> str:
        return re.split(r"[\\/]", str(p or "").strip())[-1].lower()

    by_name: Dict[str, List[str]] = {}
    for p in paths:
        by_name.setdefault(_name(p), []).append(p)
    out: List[str] = []
    for want in only:
        hit = by_path.get(_path_key(want))
        if hit is None:
            same = by_name.get(_name(want)) or []
            hit = same[0] if len(same) == 1 else None
        if hit is not None and hit not in out:
            out.append(hit)
    return out


def main(argv: Optional[Sequence[str]] = None, *, class_factory=None) -> int:
    """Run the backup read. `class_factory` lets a test hand in a fake ISwDMClassFactory."""
    args = list(sys.argv[1:] if argv is None else argv)
    if argv is None:
        _load_engine_env()
    key = _key_from_env()

    def say(msg: str = "") -> None:
        print(redact(msg, key), flush=True)

    usage = ("Usage: python sw_docmgr_analyse.py <file_or_folder> [--out <json path>] "
             "[--only <model file> ...] [--only-from <text file, one path a line>] [--trace]")
    # Accepted and ignored: the production extractor's flatten switches mean nothing to a
    # reader that never rebuilds a model, and a script that passes them must not break.
    for flag in ("--flatten", "--no-flatten"):
        while flag in args:
            args.remove(flag)
    global _TRACE
    trace = "--trace" in args
    while "--trace" in args:
        args.remove("--trace")
    out_override = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            say("ERROR: --out needs a path")
            return 2
        out_override = args[i + 1]
        del args[i:i + 2]
    # ONLY THESE FILES (D-706). The engine asks for the models SolidWorks opened and could not
    # read in the same run; the folder is still the target, so the manifest fingerprints the
    # whole folder exactly as the SolidWorks extract's does, and the read is held to the same
    # discovery rule. A list file keeps a long list off the command line.
    only: List[str] = []
    for flag in ("--only", "--only-from"):
        while flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                say(f"ERROR: {flag} needs a path")
                return 2
            if flag == "--only":
                only.append(args[i + 1])
            else:
                try:
                    only += [ln.strip() for ln in Path(args[i + 1]).read_text(
                        encoding="utf-8").splitlines() if ln.strip()]
                except OSError as exc:
                    say(f"ERROR: could not read the --only-from list {args[i + 1]}: {exc}")
                    return 2
            del args[i:i + 2]
    if not args:
        say(usage)
        return 2
    target = args[0]
    if not os.path.exists(target):
        if args[1:]:
            say(f"ERROR: the path was not quoted, so only its first word reached this tool:\n"
                f"  {target}\nTry:\n  python sw_docmgr_analyse.py \"{' '.join(args)}\"")
        else:
            say(f"ERROR: path not found or not accessible:\n  {target}")
        return 2
    if not key:
        say(f"ERROR: {KEY_ENV} is not set. The SOLIDWORKS Document Manager reads nothing without "
            f"its licence key. Set it in this machine's environment (the key itself is never "
            f"printed or written by this tool).")
        return 2
    paths = _nat.find_sw_files(target) if os.path.isdir(target) else [target]
    if only:
        paths = select_only(paths, only)
        if not paths:
            say(f"None of the {len(only)} file(s) asked for with --only is a model this tool "
                f"would read under: {target}")
            return 1
    if not paths:
        say(f"No SolidWorks files ANALYSED under: {target}")
        say(_nat.explain_no_files(target))
        return 1
    if class_factory is None:
        ok, why = com_available()
        if not ok:
            say(f"ERROR: the SOLIDWORKS Document Manager cannot be reached: {why}")
            return 2
        try:
            class_factory = dispatch_class_factory()
        except Exception as exc:                                         # noqa: BLE001
            say(f"ERROR: the SOLIDWORKS Document Manager could not be started from Python "
                f"({DM_PROGID}): {exc}")
            return 2
    try:
        app = open_application(class_factory, key)
    except Exception as exc:                                             # noqa: BLE001
        say(f"ERROR: the Document Manager refused to start with the key in {KEY_ENV}: {exc}")
        return 2
    if app is None:
        say(f"ERROR: the Document Manager refused the licence key in {KEY_ENV}.")
        return 2

    if _BINDING.get("via"):
        say(f"[docmgr] reached through {_BINDING['via']}")
    say("[docmgr] BACKUP READER — values are read from what each file SAVED. Bounding boxes, "
        "volumes and surface areas are never supplied, and nothing is measured or inferred.")
    fp_before = _nat._fingerprint_native_files(target)
    records: List[Dict[str, Any]] = []
    for p in paths:
        say(f"\n=== {p} ===")
        _TRACE = [] if trace else None
        try:
            r = analyse_file(app, p)
        except Exception as exc:                                         # noqa: BLE001
            r = _base_record(p, DOCTYPE.get(Path(p).suffix.lower()))
            r["errors"].append(f"read: {redact(exc, key)}")
        records.append(r)
        say(f"Title: {r.get('title')}  type={r.get('doctype')}  BOM lines: {len(r.get('bom') or [])}")
        rs = r.get("route_signals")
        if rs:
            say(f"  material={rs.get('material')!r} ({rs.get('material_source') or 'none'}) "
                f"sheet_metal={rs.get('is_sheet_metal')} bends={rs.get('bend_count')}")
            say(f"  FLAT: {rs.get('flat_length_mm')} x {rs.get('flat_width_mm')} mm  "
                f"thickness={rs.get('thickness_mm')}mm  cut_len={rs.get('cut_length_mm')}"
                + ("  [NEEDS THE SOLIDWORKS WORKER]" if rs.get("needs_solidworks_worker") else ""))
            say(f"  not saved: {', '.join(rs.get('not_saved') or [])}")
        if r.get("errors"):
            say(f"Errors: {r['errors']}")
        for line in (_TRACE or []):
            say(f"  trace: {line}")
        _TRACE = None
    fp_after = _nat._fingerprint_native_files(target)
    reconcile_with_drawings(records)
    for r in records:
        for x in r.get("excluded_components") or []:
            say(f"[parts list] {r.get('title')}: {x['part_number']} x{x['qty']:g} not counted "
                f"— {x['reason']}")
    payload = build_payload(records, target, fp_before, fp_after, docmgr_version(app))
    if only:
        # Which files this read was asked for, so a later run can tell a top-up of the same
        # failures from one of a different set.
        payload["_manifest"]["only"] = sorted(paths)
    out_json = out_override or os.path.join(
        target if os.path.isdir(target) else os.path.dirname(target), EXTRACT_FILENAME)
    out_json = write_extract(payload, out_json, key)
    man = payload["_manifest"]
    say(f"\nWrote {out_json}")
    say(f"EXTRACT_PATH={out_json}")
    if man["files_failed"]:
        say(f"COVERAGE: {man['files_read']} of {man['files_seen']} file(s) read, "
            f"{man['files_failed']} failed")
    if records and not man["files_read"]:
        say(f"\nERROR: {len(records)} file(s) were opened and NONE could be read. The extract "
            f"written above contains no usable model data.")
        return 1
    if man["changed_during_extraction"]:
        say("\nWARNING: the model files CHANGED DURING this read. The extract is not a snapshot "
            "of anything — re-run it.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
