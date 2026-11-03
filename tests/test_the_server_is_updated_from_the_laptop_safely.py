"""SDI-App01 is updated from the laptop, safely, with no git on the server (D-647).

JG, 3 Nov 2026: "can't run git on the server". The phone reaches SDI-App01 through the App
Proxy, and SDI-App01's own copy of the portal refused the self-running switch. The server is
updated the way Deploy-AMCRM.ps1 updates the AM CRM - copied from the laptop's checkout - with
the guards a wider copy needs: it never touches .env, refuses when the packages differ, backs
up what it replaces and puts it back if the service does not answer again.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "sdi-intelligence-backend" / "deploy" / "Deploy-Estimating.ps1"


def _src():
    return SCRIPT.read_text(encoding="utf-8")


def test_it_is_ascii_like_the_other_scripts():
    assert all(ord(c) < 128 for c in _src())


def test_it_never_copies_keys_settings_or_environments():
    s = _src()
    assert '-not ($_.Name -like ".env*")' in s
    for d in ('".venv"', '"__pycache__"', '"tests"', '"logs"', '"state"'):
        assert d in s.split("$SkipDirs", 1)[1][:300], d


def test_it_refuses_when_the_packages_differ():
    s = _src()
    assert 'requirements.txt' in s and "Nothing was copied" in s


def test_it_backs_up_and_rolls_back_if_the_service_does_not_answer():
    s = _src()
    assert "deploy-backups" in s and "function Undo-Deploy" in s
    restart = s.index('Say "Restarting $Service')
    assert "Undo-Deploy" in s[restart:restart + 600]


def test_it_checks_the_laptop_holds_the_commits_and_can_show_without_copying():
    s = _src()
    assert "git merge-base --is-ancestor $c HEAD" in s
    assert '"48ff715f"' in s and "[switch]$Check" in s
