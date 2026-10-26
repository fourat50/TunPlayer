"""Portable data layer: SQLite library, M3U / Xtream and XMLTV."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import unicodedata
from collections import defaultdict
from pathlib import Path
from datetime import datetime
from xml.etree import ElementTree as ET
from . import __version__
from .catalog import KINDS, SORTS, METADATA_FIELDS, metadata, classify_m3u, fold, genres

MAX_DOWNLOAD = 64 * 1024 * 1024


class SourceError(ValueError):
    """A user-facing error with no provider credentials in its message."""


def read_resource(location: str) -> str:
    if urllib.parse.urlsplit(location).scheme in ('http', 'https'):
        request = urllib.request.Request(location, headers={'User-Agent': f'TunPlayer/{__version__}'})
        with urllib.request.urlopen(request, timeout=25) as response:
            data = response.read(MAX_DOWNLOAD + 1)
    else:
        with open(location, 'rb') as stream:
            data = stream.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise SourceError('Source trop volumineuse (maximum 64 Mo).')
    return data.decode('utf-8-sig', errors='replace')

def parse_m3u(text: str, base: str = '') -> list[dict]:
    channels, pending = [], None
    if '#EXTM3U' not in text[:2048].upper():
        raise SourceError('Ce fichier ne contient pas de playlist M3U étendue.')
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('#EXTINF:'):
            match = re.search(r',(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)', line)
            head, name = (line[:match.start()], line[match.end():]) if match else (line, '')
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', head))
            pending = {'name': name.strip() or attrs.get('tvg-name', 'Sans nom'),
                       'group_name': attrs.get('group-title', 'Général'),
                       'tvg_id': attrs.get('tvg-id', ''), 'logo': urllib.parse.urljoin(base,attrs.get('tvg-logo','')) if attrs.get('tvg-logo') and base.startswith(('http://','https://')) else attrs.get('tvg-logo', ''),
                       **metadata(dict(attrs, name=name, language=attrs.get('tvg-language') or attrs.get('language',''))), '_attrs':attrs}
        elif line and not line.startswith('#') and pending:
            scheme = urllib.parse.urlsplit(line).scheme.lower()
            # Playlists cannot execute commands or load local files from a remote source.
            if scheme in ('http', 'https', 'rtsp', 'rtmp', 'udp', 'rtp'):
                url = line
            elif not scheme and base:
                url = urllib.parse.urljoin(base, line) if base.startswith(('https://','http://')) else str((Path(base).parent / line).resolve())
            else:
                pending = None
                continue
            kind = classify_m3u(pending['name'],url,pending.pop('_attrs'))
            channels.append({**pending, 'url': url, 'kind': kind})
            pending = None
    if not channels:
        raise SourceError('Aucun flux compatible trouvé dans cette playlist.')
    return channels

def request_xtream(config, action, **parameters):
    server=config['server'].rstrip('/')
    if urllib.parse.urlsplit(server).scheme not in ('http','https'):
        raise SourceError('Le serveur doit commencer par http:// ou https://.')
    params=dict(username=config['username'],password=config['password'],**parameters)
    if action is not None:params['action']=action
    query=urllib.parse.urlencode(params)
    return json.loads(read_resource(f'{server}/player_api.php?{query}'))


def stream_url(config, prefix, identity, extension):
    identity=str(identity)
    if not identity.isdigit():raise SourceError('Identifiant de flux Xtream invalide.')
    if not re.fullmatch(r'[A-Za-z0-9]{1,8}',str(extension)):raise SourceError('Format de flux Xtream invalide.')
    return (f'{config["server"].rstrip("/")}/{prefix}/'
        f'{urllib.parse.quote(config["username"],safe="")}/{urllib.parse.quote(config["password"],safe="")}/{identity}.{extension}')


def api_rows(data, title):
    """Accept common Xtream arrays, numeric-key objects and wrapped responses."""
    if isinstance(data,dict):
        for key in ('data','results','series','items','categories'):
            if key in data:
                return api_rows(data[key],title)
        if data and all(str(key).isdigit() for key in data):data=list(data.values())
        elif not data:return []
    if not isinstance(data,list) or any(not isinstance(row,dict) for row in data):
        raise SourceError(f'Réponse invalide pour {title}. Le catalogue précédent est conservé.')
    return data


def xtream_rows(config,kind):
    actions={'live':('get_live_streams','get_live_categories','live','ts'),
             'movie':('get_vod_streams','get_vod_categories','movie','mp4'),
             'series':('get_series','get_series_categories','series','mp4')}
    action,cat_action,prefix,extension=actions[kind]
    categories=api_rows(request_xtream(config,cat_action),'les catégories')
    rows=api_rows(request_xtream(config,action),'les séries' if kind=='series' else 'les contenus')
    groups={str(c.get('category_id')):str(c.get('category_name') or 'Général') for c in categories}
    result=[]
    for row in rows:
        sid=row.get('series_id') if kind=='series' else row.get('stream_id')
        if sid is None:continue
        sid=str(sid)
        if not sid.isdigit():raise SourceError('Identifiant Xtream invalide.')
        result.append(dict(name=str(row.get('name') or sid),group_name=groups.get(str(row.get('category_id')),'Général'),
            tvg_id=str(row.get('epg_channel_id') or ''),logo=str(row.get('cover') or row.get('stream_icon') or ''),kind=kind,
            provider_id=sid,url=f'xtream-series:{sid}' if kind=='series' else stream_url(config,prefix,sid,row.get('container_extension') or extension),
            **metadata(row)))
    if rows and not result:raise SourceError('Les identifiants du catalogue ne sont pas reconnus.')
    return result


def load_series_catalog(config):
    if config.get('type')!='xtream':raise SourceError('Connectez un compte Xtream pour récupérer son catalogue de séries.')
    return xtream_rows(config,'series')


def xtream(server: str, username: str, password: str) -> list[dict]:
    config=dict(server=server,username=username,password=password)
    result=[]
    for kind in ('live','movie','series'):result.extend(xtream_rows(config,kind))
    if not result:raise SourceError('Ce compte ne contient aucun flux.')
    return result


def load_series(config, series, with_details=False):
    if config.get('type')!='xtream':raise SourceError('Cette source ne propose pas de catalogue de saisons.')
    data=request_xtream(config,'get_series_info',series_id=series['provider_id'])
    if isinstance(data,dict) and 'episodes' not in data and isinstance(data.get('data'),dict):data=data['data']
    if not isinstance(data,dict) or not isinstance(data.get('episodes'),(dict,list)):
        raise SourceError('La liste des épisodes de cette série est indisponible.')
    groups=data['episodes']
    if isinstance(groups,list):
        if all(isinstance(row,dict) and 'id' in row for row in groups):groups={'0':groups}
        else:groups={str(index):rows for index,rows in enumerate(groups)}
    episodes=[]
    for season,rows in groups.items():
        if isinstance(rows,dict) and all(str(key).isdigit() for key in rows):rows=list(rows.values())
        if not isinstance(rows,list):raise SourceError('Réponse de saison invalide.')
        for index,row in enumerate(rows,1):
            if not isinstance(row,dict):raise SourceError('Épisode invalide.')
            info=row.get('info') if isinstance(row.get('info'),dict) else {}
            season_number=metadata(dict(season=row.get('season') or season))['season']
            episode_number=metadata(row)['episode_num'] or index
            sid=str(row.get('id') or '')
            extension=str(row.get('container_extension') or 'mp4').lstrip('.')
            url=stream_url(config,'series',sid,extension)
            title=str(row.get('title') or f'Épisode {episode_number}')
            episodes.append(dict(name=f'{series["name"]} · S{season_number:02}E{episode_number:02} · {title}',
                group_name=series['group_name'],tvg_id='',logo=str(info.get('movie_image') or series['logo'] or ''),
                kind='episode',provider_id=sid,url=url,parent_id=series['id'],
                **metadata(dict(info,season=season_number,episode_num=episode_number))))
    if not episodes:raise SourceError('Aucun épisode disponible. Les épisodes déjà enregistrés sont conservés.')
    if with_details:
        info=data.get('info') if isinstance(data.get('info'),dict) else {}
        return dict(episodes=episodes,details=media_details(series,info))
    return episodes

def media_details(channel,info):
    combined=dict(channel)
    if info.get('description') and not info.get('plot'):combined['plot']=info['description']
    if info.get('actors') and not info.get('cast'):combined['cast']=info['actors']
    if (info.get('duration') or info.get('episode_run_time')) and not (info.get('duration_secs') or info.get('duration_seconds')):
        combined['duration_seconds']=0
    for key,value in info.items():
        if value not in (None,'',[],{}):combined[key]=value
    result=metadata(combined)
    image=info.get('movie_image') or info.get('cover_big') or info.get('cover') or channel.get('logo','')
    if isinstance(image,str) and image.startswith(('http://','https://')):result['logo']=image
    return result

def load_vod_details(config,channel):
    if config.get('type')!='xtream' or not channel.get('provider_id'):
        return media_details(channel,{})
    data=request_xtream(config,'get_vod_info',vod_id=channel['provider_id'])
    if isinstance(data,dict) and 'info' not in data and isinstance(data.get('data'),dict):data=data['data']
    if not isinstance(data,dict) or not isinstance(data.get('info'),dict):
        raise SourceError('La fiche détaillée est indisponible. Les informations déjà enregistrées sont conservées.')
    info=dict(data.get('movie_data') or {});info.update(data['info'])
    return media_details(channel,info)

def parse_xmltv(text: str) -> list[tuple]:
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise SourceError('Les déclarations DTD et entités XML ne sont pas acceptées.')
    root = ET.fromstring(text)
    def stamp(value):
        value = value.strip()
        return datetime.strptime(value, '%Y%m%d%H%M%S %z').timestamp() if ' ' in value else datetime.strptime(value, '%Y%m%d%H%M%S').astimezone().timestamp()
    programmes = []
    for p in root.findall('programme'):
        try:
            start, stop = stamp(p.attrib['start']), stamp(p.attrib['stop'])
            if stop > start:
                programmes.append((p.attrib['channel'], start, stop, p.findtext('title', 'Sans titre'), p.findtext('desc', '')))
        except (KeyError, ValueError):
            continue
    if not programmes:
        raise SourceError('Aucun programme XMLTV valide trouvé.')
    return programmes


def load_source(config):
    """Fetch a source from its locally stored connection settings."""
    if config.get('type') == 'm3u':
        location = config['location']
        return parse_m3u(read_resource(location), location)
    if config.get('type') == 'xtream':
        return xtream(config['server'], config['username'], config['password'])
    raise SourceError('Reconnectez cette source pour enregistrer ses paramètres.')


def search_text(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value or '').casefold()
                   if not unicodedata.combining(c))

class Library:
    def __init__(self, path, *, migrate=True, read_only=False):
        self.path = Path(path)
        if read_only or not migrate:
            self.db=sqlite3.connect(f'file:{self.path}?mode=ro',uri=True,timeout=5) if read_only else sqlite3.connect(self.path,timeout=15)
            self.db.row_factory=sqlite3.Row
            self.db.create_function('search_text',1,search_text,deterministic=True)
            self.db.execute('PRAGMA foreign_keys=ON')
            if read_only:self.db.execute('PRAGMA query_only=ON')
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        try:
            self.path.chmod(0o600)
            for suffix in ('-wal', '-shm'):
                sidecar = Path(str(self.path) + suffix)
                if sidecar.exists():
                    sidecar.chmod(0o600)
        except OSError:
            pass
        self.db = sqlite3.connect(self.path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.create_function('search_text', 1, search_text, deterministic=True)
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, name TEXT NOT NULL, count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY, source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
          name TEXT, group_name TEXT, tvg_id TEXT, logo TEXT, url TEXT, kind TEXT, favorite INTEGER DEFAULT 0,
          watched REAL DEFAULT 0, position REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS programmes(channel TEXT, start REAL, stop REAL, title TEXT, description TEXT);
        CREATE INDEX IF NOT EXISTS epg_lookup ON programmes(channel,start,stop);
        CREATE INDEX IF NOT EXISTS channel_name ON channels(name COLLATE NOCASE,id);
        CREATE INDEX IF NOT EXISTS channel_source ON channels(source_id,kind);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        ''')
        # Additive migration: existing libraries keep identifiers and viewing state.
        catalog_migration='quality' not in {r['name'] for r in self.db.execute('PRAGMA table_info(channels)')}
        migrations = {'sources': {'config': "TEXT NOT NULL DEFAULT '{}'", 'account': "TEXT NOT NULL DEFAULT '{}'", 'updated_at': 'REAL NOT NULL DEFAULT 0', 'series_checked': 'REAL NOT NULL DEFAULT 0'},
                      'channels': {'provider_id': "TEXT NOT NULL DEFAULT ''", 'search_name': 'TEXT', 'search_group': 'TEXT',
                          'genre': "TEXT NOT NULL DEFAULT ''", 'year': 'INTEGER NOT NULL DEFAULT 0',
                          'rating': 'REAL NOT NULL DEFAULT 0', 'added': 'REAL NOT NULL DEFAULT 0',
                          'language': "TEXT NOT NULL DEFAULT ''", 'quality': "TEXT NOT NULL DEFAULT ''",
                          'plot': "TEXT NOT NULL DEFAULT ''", 'search_genre': "TEXT NOT NULL DEFAULT ''",
                          'parent_id': 'TEXT REFERENCES channels(id) ON DELETE CASCADE',
                          'imported_at': 'REAL NOT NULL DEFAULT 0',
                          'cast': "TEXT NOT NULL DEFAULT ''", 'director': "TEXT NOT NULL DEFAULT ''",
                          'duration_seconds': 'INTEGER NOT NULL DEFAULT 0', 'details_loaded_at':'REAL NOT NULL DEFAULT 0',
                          'completed':'INTEGER NOT NULL DEFAULT 0',
                          'season': 'INTEGER NOT NULL DEFAULT 0', 'episode_num': 'INTEGER NOT NULL DEFAULT 0'}}
        with self.db:
            for table, fields in migrations.items():
                existing = {r['name'] for r in self.db.execute(f'PRAGMA table_info({table})')}
                for field, declaration in fields.items():
                    if field not in existing:
                        self.db.execute(f'ALTER TABLE {table} ADD COLUMN {field} {declaration}')
            self.db.execute('''UPDATE channels SET search_name=search_text(name),search_group=search_text(group_name)
                               WHERE search_name IS NULL OR search_group IS NULL''')
            if catalog_migration:
                for row in self.db.execute('SELECT id,name FROM channels').fetchall():
                    info=metadata(dict(row))
                    self.db.execute('UPDATE channels SET quality=?,year=? WHERE id=?',(info['quality'],info['year'],row['id']))
            self.db.execute('CREATE INDEX IF NOT EXISTS channel_search_name ON channels(search_name,id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS channel_category ON channels(kind,source_id,group_name) WHERE parent_id IS NULL')
            self.db.execute('CREATE INDEX IF NOT EXISTS channel_history ON channels(watched DESC,id) WHERE watched>0')
            self.db.execute('CREATE INDEX IF NOT EXISTS channel_parent ON channels(parent_id,season,episode_num)')
            self.db.execute('CREATE INDEX IF NOT EXISTS channel_player_order ON channels(kind,source_id,group_name,search_name,id) WHERE parent_id IS NULL')
            self.db.execute('''CREATE INDEX IF NOT EXISTS channel_latest ON channels
                (kind,CASE WHEN added>0 THEN added ELSE imported_at END DESC,search_name,id)
                WHERE parent_id IS NULL''')
            self.db.execute('''CREATE INDEX IF NOT EXISTS discovery_trends ON channels
                (rating DESC,CASE WHEN added>0 THEN added ELSE imported_at END DESC,search_name,id)
                WHERE parent_id IS NULL AND kind IN ('movie','series')''')
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def close(self):
        self.db.close()

    @staticmethod
    def _unique_channels(channels):
        result = {}
        for channel in channels:
            key = (channel['kind'], channel['url'])
            # Check required fields before any writes, including duplicate entries.
            for field in ('name', 'group_name', 'tvg_id', 'logo', 'url', 'kind'):
                if not isinstance(channel[field], str):
                    raise SourceError('Une entrée de la playlist contient des champs invalides.')
            if not channel['url'] or channel['kind'] not in KINDS:
                raise SourceError('Une entrée de la playlist est invalide.')
            normalized=dict(channel,provider_id=str(channel.get('provider_id') or ''),**metadata(channel))
            normalized.update(search_name=fold(channel['name']),search_group=fold(channel['group_name']),
                search_genre=','.join(fold(g) for g in genres(normalized['genre'])),parent_id=channel.get('parent_id'))
            result.setdefault(key,normalized)
        if not result:
            raise SourceError('La source est vide. Votre bibliothèque est conservée.')
        return list(result.values())

    def import_channels(self, name, channels, config=None):
        channels = self._unique_channels(channels)
        with self.db:
            source = self.db.execute('INSERT INTO sources(name,count,config,updated_at) VALUES (?,0,?,?)',
                                     (name, json.dumps(config or {}), time.time())).lastrowid
            self._insert_channels(source, channels)
            self.db.execute('UPDATE sources SET count=? WHERE id=?', (len(channels), source))
        return source

    def _insert_channels(self, source, channels):
        for channel in channels:
            identity = hashlib.sha256(f'{source}:{channel["kind"]}:{channel["url"]}'.encode()).hexdigest()[:24]
            # A removed channel may have left its previous ID attached to another URL.
            # Resolve this rare collision without changing the matched channel's ID.
            suffix = 0
            candidate = identity
            while self.db.execute('SELECT 1 FROM channels WHERE id=?', (candidate,)).fetchone():
                suffix += 1
                candidate = hashlib.sha256(f'{identity}:{suffix}'.encode()).hexdigest()[:24]
            fields=('name','group_name','tvg_id','logo','url','kind','provider_id',
                    'search_name','search_group','search_genre','parent_id',*METADATA_FIELDS)
            columns=','.join(fields); placeholders=','.join('?' for _ in range(len(fields)+3))
            self.db.execute(f'INSERT INTO channels(id,source_id,imported_at,{columns}) VALUES ({placeholders})',
                            (candidate,source,time.time(),*(channel[k] for k in fields)))

    def refresh_source(self, source, channels, config=None, name=None, *, kind=None):
        """Atomically reconcile a playlist; never guess ambiguous channel matches."""
        channels = self._unique_channels(channels)
        with self.db:
            current = self.db.execute('SELECT * FROM sources WHERE id=?', (source,)).fetchone()
            if not current:
                raise SourceError('Cette source n’existe plus.')
            if kind and any(row['kind']!=kind for row in channels):raise SourceError('Le catalogue contient un type de contenu incorrect.')
            sql='SELECT * FROM channels WHERE source_id=? AND parent_id IS NULL'
            previous = [dict(r) for r in self.db.execute(sql+(' AND kind=?' if kind else ''),(source,kind) if kind else (source,))]
            # Match in passes. Exact URLs are reserved before weaker metadata matches.
            matches, used = {}, set()
            for field in ('url', 'provider_id', 'tvg_id'):
                old_index, new_index = defaultdict(list), defaultdict(list)
                for old in previous:
                    if old['id'] not in used and old[field]:
                        old_index[(old['kind'], old[field])].append(old)
                for index, new in enumerate(channels):
                    if index not in matches and new.get(field):
                        new_index[(new['kind'], new[field])].append(index)
                for key, indices in new_index.items():
                    candidates = old_index.get(key, [])
                    if len(indices) == len(candidates) == 1:
                        index, old = indices[0], candidates[0]
                        matches[index] = old['id']; used.add(old['id'])
            removed = [old['id'] for old in previous if old['id'] not in used]
            self.db.executemany('DELETE FROM channels WHERE id=?', ((identity,) for identity in removed))
            old_by_id={old['id']:old for old in previous}
            for index, identity in matches.items():
                new = channels[index]
                self._update_channel(identity,new,old_by_id[identity])
            added = [new for index, new in enumerate(channels) if index not in matches]
            self._insert_channels(source, added)
            total=self.db.execute('SELECT COUNT(*) FROM channels WHERE source_id=? AND parent_id IS NULL',(source,)).fetchone()[0]
            self.db.execute('UPDATE sources SET name=?,count=?,config=?,updated_at=? WHERE id=?',
                (name if name is not None else current['name'], total,
                 json.dumps(config) if config is not None else current['config'], time.time(), source))
        return {'added': len(added), 'retained': len(matches), 'removed': len(removed), 'total': len(channels)}

    def refresh_series_catalog(self, source, rows):
        # An empty/failed provider response must not erase a previously usable catalogue.
        result=self.refresh_source(source,rows,kind='series') if rows else {'added':0,'retained':0,'removed':0,'total':0}
        with self.db:self.db.execute('UPDATE sources SET series_checked=? WHERE id=?',(time.time(),source))
        return result

    def _update_channel(self, identity, channel, previous=None):
        previous=previous or self.channel(identity) or {}
        channel=dict(channel)
        for field in ('genre','plot','cast','director','duration_seconds','year','rating','logo'):
            if not channel.get(field) and previous.get(field):channel[field]=previous[field]
        channel['search_genre']=','.join(fold(g) for g in genres(channel.get('genre')))
        fields=('name','group_name','tvg_id','logo','url','kind','provider_id',
                'search_name','search_group','search_genre',*METADATA_FIELDS)
        self.db.execute('UPDATE channels SET '+','.join(f'{field}=?' for field in fields)+' WHERE id=?',
                        (*(channel[field] for field in fields),identity))

    def store_episodes(self, series_id, episodes):
        episodes=self._unique_channels(episodes)
        identifiers=[episode['provider_id'] for episode in episodes]
        if not all(identifiers) or len(set(identifiers))!=len(identifiers):raise SourceError('Identifiants d’épisodes ambigus.')
        with self.db:
            series=self.channel(series_id)
            if not series or series['kind']!='series':raise SourceError('Cette série n’existe plus.')
            old={row['provider_id']:dict(row) for row in self.db.execute('SELECT * FROM channels WHERE parent_id=?',(series_id,))}
            for episode in episodes:
                if episode['kind']!='episode':raise SourceError('Épisode invalide.')
                episode['parent_id']=series_id
                if episode['provider_id'] in old:
                    previous=old.pop(episode['provider_id']);self._update_channel(previous['id'],episode,previous)
                else:self._insert_channels(series['source_id'],[episode])
            self.db.executemany('DELETE FROM channels WHERE id=?',((row['id'],) for row in old.values()))
        return self.episodes(series_id)

    def episodes(self, series_id, season=None):
        sql='SELECT * FROM channels WHERE parent_id=?';args=[series_id]
        if season is not None:sql+=' AND season=?';args.append(season)
        return [dict(row) for row in self.db.execute(sql+' ORDER BY season,episode_num,name,id',args)]

    def update_details(self,identity,details):
        old=self.channel(identity)
        if not old:raise SourceError('Ce contenu n’existe plus.')
        updated=dict(old,**details);normalized=self._unique_channels([updated])[0]
        with self.db:
            self._update_channel(identity,normalized,old)
            self.db.execute('UPDATE channels SET details_loaded_at=? WHERE id=?',(time.time(),identity))
        return self.channel(identity)

    def next_episode(self,identity):
        current=self.channel(identity)
        if not current or current['kind']!='episode' or not current['parent_id']:return None
        row=self.db.execute('''SELECT * FROM channels WHERE parent_id=?
            AND (season,episode_num,name,id)>(?,?,?,?) ORDER BY season,episode_num,name,id LIMIT 1''',
            (current['parent_id'],current['season'],current['episode_num'],current['name'],identity)).fetchone()
        return dict(row) if row else None

    def continue_episode(self,parent):
        recent=self.db.execute('SELECT * FROM channels WHERE parent_id=? AND watched>0 ORDER BY watched DESC,id LIMIT 1',(parent,)).fetchone()
        if recent:
            recent=dict(recent)
            if not recent['completed']:return recent
            following=self.next_episode(recent['id'])
            if following:return following
        row=self.db.execute('SELECT * FROM channels WHERE parent_id=? AND completed=0 ORDER BY season,episode_num,name,id LIMIT 1',(parent,)).fetchone()
        if not row:row=self.db.execute('SELECT * FROM channels WHERE parent_id=? ORDER BY season,episode_num,name,id LIMIT 1',(parent,)).fetchone()
        return dict(row) if row else None

    def finish_media(self,identity):
        with self.db:self.db.execute('UPDATE channels SET completed=1,position=0,watched=? WHERE id=?',(time.time(),identity))

    def set_duration(self,identity,seconds):
        if seconds>0:
            with self.db:self.db.execute('UPDATE channels SET duration_seconds=? WHERE id=?',(int(seconds),identity))

    @staticmethod
    def _filter(search='', group=None, view='all', source_id=None, *, kind=None, favorites=False,
                quality=None, language=None, genre=None, year=None, min_rating=0, unwatched=False, has_artwork=False):
        clauses, args = ['1=1'], []
        if view not in ('history','favorites'):clauses.append('parent_id IS NULL')
        if search:
            for term in fold(search).split():
                clauses.append('(instr(search_name,?)>0 OR instr(search_group,?)>0 OR instr(search_genre,?)>0)')
                args.extend([term]*3)
        if group is not None:
            clauses.append('group_name=?'); args.append(group)
        if source_id is not None:
            clauses.append('source_id=?'); args.append(source_id)
        if view == 'favorites' or favorites: clauses.append('favorite=1')
        if view == 'history': clauses.append('watched>0')
        if view in ('live', 'movie','series'):
            clauses.append('kind=?'); args.append(view)
        elif kind:
            if kind not in ('live','movie','series'):raise SourceError('Type de contenu invalide.')
            if kind=='series':clauses.append("kind IN ('series','episode')")
            else:clauses.append('kind=?');args.append(kind)
        for field,value in [('quality',quality),('language',language),('year',year)]:
            if value is not None and value!='':clauses.append(f'{field}=?');args.append(value)
        if genre:
            clauses.append("instr(','||search_genre||',',?)>0");args.append(','+fold(genre)+',')
        if min_rating:
            clauses.append('rating>=?');args.append(float(min_rating))
        if unwatched:clauses.append('watched=0')
        if has_artwork:clauses.append("logo LIKE 'http://%' OR logo LIKE 'https://%'")
        return ' AND '.join(f'({clause})' for clause in clauses), args

    def channels(self, search='', group=None, view='all', *, source_id=None, limit=None, offset=0, sort=None, **filters):
        where, args = self._filter(search, group, view, source_id,**filters)
        selected_sort=sort or ('watched' if view=='history' else 'name')
        if selected_sort not in SORTS:raise SourceError('Tri invalide.')
        order = SORTS[selected_sort]
        sql = f'SELECT * FROM channels WHERE {where} ORDER BY {order}'
        if limit is not None:
            if limit < 1 or offset < 0:
                raise SourceError('Pagination invalide.')
            sql += ' LIMIT ? OFFSET ?'; args.extend([limit, offset])
        return [dict(row) for row in self.db.execute(sql, args)]

    def discovery(self,search='',limit=12):
        movies=self.channels(search=search,view='movie',sort='added',limit=limit)
        series=self.channels(search=search,view='series',sort='added',limit=limit)
        where,args=self._filter(search=search)
        # No invented worldwide popularity: rank only the ratings supplied by sources.
        trends=[dict(row) for row in self.db.execute(f'''SELECT * FROM channels WHERE {where}
            AND kind IN ('movie','series') ORDER BY rating DESC,
            CASE WHEN added>0 THEN added ELSE imported_at END DESC,search_name,id LIMIT ?''',(*args,limit))]
        return [dict(key='movies',title='Derniers films ajoutés',view='movie',sort='added',rows=movies),
                dict(key='series',title='Dernières séries ajoutées',view='series',sort='added',rows=series),
                dict(key='trends',title='Tendances',view=None,sort=None,rows=trends)]

    def channel_count(self, search='', group=None, view='all', *, source_id=None, **filters):
        where, args = self._filter(search, group, view, source_id,**filters)
        return self.db.execute(f'SELECT COUNT(*) FROM channels WHERE {where}', args).fetchone()[0]

    def groups(self, view='all', source_id=None):
        where, args = self._filter(view=view, source_id=source_id)
        return [r[0] for r in self.db.execute(
            f'SELECT DISTINCT group_name FROM channels WHERE {where} ORDER BY group_name COLLATE NOCASE', args)]

    def group_counts(self, view='all',source_id=None,search='',**filters):
        where,args=self._filter(search=search,view=view,source_id=source_id,**filters)
        return [dict(row) for row in self.db.execute(f'SELECT group_name,COUNT(*) AS count FROM channels WHERE {where} GROUP BY group_name ORDER BY group_name COLLATE NOCASE',args)]

    def facets(self, view='all', source_id=None):
        where,args=self._filter(view=view,source_id=source_id)
        result={}
        for field in ('language','quality','year','genre'):
            values=[r[0] for r in self.db.execute(f'SELECT DISTINCT {field} FROM channels WHERE {where} AND {field}!=? ORDER BY {field}',(*args,0 if field=='year' else ''))]
            result[field]=sorted({g for value in values for g in genres(value)},key=fold) if field=='genre' else values
        return result

    def channel(self, identity):
        row = self.db.execute('SELECT * FROM channels WHERE id=?', (identity,)).fetchone()
        return dict(row) if row else None

    def favorite(self, identity):
        with self.db:
            self.db.execute('UPDATE channels SET favorite=1-favorite WHERE id=?', (identity,))

    def watched(self, identity, position=None):
        with self.db:
            self.db.execute('UPDATE channels SET watched=?,completed=0 WHERE id=?', (time.time(), identity))
            if position is not None:
                self.db.execute('UPDATE channels SET position=? WHERE id=?', (position, identity))

    def sources(self):
        # Connection secrets are deliberately absent from list views.
        return [dict(r) for r in self.db.execute("SELECT id,name,count,updated_at,series_checked,config!='{}' AS refreshable FROM sources ORDER BY name COLLATE NOCASE,id")]

    def source_config(self, identity):
        row = self.db.execute('SELECT config FROM sources WHERE id=?', (identity,)).fetchone()
        if not row:
            raise SourceError('Cette source n’existe plus.')
        return json.loads(row[0])

    def source_account(self, identity):
        row=self.db.execute('SELECT account FROM sources WHERE id=?',(identity,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_source_account(self,identity,account,expected_config):
        with self.db:
            row=self.db.execute('SELECT config FROM sources WHERE id=?',(identity,)).fetchone()
            if row and json.loads(row[0])==expected_config:
                self.db.execute('UPDATE sources SET account=? WHERE id=?',(json.dumps(account),identity))
                return True
        return False

    def source_counts(self,identity):
        return dict(self.db.execute('SELECT kind,COUNT(*) FROM channels WHERE source_id=? GROUP BY kind',(identity,)))

    def delete_source(self, identity):
        with self.db:
            self.db.execute('DELETE FROM sources WHERE id=?', (identity,))

    def import_epg(self, programmes):
        with self.db:
            self.db.execute('DELETE FROM programmes')
            self.db.executemany('INSERT INTO programmes VALUES (?,?,?,?,?)', programmes)

    def programmes(self, tvg_id, now=None):
        return [dict(r) for r in self.db.execute('SELECT * FROM programmes WHERE channel=? AND stop>? ORDER BY start LIMIT 12',
                                               (tvg_id, time.time() if now is None else now))]

    def guide_channels(self, search='', limit=60, offset=0):
        where, args = self._filter(search=search, view='live')
        rows = self.db.execute(f'''SELECT * FROM channels WHERE {where} AND EXISTS
            (SELECT 1 FROM programmes p WHERE p.channel=channels.tvg_id AND p.stop>?)
            ORDER BY name COLLATE NOCASE,id LIMIT ? OFFSET ?''', (*args, time.time(), limit, offset))
        return [dict(r) for r in rows]

    def guide_count(self, search=''):
        where, args = self._filter(search=search, view='live')
        return self.db.execute(f'''SELECT COUNT(*) FROM channels WHERE {where} AND EXISTS
            (SELECT 1 FROM programmes p WHERE p.channel=channels.tvg_id AND p.stop>?)''',
            (*args, time.time())).fetchone()[0]

    def setting(self, key, default=''):
        row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, str(value)))
