#!/usr/bin/env python3
"""Measure SQLite operations on a temporary catalogue; no network or GTK required."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tunplayer.core import Library


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channels',type=int,default=20000)
    args=parser.parse_args()
    if args.channels<60:parser.error('--channels doit être supérieur ou égal à 60')
    with TemporaryDirectory(prefix='tunplayer-benchmark-') as folder:
        library=Library(Path(folder)/'library.sqlite3')
        rows=[dict(name=f'Chaîne {i:05d}',group_name=f'Groupe {i%40:02d}',tvg_id=str(i),
                   logo='',url=f'https://example.org/{i}',kind='live') for i in range(args.channels)]
        start=perf_counter();source=library.import_channels('Catalogue de test',rows)
        import_seconds=perf_counter()-start
        start=perf_counter();page=library.channels(limit=60,offset=args.channels-60)
        page_ms=(perf_counter()-start)*1000
        start=perf_counter();count=library.channel_count(search='chaine 199')
        search_ms=(perf_counter()-start)*1000
        start=perf_counter()
        result=library.refresh_source(source,[dict(row,url=row['url']+'?token=new') for row in rows])
        refresh_seconds=perf_counter()-start
        assert result['retained']==args.channels
        assert len(page)==60
        print(json.dumps(dict(channels=args.channels,import_seconds=round(import_seconds,3),
            last_page_rows=len(page),last_page_ms=round(page_ms,2),search_count=count,
            search_ms=round(search_ms,2),refresh_seconds=round(refresh_seconds,3),
            retained=result['retained']),ensure_ascii=False,indent=2))
        library.close()

if __name__=='__main__':main()
