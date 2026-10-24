"""Persistent VOD download queue. HTTP ranges are validated before appending."""
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
from . import __version__

CHUNK=256*1024
ACTIVE=('queued','running','pausing','cancelling')


class DownloadError(ValueError):pass
class Stopped(Exception):pass


def safe_name(value):
    text=re.sub(r'[\x00-\x1f<>:"/\\|?*]','_',unicodedata.normalize('NFC',str(value)))
    text=text.encode('utf-8')[:120].decode('utf-8',errors='ignore').strip(' .') or 'Sans titre'
    if text.upper() in ('CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(10)),*(f'LPT{i}' for i in range(10))):text='_'+text
    return text


def plan(channels,directory,series=None):
    directory=Path(directory).expanduser().resolve();result=[]
    for channel in channels:
        url=channel.get('url','');parsed=urlsplit(url)
        if channel.get('kind') not in ('movie','episode','series') or channel.get('radio') or parsed.scheme not in ('http','https') or not parsed.hostname:
            raise DownloadError('Ce contenu ne possède pas de lien vidéo HTTP(S) téléchargeable.')
        if channel['kind']=='series' and url.startswith('xtream-series:'):raise DownloadError('Choisissez une saison ou un épisode.')
        token=hashlib.sha256((str(channel['id'])+'\0'+url).encode()).hexdigest()[:12]
        root=directory
        if series:
            series_token=hashlib.sha256(str(series['id']).encode()).hexdigest()[:8]
            root=root/f'{safe_name(series["name"])}-{series_token}'/f'Saison {int(channel.get("season") or 0):02d}'
        suffix=Path(parsed.path).suffix.lower()
        hls=suffix in ('.m3u8','.mpd')
        extension='.mkv' if hls else suffix if suffix in ('.mp4','.mkv','.m4v','.avi','.mov','.webm','.ts','.mpg','.mpeg') else '.video'
        prefix=f'S{int(channel.get("season") or 0):02d}E{int(channel.get("episode_num") or 0):02d} - ' if channel['kind']=='episode' else ''
        path=root/f'{prefix}{safe_name(channel["name"])}-{token}{extension}'
        identity=hashlib.sha256((str(path)+'\0'+url).encode()).hexdigest()
        result.append(dict(id=identity,channel_id=channel['id'],name=channel['name'],url=url,path=str(path),
            state='queued',downloaded=0,total=0,etag='',error='',hls=hls,created=time.time()))
    return result


class DownloadManager:
    def __init__(self,journal,opener=None,ffmpeg=None):
        self.journal=Path(journal);self.opener=opener or urlopen;self.ffmpeg=ffmpeg
        self.lock=threading.RLock();self.jobs={};self.events={};self.processes={}
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='tunplayer-download')
        self.closed=False;self.running=False;self.last_save=0;self.persistence_error=False
        try:
            for row in json.loads(self.journal.read_text()):
                if not isinstance(row,dict) or not re.fullmatch('[a-f0-9]{64}',str(row.get('id',''))):continue
                if not all(k in row for k in ('path','url','name','state','channel_id')):continue
                if row['state'] in ACTIVE:row['state']='paused'
                self.jobs[row['id']]=row;self.events[row['id']]=threading.Event()
        except (OSError,ValueError,TypeError):pass

    def _save(self,force=False):
        if not force and time.monotonic()-self.last_save<1:return
        temporary=None
        try:
            self.journal.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.journal.parent,delete=False) as stream:
                temporary=Path(stream.name);json.dump(list(self.jobs.values()),stream,ensure_ascii=False)
            temporary.chmod(0o600);os.replace(temporary,self.journal);self.last_save=time.monotonic();self.persistence_error=False
        except OSError:self.persistence_error=True;self.last_save=time.monotonic()
        finally:
            if temporary:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass

    def snapshot(self):
        with self.lock:return [dict({k:v for k,v in row.items() if k not in ('url','etag')},
            resume_supported=bool(row.get('etag') and not row['etag'].startswith('W/') and not row.get('hls'))) for row in self.jobs.values()]

    @property
    def idle(self):
        with self.lock:return not self.running

    def _schedule(self):
        if not self.running and not self.closed:
            self.running=True;self.pool.submit(self._drain)

    def enqueue(self,items):
        with self.lock:
            if self.closed:raise DownloadError('Le gestionnaire se ferme.')
            added=0
            for row in items:
                if row['id'] in self.jobs:continue
                self.jobs[row['id']]=dict(row);self.events[row['id']]=threading.Event();added+=1
            self._save(True);self._schedule();return added

    def pause(self,identity,cancel=False):
        with self.lock:
            row=self.jobs[identity]
            if row['state']=='done':return
            event=self.events[identity];event.set()
            row['stop']='cancelled' if cancel else 'paused'
            if row['state'] in ('running','pausing','cancelling'):row['state']='cancelling' if cancel else 'pausing'
            else:
                row['state']=row['stop']
                if cancel:self._part(row).unlink(missing_ok=True)
            process=self.processes.get(identity)
            if process and process.poll() is None:self._stop_process(process)
            self._save(True)

    def resume(self,identity):
        with self.lock:
            row=self.jobs[identity]
            if row['state'] not in ('paused','error','cancelled'):return
            row.update(state='queued',error='',stop='paused');self.events[identity]=threading.Event()
            self._save(True);self._schedule()

    def _part(self,row):
        target=Path(row['path']);return target.with_name('.'+target.name+'.'+row['id'][:12]+'.part')

    def _progress(self,row,count,total=0):
        with self.lock:
            row['downloaded']=count;row['total']=total;self._save()

    def _check(self,event):
        if event.is_set() or self.closed:raise Stopped()

    @staticmethod
    def _stop_process(process):
        try:process.terminate()
        except OSError:return
        def kill():
            try:
                if process.poll() is None:process.kill()
            except OSError:pass
        timer=threading.Timer(3,kill);timer.daemon=True;timer.start()

    def _drain(self):
        try:
            while True:
                with self.lock:
                    if self.closed:return
                    row=next((r for r in self.jobs.values() if r['state']=='queued'),None)
                    if row is None:return
                    row['state']='running';event=self.events[row['id']];self._save(True)
                try:
                    self._transfer(row,event);self._check(event)
                    self._finish_file(row,event)
                    with self.lock:row.update(state='done',error='')
                except Stopped:
                    with self.lock:
                        row['state']=row.get('stop','paused')
                        if row['state']=='cancelled':self._part(row).unlink(missing_ok=True);row['downloaded']=0
                except Exception as error:
                    with self.lock:
                        row['state']='error'
                        row['error']=str(error) if isinstance(error,DownloadError) else 'Espace disque insuffisant.' if isinstance(error,OSError) and error.errno==errno.ENOSPC else 'Transfert interrompu. Vérifiez la connexion, l’espace libre et les droits du dossier.'
                with self.lock:self.processes.pop(row['id'],None);self._save(True)
        finally:
            with self.lock:
                self.running=False
                if not self.closed and any(r['state']=='queued' for r in self.jobs.values()):self._schedule()

    def _transfer(self,row,event):
        self._check(event)
        target=Path(row['path']);target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():raise DownloadError('Un fichier du même nom existe déjà. Il n’a pas été écrasé.')
        if row.get('hls'):return self._segmented(row,event)
        part=self._part(row);offset=part.stat().st_size if part.exists() else 0
        # A strong ETag prevents concatenating two different versions of a film.
        if not row.get('etag') or row['etag'].startswith('W/'):offset=0
        headers={'User-Agent':f'TunPlayer/{__version__}','Accept-Encoding':'identity'}
        if offset:headers.update(Range=f'bytes={offset}-',**{'If-Range':row['etag']})
        try:response=self.opener(Request(row['url'],headers=headers),timeout=8)
        except HTTPError as error:
            if error.code==416 and offset:
                error.close();offset=0;headers.pop('Range');headers.pop('If-Range')
                response=self.opener(Request(row['url'],headers=headers),timeout=8)
            else:
                error.close()
                raise DownloadError(f'Le serveur a refusé le téléchargement (HTTP {error.code}).') from None
        with response:
            status=getattr(response,'status',200);mime=response.headers.get('Content-Type','').split(';')[0].lower()
            if mime in ('application/vnd.apple.mpegurl','application/x-mpegurl','audio/mpegurl','audio/x-mpegurl','application/dash+xml'):
                part.unlink(missing_ok=True)
                with self.lock:row['hls']=True;row['path']=str(target.with_suffix('.mkv'))
                response.close()
                if Path(row['path']).exists():raise DownloadError('Un fichier du même nom existe déjà. Il n’a pas été écrasé.')
                return self._segmented(row,event)
            if mime.startswith('text/') or mime in ('application/json','application/problem+json','application/xml'):
                raise DownloadError('Le serveur a renvoyé une page ou un message au lieu du fichier vidéo.')
            total=0
            if status==206:
                match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                if not match or int(match[1])!=offset or int(match[2])<offset or int(match[3])<=int(match[2]):
                    raise DownloadError('Le serveur a renvoyé une plage de reprise invalide. Le fichier partiel est conservé.')
                if offset and response.headers.get('ETag',row['etag'])!=row['etag']:raise DownloadError('Le fichier a changé sur le serveur. Annulez puis recommencez.')
                total=int(match[3])
            elif status==200:offset=0
            else:raise DownloadError(f'Réponse HTTP inattendue : {status}.')
            length=response.headers.get('Content-Length')
            if length:
                try:length=int(length)
                except ValueError:raise DownloadError('Taille de fichier invalide.') from None
                if length<0:raise DownloadError('Taille de fichier invalide.')
                if not total:total=offset+length
            with self.lock:row['etag']=response.headers.get('ETag','')
            count=offset;self._progress(row,count,total)
            with part.open('ab' if offset else 'wb') as stream:
                while True:
                    self._check(event);data=response.read(CHUNK);self._check(event)
                    if not data:break
                    stream.write(data);count+=len(data);self._progress(row,count,total)
                stream.flush();os.fsync(stream.fileno())
            if not count or (total and count!=total):raise DownloadError('Le fichier reçu est incomplet. Vous pouvez reprendre le téléchargement.')

    def _segmented(self,row,event):
        ffmpeg=self.ffmpeg or shutil.which('ffmpeg')
        if not ffmpeg:raise DownloadError('FFmpeg est introuvable pour télécharger ce flux vidéo.')
        self._check(event);part=self._part(row);part.unlink(missing_ok=True)
        command=[str(ffmpeg),'-hide_banner','-loglevel','error','-nostdin','-n','-rw_timeout','15000000',
            '-protocol_whitelist','http,https,tcp,tls,crypto,data','-i',row['url'],
            '-map','0:v?','-map','0:a?','-map','0:s?','-c','copy','-progress','pipe:1','-nostats','-f','matroska',str(part)]
        with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True) as process:
            with self.lock:self.processes[row['id']]=process
            try:
                self._check(event)
                for line in process.stdout:
                    self._check(event)
                    if line.startswith('total_size='):
                        try:self._progress(row,int(line.split('=',1)[1]),0)
                        except ValueError:pass
                code=process.wait();self._check(event)
                if code or not part.exists() or part.stat().st_size==0:raise DownloadError('FFmpeg n’a pas pu terminer le fichier vidéo. Réessayez depuis le début.')
                self._progress(row,part.stat().st_size,0)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.kill();process.wait()

    def _finish_file(self,row,event):
        self._check(event);part=self._part(row);target=Path(row['path'])
        try:os.link(part,target)
        except OSError as error:
            if error.errno==errno.EEXIST:raise DownloadError('Un fichier du même nom existe déjà. Il n’a pas été écrasé.') from None
            if error.errno not in (errno.EPERM,errno.EOPNOTSUPP,errno.EXDEV):raise
            # Removable filesystems may not support hard links. Exclusive creation
            # still guarantees that an existing user file is never overwritten.
            with target.open('xb') as output,part.open('rb') as source:
                try:
                    while True:
                        self._check(event);data=source.read(CHUNK)
                        if not data:break
                        output.write(data)
                except BaseException:target.unlink(missing_ok=True);raise
        part.unlink()

    def close(self,wait=False):
        with self.lock:
            self.closed=True
            for row in self.jobs.values():
                if row['state'] in ACTIVE:
                    self.events[row['id']].set();row['stop']='paused';row['state']='paused'
            for process in self.processes.values():
                if process.poll() is None:self._stop_process(process)
            self._save(True)
        self.pool.shutdown(wait=wait,cancel_futures=True)
