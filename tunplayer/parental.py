"""Application category locks: salted scrypt PIN, cooldown and session grants."""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
import unicodedata

KINDS=('live','movie','series','radio')


class PinError(ValueError):pass


def category_key(kind,name):
    if kind not in KINDS:raise PinError('Type de catégorie invalide.')
    return json.dumps([kind,unicodedata.normalize('NFC',str(name)).strip().casefold()],ensure_ascii=False)


class CategoryLocks:
    def __init__(self,path,clock=time.time):
        self.path=Path(path);self.clock=clock;self.record=None;self.locks={};self.grants=set()
        self.failures=0;self.blocked_until=0.;self.invalid=False
        try:
            data=json.loads(self.path.read_text())
            record=data.get('pin')
            if record is not None:
                if len(bytes.fromhex(record['salt']))!=16 or len(bytes.fromhex(record['digest']))!=32:raise ValueError('PIN record')
            self.record=record
            for row in data.get('categories',[]):self.locks[category_key(row['kind'],row['name'])]=dict(kind=row['kind'],name=str(row['name']))
            self.failures=max(0,int(data.get('failures',0)));self.blocked_until=float(data.get('blocked_until',0))
            if not math.isfinite(self.blocked_until):raise ValueError('Invalid cooldown')
            if self.locks and not self.record:raise ValueError('Missing PIN')
        except FileNotFoundError:pass
        except (OSError,ValueError,TypeError,KeyError,AttributeError):self.invalid=True

    @property
    def configured(self):return self.record is not None or self.invalid

    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        data=dict(pin=self.record,categories=list(self.locks.values()),failures=self.failures,blocked_until=self.blocked_until)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.path.parent,delete=False) as stream:
                temporary=Path(stream.name);json.dump(data,stream,ensure_ascii=False)
            temporary.chmod(0o600);os.replace(temporary,self.path)
        finally:
            if temporary:temporary.unlink(missing_ok=True)

    def remaining(self):return max(0,min(300,math.ceil(self.blocked_until-self.clock())))

    @staticmethod
    def validate(pin):
        if not isinstance(pin,str) or not re.fullmatch(r'[0-9]{4,8}',pin):raise PinError('Le PIN doit contenir entre 4 et 8 chiffres.')

    @staticmethod
    def derive(pin,salt):return hashlib.scrypt(pin.encode(),salt=salt,n=16384,r=8,p=1,dklen=32)

    def _state(self):return self.record,self.locks.copy(),self.grants.copy(),self.failures,self.blocked_until

    def _commit(self,before):
        try:self._save()
        except OSError:
            self.record,self.locks,self.grants,self.failures,self.blocked_until=before
            raise

    def verify(self,pin):
        if self.invalid or self.record is None or self.remaining():return False
        valid=isinstance(pin,str) and re.fullmatch('[0-9]{4,8}',pin)
        match=bool(valid and hmac.compare_digest(self.derive(pin,bytes.fromhex(self.record['salt'])),bytes.fromhex(self.record['digest'])))
        if match:self.failures=0;self.blocked_until=0
        else:
            self.failures+=1
            if self.failures>=5:self.blocked_until=self.clock()+min(300,30*2**min(4,self.failures-5))
        self._save();return match

    def set_pin(self,pin,current=None):
        self.validate(pin)
        if self.configured and not self.verify(current):raise PinError('PIN actuel incorrect ou temporairement bloqué.')
        before=self._state()
        salt=os.urandom(16);self.record=dict(salt=salt.hex(),digest=self.derive(pin,salt).hex())
        self.failures=0;self.blocked_until=0;self.grants.clear();self._commit(before)

    def protect(self,kind,name,pin,locked=True):
        if not self.verify(pin):raise PinError('PIN incorrect ou temporairement bloqué.')
        before=self._state()
        key=category_key(kind,name)
        if locked:self.locks[key]=dict(kind=kind,name=str(name))
        else:self.locks.pop(key,None)
        self.grants.discard(key);self._commit(before)

    def locked(self,kind,name):return self.invalid or category_key(kind,name) in self.locks

    def pending(self,keys):return {key for key in keys if self.invalid or key in self.locks} - self.grants

    def relock(self):self.grants.clear()

    def disable(self,pin):
        if not self.verify(pin):raise PinError('PIN incorrect ou temporairement bloqué.')
        before=self._state();self.record=None;self.locks.clear();self.grants.clear();self._commit(before)
