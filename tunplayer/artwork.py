"""Bounded image download/cache and asynchronous delivery on the GTK main loop."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import gi
gi.require_version('GdkPixbuf','2.0')
from gi.repository import GdkPixbuf, GLib
from . import __version__

MAX_IMAGE=8*1024*1024
CACHE_BUDGET=160*1024*1024
CACHE_AGE=14*24*3600


def decode_image(data,max_width=720,max_height=1080):
    if len(data)>MAX_IMAGE:raise ValueError('Image too large')
    # Restrict the format to static raster decoders; remote SVGs are not needed.
    if data.startswith(b'\x89PNG\r\n\x1a\n'):format_name='png'
    elif data.startswith(b'\xff\xd8'):format_name='jpeg'
    elif data[:6] in (b'GIF87a',b'GIF89a'):format_name='gif'
    elif data.startswith(b'RIFF') and data[8:12]==b'WEBP':format_name='webp'
    else:raise ValueError('Unsupported image format')
    loader=GdkPixbuf.PixbufLoader.new_with_type(format_name)
    dimensions=[]
    def size_ready(loader,width,height):
        dimensions.append((width,height))
        scale=min(1,max_width/max(1,width),max_height/max(1,height))
        loader.set_size(max(1,int(width*scale)),max(1,int(height*scale)))
    loader.connect('size-prepared',size_ready)
    try:
        loader.write(data);loader.close()
        if not dimensions or max(dimensions[0])>16000 or dimensions[0][0]*dimensions[0][1]>50_000_000:
            raise ValueError('Image dimensions too large')
        pixbuf=loader.get_pixbuf()
        if pixbuf is None:raise ValueError('Empty image')
        return pixbuf
    except Exception:
        try:loader.close()
        except Exception:pass
        raise


class ArtworkCache:
    def __init__(self,directory,budget=CACHE_BUDGET,*,max_width=720,max_height=1080):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.budget=budget;self.lock=threading.Lock();self.cache_bytes=None;self.last_prune=0
        self.max_width=max_width;self.max_height=max_height

    def path_for(self,url):
        return self.directory/(hashlib.sha256(url.encode()).hexdigest()+'.image')

    def load(self,url):
        if urllib.parse.urlsplit(url).scheme not in ('http','https'):return None
        path=self.path_for(url)
        try:
            if path.exists() and time.time()-path.stat().st_mtime<CACHE_AGE:
                data=path.read_bytes()
                if len(data)>MAX_IMAGE:raise ValueError('Cached image too large')
                return decode_image(data,self.max_width,self.max_height)
        except (OSError,ValueError,GLib.Error):
            try:path.unlink(missing_ok=True)
            except OSError:pass
        request=urllib.request.Request(url,headers={'User-Agent':f'TunPlayer/{__version__}','Accept':'image/*'})
        with urllib.request.urlopen(request,timeout=8) as response:
            if urllib.parse.urlsplit(response.geturl()).scheme not in ('http','https'):raise ValueError('Invalid redirect')
            data=response.read(MAX_IMAGE+1)
        pixbuf=decode_image(data,self.max_width,self.max_height)
        with self.lock:
            temporary=None
            try:
                with tempfile.NamedTemporaryFile(dir=self.directory,prefix='.download-',delete=False) as stream:
                    temporary=Path(stream.name);stream.write(data)
                old_size=path.stat().st_size if path.exists() else 0
                os.replace(temporary,path)
                if self.cache_bytes is not None:self.cache_bytes+=len(data)-old_size
                if self.cache_bytes is None or self.cache_bytes>self.budget or time.monotonic()-self.last_prune>30:
                    self.prune(protect=path)
            finally:
                if temporary:temporary.unlink(missing_ok=True)
        return pixbuf

    def prune(self,protect=None):
        files=[]
        for path in self.directory.glob('*.image'):
            try:files.append((path.stat().st_mtime,path,path.stat().st_size))
            except OSError:pass
        total=sum(item[2] for item in files)
        for modified,path,size in sorted(files,key=lambda record:(record[1]==protect,record[0])):
            if total<=self.budget and time.time()-modified<CACHE_AGE:continue
            try:path.unlink();total-=size
            except OSError:pass
        self.cache_bytes=total;self.last_prune=time.monotonic()


class ArtworkLoader:
    def __init__(self,directory):
        self.cache=ArtworkCache(directory,max_width=360,max_height=540)
        self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='tunplayer-art')
        self.pending={};self.closed=False
        self.failed={}
        self.memory=OrderedDict();self.memory_bytes=0

    def request(self,url,callback):
        if self.closed or not url.startswith(('http://','https://')):return
        if url in self.memory:
            pixbuf=self.memory.pop(url);self.memory[url]=pixbuf;callback(pixbuf);return
        if self.failed.get(url,0)>time.monotonic()-60:return
        if url in self.pending:
            self.pending[url]['callbacks'].append(callback);return
        record={'callbacks':[callback]};self.pending[url]=record
        future=self.pool.submit(self.cache.load,url)
        record['future']=future
        def completed(future):
            try:pixbuf=future.result()
            except Exception:pixbuf=None
            GLib.idle_add(self.deliver,url,record,pixbuf)
        future.add_done_callback(completed)

    def deliver(self,url,record,pixbuf):
        if self.pending.get(url) is not record:return False
        self.pending.pop(url,None);callbacks=record['callbacks']
        if self.closed:return False
        if pixbuf is None:self.failed[url]=time.monotonic()
        else:
            size=pixbuf.get_rowstride()*pixbuf.get_height()
            self.memory[url]=pixbuf;self.memory_bytes+=size
            while self.memory_bytes>64*1024*1024 and self.memory:
                _,old=self.memory.popitem(last=False);self.memory_bytes-=old.get_rowstride()*old.get_height()
            for callback in callbacks:callback(pixbuf)
        return False

    def retire(self):
        """Drop callbacks for a replaced page and cancel downloads not yet started."""
        for url,record in list(self.pending.items()):
            record['callbacks'].clear()
            if record['future'].cancel():self.pending.pop(url,None)

    def close(self):
        self.closed=True;self.pending.clear()
        self.memory.clear();self.memory_bytes=0
        self.pool.shutdown(wait=False,cancel_futures=True)
