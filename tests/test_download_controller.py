from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_playback_integration as playback
from tunplayer.downloads import plan


class DownloadController(unittest.TestCase):
    setUp=playback.PlaybackIntegration.setUp
    wait=playback.PlaybackIntegration.wait
    add=playback.PlaybackIntegration.add

    def tearDown(self):
        self.app.cancel_stream_start()
        if self.app.download_manager:self.app.download_manager.close(wait=True)
        playback.PlaybackIntegration.tearDown(self)

    def staged(self,mapped=True):
        state=[mapped]
        self.app.view_stack=SimpleNamespace()
        self.app.video=SimpleNamespace(get_mapped=lambda:state[0],get_allocated_width=lambda:640,get_allocated_height=lambda:360)
        self.app.player=playback.FakePlayer();self.app.ensure_player=lambda:None
        return state

    def test_player_waits_for_the_mapped_layout_before_loading(self):
        channel=self.add();mapped=self.staged(False);self.app.play(channel)
        self.assertEqual(self.app.player.loads,[])
        mapped[0]=True;self.wait(lambda:self.app.tick() and self.app.media_loaded)
        self.assertEqual(self.app.player.loads,[channel['url']])

    def test_stop_cancels_an_unmapped_pending_stream(self):
        channel=self.add();mapped=self.staged(False);self.app.play(channel);self.app.back_from_playback();mapped[0]=True
        until=time.monotonic()+.05;self.wait(lambda:time.monotonic()>=until)
        self.assertIsNone(self.app.current);self.assertEqual(self.app.player.loads,[]);self.assertIsNone(self.app.stream_start_timer)

    def test_rapid_switches_never_load_the_stale_selection(self):
        first=self.add();self.app.library.import_channels('Second',[dict(name='Second',kind='movie',url='https://example.org/second',group_name='Test',logo='',tvg_id='')])
        second=self.app.library.channels(search='Second')[0];self.staged(True)
        self.app.play(first);self.app.play(second);self.wait(lambda:self.app.tick() and self.app.media_loaded)
        self.assertEqual(self.app.player.loads,[second['url']])

    def test_season_download_uses_all_episodes_not_the_current_search_page(self):
        self.app.library.import_channels('Series',[dict(name='Saga',kind='series',url='xtream-series:1',group_name='Test',logo='',tvg_id='')])
        series=self.app.library.channels(view='series')[0]
        self.app.library.store_episodes(series['id'],[dict(name=f'Episode {n}',kind='episode',url=f'https://example.org/{n}.mp4',
            provider_id=str(n),season=2,episode_num=n,group_name='Test',logo='',tvg_id='') for n in range(1,81)])
        self.app.series_id=series['id'];self.app.season=2;self.app.page=4;self.app.episode_query='Episode 1'
        with patch.object(self.app,'choose_download_folder',return_value=self.tmp.name),patch.object(self.app,'queue_downloads') as queue:
            self.app.download_season()
        self.assertEqual(len(queue.call_args.args[0]),80)

    def test_offline_file_plays_in_app_and_stop_returns_to_downloads(self):
        channel=self.add();row=plan([channel],self.tmp.name)[0]
        target=Path(row['path']);target.write_bytes(b'local fixture');row['state']='done'
        self.app.transfers().jobs[row['id']]=row
        self.app.player=playback.FakePlayer()
        with patch.object(self.app,'ensure_player'):
            self.app.play_download(row);self.app.tick()
        self.assertTrue(self.app.current['local_download']);self.assertEqual(self.app.player.loads,[str(target)])
        self.assertEqual(self.app.library.channel(channel['id'])['url'],channel['url'])
        self.app.back_from_playback();self.assertEqual(self.app.view,'downloads')
