from pathlib import Path
import time
import sys
import unittest
from unittest.mock import patch
from tunplayer.player import Player

class Playback(unittest.TestCase):
    def test_event_observed_properties_follow_real_playback_and_pause(self):
        player=Player(headless=True)
        try:
            player.command('loadfile',str(Path(__file__).resolve().parents[1]/'assets/demo.mp4'))
            until=time.monotonic()+3
            while time.monotonic()<until:
                player.events()
                if float(player.cached('time-pos','0'))>.05:break
                time.sleep(.01)
            self.assertGreater(float(player.cached('time-pos','0')),0)
            self.assertGreater(float(player.cached('duration','0')),10)
            player.set('pause','yes')
            until=time.monotonic()+1
            while time.monotonic()<until and player.cached('pause')!='yes':
                player.events();time.sleep(.01)
            self.assertEqual(player.cached('pause'),'yes')
            player.command('stop');self.assertEqual(player.cached('time-pos','0'),'0')
            self.assertEqual(player.cached('missing','fallback'),'fallback')
        finally:player.close()

    def test_live_startup_profile_is_reset_for_vod_radio_and_retry(self):
        player=Player(headless=True)
        try:
            live={'kind':'live','url':'https://example.org/live.ts'}
            player.prepare_stream(live)
            self.assertEqual(float(player.get('demuxer-lavf-analyzeduration')),.5)
            player.prepare_stream(live,conservative=True)
            self.assertEqual(float(player.get('demuxer-lavf-analyzeduration')),0)
            for channel in ({'kind':'movie','url':'https://example.org/movie.mp4'},
                            {'kind':'episode','url':'https://example.org/episode.mkv'},dict(live,radio=True),dict(live,url='/tmp/live.ts')):
                player.prepare_stream(channel)
                self.assertEqual(float(player.get('demuxer-lavf-analyzeduration')),0)
            self.assertEqual(player.get('demuxer-lavf-probe-info'),'auto')
            self.assertEqual(player.get('cache'),'yes')
        finally:player.close()

    def test_visible_player_cannot_start_without_valid_host_window(self):
        with patch('tunplayer.player.C.CDLL') as library:
            for identity in (None,0,-1,True,'42'):
                with self.subTest(identity=identity),self.assertRaises(RuntimeError):Player(window_id=identity)
            library.assert_not_called()

    @unittest.skipUnless(sys.platform.startswith('linux'),'X11 embedding is Linux-specific')
    def test_wayland_session_keeps_x11_host_and_restricts_renderer_on_real_mpv(self):
        with patch.dict('os.environ',{'WAYLAND_DISPLAY':'wayland-test','XDG_SESSION_TYPE':'wayland'}):
            # Initialize only: no media/window is opened against this synthetic XID.
            player=Player(window_id=42)
            try:
                self.assertEqual(player.get('wid'),'42')
                self.assertEqual(player.get('vo'),'gpu,x11')
                self.assertEqual(player.get('gpu-context'),'x11egl')
                self.assertEqual(player.get('gpu-api'),'opengl')
            finally:player.close()

    def test_aspect_modes_and_cursor_settings_on_real_decoder(self):
        player=Player(headless=True)
        try:
            player.command('loadfile',str(Path(__file__).resolve().parents[1]/'assets/demo.mp4'))
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                if any(event[0]=='loaded' for event in player.events()):break
                time.sleep(.02)
            self.assertEqual(player.get('width'),'1280')
            for mode,ratio in [('16:9',16/9),('4:3',4/3),('21:9',21/9),('1:1',1)]:
                player.set_aspect(mode)
                self.assertAlmostEqual(float(player.get('video-aspect-override')),ratio,places=5)
            player.set_aspect('fill');self.assertEqual(float(player.get('panscan')),1)
            player.set_aspect('stretch');self.assertEqual(player.get('keepaspect'),'no')
            player.set_aspect('auto');self.assertEqual(player.get('keepaspect'),'yes')
            self.assertEqual(float(player.get('panscan')),0)
            self.assertLess(float(player.get('video-aspect-override')),0)
            player.set('cursor-autohide','always');self.assertEqual(player.get('cursor-autohide'),'always')
            player.set('cursor-autohide','no');self.assertEqual(player.get('cursor-autohide'),'no')
            with self.assertRaises(ValueError):player.set_aspect('invalid')
        finally:player.close()

    def test_actual_decode_pause_seek_audio_and_close(self):
        player=Player(headless=True)
        try:
            player.command('loadfile',str(Path(__file__).resolve().parents[1]/'assets/demo.mp4'))
            deadline=time.monotonic()+8
            loaded=False
            while time.monotonic()<deadline:
                events=player.events()
                self.assertFalse([e for e in events if e[0]=='error'])
                if any(e[0]=='loaded' for e in events):loaded=True;break
                time.sleep(.05)
            self.assertTrue(loaded,'mpv did not load the bundled media')
            self.assertEqual(player.get('width'),'1280')
            self.assertEqual(player.get('height'),'720')
            self.assertTrue(any(t['type']=='audio' for t in player.tracks()))
            player.set('pause','yes');self.assertEqual(player.get('pause'),'yes')
            player.command('seek',5,'absolute')
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                if float(player.get('time-pos','0'))>=4.9:break
                time.sleep(.05)
            self.assertGreaterEqual(float(player.get('time-pos','0')),4.9)
            player.set('volume',33);self.assertEqual(round(float(player.get('volume'))),33)
        finally:player.close()
        self.assertIsNone(player.handle)

if __name__=='__main__':unittest.main()
