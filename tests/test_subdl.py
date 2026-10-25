import io
import json
import threading
import unittest
from urllib.parse import parse_qs,urlsplit
from tunplayer.subtitles import SubtitleError,SubtitleHTTP,SubtitleService
from tunplayer.subtitle_subdl import SubDL,download_url
from test_subtitles import QUERY,SRT


def subtitle(**changes):
    row=dict(name='Saga.S01E02.zip',release_name='Saga.S01E02.WEB-DL',language='FR',season=1,episode=2,
        episode_from=2,episode_end=2,full_season=False,hi=False,url='/subtitle/123-456.zip')
    return dict(row,**changes)


def response(rows):return dict(status=True,results=[dict(name='Saga',year=2024,type='tv')],subtitles=rows)


class SubDLProvider(unittest.TestCase):
    def provider(self,data):
        self.requests=[]
        def opener(request,**kwargs):
            self.requests.append(request);return io.BytesIO(json.dumps(data).encode())
        return SubDL(SubtitleHTTP(opener),dict(api_key='OPENSUBTITLES_SECRET',subdl_api_key='SUBDL_SECRET'))

    def test_search_uses_separate_subdl_key_and_exact_episode(self):
        rows=self.provider(response([subtitle(),subtitle(episode=3)])).search(QUERY,threading.Event())
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['provider'],'subdl');self.assertEqual(rows[0]['score'],100)
        request=self.requests[0];params=parse_qs(urlsplit(request.full_url).query)
        self.assertNotIn('api_key',params);self.assertNotIn('SECRET',request.full_url)
        self.assertEqual(request.get_header('Authorization'),'Bearer SUBDL_SECRET')
        self.assertEqual(urlsplit(request.full_url).path,'/api/v2/subtitles/search')
        self.assertEqual(params['season'],['1']);self.assertEqual(params['episode'],['2'])
        self.assertEqual(params['type'],['tv']);self.assertEqual(params['unpack'],['1']);self.assertEqual(params['languages'],['FR'])
        self.assertIsNone(request.get_header('Api-key'))

    def test_key_is_required_and_opensubtitles_key_is_not_a_fallback(self):
        provider=SubDL(SubtitleHTTP(),{'api_key':'OPENSUBTITLES_SECRET'})
        with self.assertRaises(SubtitleError):provider.search(QUERY,threading.Event())

    def test_full_season_pack_selects_only_the_requested_episode_file(self):
        files=[dict(name=f'Saga.S01E{ep:02}.srt',language='FR',season=1,episode=ep,url=f'/subtitle/pack/file{ep}') for ep in (1,2,3)]
        row=subtitle(full_season=True,episode=0,episode_from=0,episode_end=0,unpack_files=files)
        rows=self.provider(response([row])).search(QUERY,threading.Event())
        self.assertEqual([r['download_url'] for r in rows],['https://dl.subdl.com/subtitle/pack/file2'])

    def test_unexpanded_packs_and_wrong_seasons_are_not_offered_as_single_episodes(self):
        rows=self.provider(response([subtitle(full_season=True),subtitle(episode_from=1,episode_end=10),subtitle(season=2)])).search(QUERY,threading.Event())
        self.assertEqual(rows,[])

    def test_single_episode_range_is_a_fallback_when_episode_field_is_missing(self):
        rows=self.provider(response([subtitle(episode=None)])).search(QUERY,threading.Event())
        self.assertEqual(len(rows),1)

    def test_other_languages_and_untrusted_download_hosts_are_skipped(self):
        rows=self.provider(response([subtitle(language='EN'),subtitle(url='https://evil.example/subtitle/a'),subtitle()])).search(QUERY,threading.Event())
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['language'],'fr')

    def test_brazilian_and_traditional_chinese_language_codes_are_translated(self):
        for language,code in (('pt-br','BR_PT'),('zh-tw','ZH_BG'),('pt-pt','PT'),('zh-cn','ZH')):
            with self.subTest(language=language):
                provider=self.provider(response([subtitle(language=code)]));rows=provider.search(dict(QUERY,language=language),threading.Event())
                self.assertEqual(rows[0]['language'],language)
                self.assertEqual(parse_qs(urlsplit(self.requests[0].full_url).query)['languages'],[code])

    def test_movie_search_sends_year_without_episode_parameters(self):
        data=response([subtitle()]);data['results'][0]['type']='movie'
        provider=self.provider(data);provider.search(dict(QUERY,kind='movie'),threading.Event())
        params=parse_qs(urlsplit(self.requests[0].full_url).query)
        self.assertEqual(params['type'],['movie']);self.assertEqual(params['year'],['2024']);self.assertNotIn('season_number',params)

    def test_provider_error_cannot_echo_the_private_key(self):
        provider=self.provider(dict(status=False,error='Invalid api_key=SUBDL_SECRET'))
        with self.assertRaises(SubtitleError) as error:provider.search(QUERY,threading.Event())
        self.assertNotIn('SUBDL_SECRET',str(error.exception))

    def test_pagination_is_bounded(self):
        provider=self.provider(response([subtitle() for _ in range(30)]));provider.search(QUERY,threading.Event())
        self.assertEqual(len(self.requests),2)

    def test_cancelled_search_does_not_contact_subdl(self):
        provider=self.provider(response([]));cancel=threading.Event();cancel.set()
        self.assertEqual(provider.search(QUERY,cancel),[]);self.assertEqual(self.requests,[])

    def test_download_sends_no_provider_credentials_to_the_cdn(self):
        requests=[]
        def opener(request,**kwargs):requests.append(request);return io.BytesIO(SRT)
        provider=SubDL(SubtitleHTTP(opener),{'api_key':'OS_SECRET','subdl_api_key':'SUBDL_SECRET'})
        data,name=provider.download({'download_url':'https://dl.subdl.com/subtitle/123-456.zip'})
        self.assertEqual(data,SRT);self.assertEqual(name,'123-456.zip')
        self.assertNotIn('SECRET',requests[0].full_url);self.assertIsNone(requests[0].get_header('Authorization'))
        self.assertIsNone(requests[0].get_header('Api-key'));self.assertIsNone(requests[0].get_header('X-api-key'))

    def test_download_link_cannot_include_a_key_or_an_untrusted_host(self):
        for url in ('//evil.example/subtitle/a','https://api.subdl.com/subtitle/a','/subtitle/a?api_key=secret','file:///etc/passwd','/panel/api'):
            with self.subTest(url=url),self.assertRaises(SubtitleError):download_url(url)

    def test_subdl_is_available_without_an_extra_python_package(self):
        self.assertIn('subdl',SubtitleService().providers())
