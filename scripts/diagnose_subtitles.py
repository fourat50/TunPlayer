#!/usr/bin/env python3
"""Collect real SubDL responses using the installed backend, without exposing keys."""
import argparse
from datetime import datetime,timezone
import importlib
import json
import os
from pathlib import Path
import re
import sys
import threading
from urllib.error import HTTPError
from urllib.parse import urlsplit,urlunsplit

ROOT=Path(__file__).resolve().parents[1]
PRIVATE_FIELDS={'api_key','apikey','subdl_api_key','x_api_key','authorization','token','password','email','username','access_token','refresh_token','client_secret'}


def scrub(value,secrets=()):
    if isinstance(value,dict):
        return {str(k):'[masqué]' if str(k).lower().replace('-','_') in PRIVATE_FIELDS else scrub(v,secrets) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [scrub(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in sorted((str(s) for s in secrets if s),key=len,reverse=True):value=value.replace(secret,'[masqué]')
        def url(match):
            try:
                parsed=urlsplit(match[0]);host=parsed.hostname or ''
                return urlunsplit((parsed.scheme,host,parsed.path,'[masqué]' if parsed.query else '', ''))
            except ValueError:return '[adresse masquée]'
        value=re.sub(r'https?://[^\s"<>]+',url,value)
        return value[:1200]
    return value


def shape(value,depth=0):
    if depth>=3:return type(value).__name__
    if isinstance(value,dict):return {str(k):shape(v,depth+1) for k,v in list(value.items())[:35]}
    if isinstance(value,list):return {'type':'list','count':len(value),'first':shape(value[0],depth+1) if value else None}
    return type(value).__name__


def response_excerpt(data,secrets=()):
    if not isinstance(data,dict):return {'schema':shape(data)}
    result={'schema':shape(data)}
    for key in ('status','error','message'):
        if key in data:result[key]=scrub(data[key],secrets)
    # Account identity, usage details and unrelated body fields are not recorded.
    candidates=data.get('subtitles')
    if candidates is None and isinstance(data.get('data'),dict):candidates=data['data'].get('subtitles')
    if isinstance(candidates,list):result['subtitle_examples']=scrub(candidates[:3],secrets)
    features=data.get('results')
    if isinstance(features,list):result['title_examples']=scrub([{k:r[k] for k in ('name','type','year','sd_id','imdb_id') if k in r} for r in features[:3] if isinstance(r,dict)],secrets)
    return result


def traced_http(http_type,secrets=()):
    class TraceHTTP(http_type):
        def __init__(self):
            super().__init__();self.trace=[];opener=self.opener
            def open_response(request,**kwargs):
                event=self.trace[-1]
                event['authentication_present']=bool(request.get_header('Authorization') or request.get_header('X-api-key'))
                try:
                    response=opener(request,**kwargs)
                    event['http_status']=getattr(response,'status',None)
                    return response
                except HTTPError as error:
                    event['http_status']=error.code
                    try:
                        body=error.read(16384)
                        event['error_response']=response_excerpt(json.loads(body),secrets)
                    except (ValueError,OSError,AttributeError,TypeError):pass
                    raise
                except OSError as error:
                    event['transport_error']=type(getattr(error,'reason',error)).__name__
                    raise
            self.opener=open_response

        def fetch(self,url,params=None,**kwargs):
            parsed=urlsplit(url)
            event={'endpoint':parsed.scheme+'://'+(parsed.hostname or '')+parsed.path,'parameters':scrub(params or {},secrets)}
            self.trace.append(event)
            data=super().fetch(url,params=params,**kwargs)
            try:event['response']=response_excerpt(json.loads(data),secrets)
            except (ValueError,UnicodeError):event['response']={'bytes':len(data),'json':False}
            return data
    return TraceHTTP()


def attempt(label,query,provider_type,http_type,settings,download=False):
    secrets=[settings.get(k) for k in PRIVATE_FIELDS if settings.get(k)]
    http=traced_http(http_type,secrets);provider=provider_type(http,settings)
    result={'case':label,'query':dict(query) if query else None}
    try:
        if query:
            rows=provider.search(query,threading.Event())
            result.update(ok=True,count=len(rows),diagnostic=getattr(provider,'diagnostic',{}),
                normalized_examples=[{k:r.get(k) for k in ('language','release','warning','score')} for r in rows[:3]])
            if download and rows:
                from tunplayer.subtitles import subtitle_text
                row=next((r for r in rows if r.get('language')=='en'),rows[0])
                try:
                    data,filename=provider.download(row);content,extension=subtitle_text(data,filename,row['language'])
                    result['download_probe']={'ok':True,'language':row['language'],'bytes':len(content),'format':extension}
                except Exception as error:result['download_probe']={'ok':False,'error':scrub(str(error),secrets)}
        else:result.update(ok=True,account_verified=provider.connection().get('connected') is True)
    except Exception as error:result.update(ok=False,error_type=type(error).__name__,error=scrub(str(error),secrets))
    result['requests']=http.trace
    return scrub(result,secrets)


def recent_query(library):
    rows=library.channels(view='history',sort='watched',limit=50)
    row=next((r for r in rows if r.get('kind') in ('movie','episode')),None)
    if row is None:return None
    from tunplayer.subtitles import media_query,validate_query
    parent=library.channel(row['parent_id']) if row.get('parent_id') else None
    return validate_query(dict(media_query(row,parent),language=library.setting('subtitle_language','fr')))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',type=Path,default=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'tunplayer')
    parser.add_argument('--app-path',type=Path,default=Path('/opt/tunplayer/app') if Path('/opt/tunplayer/app/tunplayer').is_dir() else ROOT)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/subtitle-diagnostic.json')
    parser.add_argument('--download',action='store_true',help='Télécharger et valider un seul sous-titre témoin, sans modifier le profil')
    args=parser.parse_args(argv)
    sys.path.insert(0,str(args.app_path.resolve()))
    app=importlib.import_module('tunplayer')
    from tunplayer.subtitles import read_json,private_json,SubtitleHTTP
    from tunplayer.subtitle_subdl import SubDL
    from tunplayer.core import Library
    settings=read_json(args.profile/'subtitle-providers.json')
    if not settings.get('subdl_api_key'):
        print('Aucune clé SubDL dans ce profil. Enregistrez-la dans l’application.');return 2
    report={'version':app.__version__,'app_path':str(args.app_path),'module_path':str(Path(app.__file__).parent),'time_utc':datetime.now(timezone.utc).isoformat(),
            'proxy_variables_present':[k for k in ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy','ALL_PROXY') if os.environ.get(k)],'cases':[]}
    query=None
    if (args.profile/'library.sqlite3').is_file():
        library=Library(args.profile/'library.sqlite3',read_only=True)
        try:query=recent_query(library)
        finally:library.close()
    cases=[('Compte',None),('Film témoin : Inception',dict(title='Inception',year=2010,kind='movie',season=0,episode=0,language='all'))]
    print('Diagnostic de TunPlayer '+str(app.__version__)+' · '+str(Path(app.__file__).parent),flush=True)
    if query:
        cases.append(('Contenu récent du profil',query))
        if query['language']!='all':cases.append(('Même contenu, toutes les langues',dict(query,language='all')))
    for label,value in cases:
        print(label+'…',flush=True)
        result=attempt(label,value,SubDL,SubtitleHTTP,settings,download=args.download and label.startswith('Film témoin'));report['cases'].append(result)
        if not result['ok']:print('  Échec : '+result['error'],flush=True)
        elif value:
            info=result.get('diagnostic',{})
            print(f'  {info.get("received","?")} reçu(s), {info.get("kept",result["count"])} retenu(s).',flush=True)
        else:print('  Compte vérifié.' if result['account_verified'] else '  Compte non confirmé.',flush=True)
        if result.get('download_probe'):
            probe=result['download_probe']
            print('  Sous-titre témoin téléchargé et validé.' if probe['ok'] else '  Échec du téléchargement témoin : '+probe['error'],flush=True)
    private_json(args.output,report)
    print('Rapport enregistré (clés masquées) : '+str(args.output),flush=True)
    print('Vous pouvez transmettre ce rapport pour identifier la cause exacte.')
    return 0


if __name__=='__main__':raise SystemExit(main())
