"""SubDL v2 search with normalized metadata and authenticated account access.

API contract: https://subdl.com/developers
"""
import json
import re
from urllib.parse import urljoin,urlsplit
from .subtitles import SubtitleError,number,ranking,trusted_url,language_code
from .subtitle_languages import ENGLISH_NAMES
from .catalog import fold


def download_url(value):
    if not isinstance(value,str) or not value:raise SubtitleError('Lien de téléchargement SubDL invalide.')
    url=urljoin('https://dl.subdl.com/',value)
    trusted_url(url);parsed=urlsplit(url)
    if parsed.hostname!='dl.subdl.com' or not parsed.path.startswith('/subtitle/') or parsed.query or parsed.fragment:
        raise SubtitleError('Lien de téléchargement SubDL refusé.')
    return url


def flag(value):return value.lower() in ('true','1','yes') if isinstance(value,str) else bool(value)


def subtitle_language(value):
    if isinstance(value,dict):value=value.get('code') or value.get('name') or ''
    raw=str(value or '').strip()
    custom={'BR_PT':'pt-br','ZH_BG':'zh-tw','brazilianportuguese':'pt-br','brazillianportuguese':'pt-br',
            'portuguesebrazil':'pt-br','farsipersian':'fa','farsi':'fa','greek':'el','sinhalese':'si',
            'khmer':'km','lao':'lo','filipino':'tl','traditionalchinese':'zh-tw','chinesetraditional':'zh-tw',
            'chinesebig5':'zh-tw','simplifiedchinese':'zh-cn','chinesesimplified':'zh-cn'}
    normalized=re.sub(r'[^a-z0-9]','',fold(raw))
    code=custom.get(raw.upper()) or custom.get(normalized) or ENGLISH_NAMES.get(normalized) or language_code(raw)
    return code if re.fullmatch(r'[a-z]{2,3}(?:-[a-z]{2,4})?',code) else ''


def episode_numbers(file,parent):
    season=number(file.get('season')) or number(parent.get('season'))
    episode=number(file.get('episode'))
    if not episode and file is parent:
        start=number(parent.get('episode_from'));end=number(parent.get('episode_end'))
        if start and end in (0,start):episode=start
    text=' '.join(str(file.get(key) or '') for key in ('name','release_name'))
    match=re.search(r'\bS(\d{1,3})[ ._-]*E(\d{1,4})(?!\d)',text,re.I) or re.search(r'\b(\d{1,3})x(\d{1,4})(?!\d)',text,re.I)
    if match:season=season or number(match[1]);episode=episode or number(match[2])
    return season,episode


