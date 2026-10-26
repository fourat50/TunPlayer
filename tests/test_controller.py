"""Controller integration tests using GLib's real event loop, without an X11 display."""
import argparse
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tunplayer.app import App, GLib, ROOT
from tunplayer.player import Player
from tunplayer.playback_ui import PlaybackIdle


def sink(*_):pass


class Controller(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=App(argparse.Namespace(data_dir=self.tmp.name,screenshot=None))
        self.messages=[];self.views=[]
        self.app.notify=lambda text,error=False:self.messages.append((text,error))
        self.app.navigate=lambda view:self.views.append(view)
        self.app.add_button=SimpleNamespace(set_sensitive=sink)
        self.app.bottom_title=SimpleNamespace(set_text=sink)
        self.app.player_status=SimpleNamespace(set_text=sink)
        self.app.timeline=SimpleNamespace(set_range=sink,set_value=sink,set_sensitive=sink)
        self.app.time_label=SimpleNamespace(set_text=sink)
        self.app.pause_button=SimpleNamespace(set_label=sink)

    def tearDown(self):
        self.wait(lambda:self.app.writes.idle)
        if hasattr(self.app,'source_account_tasks'):self.app.source_account_tasks.close()
        self.app.catalog_tasks.close();self.app.detail_tasks.close();self.app.writes.close()
        if self.app.player:self.app.player.close()
        self.app.library.close();self.tmp.cleanup()

    def wait(self, predicate, seconds=5):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            while GLib.MainContext.default().iteration(False):pass
            if predicate():return
            time.sleep(.01)
        self.fail('Asynchronous controller operation timed out')

    def import_file(self):
        path=Path(self.tmp.name)/'list.m3u'
        path.write_text('#EXTM3U\n#EXTINF:-1 tvg-id="one",Chaîne\nhttps://example.org/one')
        self.app.source_job('Test',{'type':'m3u','location':str(path)})
        self.wait(lambda:not self.app.busy)
        return path

    def test_async_import_and_refresh_keep_favorite(self):
        path=self.import_file()
        self.assertEqual(self.views,['live'])
        old=self.app.library.channels()[0];self.app.library.favorite(old['id'])
        path.write_text('#EXTM3U\n#EXTINF:-1 tvg-id="one",Chaîne HD\nhttps://example.org/new')
        self.app.refresh_source(self.app.library.sources()[0])
        self.wait(lambda:not self.app.busy)
        current=self.app.library.channels(view='favorites')[0]
        self.assertEqual(current['id'],old['id']);self.assertEqual(current['name'],'Chaîne HD')
        self.assertEqual(self.views[-1],'sources')
        self.assertFalse(any(error for _,error in self.messages))

    def test_failed_async_refresh_keeps_old_library_and_surfaces_error(self):
        path=self.import_file();before=self.app.library.channels()
        path.write_text('invalid playlist')
        self.app.refresh_source(self.app.library.sources()[0]);self.wait(lambda:not self.app.busy)
        self.assertEqual(self.app.library.channels(),before)
        self.assertTrue(self.messages[-1][1])
        self.assertIn('M3U',self.messages[-1][0])

    def test_untrusted_exception_does_not_expose_provider_credentials(self):
        def work():raise ValueError('https://provider/?password=secret-value')
        self.app.run_job(work,lambda _:self.fail('Failure must not call success'))
        self.wait(lambda:not self.app.busy)
        self.assertTrue(self.messages[-1][1])
        self.assertNotIn('secret-value',self.messages[-1][0])

    def test_failed_load_and_pending_resume_do_not_erase_position(self):
        source=self.app.library.import_channels('Film',[dict(name='Film',group_name='Films',url=str(ROOT/'assets/demo.mp4'),kind='movie',tvg_id='',logo='')])
        channel=self.app.library.channels(source_id=source)[0]
        self.app.library.watched(channel['id'],5)
        self.app.current=channel;self.app.position=0
        self.app.save_position()
        self.assertEqual(self.app.library.channel(channel['id'])['position'],5)
        self.app.media_loaded=True;self.app.resume_target=5
        self.app.save_position()
        self.assertEqual(self.app.library.channel(channel['id'])['position'],5)
        self.app.resume_target=None;self.app.position=7
        self.app.save_position()
        self.wait(lambda:self.app.writes.idle)
        self.assertEqual(self.app.library.channel(channel['id'])['position'],7)

    def test_real_playback_resume_stop_and_failed_retry(self):
        self.app.library.import_channels('Film',[dict(name='Film',group_name='Films',url=str(ROOT/'assets/demo.mp4'),kind='movie',tvg_id='',logo='')])
        channel=self.app.library.channels()[0];self.app.library.watched(channel['id'],5)
        self.app.player=Player(headless=True)
        self.app.play(channel)
        def resumed():
            self.app.tick()
            return self.app.media_loaded and self.app.resume_target is None and self.app.position>=4.9
        self.wait(resumed)
        self.app.stop_playback()
        self.wait(lambda:self.app.writes.idle)
        self.assertIsNone(self.app.current)
        self.assertFalse(self.app.media_loaded)

        self.assertGreaterEqual(self.app.library.channel(channel['id'])['position'],4.9)
        with self.app.library.db:
            self.app.library.db.execute('UPDATE channels SET url=? WHERE id=?',('/missing/tunplayer-test.mp4',channel['id']))
        self.app.play(channel)
        def failed():
            self.app.tick()
            return any(error for _,error in self.messages)
        self.wait(failed)
        self.app.save_position()
        self.wait(lambda:self.app.writes.idle)
        self.assertGreaterEqual(self.app.library.channel(channel['id'])['position'],4.9)
        self.assertFalse(self.app.media_loaded)

    @patch('tunplayer.app.load_series')
    def test_series_opens_episodes_then_resumes_actual_episode_video(self,load):
        config=dict(type='xtream',server='https://example.org',username='u',password='p')
        self.app.library.import_channels('Séries',[dict(name='Ma série',group_name='Séries',url='xtream-series:7',kind='series',provider_id='7',tvg_id='',logo='')],config=config)
        series=self.app.library.channels(view='series')[0]
        load.return_value=[dict(name='Ma série S01E01',group_name='Séries',url=str(ROOT/'assets/demo.mp4'),kind='episode',provider_id='42',parent_id=series['id'],season=1,episode_num=1,tvg_id='',logo='')]
        self.app.play(series)
        self.wait(lambda:not self.app.busy)
        self.assertEqual(self.views[-1],'episodes');self.assertIsNone(self.app.player)
        episode=self.app.library.episodes(series['id'])[0]
        self.app.library.watched(episode['id'],5)
        self.app.player=Player(headless=True);self.app.play(episode)
        def resumed():
            self.app.tick()
            return self.app.media_loaded and self.app.resume_target is None and self.app.position>=4.9
        self.wait(resumed)
        self.app.stop_playback()
        self.wait(lambda:self.app.writes.idle)
        self.assertGreaterEqual(self.app.library.channel(episode['id'])['position'],4.9)

    def test_view_preferences_are_saved_for_next_launch(self):
        self.app.render=lambda:None
        self.app.apply_sidebar=lambda:None;self.app.toggle_sidebar()
        self.app.change_display('list');self.app.change_density(True);self.app.change_page_size('120')
        self.wait(lambda:self.app.writes.idle)
        other=App(argparse.Namespace(data_dir=self.tmp.name,screenshot=None))
        try:
            self.assertEqual((other.display_mode,other.compact,other.page_size),('list',True,120))
            self.assertTrue(other.sidebar_collapsed)
        finally:other.catalog_tasks.close();other.detail_tasks.close();other.writes.close();other.library.close()

    @patch('tunplayer.app.load_series_catalog')
    def test_old_source_fetches_only_series_automatically_once(self,fetch):
        config=dict(type='xtream',server='https://example.org',username='u',password='p')
        live=dict(name='TV',group_name='Direct',url='https://example.org/live.ts',kind='live',tvg_id='',logo='')
        movie=dict(live,name='Film',kind='movie',url='https://example.org/movie.mp4')
        source=self.app.library.import_channels('Ancienne source',[live,movie],config=config)
        fetch.return_value=[dict(live,name='Série',kind='series',provider_id='7',url='xtream-series:7')]
        self.app.render=lambda:None;self.app.view='series'
        self.app.ensure_series_catalog();self.wait(lambda:not self.app.busy)
        self.assertEqual(fetch.call_count,1)
        self.assertEqual((self.app.library.channel_count(view='series'),self.app.library.channel_count(view='live'),self.app.library.channel_count(view='movie')),(1,1,1))
        self.assertEqual(self.app.library.sources()[0]['count'],3)
        self.assertGreater(self.app.library.sources()[0]['series_checked'],0)
        self.app.ensure_series_catalog();self.assertEqual(fetch.call_count,1)

    @patch('tunplayer.app.load_series_catalog')
    def test_series_failure_keeps_existing_catalogue_and_allows_retry(self,fetch):
        config=dict(type='xtream',server='https://example.org',username='u',password='p')
        row=dict(name='Série',group_name='Séries',url='xtream-series:7',kind='series',provider_id='7',tvg_id='',logo='')
        self.app.library.import_channels('Source',[row],config=config)
        self.app.render=lambda:None;self.app.view='series'
        fetch.side_effect=OSError('network unavailable')
        self.app.ensure_series_catalog();self.wait(lambda:not self.app.busy)
        self.assertEqual(self.app.library.channel_count(view='series'),1)
        self.assertIn('inaccessible',self.app.series_message)
        fetch.side_effect=None;fetch.return_value=[dict(row,name='Série à jour')]
        self.app.ensure_series_catalog(force=True);self.wait(lambda:not self.app.busy)
        self.assertEqual(self.app.library.channels(view='series')[0]['name'],'Série à jour')

    def test_progressive_cards_show_their_flow_wrappers_and_cancel_when_replaced(self):
        widgets=[];shown=[]
        def make(channel):
            widget=SimpleNamespace(get_parent=lambda:SimpleNamespace(show_all=lambda:shown.append(channel)))
            return widget
        self.app.card=make
        flow=SimpleNamespace(add=widgets.append)
        generation=self.app.render_generation
        self.app.build_cards(list(range(60)),None,flow,generation)
        self.assertFalse(widgets)
        self.wait(lambda:bool(widgets))
        self.assertLess(len(widgets),60);self.assertEqual(len(shown),len(widgets))
        count=len(widgets);self.app.render_generation+=1
        self.wait(lambda:self.app.paint_timer is None)
        self.assertEqual(len(widgets),count)

    @patch('tunplayer.app.Gtk.grab_get_current',return_value=None)
    def test_player_chrome_hides_and_wakes_without_hiding_during_a_seek(self,grab):
        now=[0.0];visible=[]
        self.app.player_idle=PlaybackIdle(clock=lambda:now[0])
        self.app.player_hud=SimpleNamespace(set_visible=visible.append)
        self.app.poll_player_pointer=lambda:None
        self.app.view='player';self.app.media_loaded=True
        self.app.check_player_idle();now[0]=4.99;self.app.check_player_idle()
        self.assertTrue(self.app.controls_visible)
        now[0]=5;self.app.check_player_idle();self.assertFalse(self.app.controls_visible)
        self.app.player_activity();self.assertTrue(self.app.controls_visible)
        self.app.seeking=True;now[0]=20;self.app.check_player_idle();self.assertTrue(self.app.controls_visible)
        self.app.seeking=False;now[0]=25;self.app.check_player_idle();self.assertFalse(self.app.controls_visible)
        self.app.media_loaded=False;self.app.check_player_idle();self.assertTrue(self.app.controls_visible)
        self.assertEqual(visible,[False,True,False,True])

    def test_aspect_ratio_reaches_mpv_and_is_saved_for_next_launch(self):
        self.app.player=Player(headless=True);self.app.change_aspect('4:3')
        self.assertAlmostEqual(float(self.app.player.get('video-aspect-override')),4/3,places=5)
        self.wait(lambda:self.app.writes.idle)
        other=App(argparse.Namespace(data_dir=self.tmp.name,screenshot=None))
        try:self.assertEqual(other.aspect_mode,'4:3')
        finally:other.catalog_tasks.close();other.detail_tasks.close();other.writes.close();other.library.close()

    def test_missing_native_surface_does_not_launch_a_detached_player(self):
        self.app.video=SimpleNamespace(realize=sink,get_window=lambda:None)
        with patch('tunplayer.app.Player') as engine:
            with self.assertRaises(RuntimeError):self.app.ensure_player()
            engine.assert_not_called()
        self.assertIsNone(self.app.player)

    @patch('tunplayer.app.Gtk.grab_get_current',return_value=None)
    def test_open_settings_keeps_controls_visible_and_escape_closes_menu(self,grab):
        now=[0.];opened=[True]
        self.app.player_idle=PlaybackIdle(clock=lambda:now[0]);self.app.view='player';self.app.media_loaded=True
        self.app.poll_player_pointer=lambda:None
        self.app.player_settings=SimpleNamespace(get_visible=lambda:opened[0],popdown=lambda:opened.__setitem__(0,False))
        self.app.check_player_idle();now[0]=20;self.app.check_player_idle()
        self.assertTrue(self.app.controls_visible)
        # Space and arrows belong to the menu while it is open; Escape dismisses it.
        with patch('tunplayer.app.Gdk.keyval_name',return_value='space'):
            self.assertFalse(self.app.key(None,SimpleNamespace(keyval=0)))
        with patch('tunplayer.app.Gdk.keyval_name',return_value='Escape'):
            self.assertTrue(self.app.key(None,SimpleNamespace(keyval=0)))
        self.assertFalse(opened[0])
        now[0]=25;self.app.check_player_idle();self.assertFalse(self.app.controls_visible)

    def test_browser_adapts_to_window_and_manual_reopen_preserves_preference(self):
        visible=[True];position=[1064];width=[1080];refreshes=[]
        self.app.view='player';self.app.browser_open=True;self.app.browser_width=310
        self.app.player_browser=SimpleNamespace(get_visible=lambda:visible[0],set_visible=lambda value:visible.__setitem__(0,value))
        paned=SimpleNamespace(get_position=lambda:position[0],set_position=lambda value:position.__setitem__(0,value),
            get_allocation=lambda:SimpleNamespace(width=width[0]))
        self.app.player_split=paned;self.app.refresh_player_catalog=lambda **kw:refreshes.append(kw)
        self.app.resize_player_browser(paned,paned.get_allocation())
        self.assertFalse(visible[0]);self.assertTrue(self.app.browser_open);self.assertEqual(self.app.browser_width,310)
        self.app.toggle_player_browser()
        self.assertTrue(visible[0]);self.assertTrue(self.app.browser_manual_narrow)
        width[0]=1380;self.app.resize_player_browser(paned,paned.get_allocation())
        self.assertTrue(visible[0]);self.assertFalse(self.app.browser_manual_narrow);self.assertEqual(position[0],1064)
        # Platform font metrics can impose a wider minimum than the requested pane width.
        self.app.browser_width=240;paned.get_property=lambda name:640 if name=='min-position' else 1090
        self.app.resize_player_browser(paned,paned.get_allocation());self.assertEqual(position[0],1090)
        self.app.resize_player_browser(paned,paned.get_allocation());self.assertEqual(position[0],1090)

    def test_browser_drag_width_is_persisted_and_automatic_position_changes_are_ignored(self):
        self.app.browser_open=True;self.app.browser_dragging=True
        position=[1014]
        paned=SimpleNamespace(get_allocated_width=lambda:1380,get_position=lambda:position[0],get_property=lambda _:False)
        self.app.player_browser_width_changed(paned)
        self.wait(lambda:self.app.library.setting('player_browser_width')=='360')
        self.app.browser_dragging=False;position[0]=850;self.app.player_browser_width_changed(paned)
        self.assertEqual(self.app.browser_width,360)
        other=App(argparse.Namespace(data_dir=self.tmp.name,screenshot=None))
        try:self.assertEqual(other.browser_width,360)
        finally:other.catalog_tasks.close();other.detail_tasks.close();other.writes.close();other.library.close()

    def test_keyboard_escape_layers_and_neighbor_shortcuts(self):
        self.app.view='player';self.app.fullscreen=True;self.app.browser_open=True
        opened=[True];actions=[]
        self.app.window=SimpleNamespace(get_focus=lambda:None)
        def close_settings():opened[0]=False;actions.append('settings')
        self.app.player_settings=SimpleNamespace(get_visible=lambda:opened[0],popdown=close_settings)
        def browser():self.app.browser_open=not self.app.browser_open;actions.append('browser')
        def fullscreen():self.app.fullscreen=not self.app.fullscreen;actions.append('fullscreen')
        self.app.toggle_player_browser=browser;self.app.toggle_fullscreen=fullscreen
        self.app.play_neighbor=actions.append
        event=SimpleNamespace(keyval=0,state=0)
        for _ in range(3):
            with patch('tunplayer.app.Gdk.keyval_name',return_value='Escape'):self.assertTrue(self.app.key(None,event))
        self.assertEqual(actions,['settings','browser','fullscreen'])
        for key in ('Page_Down','Page_Up','b'):
            with patch('tunplayer.app.Gdk.keyval_name',return_value=key):self.assertTrue(self.app.key(None,event))
        self.assertEqual(actions,['settings','browser','fullscreen','next','previous','browser'])
        class Entry:pass
        self.app.window.get_focus=lambda:Entry()
        with patch('tunplayer.app.Gtk.Entry',Entry),patch('tunplayer.app.Gdk.keyval_name',return_value='Page_Down'):
            self.assertFalse(self.app.key(None,event))
        self.assertEqual(len(actions),6)
        handle=SimpleNamespace();self.app.player_split=handle;self.app.window.get_focus=lambda:handle
        with patch('tunplayer.app.Gdk.keyval_name',return_value='Right'):
            self.assertFalse(self.app.key(None,event))
        self.assertEqual(len(actions),6)

    @patch('tunplayer.app.Gtk.grab_get_current',return_value=None)
    def test_resume_prompt_keeps_controls_visible_until_choice(self,grab):
        now=[0.];self.app.player_idle=PlaybackIdle(clock=lambda:now[0]);self.app.view='player';self.app.media_loaded=True
        self.app.poll_player_pointer=lambda:None;self.app.resume_prompt_open=True
        self.app.check_player_idle();now[0]=30;self.app.check_player_idle();self.assertTrue(self.app.controls_visible)
        self.app.resume_prompt_open=False;now[0]=34.9;self.app.check_player_idle();self.assertTrue(self.app.controls_visible)
        now[0]=35;self.app.check_player_idle();self.assertFalse(self.app.controls_visible)

    def test_source_account_is_imported_and_refreshed_off_the_gtk_thread(self):
        import threading
        from tunplayer.source_info import normalize_account
        main_thread=threading.get_ident();threads=[]
        config={'type':'xtream','server':'https://example.org','username':'test','password':'secret'}
        rows=[dict(name='News',group_name='Infos',url='https://example.org/live/1.ts',kind='live',tvg_id='',logo='')]
        def account(*args):
            threads.append(threading.get_ident())
            return normalize_account({'user_info':{'auth':1,'status':'Active','exp_date':'1900000000'}})
        with patch('tunplayer.app.load_source',return_value=rows),patch('tunplayer.source_ui.fetch_account',side_effect=account):
            self.app.source_job('Compte',config)
            self.wait(lambda:not self.app.busy)
            self.wait(lambda:not self.app.source_accounts_loading)
            source=self.app.library.sources()[0]
            self.assertEqual(self.app.library.source_account(source['id'])['expires_at'],1900000000)
            self.app.refresh_source(source);self.wait(lambda:not self.app.busy)
            self.wait(lambda:not self.app.source_accounts_loading)
        self.assertEqual(len(threads),2);self.assertTrue(all(t!=main_thread for t in threads))

    def test_slow_account_api_does_not_delay_source_import_or_playback(self):
        import threading
        config={'type':'xtream','server':'https://example.org','username':'test','password':'secret'}
        rows=[dict(name='News',group_name='Infos',url=str(ROOT/'assets/demo.mp4'),kind='live',tvg_id='',logo='')]
        started=threading.Event();proceed=threading.Event()
        def account(*args):
            started.set();proceed.wait(4)
            return {'checked_at':100,'expires_at':1900000000}
        try:
            with patch('tunplayer.app.load_source',return_value=rows),patch('tunplayer.source_ui.fetch_account',side_effect=account):
                self.app.source_job('Compte',config)
                self.wait(lambda:not self.app.busy,seconds=1)
                self.assertTrue(started.wait(1));self.assertFalse(proceed.is_set())
                self.assertEqual(self.views,['live'])
                self.assertEqual(len(self.app.library.channels()),1)
                self.app.ensure_player=lambda:setattr(self.app,'player',self.app.player or Player(headless=True))
                self.app.play(self.app.library.channels()[0])
                self.wait(lambda:self.app.tick() and self.app.media_loaded,seconds=2)
                self.assertFalse(proceed.is_set())
                proceed.set();self.wait(lambda:not self.app.source_accounts_loading)
        finally:proceed.set()

    def test_background_account_check_preserves_catalog_and_ignores_changed_credentials(self):
        import threading
        identity=self.app.library.import_channels('Compte',[dict(name='News',group_name='Infos',url='https://example.org/live/1.ts',kind='live',tvg_id='',logo='')],
            config={'type':'xtream','server':'https://example.org','username':'test','password':'secret'})
        started=threading.Event();proceed=threading.Event()
        def fetch(*args):
            started.set();proceed.wait(3)
            return {'expires_at':1900000000,'checked_at':100}
        try:
            with patch('tunplayer.source_ui.fetch_account',side_effect=fetch):
                self.app.refresh_source_accounts()
                self.assertTrue(started.wait(2))
                self.assertFalse(self.app.busy)
                with self.app.library.db:
                    self.app.library.db.execute('UPDATE sources SET config=? WHERE id=?',('{"type":"m3u","location":"/tmp/other.m3u"}',identity))
                proceed.set();self.wait(lambda:not self.app.source_accounts_loading)
            self.assertEqual(self.app.library.source_account(identity),{})
            self.assertEqual(len(self.app.library.channels()),1)
        finally:
            proceed.set()
            self.app.source_account_tasks.close()

    def test_playback_tick_does_not_synchronously_query_mpv_properties(self):
        self.app.player=Player(headless=True)
        self.app.player.command('loadfile',str(ROOT/'assets/demo.mp4'))
        self.wait(lambda:self.app.player.events() or float(self.app.player.cached('time-pos','0'))>.05)
        with patch.object(self.app.player,'get',side_effect=AssertionError('Blocking property request in GTK loop')):
            for _ in range(3):self.assertTrue(self.app.tick())

    def test_category_tooltip_uses_literal_text_with_ampersands(self):
        values=[];rows=[]
        # Build the tuple from the installed typelib, including GTK's INOUT x/y.
        # A four-value widget mock concealed the original binding mismatch.
        from gi.repository import Gtk
        output_names=[arg.get_name() for arg in Gtk.TreeView.get_tooltip_context.get_arguments() if int(arg.get_direction()) in (1,2)]
        output={'x':20,'y':30,'model':[['4K MAFIA & GANGSTER [EN]']],'path':[0],'iter':0}
        context=(True,*(output[name] for name in output_names))
        self.assertEqual(len(context),6)
        tree=SimpleNamespace(get_tooltip_context=lambda *a:context,set_tooltip_row=lambda tip,path:rows.append(path))
        tip=SimpleNamespace(set_text=values.append)
        self.assertTrue(self.app.category_tooltip(tree,0,0,False,tip))
        self.assertEqual(values,['4K MAFIA & GANGSTER [EN]']);self.assertEqual(rows,[[0]])
        tree.get_tooltip_context=lambda *a:(False,20,30,None,None,None)
        self.assertFalse(self.app.category_tooltip(tree,20,30,False,tip))

if __name__=='__main__':unittest.main()
