"""Cancellable catalogue reads and serialized/coalesced writes off the GTK thread."""
from collections import OrderedDict
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
from gi.repository import GLib
from .core import Library


class SnapshotCache:
    """Small expiring LRU; callers never share mutable results across threads."""
    def __init__(self,limit=12,ttl=15,clock=time.monotonic):
        self.limit=limit;self.ttl=ttl;self.clock=clock
        self.items=OrderedDict();self.lock=threading.Lock()

    @staticmethod
    def key(request):return json.dumps(request,sort_keys=True,separators=(',',':'))

    def get(self,request):
        key=self.key(request)
        with self.lock:
            item=self.items.pop(key,None)
            if item is None:return None
            deadline,value=item
            if self.clock()>=deadline:return None
            self.items[key]=item
            return deepcopy(value)

    def put(self,request,value):
        key=self.key(request)
        with self.lock:
            self.items.pop(key,None)
            self.items[key]=(self.clock()+self.ttl,deepcopy(value))
            while len(self.items)>self.limit:self.items.popitem(last=False)


class LatestTask:
    def __init__(self,workers=1):
        self.pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='tunplayer-read')
        self.serial=0;self.cancel_event=None;self.future=None;self.closed=False

    def cancel(self):
        self.serial+=1
        if self.cancel_event:self.cancel_event.set()
        if self.future:self.future.cancel()

    def submit(self,work,done,error):
        self.cancel();serial=self.serial;cancel=threading.Event();self.cancel_event=cancel
        future=self.pool.submit(work,cancel);self.future=future
        def finished(future):
            if cancel.is_set() or self.closed:return
            try:result=future.result();failure=None
            except Exception as exc:result=None;failure=exc
            GLib.idle_add(deliver,result,failure)
        def deliver(result,failure):
            if self.closed or cancel.is_set() or serial!=self.serial:return False
            if failure is not None:error(failure)
            else:done(result)
            return False
        future.add_done_callback(finished)

    def close(self):
        self.closed=True;self.cancel();self.pool.shutdown(wait=False,cancel_futures=True)


class CatalogReader:
    def __init__(self,path):
        self.path=path;self.cache={};self.snapshots=SnapshotCache();self.totals=SnapshotCache()

    def lookup(self,request):return self.snapshots.get(request)

    def snapshot(self,request,cancel):
        if cancel.is_set():return None
        cached=self.lookup(request)
        if cached is not None:return cached
        result=self._snapshot(request,cancel)
        if not cancel.is_set():self.snapshots.put(request,result)
        return result

    @staticmethod
    def next_request(request,data):
        if request.get('discovery') or (data['page']+1)*request['page_size']>=data['total']:return None
        return dict(request,page=data['page']+1)

    def _snapshot(self,request,cancel):
        library=Library(self.path,read_only=True)
        library.db.set_progress_handler(lambda:1 if cancel.is_set() else 0,1000)
        try:
            view=request['view'];source=request.get('source_id');options=request.get('filters',{})
            if request.get('discovery'):
                sections=library.discovery(search=request.get('search',''),limit=12)
                return dict(sections=sections,sources=library.sources(),groups=[],facets=None,page=0,
                            rows=[],total=sum(len(section['rows']) for section in sections))
            query=dict(search=request.get('search',''),group=request.get('group'),view=view,source_id=source,**options)
            count_key=dict(query,revision=request.get('revision',0))
            total=self.totals.get(count_key)
            if total is None:
                total=library.channel_count(**query)
                if not cancel.is_set():self.totals.put(count_key,total)
            size=request['page_size'];page=min(request.get('page',0),max(0,(total-1)//size))
            rows=library.channels(**query,sort=request.get('sort'),limit=size,offset=page*size)
            scope=(request.get('revision',0),view,source,options.get('kind'))
            if scope not in self.cache:
                if len(self.cache)>12:self.cache.clear()
                self.cache[scope]={'groups':library.group_counts(view=view,source_id=source,**({'kind':options['kind']} if options.get('kind') else {}))}
            cached=self.cache[scope]
            if request.get('advanced') and 'facets' not in cached:cached['facets']=library.facets(view,source)
            result=dict(rows=rows,total=total,page=page,sources=library.sources(),groups=cached['groups'],facets=cached.get('facets'))
            if view=='all':result['recent']=library.channels(view='history',limit=1)
            ids=list({row['tvg_id'] for row in rows if row['kind']=='live' and row['tvg_id']})
            now=time.time();programmes={}
            if ids:
                sql='SELECT * FROM programmes WHERE channel IN ('+','.join('?' for _ in ids)+') AND start<=? AND stop>? ORDER BY start DESC'
                for row in library.db.execute(sql,(*ids,now,now)):programmes.setdefault(row['channel'],dict(row))
            for row in rows:row['_now']=programmes.get(row['tvg_id'])
            return result
        finally:library.close()


class WriteQueue:
    def __init__(self,path,on_error=None):
        self.path=path;self.on_error=on_error;self.pending=OrderedDict();self.lock=threading.Lock()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='tunplayer-write')
        self.running=False;self.closed=False;self.counter=0

    @property
    def idle(self):
        with self.lock:return not self.running and not self.pending

    def submit(self,work,done=None,key=None):
        with self.lock:
            if self.closed:return
            if key is None:self.counter+=1;key=('job',self.counter)
            self.pending[key]=(work,done)
            if not self.running:self.running=True;self.pool.submit(self.drain)

    def drain(self):
        library=None
        try:
            library=Library(self.path,migrate=False)
            while True:
                with self.lock:
                    if not self.pending:self.running=False;return
                    _,(work,done)=self.pending.popitem(last=False)
                try:
                    result=work(library)
                    if done:GLib.idle_add(self.deliver,done,result)
                except Exception:
                    if self.on_error:GLib.idle_add(self.deliver,self.on_error,None)
        finally:
            if library:library.close()
            else:
                with self.lock:self.pending.clear();self.running=False
                if self.on_error:GLib.idle_add(self.deliver,self.on_error,None)

    def deliver(self,callback,result):
        if not self.closed:callback(result)
        return False

    def close(self):
        # Already accepted writes are drained; no UI thread waits on a database lock.
        with self.lock:self.closed=True
        self.pool.shutdown(wait=False)
