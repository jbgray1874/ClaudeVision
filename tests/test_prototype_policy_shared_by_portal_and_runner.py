"""Customer/job-scoped Prototype supplements. No live files, service or queue."""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import pack_resolver as pr
import live_enquiry_runner as ler


@pytest.mark.parametrize('client,drawing,allowed', [
    ('TTI', '50042-01-GA', True), ('tti', '50042-01-GA', True),
    ('', '50042-01-GA', False), ('Other', '50042-01-GA', False),
    ('TTI Something Else', '50042-01-GA', False)])
def test_prototype_is_not_enabled_for_every_customer(monkeypatch, client, drawing, allowed):
    monkeypatch.delenv('SDI_PACK_PROTOTYPE_JOBS', raising=False)
    assert pr.prototype_allowed(client, drawing) is allowed


@pytest.mark.parametrize('drawing,allowed', [
    ('50042-01-GA', True), ('50043-01-GA', True), ('50043-02-GA', False),
    ('500420-01-GA', False), ('5004-01-GA', False)])
def test_bespoke_opt_in_is_exact_job_or_drawing(monkeypatch, drawing, allowed):
    monkeypatch.setenv('SDI_PACK_PROTOTYPE_JOBS', '50042;50043-01-GA')
    assert pr.prototype_allowed('Other', drawing) is allowed


@pytest.mark.parametrize('client,only', [('TTI', False), ('Other', True)])
def test_portal_cli_uses_customer_policy_without_index(monkeypatch, client, only, capsys):
    calls = []
    monkeypatch.delenv('SDI_PACK_PROTOTYPE_JOBS', raising=False)
    monkeypatch.setitem(sys.modules, 'config', types.ModuleType('config'))
    monkeypatch.setattr(pr, 'folders_now', lambda drawing, design_only: (calls.append((drawing, design_only)) or ([], 'test', None)))
    monkeypatch.setattr(pr, 'folders_for', lambda *a, **k: pytest.fail('index used'))
    monkeypatch.setattr(pr, 'resolve', lambda *a, **k: {'price_ok': False})
    assert pr.main(['--drawing', '50042-01-GA', '--client', client, '--json']) == 2
    assert calls == [('50042-01-GA', only)]


@pytest.mark.parametrize('client,only', [('TTI', False), ('Other', True)])
def test_live_enquiry_runner_uses_same_policy(tmp_path, monkeypatch, client, only):
    calls = []
    monkeypatch.delenv('SDI_PACK_PROTOTYPE_JOBS', raising=False)
    monkeypatch.setattr(pr, 'folders_now', lambda drawing, design_only: (calls.append((drawing, design_only)) or ([], 'test', None)))
    monkeypatch.setattr(pr, 'folders_for', lambda *a, **k: pytest.fail('index used'))
    source = ler.DesignShare(tmp_path / 'does-not-exist')
    assert source.find(ler.EnquiryRow(row=3, customer=client, drawing='50042-01-GA')) is None
    assert calls == [('50042-01-GA', only)]


def test_manual_pack_is_not_supplemented_from_conflicting_revision(tmp_path, monkeypatch):
    supplied = tmp_path/'supplied'
    supplied.mkdir()
    row = ler.EnquiryRow(row=3, customer='TTI', drawing='50042-01-GA')
    share = ler.Located('found', 'user pack', folder=supplied, files=[])
    monkeypatch.setattr(pr, 'folders_for_customer_now', lambda *a: ([('fixture', [], False)], 'test', None))
    monkeypatch.setattr(pr, 'resolve', lambda *a, **k: {
        'status': 'ambiguous', 'price_ok': False, 'question': 'revision B versus C', 'members': []})
    got = ler.DesignShare(tmp_path)._with_what_the_ga_calls_for(row, share)
    assert got.status == 'held' and 'revision B versus C' in got.reason
