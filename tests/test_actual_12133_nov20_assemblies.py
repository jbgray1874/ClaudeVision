"""External private real-record regression. Missing evidence is a skip, not a pass."""
import os
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from audit_12133_20261120_offline import replay


def test_actual_nov20_record_keeps_both_assembly_families(monkeypatch):
    record=os.environ.get('SDI_12133_NOV20_RECORD')
    drawings=os.environ.get('SDI_12133_NOV20_DRAWINGS')
    if not record or not drawings:
        pytest.skip('Set SDI_12133_NOV20_RECORD and SDI_12133_NOV20_DRAWINGS to external private evidence')
    import socket
    def no_network(*args, **kwargs):
        raise AssertionError('Real-record regression attempted network access')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    result=replay(Path(record),Path(drawings))
    assert result['passed'],result
