"""SubDL search API v1 and exact episode files from unpacked season packs.

API contract: https://subdl.com/api-doc
"""
from urllib.parse import urljoin,urlsplit
from .subtitles import SubtitleError,number,ranking,trusted_url


def download_url(value):
    if not isinstance(value,str) or not value:raise SubtitleError('Lien de téléchargement SubDL invalide.')
    url=urljoin('https://dl.subdl.com/',value)
    trusted_url(url);parsed=urlsplit(url)
    if parsed.hostname!='dl.subdl.com' or not parsed.path.startswith('/subtitle/') or parsed.query or parsed.fragment:
        raise SubtitleError('Lien de téléchargement SubDL refusé.')
    return url


class SubDL:
    name='subdl'
    variants={'pt-br':'BR_PT','pt-pt':'PT','zh-cn':'ZH','zh-tw':'ZH_BG'}

    def __init__(self,http,settings):self.http=http;self.settings=dict(settings)

    def search(self,query,cancel):
        key=str(self.settings.get('subdl_api_key','')).strip()
        if not key:raise SubtitleError('Ajoutez votre clé SubDL dans les préférences des sous-titres.')
        language=self.variants.get(query['language'],query['language'].upper())
        if '-' in language:raise SubtitleError('Cette variante de langue n’est pas prise en charge par SubDL. Essayez la langue principale.')
        params=dict(api_key=key,film_name=query['title'],type='tv' if query['kind']=='episode' else 'movie',
            languages=language,subs_per_page=30,releases=1,unpack=1,client='custom_integration')
        if query['kind']=='episode':params.update(season_number=query['season'],episode_number=query['episode'])
        elif query['year']:params['year']=query['year']
        rows=[]
        for page in range(1,3):
            if cancel.is_set():break
            params['page']=page
            data=self.http.json('https://api.subdl.com/api/v1/subtitles',params=params)
            if data.get('status') is not True:
                # Provider errors may echo the key or request URL. Never display them.
                raise SubtitleError('SubDL a refusé la recherche. Vérifiez la clé API, le quota et le titre.')
            subtitles=data.get('subtitles') or [];results=data.get('results') or []
            feature=results[0] if results else {}
            if feature.get('type') not in (None,params['type']):break
            for item in subtitles[:30]:
                if not isinstance(item,dict):continue
                start=number(item.get('episode_from'));end=number(item.get('episode_end'))
                pack=bool(item.get('full_season')) or (start>0 and end>0 and start!=end)
                files=item.get('unpack_files') or ([] if pack else [item])
                for file in files[:100]:
                    if not isinstance(file,dict):continue
                    season=number(file.get('season')) or number(item.get('season'))
                    episode=number(file.get('episode')) or (0 if pack else number(item.get('episode')) or start)
                    if query['kind']=='episode' and (season,episode)!=(query['season'],query['episode']):continue
                    source_language=str(file.get('language') or item.get('language') or language).upper()
                    if source_language!=language:continue
                    try:url=download_url(file.get('url'))
                    except SubtitleError:continue
                    release=str(file.get('release_name') or file.get('name') or item.get('release_name') or item.get('name') or feature.get('name') or '')[:320]
                    rows.append(dict(provider=self.name,id=url,download_url=url,language=query['language'],release=release,
                        hearing=bool(file.get('hi',item.get('hi',False))),machine=bool(item.get('ai_translated')),
                        score=ranking(query,feature.get('name',''),feature.get('year'),season,episode)))
            if len(subtitles)<30:break
        return rows

    def download(self,row):
        url=download_url(row.get('download_url',''))
        # Download URLs are public. Keep both providers' API keys off the CDN.
        return self.http.fetch(url),urlsplit(url).path.rsplit('/',1)[-1]