class SubDL:
    name='subdl'
    variants={'pt-br':'BR_PT','pt-pt':'PT','zh-cn':'ZH','zh-tw':'ZH_BG'}

    def __init__(self,http,settings):self.http=http;self.settings=dict(settings)

    def headers(self):
        key=str(self.settings.get('subdl_api_key','')).strip()
        if not key:raise SubtitleError('Ajoutez votre clé SubDL dans les préférences des sous-titres.')
        return {'Authorization':'Bearer '+key}

    def connection(self):
        """Validate the entered key against an authenticated account endpoint, not a title search."""
        key=str(self.settings.get('subdl_api_key','')).strip()
        if not key:raise SubtitleError('Saisissez votre clé API SubDL avant de tester la connexion.')
        data=self.http.json('https://api.subdl.com/api/v2/me',headers={'Authorization':'Bearer '+key})
        usage=data.get('usage');plan=data.get('plan')
        if data.get('error') or data.get('status') is False or not isinstance(usage,dict) or not isinstance(plan,dict):
            raise SubtitleError('SubDL n’a pas confirmé l’accès au compte avec cette clé.')
        search=usage.get('search');downloads=usage.get('downloads')
        if not isinstance(search,dict):raise SubtitleError('Réponse du compte SubDL invalide. Réessayez plus tard.')
        def remaining(value):
            result=value.get('remaining') if isinstance(value,dict) else None
            return result if isinstance(result,int) and not isinstance(result,bool) and result>=0 else None
        return dict(connected=True,search_remaining=remaining(search),download_remaining=remaining(downloads))

    def search(self,query,cancel):
        headers=self.headers()
        language=self.variants.get(query['language'],query['language'].upper())
        if '-' in language:raise SubtitleError('Cette variante de langue n’est pas prise en charge par SubDL. Essayez la langue principale.')
        params=dict(film_name=query['title'],type='tv' if query['kind']=='episode' else 'movie',
            subs_per_page=30,releases=1,unpack=1,client='custom_integration')
        if query['language']!='all':params['languages']=language
        if query['kind']=='episode':params.update(season=query['season'],episode=query['episode'])
        elif query['year']:params['year']=query['year']
        rows=[];self.diagnostic=dict(received=0,kept=0,language=0,episode=0,link=0,pack=0)
        for page in range(1,3):
            if cancel.is_set():break
            params['page']=page
            data=self.http.json('https://api.subdl.com/api/v2/subtitles/search',params=params,headers=headers)
            if page==1 and not data.get('subtitles') and 'year' in params and not data.get('error') and data.get('status') is not False:
                params.pop('year')
                if cancel.is_set():break
                data=self.http.json('https://api.subdl.com/api/v2/subtitles/search',params=params,headers=headers)
            if data.get('error') or data.get('status') is False:
                raise SubtitleError('SubDL a refusé la recherche. Vérifiez la clé API, le quota et le titre.')
            subtitles=data.get('subtitles');results=data.get('results') or []
            if not isinstance(subtitles,list) or not isinstance(results,list):raise SubtitleError('Réponse de recherche SubDL invalide.')
            feature=results[0] if results else {}
            if feature.get('type') not in (None,params['type']):break
            for item in subtitles[:30]:
                if not isinstance(item,dict):continue
                start=number(item.get('episode_from'));end=number(item.get('episode_end'))
                pack=flag(item.get('full_season')) or (start>0 and end>0 and start!=end)
                files=item.get('unpack_files') or ([] if pack else [item])
                if not files:self.diagnostic['received']+=1;self.diagnostic['pack']+=1
                for file in files[:1000]:
                    if not isinstance(file,dict):continue
                    self.diagnostic['received']+=1
                    season,episode=episode_numbers(file,item)
                    warning=''
                    if query['kind']=='episode':
                        if (season and season!=query['season']) or (episode and episode!=query['episode']):self.diagnostic['episode']+=1;continue
                        season_known=bool(season) or (query['season']==0 and (file.get('season') is not None or item.get('season') is not None))
                        if not season_known or not episode:
                            if pack or file is not item:self.diagnostic['episode']+=1;continue
                            warning='Numéro d’épisode à vérifier'
                    raw=file.get('language') or file.get('lang') or item.get('language') or item.get('lang')
                    source_language=subtitle_language(raw)
                    if query['language'] in self.variants and source_language==subtitle_language(language):source_language=query['language']
                    if not source_language and query['language']!='all' and not raw:source_language=query['language']
                    if not source_language or (query['language']!='all' and source_language!=query['language']):self.diagnostic['language']+=1;continue
                    try:url=download_url(file.get('url'))
                    except SubtitleError:url=''
                    identity=str(item.get('n_id') or '')
                    if not url and (file is not item or not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',identity)):
                        self.diagnostic['link']+=1;continue
                    release=str(file.get('release_name') or file.get('name') or item.get('release_name') or item.get('name') or feature.get('name') or '')[:320]
                    rows.append(dict(provider=self.name,id=url or identity,subdl_id=identity,download_url=url,language=source_language,release=release,
                        hearing=flag(file.get('hi',item.get('hi',False))),machine=flag(item.get('ai_translated')),warning=warning,
                        score=ranking(query,feature.get('name',''),feature.get('year'),season,episode)))
            if len(subtitles)<30:break
        unique={(r['id'],r['language']):r for r in rows};self.diagnostic['kept']=len(unique)
        return list(unique.values())

    def download(self,row):
        if row.get('download_url'):
            url=download_url(row['download_url'])
            return self.http.fetch(url),urlsplit(url).path.rsplit('/',1)[-1]
        identity=str(row.get('subdl_id') or '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',identity):raise SubtitleError('Lien de sous-titre SubDL absent. Relancez la recherche.')
        data=self.http.fetch('https://api.subdl.com/api/v2/subtitles/'+identity+'/download',params={'format':'file'},headers=self.headers())
        if data.lstrip().startswith(b'{'):
            try:
                result=json.loads(data);url=download_url(result.get('url') or result.get('link') or result.get('download_url'))
            except (ValueError,AttributeError):raise SubtitleError('Le téléchargement SubDL ne contient pas de fichier valide.') from None
            data=self.http.fetch(url)
        return data,'subtitle.srt'
