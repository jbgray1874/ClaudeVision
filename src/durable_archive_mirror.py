"""One local archive write, durably journalled before retrying its shared mirror.

Only known old/new hashes may be installed. Divergent shared evidence is never
overwritten. This module cannot submit, price or rerun a job.
"""
from __future__ import annotations
import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid


def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value,sort_keys=True)+'\n').encode()
def atomic(path,raw):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def network_error(exc):
    return (getattr(exc,'winerror',None) in {3,53,54,59,64,67,121,1231,1232}
            or getattr(exc,'errno',None) in {errno.ENETDOWN,errno.ENETUNREACH,errno.EHOSTUNREACH,
                                           errno.ECONNRESET,errno.ETIMEDOUT})


class Mirror:
    def __init__(self,local,shared,stop_file=None,sleep=time.sleep):
        self.local,self.shared=Path(local),Path(shared)
        self.stop_file=Path(stop_file) if stop_file else None
        self.sleep=sleep

    def _stop(self):
        if self.stop_file and self.stop_file.exists():
            raise InterruptedError('stop requested while shared filing waits; C intent retained, no resubmission')

    def _publish(self,intent,raw):
        if intent['shared_root']!=str(self.shared): raise ValueError('pending mirror targets another shared root')
        target=self.shared/intent['relative']
        # Root stat distinguishes an offline share from an absent new run directory.
        self.shared.parent.stat()
        target.parent.mkdir(parents=True,exist_ok=True)
        lock=target.with_name(target.name+'.mirror.lock')
        try:
            fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as f:
                f.write(encoded({'token':intent['lock_token'],'pid':os.getpid()}));f.flush();os.fsync(f.fileno())
        except FileExistsError:
            if json.loads(lock.read_text(encoding='utf-8')).get('token')!=intent['lock_token']:
                raise ValueError('another shared archive writer holds this target; no overwrite')
        try:
            if target.exists():
                current=sha(target.read_bytes())
                if current==intent['sha256']: return
                if intent['immutable'] or current!=intent['previous_sha256']:
                    raise ValueError('shared archive conflict; retained C, refused overwrite: '+intent['relative'])
            atomic(target,raw)
            if sha(target.read_bytes())!=intent['sha256']: raise OSError('shared mirror verification failed')
        finally:
            try:
                if json.loads(lock.read_text(encoding='utf-8')).get('token')==intent['lock_token']:lock.unlink()
            except OSError:
                pass  # same persisted token may recover this lock after the connection returns

    def sync(self):
        folder=self.local/'.pending-shared'
        for manifest in sorted(folder.glob('*.json')):
            intent=json.loads(manifest.read_text(encoding='utf-8'))
            relative=Path(intent['relative'])
            if relative.is_absolute() or relative.drive or not relative.parts or '..' in relative.parts or relative.parts[0]=='.pending-shared':
                raise ValueError('unsafe pending archive name')
            raw=manifest.with_suffix('.data').read_bytes()
            if sha(raw)!=intent['sha256']: raise ValueError('local archive intent hash changed')
            local=self.local/relative
            current=sha(local.read_bytes()) if local.exists() else None
            if current not in {intent['previous_sha256'],intent['sha256']}:
                raise ValueError('local archive changed after pending intent')
            if current!=intent['sha256']: atomic(local,raw)
            while True:
                try:
                    self._publish(intent,raw)
                    break
                except OSError as exc:
                    if not network_error(exc): raise
                    self._stop()
                    print('SHARED FILING WAIT: verified data safe on C; retrying K only, no job resubmitted.',flush=True)
                    self.sleep(15)
            # Remove the intent first. An orphaned immutable .data is harmless, never replayed.
            manifest.unlink();manifest.with_suffix('.data').unlink()

    def put(self,relative,raw,immutable=True):
        relative=Path(relative)
        if relative.is_absolute() or relative.drive or '..' in relative.parts or not relative.parts or relative.parts[0]=='.pending-shared':
            raise ValueError('unsafe archive name')
        self.sync()
        local=self.local/relative
        previous=local.read_bytes() if local.exists() else None
        if immutable and previous is not None and previous!=raw: raise ValueError('local immutable archive conflict')
        intent={'relative':str(relative),'sha256':sha(raw),'previous_sha256':sha(previous) if previous is not None else None,
                'immutable':immutable,'shared_root':str(self.shared),'lock_token':uuid.uuid4().hex}
        manifest=self.local/'.pending-shared'/(uuid.uuid4().hex+'.json')
        atomic(manifest.with_suffix('.data'),raw)
        atomic(manifest,encoded(intent))  # crash before local replacement is recoverable
        atomic(local,raw)
        self.sync()

    def wait_online(self):
        while True:
            try: self.shared.parent.stat();return
            except OSError as exc:
                if not network_error(exc): raise
                self._stop()
                print('WAITING FOR SHARE: no new submissions; existing C estimates retained.',flush=True)
                self.sleep(15)
