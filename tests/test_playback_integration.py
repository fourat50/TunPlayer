import argparse
from pathlib import Path
import shutil
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from gi.repository import GLib
from tunplayer.app import App,ROOT
from tunplayer.player import Player
from tunplayer.playback_flow import ReconnectPolicy,NextEpisodeCountdown
from tunplayer.player_catalog import neighbors


def sink(*_):pass

class FakePlayer:
    def __init__(self,autoload=True):
        self.loads=[];self.commands=[];self.queue=[];self.autoload=autoload
        self.props={'time-pos':'0','duration':'100','pause':'no','eof-reached':'no','paused-for-cache':'no','idle-active':'no'}
    def command(self,*args):
        self.commands.append(args)
        if args[0]=='loadfile':
            self.loads.append(args[1]);self.props.update({'time-pos':'0','eof-reached':'no','idle-active':'no'})
            if self.autoload:self.queue.append(('loaded',''))
        elif args[0]=='seek':self.props['time-pos']=str(args[1]);self.props['eof-reached']='no'
        elif args[0]=='stop':self.props['idle-active']='yes';self.queue.clear()
    def events(self):events=self.queue[:];self.queue.clear();return events
    def get(self,name,default=''):return self.props.get(name,default)
    def set(self,name,value):self.props[name]=str(value)
    def close(self):pass

class PlaybackIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=App(argparse.Namespace(data_dir=self.tmp.name,screenshot=None));self.messages=[]
        self.app.navigate=lambda view:setattr(self.app,'view',view)
        self.app.notify=lambda text,error=False:self.messages.append((text,error))
        self.app.add_button=SimpleNamespace(set_sensitive=sink)
        self.app.bottom_title=SimpleNamespace(set_text=sink);self.app.player_status=SimpleNamespace(set_text=sink)
        self.app.timeline=SimpleNamespace(set_range=sink,set_value=sink,set_sensitive=sink)
        self.app.time_label=SimpleNamespace(set_text=sink);self.app.pause_button=SimpleNamespace(set_label=sink)
        self.app.render=lambda:None
        self.now=0.;self.app.reconnect=ReconnectPolicy(clock=lambda:self.now);self.app.next_episode=NextEpisodeCountdown(clock=lambda:self.now)
    def tearDown(self):
        self.wait(lambda:self.app.writes.idle)
        self.app.catalog_tasks.close();self.app.detail_tasks.close();self.app.detail_tasks.pool.shutdown(wait=True);self.app.writes.close()
        if self.app.player:self.app.player.close()
        self.app.library.close();self.tmp.cleanup()
    def wait(self,predicate,seconds=5):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            while GLib.MainContext.default().iteration(False):pass
            if predicate():return
            time.sleep(.01)
        self.fail('Playback operation timed out')
    def add(self,kind='movie',url='https://example.org/movie.mp4'):
        self.app.library.import_channels('Test',[dict(name='Test',kind=kind,url=url,group_name='Test',tvg_id='',logo='')])
        return self.app.library.channels()[0]
    def test_network_failure_retries_and_cancel_stops_late_attempts(self):
        channel=self.add(kind='live');player=FakePlayer(autoload=False);self.app.player=player
        self.app.play(channel);player.queue.append(('error','network error'));self.app.tick()
        self.assertTrue(self.app.reconnect.pending);self.assertEqual(len(player.loads),1)
        self.now=.99;self.app.tick();self.assertEqual(len(player.loads),1)
        self.now=1;self.app.tick();self.assertEqual(len(player.loads),2)
        self.app.cancel_reconnect();self.now=100;self.app.tick()
        self.assertEqual(len(player.loads),2);self.assertFalse(self.app.accepting_load)

    def test_browse_category_and_named_next_keep_playback_in_the_player(self):
        source=self.app.library.import_channels('Live',[
            dict(name=name,kind='live',url=f'https://example.org/{name}',group_name=group,tvg_id='',logo='')
            for name,group in [('Alpha','Info'),('Bravo','Info'),('Charlie','Info'),('Sport','Sport')]])
        rows=self.app.library.channels(view='live',source_id=source);bravo=next(row for row in rows if row['name']=='Bravo')
        self.app.player=FakePlayer();self.app.play(bravo);self.app.tick()
        self.app.browser_store=SimpleNamespace(clear=sink);self.app.browser_status=SimpleNamespace(set_text=sink)
        names={};widget=SimpleNamespace(set_sensitive=sink,set_tooltip_text=sink,get_accessible=lambda:SimpleNamespace(set_name=sink))
        self.app.player_prev_button=widget;self.app.player_next_button=widget
        self.app.player_prev_name=SimpleNamespace(set_text=lambda text:names.__setitem__('previous',text))
        self.app.player_next_name=SimpleNamespace(set_text=lambda text:names.__setitem__('next',text))
        snapshots=[];self.app.paint_player_browser=lambda data,focus:snapshots.append(data)
        self.app.browser_group='Sport';self.app.refresh_player_catalog()
        self.wait(lambda:bool(snapshots))
        self.assertEqual([r['name'] for r in snapshots[0]['rows']],['Sport'])
        self.assertEqual(names,{'previous':'Alpha','next':'Charlie'})
        self.assertEqual(self.app.current['id'],bravo['id']);self.assertEqual(len(self.app.player.loads),1)
        self.app.play_neighbor('next')
        self.assertEqual(self.app.current['name'],'Charlie');self.assertEqual(self.app.view,'player')
        self.assertEqual(len(self.app.player.loads),2);self.assertNotIn(('stop',),self.app.player.commands)

    def test_obsolete_browser_results_do_not_replace_the_new_category(self):
        current=self.add(kind='live');self.app.player=FakePlayer();self.app.play(current)
        self.app.browser_store=SimpleNamespace(clear=sink);self.app.browser_status=SimpleNamespace(set_text=sink)
        seen=[];self.app.paint_player_browser=lambda data,focus:seen.append(data['tag'])
        started=threading.Event();release=threading.Event()
        def snapshot(request,cancel):
            if request['group']=='old':started.set();release.wait(2)
            return dict(neighbors={'previous':None,'next':None},tag=request['group'])
        try:
            with patch.object(self.app.player_catalog,'snapshot',side_effect=snapshot):
                self.app.browser_group='old';self.app.refresh_player_catalog();self.assertTrue(started.wait(1))
                self.app.browser_group='new';self.app.refresh_player_catalog()
                self.wait(lambda:bool(seen));self.assertEqual(seen,['new'])
                release.set();self.app.detail_tasks.pool.shutdown(wait=True)
                while GLib.MainContext.default().iteration(False):pass
                self.assertEqual(seen,['new'])
        finally:release.set()

    def test_opening_cached_series_in_browser_does_not_interrupt_current_stream(self):
        current=self.add(kind='live');self.app.player=FakePlayer();self.app.play(current)
        self.app.library.import_channels('Série',[dict(name='Saga',kind='series',url='xtream-series:7',group_name='Drame',tvg_id='',logo='')])
        series=self.app.library.channels(view='series')[0]
        self.app.library.store_episodes(series['id'],[dict(name='Épisode',kind='episode',url='https://example.org/episode',season=1,episode_num=1,provider_id='1',group_name='Drame',tvg_id='',logo='')])
        self.app.browser_rows={series['id']:series};self.app.browser_store=[[series['id']]]
        self.app.browser_status=SimpleNamespace(set_text=sink);self.app.browser_search=SimpleNamespace(set_text=sink)
        refreshed=[];self.app.refresh_player_catalog=lambda:refreshed.append(True)
        with patch('tunplayer.app.load_series') as fetch:
            self.app.player_browser_activate(None,0,None);self.wait(lambda:bool(refreshed));fetch.assert_not_called()
        self.assertEqual(self.app.browser_series,series['id']);self.assertEqual(self.app.current['id'],current['id'])
        self.assertEqual(self.app.view,'player');self.assertEqual(len(self.app.player.loads),1)
    def test_network_vod_retry_resumes_last_known_position(self):
        channel=self.add();player=FakePlayer();self.app.player=player
        self.app.play(channel);self.app.tick();player.props['time-pos']='47';self.app.tick()
        player.queue.append(('error','network error'));self.app.tick()
        self.assertEqual(self.app.current['position'],47)
        self.now=1;self.app.tick();self.app.tick()
        self.assertEqual(len(player.loads),2);self.assertIn(('seek',47.0,'absolute'),player.commands)
        self.assertEqual(self.app.position,47)

    def test_cancelling_resume_choice_keeps_current_stream_and_saved_position(self):
        live=self.add(kind='live');movie=self.add()
        self.app.library.watched(movie['id'],47)
        self.app.player=FakePlayer();self.app.play(live);self.app.tick()
        with patch.object(self.app,'choose_resume',return_value=None) as choose:
            self.app.play(movie);choose.assert_called_once()
        self.assertEqual(self.app.current['id'],live['id']);self.assertEqual(len(self.app.player.loads),1)
        self.assertEqual(self.app.library.channel(movie['id'])['position'],47)

    def test_resume_and_restart_choices_reach_decoder_without_losing_saved_state_on_cancel(self):
        movie=self.add();self.app.library.watched(movie['id'],47);self.app.player=FakePlayer()
        with patch.object(self.app,'choose_resume',return_value='resume'):
            self.app.play(movie);self.app.tick()
        self.assertIn(('seek',47.0,'absolute'),self.app.player.commands)
        with patch.object(self.app,'choose_resume',return_value='start'):
            self.app.play(movie);self.app.tick()
        self.assertEqual(self.app.position,0);self.assertEqual(self.app.current['position'],0)
        self.app.save_position();self.wait(lambda:self.app.writes.idle)
        self.assertEqual(self.app.library.channel(movie['id'])['position'],0)

    def test_retry_never_reopens_resume_dialog(self):
        movie=self.add();self.app.library.watched(movie['id'],47);self.app.player=FakePlayer()
        with patch.object(self.app,'choose_resume',side_effect=AssertionError('Retry asked for resume')):
            self.app.play(movie,resume='auto');self.app.tick();self.app.retry_playback();self.app.tick()
        self.assertEqual(len(self.app.player.loads),2);self.assertEqual(self.app.position,47)

    def test_autoplay_resumes_next_episode_without_a_modal_choice(self):
        parent=self.add(kind='series',url='xtream-series:7')
        first,following=self.app.library.store_episodes(parent['id'],[
            dict(name=f'Épisode {i}',kind='episode',url=f'https://example.org/{i}',group_name='Série',tvg_id='',logo='',season=1,episode_num=i,provider_id=str(i)) for i in (1,2)])
        self.app.library.watched(following['id'],47);self.app.player=FakePlayer();self.app.play(first);self.app.tick()
        self.app.player.props.update({'time-pos':'100','eof-reached':'yes'});self.app.tick()
        with patch.object(self.app,'choose_resume',side_effect=AssertionError('Autoplay opened a dialog')):
            self.now=5;self.app.tick();self.app.tick()
        self.assertEqual(self.app.current['id'],following['id']);self.assertEqual(self.app.position,47)

    def test_playback_status_is_simple_and_diagnostics_are_lazy(self):
        channel=self.add();player=FakePlayer();player.props.update({'video-codec':'h264','width':'1920','height':'1080'})
        self.app.player=player;states=[];self.app.player_status=SimpleNamespace(set_text=states.append)
        self.app.play(channel);self.app.tick();self.assertEqual(states[-1],'Lecture en cours')
        player.props['pause']='yes';self.app.tick();self.assertEqual(states[-1],'Pause')
        player.props['paused-for-cache']='yes';self.app.tick();self.assertEqual(states[-1],'Mise en mémoire tampon…')
        opened=[False];expanded=[False];texts=[]
        self.app.player_settings=SimpleNamespace(get_visible=lambda:opened[0])
        self.app.diagnostic_expander=SimpleNamespace(get_expanded=lambda:expanded[0])
        self.app.diagnostic_label=SimpleNamespace(set_text=texts.append)
        with patch.object(player,'get',side_effect=AssertionError('Hidden diagnostic read mpv')):
            self.app.refresh_diagnostics();expanded[0]=True;self.app.refresh_diagnostics()
        opened[0]=True
        with patch('tunplayer.app.time.monotonic',return_value=100):self.app.refresh_diagnostics()
        with patch('tunplayer.app.time.monotonic',return_value=101):self.app.refresh_diagnostics()
        self.assertEqual(len(texts),1);self.assertIn('h264',texts[0]);self.assertIn('1920 × 1080',texts[0])

    def test_back_from_live_stops_stream_and_cancels_pending_recovery(self):
        channel=self.add(kind='live');player=FakePlayer(autoload=False);self.app.player=player
        self.app.play(channel);player.queue.append(('error','network error'));self.app.tick()
        self.app.back_from_playback();self.now=100;self.app.tick()
        self.assertEqual(self.app.view,'live');self.assertIsNone(self.app.current)
        self.assertIn(('stop',),player.commands);self.assertEqual(len(player.loads),1)
        self.assertFalse(self.app.reconnect.pending);self.assertFalse(self.app.accepting_load)

    def test_back_from_movie_returns_to_fiche_with_final_resume_position(self):
        channel=self.add();self.app.library.update_details(channel['id'],dict(plot='Fiche en cache'))
        player=FakePlayer();self.app.player=player;self.app.play(channel);self.app.tick()
        player.props['time-pos']='47';self.app.tick();self.app.back_from_playback()
        self.wait(lambda:self.app.writes.idle)
        self.assertEqual(self.app.view,'details');self.assertEqual(self.app.detail_id,channel['id'])
        self.assertIsNone(self.app.current);self.assertEqual(self.app.library.channel(channel['id'])['position'],47)
        self.assertIn(('stop',),player.commands)

    def test_back_from_episode_returns_to_parent_and_keeps_season_selection(self):
        parent=self.add(kind='series',url='xtream-series:7')
        episode=self.app.library.store_episodes(parent['id'],[
            dict(name='Épisode',kind='episode',url='https://example.org/1.mp4',group_name='Série',tvg_id='',logo='',provider_id='1',season=2,episode_num=3)])[0]
        self.app.player=FakePlayer();self.app.series_id=parent['id'];self.app.season=2
        self.app.episode_query='Épisode';self.app.navigation.pages['episodes']=1
        self.app.play(episode);self.app.tick();self.app.next_episode.schedule(dict(episode,id='another'))
        self.app.back_from_playback()
        self.assertEqual((self.app.view,self.app.series_id,self.app.season),('episodes',parent['id'],2))
        self.assertEqual(self.app.episode_query,'Épisode');self.assertEqual(self.app.navigation.pages['episodes'],1)
        self.assertFalse(self.app.next_episode.pending);self.assertIsNone(self.app.current)

    def test_back_from_history_episode_selects_its_own_parent_and_season(self):
        parent=self.add(kind='series',url='xtream-series:7')
        episode=self.app.library.store_episodes(parent['id'],[
            dict(name='Épisode',kind='episode',url='https://example.org/1.mp4',group_name='Série',tvg_id='',logo='',provider_id='1',season=3,episode_num=2)])[0]
        self.app.player=FakePlayer();self.app.series_id='other';self.app.episode_query='Ancienne recherche'
        self.app.play(episode);self.app.back_from_playback()
        self.assertEqual((self.app.view,self.app.series_id,self.app.season),('episodes',parent['id'],3))
        self.assertEqual(self.app.episode_query,'')

    def test_back_to_playlist_series_without_parent_has_safe_fallback(self):
        channel=self.add(kind='series',url='https://example.org/series/1.mp4')
        self.app.player=FakePlayer();self.app.play(channel);self.app.back_from_playback()
        self.assertEqual(self.app.view,'series');self.assertIsNone(self.app.current)

    def test_back_preserves_existing_recording_guard(self):
        channel=self.add(kind='live');self.app.player=FakePlayer();self.app.play(channel)
        self.app.recording=SimpleNamespace();self.app.back_from_playback()
        self.assertEqual(self.app.view,'player');self.assertEqual(self.app.current['id'],channel['id'])
        self.assertNotIn(('stop',),self.app.player.commands);self.assertTrue(self.messages[-1][1])
        self.app.recording=None

    def test_repeated_network_failures_exhaust_budget_and_stop_requests(self):
        channel=self.add(kind='live');player=FakePlayer(autoload=False);self.app.player=player
        self.app.play(channel)
        for attempt,delay in enumerate((1,2,4,8),1):
            player.queue.append(('error','network error'));self.app.tick()
            self.assertEqual(self.app.reconnect.attempts,attempt)
            self.now+=delay;self.app.tick()
        player.queue.append(('error','network error'));self.app.tick()
        self.assertFalse(self.app.reconnect.pending);self.assertEqual(len(player.loads),5)
        self.now+=100;self.app.tick();self.assertEqual(len(player.loads),5)
        self.assertTrue(self.messages[-1][1])

    def test_disabling_reconnect_cancels_a_pending_attempt(self):
        channel=self.add(kind='live');player=FakePlayer(autoload=False);self.app.player=player
        self.app.play(channel);player.queue.append(('error','network error'));self.app.tick()
        self.app.set_auto_reconnect(False);self.now=100;self.app.tick()
        self.assertEqual(len(player.loads),1);self.assertFalse(self.app.reconnect.pending)
    def test_normal_movie_end_marks_complete_without_reconnect_or_repeating_finish(self):
        channel=self.add();player=FakePlayer();self.app.player=player
        self.app.play(channel);self.app.tick();player.props.update({'time-pos':'100','eof-reached':'yes'})
        self.app.tick();self.app.tick_count=19;self.app.tick();self.wait(lambda:self.app.writes.idle)
        row=self.app.library.channel(channel['id'])
        self.assertEqual((row['completed'],row['position']),(1,0))
        self.assertFalse(self.app.reconnect.pending);self.assertFalse(self.app.next_episode.pending)
        self.assertEqual(len(player.loads),1)
    def test_error_does_not_treat_incomplete_network_video_as_finished(self):
        channel=self.add();player=FakePlayer();self.app.player=player
        self.app.play(channel);self.app.tick();player.props.update({'time-pos':'40','eof-reached':'yes'})
        self.app.tick();self.wait(lambda:self.app.writes.idle)
        self.assertTrue(self.app.reconnect.pending);self.assertFalse(self.app.library.channel(channel['id'])['completed'])
    @patch('tunplayer.app.load_vod_details')
    def test_details_fetch_is_async_and_persisted_without_losing_resume(self,fetch):
        channel=self.add();self.app.library.watched(channel['id'],35)
        fetch.return_value=dict(plot='Un synopsis',cast='A, B',duration_seconds=100)
        self.app.open_details(channel);self.wait(lambda:not self.app.detail_loading)
        updated=self.app.library.channel(channel['id'])
        self.assertEqual((updated['plot'],updated['cast'],updated['position']),('Un synopsis','A, B',35))
        self.assertGreater(updated['details_loaded_at'],0)

    @patch('tunplayer.app.load_vod_details',side_effect=OSError('unreachable provider'))
    def test_details_error_keeps_cached_synopsis_and_playable_entry(self,fetch):
        channel=self.add();self.app.library.update_details(channel['id'],dict(plot='Synopsis conservé'))
        self.app.detail_id=channel['id'];self.app.view='details';self.app.refresh_details(channel)
        self.wait(lambda:not self.app.detail_loading)
        self.assertEqual(self.app.library.channel(channel['id'])['plot'],'Synopsis conservé')
        self.assertIn('indisponibles',self.app.detail_message)

    @patch('tunplayer.app.load_vod_details')
    def test_reopening_cached_details_clears_stale_loading_state(self,fetch):
        channel=self.add();self.app.library.update_details(channel['id'],dict(plot='En cache'))
        self.app.detail_loading=True;self.app.view='home';self.app.open_details(channel)
        self.assertFalse(self.app.detail_loading);fetch.assert_not_called()

    def test_cancelled_countdown_does_not_restart_while_still_at_eof(self):
        channel=self.add();player=FakePlayer();self.app.player=player
        self.app.play(channel);self.app.tick()
        player.props.update({'time-pos':'100','eof-reached':'yes'})
        self.app.eof_handled=True;self.app.completed_current=True
        self.app.next_episode.schedule(dict(channel,id='another'))
        self.app.cancel_next();self.now=100;self.app.tick()
        self.assertEqual(self.app.current['id'],channel['id']);self.assertEqual(len(player.loads),1)
    def test_real_decoder_eof_advances_only_after_cancellable_countdown(self):
        parent=self.add(kind='series',url='xtream-series:7')
        second=Path(self.tmp.name)/'second.mp4';shutil.copyfile(ROOT/'assets/demo.mp4',second)
        rows=[dict(name=f'Épisode {index}',kind='episode',url=str(path),group_name='Série',tvg_id='',logo='',provider_id=str(index),season=1,episode_num=index)
              for index,path in [(1,ROOT/'assets/demo.mp4'),(2,second)]]
        first,following=self.app.library.store_episodes(parent['id'],rows)
        self.app.player=Player(headless=True);self.app.play(first)
        def loaded():self.app.tick();return self.app.media_loaded
        self.wait(loaded)
        self.app.player.command('seek',11.8,'absolute')
        def ended():self.app.tick();return self.app.next_episode.pending
        self.wait(ended);self.wait(lambda:self.app.writes.idle)
        self.assertEqual(self.app.library.channel(first['id'])['completed'],1)
        self.now=4.99;self.app.tick();self.assertEqual(self.app.current['id'],first['id'])
        self.now=5;self.app.tick();self.assertEqual(self.app.current['id'],following['id'])
        self.wait(loaded);self.assertFalse(self.app.next_episode.pending)
        engine=self.app.player
        self.app.player_neighbors=neighbors(self.app.library,following['id']);self.app.play_neighbor('previous');self.wait(loaded)
        self.assertEqual(self.app.current['id'],first['id']);self.assertIs(self.app.player,engine)
        self.app.player_neighbors=neighbors(self.app.library,first['id']);self.app.play_neighbor('next');self.wait(loaded)
        self.assertEqual(self.app.current['id'],following['id']);self.assertIs(self.app.player,engine)
        self.app.back_from_playback()
        self.assertEqual(self.app.view,'episodes');self.assertIsNone(self.app.current)
        self.wait(lambda:self.app.player.get('idle-active')=='yes')

if __name__=='__main__':unittest.main()
