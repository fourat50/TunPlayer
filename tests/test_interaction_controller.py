from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_playback_integration as playback
from tunplayer.parental import category_key
from tunplayer.player import Player
from tunplayer.radio import stations
from test_radio import station


class PlaybackControls(unittest.TestCase):
    setUp=playback.PlaybackIntegration.setUp
    tearDown=playback.PlaybackIntegration.tearDown
    wait=playback.PlaybackIntegration.wait
    add=playback.PlaybackIntegration.add

    def protect(self,kind='movie',group='Test'):
        self.app.category_locks.set_pin('7391');self.app.category_locks.protect(kind,group,'7391')

    def test_locked_movie_cannot_play_or_open_details_without_pin(self):
        row=self.add();self.protect();self.app.player=playback.FakePlayer()
        with patch.object(self.app,'ask_pin',return_value=None):
            self.app.play(row);self.app.open_details(row)
        self.assertEqual(self.app.player.loads,[]);self.assertIsNone(self.app.current);self.assertIsNone(self.app.detail_id)

    def test_authorized_category_can_play_and_is_locked_again_on_request(self):
        row=self.add();self.protect();self.app.player=playback.FakePlayer()
        with patch.object(self.app,'ask_pin',return_value='7391'):self.app.play(row);self.app.tick()
        self.assertEqual(self.app.current['id'],row['id'])
        self.app.relock_categories();self.assertIsNone(self.app.current)
        self.assertTrue(self.app.content_locked(row))

    def test_episode_inherits_its_parent_series_category(self):
        self.app.library.import_channels('Series',[dict(name='Saga',kind='series',url='xtream-series:1',group_name='Adultes',logo='',tvg_id='')])
        series=self.app.library.channels(view='series')[0]
        episode=self.app.library.store_episodes(series['id'],[dict(name='Episode',kind='episode',url='https://example.org/ep.mp4',
            provider_id='1',season=1,episode_num=1,group_name='Saison 1',logo='',tvg_id='')])[0]
        self.protect('series','Adultes')
        self.assertTrue(self.app.content_locked(episode))
        self.assertIn(category_key('series','Adultes'),self.app.access_keys(episode))

    def test_protected_category_cannot_be_downloaded_before_authentication(self):
        row=self.add();self.protect()
        with patch.object(self.app,'ask_pin',return_value=None),patch.object(self.app,'choose_download_folder') as chooser:
            self.app.download_content(row)
        chooser.assert_not_called();self.assertIsNone(self.app.download_manager)

    def test_radio_lock_matches_any_station_tag(self):
        self.protect('radio','music');row=stations([station()])[0]
        self.assertTrue(self.app.content_locked(row))

    def test_download_category_survives_source_removal(self):
        self.protect('series','Adultes')
        row=dict(channel_id='removed',category_kind='series',category_name='Adultes')
        self.assertTrue(self.app.content_locked(self.app.download_channel(row)))

    def test_orphan_episode_cannot_bypass_series_locks(self):
        self.protect('series','Adultes')
        self.assertTrue(self.app.content_locked(dict(kind='episode',group_name='Saison 1',parent_id='removed')))

    def test_native_quit_event_stops_polling_the_destroyed_player(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row)
        def quit_player(_):self.app.closing=True;self.app.player=None
        with patch.object(self.app.player,'events',return_value=[('input','quit')]),patch.object(self.app,'player_input',side_effect=quit_player):
            self.assertFalse(self.app.tick())
        self.app.closing=False

    def test_volume_and_mute_preserve_the_previous_level(self):
        self.app.player=playback.FakePlayer();self.app.set_volume(.43);self.app.toggle_mute()
        self.assertEqual(self.app.volume,.43);self.assertEqual(self.app.player.get('mute'),'yes')
        self.app.toggle_mute();self.assertEqual(self.app.player.get('volume'),'43');self.assertEqual(self.app.player.get('mute'),'no')
        self.app.set_volume(0);self.app.toggle_mute();self.assertEqual(self.app.volume,.43)

    def test_volume_is_clamped_and_ignores_invalid_values(self):
        self.app.set_volume(2);self.assertEqual(self.app.volume,1)
        self.app.set_volume(-1);self.assertEqual(self.app.volume,0)
        self.app.set_volume(.6);self.app.set_volume(float('nan'));self.assertEqual(self.app.volume,.6)
        self.app.step_volume(-1);self.assertAlmostEqual(self.app.volume,.55)

    def test_window_close_can_stop_only_the_content(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row)
        with patch.object(self.app,'choose_close_action',return_value='content'),patch.object(self.app,'close') as close:
            self.assertTrue(self.app.request_close())
        close.assert_not_called();self.assertIsNone(self.app.current);self.assertEqual(self.app.view,'details')

    def test_cancel_window_close_keeps_playback_running(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row)
        with patch.object(self.app,'choose_close_action',return_value='cancel'),patch.object(self.app,'close') as close:self.app.request_close()
        close.assert_not_called();self.assertEqual(self.app.current['id'],row['id'])

    def test_explicit_quit_closes_the_application(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row)
        destroyed=[];self.app.window=SimpleNamespace(destroy=lambda:destroyed.append(True))
        with patch.object(self.app,'choose_close_action',return_value='quit'),patch.object(self.app,'close') as close:self.app.request_close()
        close.assert_called_once();self.assertTrue(destroyed)

    def test_double_click_toggles_fullscreen_once_per_gesture(self):
        self.app.view='player'
        with patch('tunplayer.interactions.time.monotonic',side_effect=[10,10.1,11]),patch.object(self.app,'toggle_fullscreen') as toggle:
            self.app.video_double_click();self.app.video_double_click();self.app.video_double_click()
        self.assertEqual(toggle.call_count,2)

    def test_native_mpv_mouse_and_volume_events_reach_the_application(self):
        player=Player(headless=True)
        try:
            player.command('keypress','MBTN_LEFT_DBL');player.command('keypress','WHEEL_UP');player.command('keypress','m')
            messages=[]
            self.wait(lambda:bool(messages.extend(player.events())) or len([r for r in messages if r[0]=='input'])>=3)
            self.assertIn(('input','fullscreen-double'),messages);self.assertIn(('input','volume-up'),messages);self.assertIn(('input','mute'),messages)
            self.assertEqual(player.get('fullscreen'),'no')
        finally:player.close()
