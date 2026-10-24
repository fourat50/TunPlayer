#!/usr/bin/env python3
"""Measure GLib heartbeat during real catalogue queries, without a display or account."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gi.repository import GLib
from tunplayer.core import Library
from tunplayer.jobs import LatestTask,CatalogReader


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channels',type=int,default=143500)
    args=parser.parse_args()
    if args.channels<120:parser.error('--channels doit être supérieur ou égal à 120')
    with TemporaryDirectory(prefix='tunplayer-responsive-') as directory:
        library=Library(Path(directory)/'db.sqlite3')
        rows=[dict(name=f'Film {i:06d}',kind='movie',url=f'https://example.org/{i}.mp4',group_name=f'Catégorie {i%60:02}',
            tvg_id='',logo='',genre='Drame, Aventure',year=2000+i%25,rating=i%10,language='fr') for i in range(args.channels)]
        library.import_channels('Catalogue synthétique',rows)
        reader=CatalogReader(library.path);task=LatestTask();ticks=[];results=[];errors=[]
        timer=GLib.timeout_add(5,lambda:ticks.append(time.monotonic()) or True)
        request=dict(view='movie',page_size=120,page=0,search='film',filters={},revision=0,advanced=True)
        start=time.monotonic()
        try:
            task.submit(lambda cancel:reader.snapshot(request,cancel),results.append,errors.append)
            while not results and not errors and time.monotonic()-start<20:
                while GLib.MainContext.default().iteration(False):pass
                time.sleep(.001)
            if errors:raise RuntimeError(type(errors[0]).__name__)
            if not results:raise RuntimeError('Catalogue query timed out')
            elapsed=(time.monotonic()-start)*1000
            gaps=[(b-a)*1000 for a,b in zip([start]+ticks,ticks)]
            warm=[]
            for _ in range(20):
                began=time.monotonic();cached=reader.lookup(request)
                warm.append((time.monotonic()-began)*1000)
                assert cached is not None and len(cached['rows'])==120
            next_request=reader.next_request(request,results[0]);prepared=[]
            prefetch_ms=next_ms=None
            if next_request is not None:
                prefetch_started=time.monotonic()
                task.submit(lambda cancel:reader.snapshot(next_request,cancel),prepared.append,errors.append)
                while not prepared and not errors and time.monotonic()-prefetch_started<20:
                    while GLib.MainContext.default().iteration(False):pass
                    time.sleep(.001)
                if errors or not prepared:raise RuntimeError('Prefetch failed or timed out')
                prefetch_ms=round((time.monotonic()-prefetch_started)*1000,2)
                began=time.monotonic();next_page=reader.lookup(next_request)
                next_ms=round((time.monotonic()-began)*1000,2)
                assert next_page is not None and next_page['page']==1
            print(json.dumps(dict(channels=args.channels,returned=len(results[0]['rows']),catalogue_ms=round(elapsed,2),
                glib_ticks=len(gaps),maximum_tick_gap_ms=round(max(gaps,default=0),2),
                cached_page_median_ms=round(sorted(warm)[len(warm)//2],2),
                background_next_page_ms=prefetch_ms,prepared_next_page_ms=next_ms,
                note='Mesure de la boucle GLib et des requêtes SQLite, sans rendu graphique.'),ensure_ascii=False,indent=2))
        finally:
            GLib.source_remove(timer);task.close();task.pool.shutdown(wait=True);library.close()

if __name__=='__main__':main()
