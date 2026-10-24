import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlsplit
from urllib.request import Request
from zipfile import ZipFile
from tunplayer.subtitles import (SubtitleError,SubtitleHTTP,SubtitleRedirect,OpenSubtitles,Podnapisi,
    SubtitleService,SubtitleStore,media_query,validate_query,subtitle_text,trusted_url,MAX_BYTES,private_json)

SRT='1\n00:00:00,000 --> 00:00:09,000\nBonjour · مرحبا\n'.encode()
QUERY=dict(title='Saga',kind='episode',year=2024,season=1,episode=2,language='fr')


def os_row(identity=42,episode=2,language='fr'):
    return {'attributes':dict(language=language,release='Saga WEB-DL',files=[dict(file_id=identity,file_name='Saga.S01E02.srt')],
        feature_details=dict(parent_title='Saga',title='Pilot',year=2024,season_number=1,episode_number=episode))}


def pod_row(identity='abc',episode=2):
    return dict(id=identity,language='fr',flags=['hearing_impaired'],releases=['Saga.S01E02.WEB-DL'],custom_releases=[],
        movie=dict(title='Saga',type='tv-series',year=2024,episode_info=dict(season=1,episode=episode)))


class SubtitleAPIs(unittest.TestCase):
    def test_movie_title_and_year_are_cleaned_without_using_its_stream_url(self):
        query=media_query(dict(name='The Matrix (1999) FHD',kind='movie',url='https://secret:password@example.com/file'))
        self.assertEqual(query['title'],'The Matrix');self.assertEqual(query['year'],1999)
        self.assertNotIn('url',query)

    def test_episode_uses_parent_series_title_and_numbers(self):
        query=media_query(dict(name='Saga · S02E03 · Titre',kind='episode',season=2,episode_num=3),{'name':'Saga'})
        self.assertEqual((query['title'],query['season'],query['episode']),('Saga',2,3))

    def test_iso_three_letter_aliases_are_normalized(self):
        self.assertEqual(validate_query(dict(QUERY,language='fre'))['language'],'fr')
        self.assertEqual(validate_query(dict(QUERY,language='ara'))['language'],'ar')
        self.assertEqual(validate_query(dict(QUERY,language='PT_BR'))['language'],'pt-br')

    def test_empty_title_unknown_language_and_missing_episode_are_rejected(self):
        for changes in ({'title':''},{'language':'not a language'},{'episode':0}):
            with self.subTest(changes=changes),self.assertRaises(SubtitleError):validate_query(dict(QUERY,**changes))

    def test_only_fixed_https_provider_hosts_are_accepted(self):
        self.assertEqual(trusted_url('https://dl.opensubtitles.com/file'),'https://dl.opensubtitles.com/file')
        for url in ('file:///etc/passwd','http://www.podnapisi.net/x','https://127.0.0.1/x','https://opensubtitles.com.evil.org/x',
                    'https://user:password@api.opensubtitles.com/x','https://api.opensubtitles.com:bad/x'):
            with self.subTest(url=url),self.assertRaises(SubtitleError):trusted_url(url)

    def test_redirects_never_forward_credentials(self):
        request=Request('https://api.opensubtitles.com/a',headers={'Authorization':'Bearer secret','Api-Key':'secret'})
        redirected=SubtitleRedirect().redirect_request(request,None,302,'redirect',{},'https://dl.opensubtitles.com/b')
        self.assertIsNone(redirected.get_header('Authorization'));self.assertIsNone(redirected.get_header('Api-key'))

    def test_response_size_is_bounded(self):
        http=SubtitleHTTP(opener=lambda *a,**k:io.BytesIO(b'x'*(MAX_BYTES+1)))
        with self.assertRaises(SubtitleError):http.fetch('https://api.opensubtitles.com/a')

    def test_http_error_hides_credentials_and_response_body(self):
        def reject(*args,**kwargs):raise HTTPError('https://api.opensubtitles.com/?key=secret',403,'secret',{},None)
        with self.assertRaises(SubtitleError) as error:SubtitleHTTP(opener=reject).fetch('https://api.opensubtitles.com/a')
        self.assertNotIn('secret',str(error.exception));self.assertIn('clé API',str(error.exception))

    def test_opensubtitles_search_sends_episode_metadata_and_filters_wrong_episode(self):
        calls=[]
        def opener(request,**kwargs):
            calls.append(request);return io.BytesIO(json.dumps(dict(data=[os_row(),os_row(43,3)],total_pages=1)).encode())
        provider=OpenSubtitles(SubtitleHTTP(opener),{'api_key':'secret'})
        rows=provider.search(QUERY,threading.Event());query=parse_qs(urlsplit(calls[0].full_url).query)
        self.assertEqual(query['season_number'],['1']);self.assertEqual(query['episode_number'],['2'])
        self.assertEqual(query['type'],['episode']);self.assertEqual(calls[0].get_header('Api-key'),'secret')
        self.assertEqual([r['id'] for r in rows],['42']);self.assertEqual(rows[0]['score'],100)

    def test_opensubtitles_login_returns_private_token_not_password(self):
        calls=[]
        def opener(request,**kwargs):
            calls.append(request);return io.BytesIO(b'{"token":"session","base_url":"vip-api.opensubtitles.com"}')
        value=OpenSubtitles(SubtitleHTTP(opener),{'api_key':'key'}).login('user','password')
        self.assertEqual(value['token'],'session');self.assertNotIn('password',value)
        self.assertEqual(json.loads(calls[0].data)['password'],'password')

    def test_opensubtitles_download_does_not_send_api_key_to_file_server(self):
        calls=[]
        def opener(request,**kwargs):
            calls.append(request)
            return io.BytesIO(b'{"link":"https://dl.opensubtitles.com/file","file_name":"chosen.srt"}' if len(calls)==1 else SRT)
        data,name=OpenSubtitles(SubtitleHTTP(opener),{'api_key':'secret','token':'token','expires':9999999999}).download({'id':'42'})
        self.assertEqual(data,SRT);self.assertEqual(name,'chosen.srt')
        self.assertEqual(calls[0].get_header('Authorization'),'Bearer token');self.assertIsNone(calls[1].get_header('Authorization'))
        self.assertIsNone(calls[1].get_header('Api-key'))

    def test_opensubtitles_requires_a_user_supplied_api_key(self):
        with self.assertRaises(SubtitleError):OpenSubtitles(SubtitleHTTP(),{}).headers()

    def test_podnapisi_search_uses_json_endpoint_and_exact_episode(self):
        calls=[]
        def opener(request,**kwargs):
            calls.append(request);return io.BytesIO(json.dumps(dict(data=[pod_row(),pod_row('other',3)],all_pages=1)).encode())
        rows=Podnapisi(SubtitleHTTP(opener)).search(QUERY,threading.Event())
        self.assertEqual([r['id'] for r in rows],['abc']);self.assertTrue(rows[0]['hearing'])
        params=parse_qs(urlsplit(calls[0].full_url).query)
        self.assertEqual(params['episodes'],['2']);self.assertEqual(params['language'],['fr'])

    def test_pagination_is_bounded_to_two_pages(self):
        calls=[]
        def opener(request,**kwargs):calls.append(request);return io.BytesIO(b'{"data":[],"all_pages":200}')
        Podnapisi(SubtitleHTTP(opener)).search(QUERY,threading.Event());self.assertEqual(len(calls),2)

    def test_cancellation_prevents_network_requests(self):
        cancel=threading.Event();cancel.set()
        with patch.object(SubtitleHTTP,'json') as request:Podnapisi(SubtitleHTTP()).search(QUERY,cancel)
        request.assert_not_called()

    def test_one_provider_failure_does_not_discard_other_results(self):
        good=dict(provider='podnapisi',id='1',language='fr',release='Saga',score=85,hearing=False,machine=False)
        providers={'podnapisi':SimpleNamespace(search=lambda *a:[good,good,dict(good,id='wrong',language='en')]),
                   'opensubtitles':SimpleNamespace(search=lambda *a:(_ for _ in ()).throw(SubtitleError('Quota atteint.')))}
        with patch.object(SubtitleService,'providers',return_value=providers):result=SubtitleService().search(QUERY,list(providers),threading.Event())
        self.assertEqual(result['rows'],[good]);self.assertEqual(result['errors'],{'opensubtitles':'Quota atteint.'})

    def test_unknown_provider_error_is_sanitized(self):
        providers={'podnapisi':SimpleNamespace(search=lambda *a:(_ for _ in ()).throw(ValueError('token=secret')))}
        with patch.object(SubtitleService,'providers',return_value=providers):result=SubtitleService().search(QUERY,list(providers),threading.Event())
        self.assertNotIn('secret',str(result))


