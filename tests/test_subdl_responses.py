"""SubDL metadata variations that previously produced a silently empty list."""
import io
import json
import threading
import unittest
from urllib.parse import parse_qs,urlsplit
from tunplayer.subtitles import SubtitleHTTP,SubtitleError,SubtitleService,media_query,validate_query
from tunplayer.subtitle_subdl import SubDL
from unittest.mock import patch
from test_subtitles import QUERY,SRT


class SubDLResponses(unittest.TestCase):
    def provider(self,rows,**changes):
        self.requests=[]
        data=dict(status=True,results=[dict(name='Saga',year=2024,type='tv')],subtitles=rows);data.update(changes)
        def opener(request,**kwargs):self.requests.append(request);return io.BytesIO(json.dumps(data).encode())
        return SubDL(SubtitleHTTP(opener),{'subdl_api_key':'TEST_KEY'})

    def test_named_languages_and_release_numbering_are_not_discarded(self):
        provider=self.provider([dict(language='French',release_name='Saga.S01E02.WEB',url='/subtitle/fr.zip')])
        rows=provider.search(QUERY,threading.Event())
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['language'],'fr');self.assertFalse(rows[0]['warning'])

    def test_lang_field_is_used_when_language_code_is_absent(self):
        provider=self.provider([dict(lang='french',name='Saga.1x02.srt',url='/subtitle/fr.zip')])
        rows=provider.search(QUERY,threading.Event())
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['score'],100)

    def test_single_episode_without_explicit_numbers_is_offered_for_manual_verification(self):
        provider=self.provider([dict(lang='french',release_name='Saga WEB',url='/subtitle/fr.zip')])
        rows=provider.search(QUERY,threading.Event())
        self.assertEqual(len(rows),1);self.assertIn('vérifier',rows[0]['warning'])

    def test_explicitly_different_episode_is_still_rejected(self):
        provider=self.provider([dict(lang='french',release_name='Saga.S01E03',url='/subtitle/fr.zip')])
        self.assertEqual(provider.search(QUERY,threading.Event()),[]);self.assertEqual(provider.diagnostic['episode'],1)

    def test_unpacked_file_numbers_can_be_read_from_its_filename(self):
        provider=self.provider([dict(full_season=True,season=1,unpack_files=[
            dict(lang='french',name='Saga.S01E01.srt',url='/subtitle/pack/one'),
            dict(lang='french',name='Saga.S01E02.srt',url='/subtitle/pack/two')])])
        rows=provider.search(QUERY,threading.Event())
        self.assertEqual([r['download_url'] for r in rows],['https://dl.subdl.com/subtitle/pack/two'])

    def test_all_languages_does_not_send_a_fake_all_language_filter(self):
        provider=self.provider([dict(lang='arabic',name='Saga.S01E02',url='/subtitle/ar.zip'),
                                dict(lang='french',name='Saga.S01E02',url='/subtitle/fr.zip')])
        rows=provider.search(dict(QUERY,language='all'),threading.Event())
        self.assertEqual({r['language'] for r in rows},{'ar','fr'})
        self.assertNotIn('languages',parse_qs(urlsplit(self.requests[0].full_url).query))

    def test_payload_without_legacy_status_field_is_accepted(self):
        provider=self.provider([dict(language='FR',season=1,episode=2,url='/subtitle/fr.zip')])
        opener=provider.http.opener
        def without_status(request,**kwargs):
            data=json.loads(opener(request,**kwargs).read());data.pop('status',None);return io.BytesIO(json.dumps(data).encode())
        provider.http.opener=without_status
        self.assertEqual(len(provider.search(QUERY,threading.Event())),1)

    def test_empty_response_is_distinguished_from_filtered_candidates(self):
        empty=self.provider([]);empty.search(QUERY,threading.Event());self.assertEqual(empty.diagnostic['received'],0)
        filtered=self.provider([dict(language='EN',season=1,episode=2,url='/subtitle/en.zip')]);filtered.search(QUERY,threading.Event())
        self.assertEqual(filtered.diagnostic['received'],1);self.assertEqual(filtered.diagnostic['kept'],0)
        self.assertEqual(filtered.diagnostic['language'],1)

    def test_movie_search_retries_without_year_after_an_empty_response(self):
        requests=[]
        def opener(request,**kwargs):
            requests.append(request);params=parse_qs(urlsplit(request.full_url).query)
            rows=[] if 'year' in params else [dict(lang='french',name='Film.srt',url='/subtitle/fr.zip')]
            return io.BytesIO(json.dumps(dict(subtitles=rows,results=[{'name':'Saga','type':'movie'}])).encode())
        provider=SubDL(SubtitleHTTP(opener),{'subdl_api_key':'TEST_KEY'})
        self.assertEqual(len(provider.search(dict(QUERY,kind='movie'),threading.Event())),1)
        self.assertEqual(len(requests),2);self.assertNotIn('year',parse_qs(urlsplit(requests[-1].full_url).query))

    def test_v2_resource_without_public_url_can_be_downloaded_by_id(self):
        provider=self.provider([dict(lang='french',name='Saga.S01E02.srt',n_id='file_123')])
        row=provider.search(QUERY,threading.Event())[0];requests=[]
        def opener(request,**kwargs):requests.append(request);return io.BytesIO(SRT)
        provider.http.opener=opener
        data,_=provider.download(row)
        self.assertEqual(data,SRT);self.assertEqual(urlsplit(requests[0].full_url).path,'/api/v2/subtitles/file_123/download')
        self.assertEqual(requests[0].get_header('Authorization'),'Bearer TEST_KEY')

    def test_empty_all_language_search_is_supported_by_aggregator(self):
        provider=self.provider([dict(lang='arabic',name='Saga.S01E02',url='/subtitle/ar.zip')])
        with patch.object(SubtitleService,'providers',return_value={'subdl':provider}):
            result=SubtitleService().search(dict(QUERY,language='all'),['subdl'],threading.Event())
        self.assertEqual(result['rows'][0]['language'],'ar');self.assertEqual(result['diagnostics']['subdl']['received'],1)

    def test_iptv_prefix_quality_and_empty_brackets_are_removed_from_suggested_title(self):
        query=media_query(dict(name='FR | The Matrix (1999) [FHD]',kind='movie'))
        self.assertEqual(query['title'],'The Matrix');self.assertEqual(query['year'],1999)
        self.assertEqual(validate_query(dict(QUERY,language='all'))['language'],'all')

    def test_specials_season_zero_is_a_valid_explicit_season_in_an_unpacked_file(self):
        provider=self.provider([dict(full_season=True,season=0,unpack_files=[
            dict(language='FR',season=0,episode=2,name='Special.srt',url='/subtitle/special/two')])])
        self.assertEqual(len(provider.search(dict(QUERY,season=0),threading.Event())),1)

    def test_named_regional_languages_are_treated_like_their_provider_codes(self):
        for language,name in (('pt-br','Brazilian Portuguese'),('pt-pt','Portuguese'),('zh-cn','Chinese'),('zh-tw','Traditional Chinese'),
                              ('el','Greek'),('fa','Farsi'),('si','Sinhalese'),('tl','Filipino')):
            with self.subTest(language=language):
                provider=self.provider([dict(lang=name,name='Saga.S01E02.srt',url='/subtitle/test.zip')])
                self.assertEqual(len(provider.search(dict(QUERY,language=language),threading.Event())),1)
