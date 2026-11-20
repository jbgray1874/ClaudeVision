"""A SERVICE ON THE SAME COMMIT IS NOT CALLED STALE (20 Nov 2026).

The 8fe4a122 release: 8071 was restarted and served c384dc8; git on the laptop gave the same
commit as c384dc80 (git lengthens a short hash that 7 characters do not make unique). Compared
whole, restart-service.ps1 printed "STILL STALE", the release stopped, and the runners were
not updated. check-services.ps1 already compared the common prefix; restart-service.ps1 now
does the same, through one function.
"""
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "start" / "restart-service.ps1"


def test_every_commit_comparison_goes_through_one_prefix_rule():
    s = SCRIPT.read_text(encoding="utf-8")
    assert "function Test-SameCommit" in s
    assert "$a.Substring(0, $n) -eq $b.Substring(0, $n)" in s
    assert "if ($n -lt 7) { return $false }" in s, "a stub of a hash proves nothing"
    # no whole-string comparison against the checkout's commit is left
    assert not re.search(r"-(?:eq|ne)\s+\$head\b", s), re.findall(r".{40}-(?:eq|ne)\s+\$head.{5}", s)


def test_a_windows_service_set_up_for_another_port_is_left_alone():
    """The same release: restarting 8072 stopped and restarted the SDIIntelligence service,
    which serves 8071, and never restarted 8072's own task. The service's own --port decides."""
    s = SCRIPT.read_text(encoding="utf-8")
    assert "function Get-ServicePort" in s and "AppParameters" in s
    a = s.index("$svcPort = Get-ServicePort $ServiceName")
    assert "$svcPort -ne $Port" in s[a:a + 300] and "$svc = $null" in s[a:a + 400]
    # decided before anything is stopped
    assert a < s.index("Stop-Service -Name $ServiceName")
