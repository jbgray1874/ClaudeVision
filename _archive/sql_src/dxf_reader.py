"""
DXF geometry extraction for ClaudeVision / file_scan.

Loads the 1,224-line upgraded implementation from ``dxf_reader.py.py`` (flat-pattern
layers, shoelace area, weight, ``_parse_filename`` with 1_5mm → 1.5 mm).

To install as a single monolithic file::

    python scripts/install_dxf_reader.py

Quick test (9376-01-001 reference)::

    python scripts/test_flat_dxf.py --strict
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = Path(__file__).with_name("dxf_reader.py.py")


def _load_impl():
    if not _IMPL_PATH.is_file():
        raise ImportError(
            f"Missing {_IMPL_PATH}. Copy Downloads dxf_reader.py.py there, then run:\n"
            "  python scripts/install_dxf_reader.py"
        )
    name = "_claudevision_dxf_reader_impl"
    spec = importlib.util.spec_from_file_location(name, _IMPL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {_IMPL_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_impl = _load_impl()

__all__ = [n for n in dir(_impl) if not n.startswith("__")]
globals().update({n: getattr(_impl, n) for n in __all__})

# Convenience aliases for callers
extract_flat_pattern = extract_flat_pattern_data  # type: ignore[misc]
