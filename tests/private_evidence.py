"""Where a test finds private evidence: a customer drawing or a frozen job record (SCRUM-137).

Job data is never committed, so a test that needs it reads it from a folder named by
SDI_PRIVATE_CORPUS and SKIPS, by name, where that folder or file is absent. Two tests here once
named a session's upload folder by absolute path, and on the CI runner merely asking whether a
file existed under /root raised PermissionError: the suite stopped at collection, every push.
os.path.isfile answers False for a path it cannot read; it never raises.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

ENV = "SDI_PRIVATE_CORPUS"


def corpus_file(name: str) -> Optional[Path]:
    """The named private file, or None when it is not on this machine."""
    root = os.environ.get(ENV, "").strip()
    if not root:
        return None
    path = os.path.join(root, name)
    return Path(path) if os.path.isfile(path) else None


def missing_reason(name: str) -> str:
    return (f"private evidence {name} is not on this machine: set {ENV} to the folder that "
            f"holds it. Job data is never committed.")
