"""Optional Subliminal 2.8 adapter; built-in APIs do not depend on this extra."""
from .subtitles import SubtitleError,ranking


class SubliminalProvider:
    name='subliminal'

    @staticmethod
    def available():
        try:
            import subliminal
            import babelfish
            from importlib.metadata import version
            return (2,8)<=tuple(int(v) for v in version('subliminal').split('.')[:2])<(3,0)
        except (ImportError,ValueError):return False

    def search(self,query,cancel):
        from babelfish import Language
        from subliminal import Movie,Episode,ProviderPool
        from subliminal.cache import region
        if not region.is_configured:region.configure('dogpile.cache.memory')
        try:language=Language.fromietf(query['language'])
        except (ValueError,KeyError):raise SubtitleError('Langue non prise en charge par Subliminal.') from None
        # Titles and episode metadata suffice; never pass an IPTV URL or account to refiners.
        if query['kind']=='episode':video=Episode('TunPlayer.mkv',query['title'],query['season'],query['episode'],year=query['year'] or None)
        else:video=Movie('TunPlayer.mkv',query['title'],year=query['year'] or None)
        rows=[]
        # These extra sources have no application API key. OpenSubtitles and Podnapisi
        # use our direct adapters, so the upstream shared API key is never used.
        names=['gestdown','tvsubtitles','subtitulamos'] if query['kind']=='episode' else ['subtis']
        with ProviderPool(providers=names,provider_configs={name:{'timeout':10} for name in names}) as pool:
            for name in names:
                if cancel.is_set():break
                result=pool.list_subtitles_provider(name,video,{language})
                if result.failure() or result.outage():continue
                for subtitle in result.subtitles:
                    matches=subtitle.get_matches(video)
                    if query['kind']=='episode' and not {'season','episode'}.issubset(matches):continue
                    title=query['title'] if ('series' if query['kind']=='episode' else 'title') in matches else ''
                    rows.append(dict(provider=self.name,id=name+':'+str(subtitle.id),language=query['language'],
                        release=str(subtitle.info)[:320],source='Subliminal · '+name,hearing=bool(subtitle.hearing_impaired),machine=False,
                        score=ranking(query,title,query['year'] if 'year' in matches else 0,query['season'],query['episode']),native=subtitle))
        return rows

    def download(self,row):
        from subliminal import ProviderPool
        subtitle=row.get('native')
        if subtitle is None:raise SubtitleError('Relancez la recherche de sous-titres.')
        with ProviderPool(providers=[subtitle.provider_name],provider_configs={subtitle.provider_name:{'timeout':10}}) as pool:
            if not pool.download_subtitle(subtitle):raise SubtitleError('Le téléchargement Subliminal a échoué.')
            # Normalize using the library's detected character encoding before storage.
            return subtitle.text.encode('utf-8'),'subtitle.srt'
