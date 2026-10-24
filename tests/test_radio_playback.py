from pathlib import Path
import unittest
from unittest.mock import patch
import test_playback_integration as playback
from tunplayer.radio import stations
from tunplayer.player import Player
from test_radio import station


class RadioPlayback(unittest.TestCase):
    setUp=playback.PlaybackIntegration.setUp
    tearDown=playback.PlaybackIntegration.tearDown
    wait=playback.PlaybackIntegration.wait

    def radio(self):return stations([station()])[0]

    def play(self,row):
        self.app.player=playback.FakePlayer()
        with patch.object(self.app,'ensure_player'):
            self.app.play(row);self.app.tick()

    def test_radio_does_not_need_a_playlist_and_does_not_pollute_tv_history(self):
        row=self.radio()
        with patch.object(self.app.library,'channel',side_effect=AssertionError('Radio accessed IPTV library')):
            self.play(row);self.app.save_position()
        self.assertEqual(self.app.current['id'],row['id']);self.assertEqual(self.app.player.get('vid'),'no')
        self.assertEqual(self.app.library.channels(view='history'),[])

    def test_stop_and_back_return_to_radio(self):
        self.play(self.radio());engine=self.app.player
        self.app.back_from_playback()
        self.assertEqual(self.app.view,'radio');self.assertIsNone(self.app.current)
        self.assertIn(('stop',),engine.commands)

    def test_reconnect_reuses_the_radio_instead_of_looking_up_an_iptv_channel(self):
        row=self.radio();self.play(row)
        self.app.handle_playback_failure('Network lost');self.now=2
        with patch.object(self.app.library,'channel',side_effect=AssertionError('Radio lookup in IPTV')):self.app.tick()
        self.assertEqual(self.app.current['id'],row['id']);self.assertEqual(len(self.app.player.loads),2)

    def test_favorites_are_restored_from_the_user_profile(self):
        row=self.radio();self.app.toggle_radio_favorite(row)
        self.wait(lambda:self.app.writes.idle)
        self.app.radio_favorites={};self.app.init_radio()
        self.assertIn(row['id'],self.app.radio_favorites)

    def test_expanding_country_keeps_the_selected_genre_and_search(self):
        self.app.radio_country='TN';self.app.group='indie';self.app.query='radio';self.app.page=4
        self.app.clear_radio_country()
        self.assertEqual(self.app.radio_query(),dict(country='',tag='indie',text='radio',order='popular',page=0))

    def test_switching_back_to_video_restores_the_video_track(self):
        media=str(Path(__file__).resolve().parents[1]/'assets/demo.mp4')
        row=dict(self.radio(),url=media);engine=Player(headless=True);self.app.player=engine
        with patch.object(self.app,'ensure_player'):
            self.app.play(row)
            self.wait(lambda:self.app.tick() and self.app.media_loaded)
            self.assertEqual(engine.get('vid'),'no')
            self.assertTrue(engine.get('audio-codec'))
            self.app.library.import_channels('Films',[dict(name='Film',kind='movie',url=media,group_name='Test',logo='',tvg_id='')])
            movie=self.app.library.channels(view='movie')[0];self.app.play(movie)
            self.wait(lambda:self.app.tick() and self.app.media_loaded and engine.get('width')=='1280')
            self.assertIs(self.app.player,engine);self.assertEqual(engine.get('vid'),'1')
