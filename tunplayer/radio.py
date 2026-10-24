"""Radio Browser directory used by OpenRadio: bounded requests, mirrors and cache."""
import hashlib
import json
import os
from pathlib import Path
import random
import re
import tempfile
import threading
import time
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen
from uuid import UUID
from . import __version__
from .catalog import fold

PAGE_SIZE=40
MAX_BYTES=4*1024*1024


class RadioError(ValueError):pass


def filter_summary(query,countries=(),favorites=False):
    code=query.get('country','')
    country=next((row['name'] for row in countries if row['code']==code),code) if code else 'Tous les pays'
    parts=['Pays : '+country,'Genre : '+(query.get('tag') or 'Toutes les catégories')]
    if query.get('text'):parts.append('Recherche : « '+query['text'][:200]+' »')
    if favorites:parts.append('Mes radios uniquement')
    return ' · '.join(parts)


def web_url(value):
    if not isinstance(value,str):return ''
    value=value.strip()
    try:parsed=urlsplit(value)
    except ValueError:return ''
    return value if parsed.scheme in ('http','https') and parsed.hostname and not parsed.username else ''


def stations(rows):
    result=[];ids=set();urls=set()
    for row in rows:
        if not isinstance(row,dict) or str(row.get('lastcheckok','1'))=='0':continue
        try:identity=str(UUID(str(row.get('stationuuid',''))))
        except ValueError:continue
        url=web_url(row.get('url_resolved')) or web_url(row.get('url'))
        name=str(row.get('name') or '').strip()[:240]
        if not url or not name or identity in ids or url in urls:continue
        ids.add(identity);urls.add(url)
        tags=list(dict.fromkeys(t.strip().lower()[:80] for t in str(row.get('tags') or '').split(',') if t.strip()))[:20]
        def number(key):
            try:return max(0,int(row.get(key) or 0))
            except (ValueError,TypeError):return 0
        result.append(dict(id='radio-'+identity,stationuuid=identity,radio=True,kind='live',name=name,url=url,
            logo=web_url(row.get('favicon')),country=str(row.get('country') or 'Pays non renseigné')[:100],
            countrycode=str(row.get('countrycode') or '').upper()[:2],tags=tags,group_name=tags[0] if tags else 'Autres',
            codec=str(row.get('codec') or '')[:20],bitrate=number('bitrate'),language=str(row.get('language') or '')[:100],
            clicks=number('clickcount'),favorite=0,position=0,tvg_id='',source_id=None))
    return result


def favorite_rows(favorites,query):
    rows=[dict(row) for row in favorites.values() if row.get('radio') and web_url(row.get('url'))]
    country=query.get('country');tag=query.get('tag');terms=fold(query.get('text','')).split()
    rows=[r for r in rows if (not country or r['countrycode']==country) and (not tag or tag in r['tags'])
          and all(t in fold(r['name']+' '+r['country']+' '+' '.join(r['tags'])) for t in terms)]
    order=query.get('order','popular')
    rows.sort(key=lambda r:(-r.get('clicks',0),fold(r['name'])) if order=='popular' else
              (fold(r['country']),fold(r['name'])) if order=='country' else fold(r['name']))
    offset=max(0,query.get('page',0))*PAGE_SIZE
    return dict(rows=rows[offset:offset+PAGE_SIZE],has_next=len(rows)>offset+PAGE_SIZE,stale=False)


