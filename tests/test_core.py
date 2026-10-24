import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from tunplayer.core import Library, parse_m3u, parse_xmltv, xtream, read_resource

PLAYLIST='''#EXTM3U
#EXTINF:-1 tvg-id="news.fr" group-title="Infos, France" tvg-logo="https://example.org/logo.png",La Une, HD
https://example.org/live/index.m3u8
#EXTINF:-1 group-title="Films",Mon film
https://example.org/movie.mp4?token=abc
'''

class Formats(unittest.TestCase):
    def test_m3u_quoted_commas_and_movie(self):
        rows=parse_m3u(PLAYLIST)
        self.assertEqual(rows[0]['name'],'La Une, HD')
        self.assertEqual(rows[0]['group_name'],'Infos, France')
        self.assertEqual(rows[0]['tvg_id'],'news.fr')
        self.assertEqual(rows[1]['kind'],'movie')

    def test_relative_url(self):
        rows=parse_m3u('#EXTM3U\n#EXTINF:-1,Relative\nchannel/index.m3u8','https://example.org/list.m3u')
        self.assertEqual(rows[0]['url'],'https://example.org/channel/index.m3u8')

    def test_invalid_and_executable_sources(self):
        for value in ['hello', '#EXTM3U\n#EXTINF:-1,Bad\nav://lavfi:testsrc', '#EXTM3U\n#EXTINF:-1,Bad\nfile:///etc/passwd']:
            with self.assertRaises(ValueError):parse_m3u(value,'https://example.org/test.m3u')

    def test_xmltv_timezone(self):
        rows=parse_xmltv('<tv><programme channel="news.fr" start="20261024080000 +0100" stop="20261024090000 +0100"><title>Journal &amp; météo</title><desc>Le direct</desc></programme></tv>')
        self.assertEqual(rows[0][3],'Journal & météo')
        self.assertEqual(rows[0][2]-rows[0][1],3600)
        self.assertEqual(time.gmtime(rows[0][1]).tm_hour,7)

    def test_xmltv_no_entities_or_empty(self):
        for value in ['<!DOCTYPE tv><tv/>','<tv/>']:
            with self.assertRaises(ValueError):parse_xmltv(value)

    @patch('tunplayer.core.read_resource')
    def test_xtream_live_vod_and_credentials_encoding(self, resource):
        resource.side_effect=[json.dumps([{'category_id':'2','category_name':'Actu'}]),json.dumps([{'stream_id':42,'name':'News','category_id':'2','epg_channel_id':'news.fr'}]),'[]',json.dumps([{'stream_id':9,'name':'Film','container_extension':'mkv'}]),'[]','[]']
        rows=xtream('https://example.org/','a/b','p?ss')
        self.assertEqual(rows[0]['url'],'https://example.org/live/a%2Fb/p%3Fss/42.ts')
        self.assertEqual(rows[1]['kind'],'movie')
        self.assertEqual(rows[0]['group_name'],'Actu')

    @patch('tunplayer.core.read_resource',return_value='{"user_info":{"auth":0}}')
    def test_xtream_auth_failure(self, resource):
        with self.assertRaises(ValueError):xtream('https://example.org','u','p')

    def test_local_resource_bom(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'list.m3u';path.write_bytes(b'\xef\xbb\xbf#EXTM3U')
            self.assertEqual(read_resource(str(path)),'#EXTM3U')

class Storage(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'db.sqlite'; self.lib=Library(self.path)
    def tearDown(self):self.lib.db.close();self.tmp.cleanup()
    def test_import_dedup_search_and_groups(self):
        rows=parse_m3u(PLAYLIST); self.lib.import_channels('TV',rows+rows)
        self.assertEqual(self.lib.sources()[0]['count'],2)
        self.assertEqual(len(self.lib.channels(search='Une')),1)
        self.assertEqual(len(self.lib.channels(group='Films')),1)
        self.assertEqual(len(self.lib.channels(view='movie')),1)
    def test_favorites_history_and_reopen(self):
        self.lib.import_channels('TV',parse_m3u(PLAYLIST)); identity=self.lib.channels()[0]['id']
        self.lib.favorite(identity);self.lib.watched(identity,123.5)
        self.lib.db.close();self.lib=Library(self.path)
        self.assertEqual(self.lib.channels(view='favorites')[0]['id'],identity)
        self.assertEqual(self.lib.channels(view='history')[0]['position'],123.5)
        self.lib.favorite(identity);self.assertFalse(self.lib.channels(view='favorites'))
    def test_cascade_delete(self):
        source=self.lib.import_channels('TV',parse_m3u(PLAYLIST)); self.lib.delete_source(source)
        self.assertFalse(self.lib.channels());self.assertFalse(self.lib.sources())
    def test_failed_import_rolls_back(self):
        with self.assertRaises(KeyError):self.lib.import_channels('Broken',[{}])
        self.assertFalse(self.lib.sources())
    def test_epg_replacement_and_lookup(self):
        self.lib.import_epg([('one',100,200,'Old',''),('one',200,300,'Next',''),('two',100,300,'Other','')])
        self.assertEqual([x['title'] for x in self.lib.programmes('one',150)],['Old','Next'])
        self.lib.import_epg([('one',200,300,'Replacement','')])
        self.assertEqual(self.lib.programmes('one',150)[0]['title'],'Replacement')
    def test_settings(self):
        self.lib.set_setting('volume',.6);self.assertEqual(self.lib.setting('volume'),'0.6')
        self.assertEqual(self.lib.setting('missing','fallback'),'fallback')

if __name__=='__main__':unittest.main()
