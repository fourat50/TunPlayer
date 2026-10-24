from pathlib import Path
import unittest
from unittest.mock import patch
import test_playback_integration as playback
from tunplayer.player import Player
from test_subtitles import SRT


class SubtitleController(unittest.TestCase):
    setUp=playback.PlaybackIntegration.setUp
    tearDown=playback.PlaybackIntegration.tearDown
    wait=playback.PlaybackIntegration.wait
    add=playback.PlaybackIntegration.add

    def cached(self,row):return self.app.subtitle_store.save(row['id'],dict(provider='podnapisi',id='one',language='fr'),SRT,'x.srt')

    def test_downloaded_subtitle_is_activated_without_reloading_the_video(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row);self.app.tick()
        path=self.cached(row);context=self.app.subtitle_context()
        self.assertTrue(self.app.activate_subtitle(context,path,.5))
        self.assertEqual(self.app.player.loads,[row['url']]);self.assertIn(('sub-add',str(path),'select'),self.app.player.commands)
        self.assertEqual(self.app.player.get('sub-delay'),'0.5')

    def test_obsolete_download_never_applies_to_another_video(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row);path=self.cached(row);context=self.app.subtitle_context()
        self.app.current=dict(row,id='other')
        self.assertFalse(self.app.activate_subtitle(context,path));self.assertFalse(any(c[0]=='sub-add' for c in self.app.player.commands))

    def test_old_playback_generation_is_rejected_even_for_the_same_movie(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row);path=self.cached(row);context=self.app.subtitle_context()
        self.app.stream_generation+=1
        self.assertFalse(self.app.activate_subtitle(context,path))

    def test_pin_locked_content_cannot_receive_an_old_download(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row);path=self.cached(row);context=self.app.subtitle_context()
        self.app.category_locks.set_pin('7391');self.app.category_locks.protect('movie','Test','7391')
        self.assertFalse(self.app.activate_subtitle(context,path))

    def test_saved_selection_is_restored_after_file_loaded(self):
        row=self.add();path=self.cached(row);self.app.subtitle_store.select(row['id'],path,.75)
        self.app.player=playback.FakePlayer();self.app.play(row);self.app.tick()
        self.assertIn(('sub-add',str(path),'select'),self.app.player.commands);self.assertEqual(self.app.player.get('sub-delay'),'0.75')

    def test_disabling_subtitles_removes_automatic_restoration(self):
        row=self.add();path=self.cached(row);self.app.subtitle_store.select(row['id'],path,.75)
        self.app.player=playback.FakePlayer();self.app.play(row);self.app.tick();self.app.set_track('sid','no')
        self.assertIsNone(self.app.subtitle_store.selected(row['id']));self.assertIsNone(self.app.active_subtitle)

    def test_live_stream_does_not_offer_movie_subtitle_search(self):
        row=self.add(kind='live');self.app.player=playback.FakePlayer();self.app.play(row)
        self.assertIsNone(self.app.subtitle_context())

    def test_a_different_movie_does_not_inherit_the_previous_subtitle_offset(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.player.set('sub-delay',4)
        self.app.play(row);self.app.tick()
        self.assertEqual(float(self.app.player.get('sub-delay')),0)

    def test_reselecting_a_cached_track_does_not_add_a_duplicate(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row);path=self.cached(row)
        self.app.player.tracks=lambda:[{'type':'sub','external-filename':str(path),'id':4}]
        self.assertTrue(self.app.activate_subtitle(self.app.subtitle_context(),path))
        self.assertEqual(self.app.player.get('sid'),'4');self.assertFalse(any(c[0]=='sub-add' for c in self.app.player.commands))

    def test_real_mpv_loads_a_saved_subtitle_and_preserves_playback(self):
        video=Path(__file__).resolve().parents[1]/'assets/demo.mp4'
        row=self.add(url=str(video));path=self.cached(row);self.app.subtitle_store.select(row['id'],path,.5)
        self.app.player=Player(headless=True);self.app.play(row)
        self.wait(lambda:self.app.tick() and self.app.media_loaded)
        self.wait(lambda:any(t.get('type')=='sub' and t.get('selected') for t in self.app.player.tracks()))
        self.assertAlmostEqual(float(self.app.player.get('sub-delay')),.5)
        self.assertEqual(self.app.player.get('path'),str(video))