class RadioDirectory:
    def __init__(self,cache,opener=None,clock=time.time):
        self.cache=Path(cache);self.opener=opener or urlopen;self.clock=clock
        self.mirrors=None;self.mirror_deadline=0;self.lock=threading.Lock()

    def fetch(self,url):
        request=Request(url,headers={'User-Agent':f'TunPlayer/{__version__} (+https://github.com/fourat50/TunPlayer)',
                                    'Accept':'application/json'})
        with self.opener(request,timeout=6) as response:data=response.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise RadioError('Réponse radio trop volumineuse.')
        result=json.loads(data)
        if not isinstance(result,list):raise RadioError('Réponse de l’annuaire radio invalide.')
        return result

    def servers(self,cancel):
        override=os.environ.get('RADIO_BROWSER_BASE_URL','').strip().rstrip('/')
        if override:
            if not web_url(override) or urlsplit(override).scheme!='https':raise RadioError('Le serveur radio doit utiliser HTTPS.')
            return [override]
        if self.mirrors and self.clock()<self.mirror_deadline:return self.mirrors
        mirrors=[]
        try:
            if not cancel.is_set():
                for row in self.fetch('https://all.api.radio-browser.info/json/servers'):
                    name=row.get('name','') if isinstance(row,dict) else ''
                    if isinstance(name,str) and re.fullmatch(r'[a-z0-9-]+\.api\.radio-browser\.info',name):mirrors.append('https://'+name)
        except (OSError,ValueError):pass
        mirrors=list(dict.fromkeys(mirrors)) or ['https://de1.api.radio-browser.info','https://fr1.api.radio-browser.info']
        random.shuffle(mirrors);self.mirrors=mirrors;self.mirror_deadline=self.clock()+3600
        return mirrors

    def request(self,path,parameters,cancel,ttl=600,refresh=False):
        key=path+'?'+urlencode(sorted(parameters.items()))
        file=self.cache/(hashlib.sha256(key.encode()).hexdigest()+'.json')
        cached=None
        try:
            if file.stat().st_size<=MAX_BYTES:
                cached=json.loads(file.read_text())
                if not isinstance(cached.get('data'),list) or not isinstance(cached.get('time'),(int,float)):cached=None
        except (OSError,ValueError,AttributeError):pass
        if cached and not refresh and self.clock()-cached['time']<ttl:return cached['data'],False
        if cancel.is_set():return [],False
        for mirror in self.servers(cancel)[:2]:
            if cancel.is_set():return [],False
            try:
                data=self.fetch(mirror+key)
                if cancel.is_set():return [],False
                try:
                    self.cache.mkdir(parents=True,exist_ok=True)
                    with tempfile.NamedTemporaryFile(mode='w',dir=self.cache,delete=False,encoding='utf-8') as stream:
                        json.dump(dict(time=self.clock(),data=data),stream);temporary=stream.name
                    os.replace(temporary,file)
                    with self.lock:
                        for old in sorted(self.cache.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[48:]:old.unlink(missing_ok=True)
                except OSError:pass
                return data,False
            except (OSError,ValueError):continue
        if cancel.is_set():return [],False
        if cached:return cached['data'],True
        raise RadioError('Annuaire radio indisponible. Vérifiez la connexion puis réessayez.')

    def search(self,query,cancel,refresh=False):
        params=dict(name=query.get('text','')[:200],countrycode=query.get('country',''),tag=query.get('tag',''),
            tagExact='true',hidebroken='true',order={'popular':'clickcount','name':'name','country':'country'}.get(query.get('order'),'clickcount'),
            reverse='true' if query.get('order','popular')=='popular' else 'false',limit=PAGE_SIZE,offset=max(0,query.get('page',0))*PAGE_SIZE)
        raw,stale=self.request('/json/stations/search',params,cancel,refresh=refresh)
        return dict(rows=stations(raw),has_next=len(raw)==PAGE_SIZE,stale=stale)

    def facets(self,cancel):
        countries,stale=self.request('/json/countries',dict(hidebroken='true'),cancel,ttl=86400)
        try:tags,old=self.request('/json/tags',dict(hidebroken='true',order='stationcount',reverse='true',limit=150),cancel,ttl=86400)
        except RadioError:tags=[];old=True
        def count(row):
            try:return max(0,int(row.get('stationcount',0)))
            except (TypeError,ValueError):return 0
        return dict(countries=sorted([dict(name=str(r.get('name','')),code=r['iso_3166_1'],count=count(r)) for r in countries
            if isinstance(r,dict) and re.fullmatch('[A-Z]{2}',str(r.get('iso_3166_1','')))],key=lambda r:fold(r['name'])),
            groups=sorted([dict(group_name=str(r['name']),count=count(r)) for r in tags if isinstance(r,dict) and r.get('name')],key=lambda r:fold(r['group_name'])),stale=stale or old)
