import contextlib
import io
import os
from pathlib import Path
import socket
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from audit_serious_fault_records import audit


def test_latest_records_not_older_replay_fixtures(monkeypatch):
    keys=('SDI_LED_LATEST_RECORD','SDI_BOARD_LATEST_RECORD','SDI_CHARGING_LATEST_RECORD','SDI_BOARD_DECISIONS')
    paths=[os.environ.get(k) for k in keys]
    if not all(paths):pytest.skip('External private evidence required: '+', '.join(keys))
    def no_network(*args,**kwargs):raise AssertionError('Offline regression attempted a network call')
    monkeypatch.setattr(socket.socket,'connect',no_network)
    with contextlib.redirect_stdout(io.StringIO()):report=audit(*paths)
    assert report['passed'],report
