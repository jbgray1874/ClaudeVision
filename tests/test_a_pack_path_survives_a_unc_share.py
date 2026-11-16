r"""A pack on a UNC share must resolve to a path the engine can open.

8352-010 SAT ON \\sdi-dc01\shareddata$ AND THE RUN NEVER REACHED THE ENGINE. run-job.ps1
resolved the folder with (Resolve-Path $x).Path, whose value on a UNC pack is the
provider-qualified form:

    Microsoft.PowerShell.Core\FileSystem::\\sdi-dc01\shareddata$\...\8352-010ReuseableBagStand

Python's Path() cannot read that prefix, so --job reported "no such folder" on a pack that was
right there, and run-packs printed a blank row and "NO WORKBOOK WRITTEN". A run on a mapped
drive letter worked, because its .Path carries no prefix — which is exactly why this bit the
share and nothing else, and why no fixture on a local folder would ever have caught it.

.ProviderPath is the bare filesystem path (\\sdi-dc01\...) the engine can open. This guard
forbids the provider-leaking form in the scripts that resolve a pack, so the next UNC job does
not rediscover the same dead run. It is a STATIC check on purpose: the failure only appears on a
real UNC share, which CI has none of, so the pattern is what gets tested, not a live path.
"""
from __future__ import annotations

import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")

# Scripts that resolve a pack folder and hand it to the engine.
_SCRIPTS = ["run-job.ps1", "run-packs.ps1", "run-enquiry.ps1"]

# (Resolve-Path ...).Path and (Get-Location).Path both yield the provider-qualified string on a
# UNC path. $MyInvocation.MyCommand.Path is a different, always-clean property and is not matched.
_LEAKING = [
    re.compile(r"Resolve-Path[^\n]*?\)\s*\.Path\b"),
    re.compile(r"Get-Location\s*\)\s*\.Path\b"),
]


@pytest.mark.parametrize("script", _SCRIPTS)
def test_no_pack_resolver_returns_a_provider_qualified_path(script):
    path = os.path.join(ROOT, script)
    if not os.path.exists(path):
        return
    text = open(path, encoding="utf-8").read()
    for rx in _LEAKING:
        hit = rx.search(text)
        assert hit is None, (
            f"{script} uses '{hit.group(0)}' — on a UNC pack this is the provider-qualified "
            f"'Microsoft.PowerShell.Core\\FileSystem::\\\\server\\...' the engine cannot open. "
            f"Use .ProviderPath (or Convert-Path) so a share pack resolves.")


def test_the_resolver_uses_providerpath():
    """The positive half: run-job.ps1 must actually resolve THROUGH .ProviderPath, so this guard
    cannot be satisfied by simply deleting the resolution."""
    text = open(os.path.join(ROOT, "run-job.ps1"), encoding="utf-8").read()
    assert ".ProviderPath" in text, "run-job.ps1 no longer resolves a pack to a filesystem path"
