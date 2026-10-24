import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlsplit,parse_qs
from unittest.mock import patch
from tunplayer.radio import RadioDirectory,RadioError,stations,favorite_rows,MAX_BYTES,filter_summary
from tunplayer.playback_ui import browser_category_caption


def station(name='Jazz Tunis',identity='01234567-89ab-cdef-0123-456789abcdef',**extra):
    return dict(stationuuid=identity,name=name,url='https://example.org/live',url_resolved='https://example.org/resolved',
        country='Tunisia',countrycode='TN',tags='jazz, music',favicon='https://example.org/logo.png',bitrate=128,lastcheckok=1,**extra)


class RadioDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.calls=[];self.now=1000.;self.offline=False
        self.directory=RadioDirectory(Path(self.tmp.name),self.opener,clock=lambda:self.now)
        self.directory.mirrors=['https://de1.api.radio-browser.info','https://fr1.api.radio-browser.info'];self.directory.mirror_deadline=99999
        self.cancel=threading.Event()

    def tearDown(self):self.tmp.cleanup()

    def opener(self,request,timeout):
        self.calls.append(request)
        if self.offline:raise OSError('offline')
        path=urlsplit(request.full_url).path
        data=[dict(name='Tunisia',iso_3166_1='TN',stationcount=42)] if path.endswith('countries') else [dict(name='jazz',stationcount=100)] if path.endswith('tags') else [station()]
        return io.BytesIO(json.dumps(data).encode())

    def test_combined_country_category_search_sort_and_pagination(self):
        result=self.directory.search(dict(country='TN',tag='jazz',text='Jazz',order='country',page=2),self.cancel)
        query=parse_qs(urlsplit(self.calls[0].full_url).query)
        self.assertEqual({k:v[0] for k,v in query.items()},{'countrycode':'TN','tag':'jazz','name':'Jazz','order':'country',
            'tagExact':'true','reverse':'false','hidebroken':'true','limit':'40','offset':'80'})
        self.assertEqual(result['rows'][0]['url'],'https://example.org/resolved')
        self.assertIn('TunPlayer/',self.calls[0].get_header('User-agent'))

    def test_fresh_cache_avoids_network_and_expired_cache_survives_outage(self):
        query=dict(country='TN');self.directory.search(query,self.cancel);count=len(self.calls)
        self.directory.search(query,self.cancel);self.assertEqual(len(self.calls),count)
        self.now+=601;self.offline=True
        result=self.directory.search(query,self.cancel)
        self.assertTrue(result['stale']);self.assertEqual(result['rows'][0]['name'],'Jazz Tunis')

    def test_cancelled_requests_make_no_network_calls(self):
        self.cancel.set();self.assertEqual(self.directory.search({},self.cancel)['rows'],[]);self.assertEqual(self.calls,[])

    def test_failure_without_cache_is_an_actionable_error(self):
        self.offline=True
        with self.assertRaises(RadioError):self.directory.search({},self.cancel)
        self.assertEqual(len(self.calls),2)

    def test_malformed_response_retries_a_different_mirror(self):
        responses=[io.BytesIO(b'not-json'),io.BytesIO(json.dumps([station()]).encode())]
        with patch.object(self.directory,'opener',side_effect=responses):
            self.assertEqual(len(self.directory.search({},self.cancel)['rows']),1)

    def test_response_size_is_bounded(self):
        with patch.object(self.directory,'opener',return_value=io.BytesIO(b' '*(MAX_BYTES+1))):
            with self.assertRaises(RadioError):self.directory.fetch('https://example.org/api')

    def test_country_and_category_facets_follow_the_provider_schema(self):
        data=self.directory.facets(self.cancel)
        self.assertEqual(data['countries'],[dict(name='Tunisia',code='TN',count=42)])
        self.assertEqual(data['groups'],[dict(group_name='jazz',count=100)])

    def test_mirror_discovery_rejects_unrelated_hosts(self):
        self.directory.mirrors=None
        with patch.object(self.directory,'fetch',return_value=[dict(name='evil.example'),dict(name='de1.api.radio-browser.info'),dict(name=123)]):
            self.assertEqual(self.directory.servers(self.cancel),['https://de1.api.radio-browser.info'])

    def test_station_validation_discards_broken_and_unsafe_streams_and_duplicates(self):
        rows=[station(),station(),dict(station(),lastcheckok=0),dict(station(),stationuuid='invalid'),
              dict(station(),url_resolved='file:///etc/passwd',url='javascript:bad'),
              dict(station(),url_resolved='https://[broken',url='bad')]
        result=stations(rows);self.assertEqual(len(result),1)
        self.assertTrue(result[0]['radio']);self.assertEqual(result[0]['kind'],'live')

    def test_favorites_can_be_searched_and_filtered_without_any_api(self):
        row=stations([station()])[0];favorites={row['id']:row}
        self.assertEqual(favorite_rows(favorites,dict(country='TN',tag='jazz',text='jazz'))['rows'],[row])
        self.assertEqual(favorite_rows(favorites,dict(country='FR'))['rows'],[])

    def test_worldwide_indie_count_is_not_presented_as_a_filtered_radio_count(self):
        group=dict(group_name='indie',count=454)
        self.assertEqual(browser_category_caption(group,radio=True),'indie')
        self.assertEqual(browser_category_caption(group,radio=False),'indie (454)')

    def test_filter_summary_explains_the_country_genre_and_favorite_intersection(self):
        summary=filter_summary(dict(country='TN',tag='indie',text='Tunis'),[dict(code='TN',name='Tunisia')],True)
        self.assertIn('Pays : Tunisia',summary);self.assertIn('Genre : indie',summary)
        self.assertIn('Recherche : « Tunis »',summary);self.assertIn('Mes radios uniquement',summary)

    def test_global_genre_can_have_stations_while_a_country_intersection_is_empty(self):
        def response(request,timeout):
            query=parse_qs(urlsplit(request.full_url).query)
            return io.BytesIO(json.dumps([] if query.get('countrycode')==['TN'] else [station()]).encode())
        with patch.object(self.directory,'opener',side_effect=response):
            self.assertEqual(self.directory.search(dict(country='TN',tag='indie'),self.cancel)['rows'],[])
            self.assertEqual(len(self.directory.search(dict(tag='indie'),self.cancel)['rows']),1)
