"""Execute only the comparator AST, never the service/release script itself.

Runs on Windows PowerShell 5.1 or pwsh. No service, task, process, network, queue,
Git checkout, or production-file mutation is performed by these tests.
"""
import base64
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools/start/restart-service.ps1"
FULL = "c384dc80f80edecc291e6f87956d711bcf9ce194"
CASES = [
    ("actual-seven-eight", "c384dc8", "c384dc80", True),
    ("actual-eight-seven", "c384dc80", "c384dc8", True),
    ("short-full", "c384dc8", FULL, True),
    ("full-short", FULL, "c384dc8", True),
    ("full-full", FULL, FULL, True),
    ("same-short", "c384dc8", "c384dc8", True),
    ("case-and-whitespace", "  C384DC80\r\n", "c384dc8", True),
    ("old-runner", "af463d9", "c384dc80", False),
    ("same-seven-different-eighth", "c384dc80", "c384dc81", False),
    ("same-seven-different-full", FULL, "c384dc81" + "0" * 32, False),
    ("different-last-digit", FULL, FULL[:-1] + "5", False),
    ("null-left", None, FULL, False),
    ("null-right", FULL, None, False),
    ("empty-both", "", "", False),
    ("whitespace", "   ", FULL, False),
    ("unknown-left", "unknown", FULL, False),
    ("unknown-both", "UNKNOWN", "unknown", False),
    ("too-short-left", "c384dc", FULL, False),
    ("too-short-right", FULL, "c384dc", False),
    ("branch-name", "main-2026", "main-2026", False),
    ("nonhex-identical", "zzzzzzz", "zzzzzzz", False),
    ("bad-longer-left", "c384dc8ZZ", "c384dc8", False),
    ("bad-longer-right", "c384dc8", "c384dc8ZZ", False),
    ("dirty-left", "c384dc8+local edits", "c384dc8", False),
    ("dirty-right", "c384dc8", "c384dc8-dirty", False),
    ("decorated-build", "c384dc8 src abc", "c384dc8", False),
    ("overlong-left", FULL + "0", FULL, False),
    ("overlong-right", FULL, FULL + "0", False),
    ("embedded-newline", "c384dc8\nother", "c384dc8", False),
]


@pytest.fixture(scope="module")
def outcomes():
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell required to execute the real comparator")
    path = str(SCRIPT).replace("'", "''")
    data = base64.b64encode(json.dumps(CASES).encode("utf-8")).decode("ascii")
    command = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('__PATH__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$defs = @($ast.FindAll({ param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-SameCommit'
}, $true))
if ($defs.Count -ne 1) { throw 'Expected exactly one Test-SameCommit definition' }
# Define only this function: dot-sourcing the whole file would restart services.
. ([scriptblock]::Create($defs[0].Extent.Text))
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__DATA__')) | ConvertFrom-Json
$results = @{}
foreach ($case in $cases) { $results[$case[0]] = Test-SameCommit $case[1] $case[2] }
$results | ConvertTo-Json -Compress
""".replace("__PATH__", path).replace("__DATA__", data)
    encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("name,a,b,expected", CASES, ids=[case[0] for case in CASES])
def test_real_powershell_comparator(outcomes, name, a, b, expected):
    assert outcomes[name] is expected


def test_all_five_release_checks_use_the_same_comparator():
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count("(Test-SameCommit $serving $head)") == 2
    assert source.count("(Test-SameCommit $otherCommit $head)") == 1
    assert source.count("(Test-SameCommit $aliveCommit $head)") == 2
    assert not re.search(r"-(?:eq|ne)\s+\$head\b", source)


def test_actual_health_condition_does_not_stop_the_release_for_a_shorter_hash():
    """Replay the real if-condition; also works on the original literal comparison."""
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell required")
    command = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('__PATH__', [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$def = $ast.Find({ param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-SameCommit'
}, $true)
if ($def) { . ([scriptblock]::Create($def.Extent.Text)) }
$guard = $ast.Find({ param($n)
    $n -is [System.Management.Automation.Language.IfStatementAst] -and
    $n.Clauses[0].Item1.Extent.Text -like '*$head -and $serving -and*'
}, $true)
if (-not $guard) { throw 'Health comparison guard not found' }
$predicate = [scriptblock]::Create($guard.Clauses[0].Item1.Extent.Text)
$head = 'c384dc80'
$results = @{}
foreach ($serving in @('c384dc8', 'c384dc80', 'af463d9', 'c384dc81')) {
    $results[$serving] = & $predicate
}
$results | ConvertTo-Json -Compress
""".replace("__PATH__", str(SCRIPT).replace("'", "''"))
    encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "c384dc8": False, "c384dc80": False, "af463d9": True, "c384dc81": True,
    }
