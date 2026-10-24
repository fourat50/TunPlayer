"""Catalogue metadata normalization and safe sort/filter choices."""
import math
import re
import unicodedata

KINDS=('live','movie','series','episode')
SORTS={
    'name': 'search_name ASC,id', 'name_desc': 'search_name DESC,id',
    'added': 'CASE WHEN added>0 THEN added ELSE imported_at END DESC,search_name,id', 'rating': 'rating DESC,search_name,id',
    'year': 'year DESC,search_name,id', 'watched': 'watched DESC,id',
}
METADATA_FIELDS=('genre','year','rating','added','language','quality','plot','season','episode_num','cast','director','duration_seconds')

def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value or '')).casefold() if not unicodedata.combining(c))

def number(value, default=0):
    try:
        n=float(str(value).replace(',','.'))
        return n if math.isfinite(n) else default
    except (ValueError,TypeError):return default

def quality(value):
    value=str(value or '').upper()
    for name,pattern in [('UHD',r'\b(?:4K|UHD|2160P?)\b'),('FHD',r'\b(?:FHD|FULL[ -]?HD|1080[PI]?)\b'),
                         ('HD',r'\b(?:HD|720P?)\b'),('SD',r'\b(?:SD|480P?|576[PI]?)\b')]:
        if re.search(pattern,value):return name
    return ''

def genres(value):
    return sorted({v.strip() for v in re.split(r'[,/;|]',str(value or '')) if v.strip()},key=fold)

def people(value):
    if isinstance(value,list):return ', '.join(str(item.get('name') or '') if isinstance(item,dict) else str(item) for item in value)
    return str(value or '')

def duration_seconds(row):
    seconds=number(row.get('duration_secs') or row.get('duration_seconds'))
    if seconds<=0:
        text=str(row.get('duration') or '')
        if re.fullmatch(r'\d{1,3}:\d{2}(?::\d{2})?',text):
            parts=[int(v) for v in text.split(':')];seconds=sum(v*60**i for i,v in enumerate(reversed(parts)))
        elif row.get('episode_run_time'):seconds=number(row['episode_run_time'])*60
    return max(0,min(7*86400,int(seconds)))

def metadata(row):
    name=str(row.get('name') or '')
    year=int(number(row.get('year') or str(row.get('releaseDate') or row.get('releasedate') or row.get('release_date') or '')[:4]))
    if not 1888<=year<=2200:
        match=re.search(r'\((19\d{2}|20\d{2})\)',name)
        year=int(match[1]) if match else 0
    rating=number(row.get('rating')) if row.get('rating') else number(row.get('rating_5based'))*2
    return dict(genre=', '.join(genres(row.get('genre'))),year=year,rating=max(0,min(10,rating)),
        added=max(0,number(row.get('added') or row.get('last_modified'))),
        language=str(row.get('language') or '').strip().lower(),
        quality=quality(row.get('quality')) or quality(name),plot=str(row.get('plot') or row.get('description') or ''),
        cast=people(row.get('cast') or row.get('actors')),director=people(row.get('director')),
        duration_seconds=duration_seconds(row),
        season=max(0,int(number(row.get('season')))),episode_num=max(0,int(number(row.get('episode_num')))))

def classify_m3u(name, url, attrs):
    declared=fold(attrs.get('type') or attrs.get('stream-type'))
    if declared in ('series','serie','episode') or '/series/' in url.lower() or re.search(r'\bS\d{1,3}\s*E\d{1,3}\b',name,re.I):
        return 'series'
    if declared in ('movie','vod','film') or '/movie/' in url.lower() or re.search(r'\.(mp4|mkv|avi|mov)(?:\?|$)',url,re.I):
        return 'movie'
    return 'live'
