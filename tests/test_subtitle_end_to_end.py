"""Audio action -> actual providers -> selection -> ZIP -> native mpv subtitle.

Only the HTTPS transport and display widgets are replaced. SVG loading, GLib,
request parsing, provider aggregation, local storage and libmpv remain real.
"""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import test_playback_integration as playback
import test_subtitle_dialogs as dialogs
from test_subtitle_dialogs import DialogHarness
from test_subtitles import SRT
from tunplayer.subtitles import private_json
from tunplayer.player import Player


class SubtitleEndToEnd(unittest.TestCase):
    setUp=playback.PlaybackIntegration.setUp
    tearDown=playback.PlaybackIntegration.tearDown
    wait=playback.PlaybackIntegration.wait
    add=playback.PlaybackIntegration.add
    show=dialogs.SubtitleDialogs.show

    def exercise(self,kind):
        video=Path(__file__).resolve().parents[1]/'assets/demo.mp4'
        if kind=='movie':channel=self.add(url=str(video));expected_title='Test'
        else:
            self.app.library.import_channels('Series',[dict(name='Saga',kind='series',url='xtream-series:1',group_name='Test',tvg_id='',logo='')])
            parent=self.app.library.channels(view='series')[0];expected_title=parent['name']
            channel=self.app.library.store_episodes(parent['id'],[dict(name='Saga · S01E02 · Episode',kind='episode',url=str(video),
                provider_id='1',season=1,episode_num=2,group_name='Test',tvg_id='',logo='')])[0]
        self.app.player=Player(headless=True);self.app.play(channel)
        self.wait(lambda:self.app.tick() and self.app.media_loaded)
        private_json(self.app.subtitle_settings_path,{'subdl_api_key':'TEST_KEY'})
        archive=io.BytesIO()
        with ZipFile(archive,'w') as stream:stream.writestr('caption.fr.srt',SRT)
        requests=[]
        def fetch(http,url,params=None,**kwargs):
            requests.append((url,dict(params or {})))
            if url=='https://api.subdl.com/api/v2/subtitles/search':
                self.assertEqual(params['film_name'],expected_title)
                self.assertEqual(params['type'],'movie' if kind=='movie' else 'tv')
                self.assertEqual(kwargs['headers'],{'Authorization':'Bearer TEST_KEY'})
                if kind=='episode':self.assertEqual((params['season'],params['episode']),(1,2))
                return json.dumps(dict(status=True,results=[dict(name=expected_title,type=params['type'])],subtitles=[dict(
                    lang='french',name='caption.fr.zip',release_name='Saga.S01E02.WEB' if kind=='episode' else 'Edition WEB',
                    url='/subtitle/1-2.zip?api_key=RESPONSE_KEY',season=None,episode=None)])).encode()
            if url.startswith('https://www.podnapisi.net/'):return b'{"data":[],"all_pages":1}'
            if url=='https://dl.subdl.com/subtitle/1-2.zip':
                self.assertEqual(kwargs['headers'],{'X-API-Key':'TEST_KEY'})
                return archive.getvalue()
            self.fail('Unexpected request endpoint')
        def run(harness):
            if harness.dialog_titles[-1]=='Audio et sous-titres':return 101
            # No second click on Rechercher: opening the window initiates search.
            self.wait(lambda:bool(harness.trees[0].model) and harness.buttons['Télécharger et activer'].get_sensitive())
            tree=harness.trees[0];self.assertEqual(tree.model[0][1],'SubDL')
            tree.select_iter(0);harness.buttons['Télécharger et activer'].click()
            self.wait(lambda:any('Sous-titre téléchargé et activé' in label.text for label in harness.labels))
            self.wait(lambda:any(t.get('type')=='sub' and t.get('selected') for t in self.app.player.tracks()))
            self.assertEqual(self.app.player.get('path'),str(video))
            selected=self.app.subtitle_store.selected(channel['id']);self.assertIsNotNone(selected)
            self.assertEqual(selected[0].read_bytes(),SRT)
        harness=DialogHarness(run)
        with patch('tunplayer.subtitles.SubtitleHTTP.fetch',new=fetch):self.show(harness,self.app.tracks_dialog)
        self.assertEqual(harness.dialog_titles,['Audio et sous-titres','Rechercher des sous-titres'])
        self.assertTrue(any(url=='https://dl.subdl.com/subtitle/1-2.zip' for url,_ in requests))

    def test_film_search_select_download_and_activate(self):self.exercise('movie')
    def test_episode_search_select_download_and_activate(self):self.exercise('episode')