class SubtitleFiles(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'subtitles';self.store=SubtitleStore(self.root)
    def tearDown(self):self.tmp.cleanup()

    def zip(self,files):
        stream=io.BytesIO()
        with ZipFile(stream,'w') as archive:
            for name,data in files.items():archive.writestr(name,data)
        return stream.getvalue()

    def test_multilingual_utf8_content_is_preserved(self):
        content,ext=subtitle_text(SRT,'caption.srt','ar');self.assertEqual(content,SRT);self.assertEqual(ext,'.srt')

    def test_utf16_is_converted_to_utf8(self):
        content,ext=subtitle_text(SRT.decode().encode('utf-16'),'x.srt');self.assertEqual(content,SRT)

    def test_archive_names_are_never_extracted(self):
        data=self.zip({'../../outside.srt':SRT})
        row=dict(provider='podnapisi',id='../traversal',language='fr')
        path=self.store.save('secret-media',row,data,'archive.zip')
        self.assertEqual(path.parent,self.root);self.assertEqual(path.read_bytes(),SRT)
        self.assertFalse((Path(self.tmp.name)/'outside.srt').exists());self.assertNotIn('secret-media',path.name)
        self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_ambiguous_archives_are_rejected_instead_of_choosing_an_episode(self):
        with self.assertRaises(SubtitleError):subtitle_text(self.zip({'ep1.srt':SRT,'ep2.srt':SRT}),'x.zip')

    def test_html_and_large_files_are_rejected(self):
        for data in (b'<html>Login required</html>',b'x'*(MAX_BYTES+1),b'not a subtitle'):
            with self.subTest(length=len(data)),self.assertRaises(SubtitleError):subtitle_text(data,'x.srt')

    def test_selected_subtitle_and_delay_survive_a_restart(self):
        path=self.store.save(42,dict(provider='podnapisi',id='one',language='fr'),SRT,'x.srt')
        self.store.select(42,path,.5)
        self.assertEqual(SubtitleStore(self.root).selected(42),(path,.5))
        self.assertEqual((self.root/'selected.json').stat().st_mode&0o777,0o600)

    def test_different_media_never_share_the_same_cache_file(self):
        row=dict(provider='podnapisi',id='same',language='fr')
        self.assertNotEqual(self.store.save(1,row,SRT,'x.srt'),self.store.save(2,row,SRT,'x.srt'))

    def test_corrupt_selection_cannot_load_an_external_file(self):
        self.root.mkdir();private_json(self.root/'selected.json',{'42':{'file':'../../passwords.srt'}})
        self.assertIsNone(self.store.selected(42))

    def test_nonfinite_offsets_are_rejected(self):
        path=self.store.save(42,dict(provider='podnapisi',id='one',language='fr'),SRT,'x.srt')
        with self.assertRaises(SubtitleError):self.store.select(42,path,float('nan'))
