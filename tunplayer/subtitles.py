"""Bounded subtitle APIs and a private, content-addressed local subtitle store."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from difflib import SequenceMatcher
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlencode,urlsplit,quote
from urllib.request import Request,build_opener,HTTPRedirectHandler
from zipfile import ZipFile,BadZipFile
from . import __version__
from .catalog import fold
from .subtitle_languages import ALIASES

MAX_BYTES=4*1024*1024
PROVIDERS={'podnapisi':'Podnapisi','opensubtitles':'OpenSubtitles.com','subdl':'SubDL','subliminal':'Subliminal'}


class SubtitleError(ValueError):pass


def number(value):
    try:return max(0,int(value or 0))
    except (TypeError,ValueError,OverflowError):return 0


def language_code(value):
    value=str(value).strip().lower().replace('_','-')
    return ALIASES.get(value,value)


def private_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as stream:
            temporary=Path(stream.name);json.dump(data,stream,ensure_ascii=False)
        temporary.chmod(0o600);os.replace(temporary,path)
    finally:
        if temporary:temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        path=Path(path)
        if path.stat().st_size>MAX_BYTES:return {}
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def media_query(channel,parent=None):
    episode=channel.get('kind')=='episode'
    title=(parent or {}).get('name') if episode else channel.get('name','')
    title=title or re.split(r'\s*[·|]\s*S\d+E\d+',channel.get('name',''),flags=re.I)[0]
    title=re.sub(r'\b(?:2160p|1080p|720p|4K|FHD|UHD|HDR|HEVC|x26[45])\b','',title,flags=re.I)
    year=number(channel.get('year'))
    found=re.search(r'\((19\d{2}|20\d{2})\)',title)
    if found:
        year=year or number(found[1]);title=title[:found.start()]+title[found.end():]
    return dict(title=' '.join(title.strip(' -·|').split())[:240],year=year,kind='episode' if episode else 'movie',
        season=number(channel.get('season')),episode=number(channel.get('episode_num')))


def validate_query(query):
    result=dict(query);result['title']=str(result.get('title','')).strip()[:240]
    if not result['title']:raise SubtitleError('Indiquez le titre à rechercher.')
    for key in ('year','season','episode'):result[key]=number(result.get(key))
    if result.get('kind')=='episode' and not result['episode']:raise SubtitleError('Indiquez le numéro de l’épisode.')
    language=language_code(result.get('language',''))
    if not re.fullmatch(r'[a-z]{2,3}(?:-[a-z]{2,4})?',language):raise SubtitleError('Choisissez une langue ou indiquez son code ISO, par exemple fr ou ar.')
    result['language']=language;return result


def ranking(query,title='',year=0,season=0,episode=0):
    similarity=SequenceMatcher(None,fold(query['title']),fold(title)).ratio() if title else 0
    points=round(similarity*60)
    if query.get('year') and number(year)==query['year']:points+=15
    if query.get('kind')=='episode' and (number(season),number(episode))==(query['season'],query['episode']):points+=25
    return points


def trusted_url(url):
    try:
        parsed=urlsplit(url);port=parsed.port
    except (ValueError,TypeError):raise SubtitleError('Adresse de sous-titres invalide.') from None
    host=parsed.hostname or ''
    allowed=any(host==domain or host.endswith('.'+domain) for domain in ('opensubtitles.com','opensubtitles.org','podnapisi.net','subdl.com'))
    if parsed.scheme!='https' or not allowed or parsed.username or parsed.password or port not in (None,443):
        raise SubtitleError('Adresse de sous-titres refusée.')
    return url


class SubtitleRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        trusted_url(newurl)
        result=super().redirect_request(req,fp,code,msg,headers,newurl)
        if result:
            for name in ('Authorization','Api-key'):result.remove_header(name)
        return result


class SubtitleHTTP:
    def __init__(self,opener=None):self.opener=opener or build_opener(SubtitleRedirect()).open

    def fetch(self,url,params=None,body=None,headers=None):
        trusted_url(url)
        if params:url+='?'+urlencode(sorted(params.items()),doseq=True)
        values={'User-Agent':f'TunPlayer v{__version__}','Accept':'application/json'};values.update(headers or {})
        data=None if body is None else json.dumps(body).encode()
        if data is not None:values['Content-Type']='application/json'
        try:
            with self.opener(Request(url,data=data,headers=values),timeout=12) as response:
                data=response.read(MAX_BYTES+1)
        except HTTPError as error:
            messages={401:'Connexion expirée ou identifiants incorrects.',403:'Accès refusé : vérifiez la clé API ou le compte.',
                406:'Quota de téléchargement atteint.',429:'Trop de requêtes. Réessayez plus tard.'}
            message=messages.get(error.code,'La source de sous-titres est indisponible.');error.close()
            raise SubtitleError(message) from None
        except OSError:raise SubtitleError('Source inaccessible. Vérifiez la connexion puis réessayez.') from None
        if len(data)>MAX_BYTES:raise SubtitleError('Réponse de sous-titres trop volumineuse.')
        return data

    def json(self,*args,**kwargs):
        try:
            value=json.loads(self.fetch(*args,**kwargs))
            if not isinstance(value,dict):raise ValueError()
            return value
        except (ValueError,UnicodeError) as error:
            if isinstance(error,SubtitleError):raise
            raise SubtitleError('Réponse invalide de la source de sous-titres.') from None


class OpenSubtitles:
    name='opensubtitles'
    def __init__(self,http,settings):self.http=http;self.settings=dict(settings)

    def headers(self):
        key=self.settings.get('api_key','').strip()
        if not key:raise SubtitleError('Ajoutez votre clé OpenSubtitles.com dans les préférences.')
        headers={'Api-Key':key}
        if self.settings.get('token') and time.time()<number(self.settings.get('expires')):headers['Authorization']='Bearer '+self.settings['token']
        return headers

    def api(self,path,**kwargs):
        base=self.settings.get('base_url','api.opensubtitles.com')
        if base not in ('api.opensubtitles.com','vip-api.opensubtitles.com'):base='api.opensubtitles.com'
        return self.http.json('https://'+base+'/api/v1/'+path,headers=self.headers(),**kwargs)

    def login(self,username,password):
        data=self.api('login',body={'username':username,'password':password})
        token=data.get('token');base=data.get('base_url','api.opensubtitles.com')
        if not isinstance(token,str) or not token or base not in ('api.opensubtitles.com','vip-api.opensubtitles.com'):
            raise SubtitleError('La connexion OpenSubtitles a échoué.')
        return dict(self.settings,token=token,base_url=base,expires=int(time.time()+23*3600),username=username)

    def search(self,query,cancel):
        params=dict(query=query['title'],languages=query['language'],type=query['kind'],page=1,order_by='download_count',order_direction='desc')
        if query['kind']=='episode':params.update(season_number=query['season'],episode_number=query['episode'])
        elif query['year']:params['year']=query['year']
        rows=[]
        for page in range(1,3):
            if cancel.is_set():break
            params['page']=page;data=self.api('subtitles',params=params)
            for item in data.get('data',[])[:100]:
                attrs=item.get('attributes',{});feature=attrs.get('feature_details') or {}
                if query['kind']=='episode' and (number(feature.get('season_number')),number(feature.get('episode_number')))!=(query['season'],query['episode']):continue
                title=feature.get('parent_title') or feature.get('title','')
                for file in (attrs.get('files') or [])[:10]:
                    if not number(file.get('file_id')):continue
                    rows.append(dict(provider=self.name,id=str(file['file_id']),language=str(attrs.get('language') or query['language']),
                        release=str(file.get('file_name') or attrs.get('release') or title)[:320],
                        hearing=bool(attrs.get('hearing_impaired')),machine=bool(attrs.get('machine_translated')),
                        score=ranking(query,title,feature.get('year'),feature.get('season_number'),feature.get('episode_number'))))
            if page>=number(data.get('total_pages',1)):break
        return rows

    def download(self,row):
        data=self.api('download',body=dict(file_id=number(row['id']),sub_format='srt'))
        link=data.get('link','')
        return self.http.fetch(trusted_url(link)),str(data.get('file_name') or 'subtitle.srt')


class Podnapisi:
    name='podnapisi';base='https://www.podnapisi.net/subtitles'
    def __init__(self,http):self.http=http

    def search(self,query,cancel):
        params=dict(keywords=query['title'],language=query['language'])
        if query['year']:params['year']=query['year']
        if query['kind']=='episode':params.update(seasons=query['season'],episodes=query['episode'],movie_type=['tv-series','mini-series'])
        else:params['movie_type']='movie'
        rows=[]
        for page in range(1,3):
            if cancel.is_set():break
            params['page']=page;data=self.http.json(self.base+'/search/advanced',params=params)
            for item in data.get('data',[])[:100]:
                movie=item.get('movie') or {};ep=movie.get('episode_info') or {};identity=str(item.get('id',''))
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',identity):continue
                if query['kind']=='episode' and (number(ep.get('season')),number(ep.get('episode')))!=(query['season'],query['episode']):continue
                if query['kind']=='movie' and movie.get('type') not in ('movie',None):continue
                release=' · '.join(str(v) for v in (item.get('releases') or [])+(item.get('custom_releases') or []))
                rows.append(dict(provider=self.name,id=identity,language=str(item.get('language') or query['language']),
                    release=(release or str(movie.get('title','')))[:320],hearing='hearing_impaired' in (item.get('flags') or []),machine=False,
                    score=ranking(query,movie.get('title',''),movie.get('year'),ep.get('season'),ep.get('episode'))))
            if page>=number(data.get('all_pages',1)):break
        return rows

    def download(self,row):return self.http.fetch(self.base+'/'+quote(row['id'],safe='')+'/download',params={'container':'zip'}),'subtitle.zip'


def subtitle_text(data,filename,language=''):
    if len(data)>MAX_BYTES:raise SubtitleError('Sous-titre trop volumineux.')
    if data.startswith(b'PK'):
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist())>100:raise SubtitleError('Archive de sous-titres invalide.')
                files=[f for f in archive.infolist() if not f.is_dir() and Path(f.filename).suffix.lower() in ('.srt','.ass','.ssa','.vtt')]
                if len(files)!=1:raise SubtitleError('L’archive doit contenir un seul sous-titre. Choisissez un autre résultat.')
                entry=files[0]
                if entry.file_size>MAX_BYTES or entry.flag_bits&1:raise SubtitleError('Archive trop volumineuse ou chiffrée.')
                data=archive.read(entry);filename=entry.filename
        except (BadZipFile,RuntimeError,NotImplementedError):raise SubtitleError('Archive de sous-titres illisible.') from None
    encoding='utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
    try:text=data.decode(encoding)
    except UnicodeError:
        legacy={'ar':'cp1256','fa':'cp1256','ur':'cp1256','ru':'cp1251','uk':'cp1251','bg':'cp1251','el':'cp1253','tr':'cp1254','he':'cp1255'}
        text=data.decode(legacy.get(language.split('-')[0],'cp1252'),errors='replace')
    text=text.replace('\r\n','\n').replace('\r','\n').strip()
    if '\x00' in text or re.search(r'<(?:!doctype|html|script)\b',text,re.I):raise SubtitleError('Le fichier reçu n’est pas un sous-titre valide.')
    extension='.ass' if '[Events]' in text and 'Dialogue:' in text else '.vtt' if text.startswith('WEBVTT') else '.srt'
    if extension in ('.srt','.vtt') and not re.search(r'\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3}\s*-->\s*\d',text):
        raise SubtitleError('Le fichier reçu ne contient pas de sous-titres reconnus.')
    return (text+'\n').encode('utf-8'),extension


class SubtitleStore:
    def __init__(self,root):self.root=Path(root)
    def save(self,channel_id,row,data,filename):
        content,extension=subtitle_text(data,filename,row['language'])
        key=hashlib.sha256((str(channel_id)+'\0'+row['provider']+'\0'+row['id']+'\0'+row['language']).encode()).hexdigest()
        self.root.mkdir(parents=True,exist_ok=True);path=self.root/(key+extension)
        with tempfile.NamedTemporaryFile(dir=self.root,delete=False) as stream:
            temporary=Path(stream.name);stream.write(content)
        try:temporary.chmod(0o600);os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
        return path

    def select(self,channel_id,path,delay=0):
        path=Path(path).resolve()
        if path.parent!=self.root.resolve() or not path.is_file():raise SubtitleError('Sous-titre local introuvable.')
        delay=float(delay)
        if not math.isfinite(delay):raise SubtitleError('Décalage invalide.')
        index=read_json(self.root/'selected.json')
        index[str(channel_id)]={'file':path.name,'delay':max(-120,min(120,delay))}
        private_json(self.root/'selected.json',index)

    def selected(self,channel_id):
        row=read_json(self.root/'selected.json').get(str(channel_id),{})
        if not isinstance(row,dict):return None
        name=row.get('file','')
        if not isinstance(name,str) or not re.fullmatch(r'[0-9a-f]{64}\.(?:srt|ass|vtt)',name):return None
        path=self.root/name
        if not path.is_file() or path.resolve().parent!=self.root.resolve():return None
        try:
            delay=float(row.get('delay',0))
            if not math.isfinite(delay):delay=0
            delay=max(-120,min(120,delay))
        except (TypeError,ValueError):delay=0
        return path,delay


class SubtitleService:
    def __init__(self,settings=None,http=None):
        self.http=http or SubtitleHTTP();self.settings=settings or {}

    def providers(self):
        values={'podnapisi':Podnapisi(self.http),'opensubtitles':OpenSubtitles(self.http,self.settings)}
        from .subtitle_subdl import SubDL
        values['subdl']=SubDL(self.http,self.settings)
        from .subtitle_subliminal import SubliminalProvider
        if SubliminalProvider.available():values['subliminal']=SubliminalProvider()
        return values

    def search(self,query,enabled,cancel):
        query=validate_query(query);providers=self.providers();rows=[];errors={}
        selected={k:v for k,v in providers.items() if k in enabled}
        if not selected:raise SubtitleError('Sélectionnez au moins une source disponible.')
        with ThreadPoolExecutor(max_workers=3,thread_name_prefix='tunplayer-subtitles') as pool:
            futures={pool.submit(p.search,query,cancel):k for k,p in selected.items()}
            for future in as_completed(futures):
                if cancel.is_set():continue
                name=futures[future]
                try:rows.extend(future.result())
                except SubtitleError as error:errors[name]=str(error)
                except Exception:errors[name]='Réponse de la source invalide ou indisponible.'
        unique={}
        for row in rows:
            # A provider must never silently return another language.
            if language_code(row['language'])!=query['language']:continue
            unique[(row['provider'],row['id'],row['language'])]=row
        return dict(rows=sorted(unique.values(),key=lambda r:(-r['score'],r['provider'],r['release']))[:240],errors=errors)

    def download(self,row):
        provider=self.providers().get(row.get('provider'))
        if provider is None:raise SubtitleError('Cette source de sous-titres est indisponible.')
        return provider.download(row)
