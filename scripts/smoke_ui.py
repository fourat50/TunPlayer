#!/usr/bin/env python3
"""Graphical smoke test with local artwork fixtures and no provider/network needed."""
import argparse
import ctypes as C
import ctypes.util
from pathlib import Path
import sys
import tempfile
import cairo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tunplayer.app import App, GLib, Gdk, Gtk, ROOT
from tunplayer.core import parse_m3u
from tunplayer.artwork import ArtworkCache
from tunplayer.visuals import draw_cover

def assert_embedded(app):
    """Check the configured host and actual X11 child hierarchy, not just decoding."""
    host=app.video.get_window().get_xid()
    assert app.player.get('wid')==str(host),'mpv lost the GTK host window'
    assert app.player.get('current-vo') in ('gpu','x11'),'Unexpected video output backend'
    x11=C.CDLL(C.util.find_library('X11'))
    x11.XOpenDisplay.argtypes=[C.c_char_p];x11.XOpenDisplay.restype=C.c_void_p
    x11.XQueryTree.argtypes=[C.c_void_p,C.c_ulong,C.POINTER(C.c_ulong),C.POINTER(C.c_ulong),C.POINTER(C.POINTER(C.c_ulong)),C.POINTER(C.c_uint)]
    x11.XQueryTree.restype=C.c_int
    x11.XFree.argtypes=[C.c_void_p];x11.XFree.restype=C.c_int
    x11.XCloseDisplay.argtypes=[C.c_void_p];x11.XCloseDisplay.restype=C.c_int
    display=x11.XOpenDisplay(None);assert display,'X11 display unavailable'
    children=C.POINTER(C.c_ulong)();root=C.c_ulong();parent=C.c_ulong();count=C.c_uint()
    try:
        assert x11.XQueryTree(display,host,C.byref(root),C.byref(parent),C.byref(children),C.byref(count))
        assert count.value>0,'No mpv child window inside the GTK video surface'
    finally:
        if children:x11.XFree(children)
        x11.XCloseDisplay(display)

with tempfile.TemporaryDirectory(prefix='tunplayer-ui-') as data:
    out=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/tunplayer-captures');out.mkdir(parents=True,exist_ok=True)
    app=App(argparse.Namespace(data_dir=data,screenshot=None));errors=[];fixture={}
    original_hook=sys.excepthook
    def hook(*args):errors.append(str(args[1]));original_hook(*args)
    sys.excepthook=hook
    def capture(name):
        w,h=app.window.get_size()
        Gdk.pixbuf_get_from_window(app.window.get_window(),0,0,w,h).savev(str(out/f'{name}.png'),'png',[],[])
    def artwork(name,poster=False):
        url=f'https://fixture.invalid/{name}.png'
        cache=ArtworkCache(Path(data)/'artwork-cache')
        surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,300,450 if poster else 180)
        draw_cover(cairo.Context(surface),300,surface.get_height(),name,'Fixture',poster)
        surface.write_to_png(str(cache.path_for(url)));return url
    def home():
        logo=artwork('TV')
        m3u='#EXTM3U\n'+''.join(f'#EXTINF:-1 tvg-id="test-{i}" tvg-logo="{logo}" group-title="Culture",Chaîne de test {i:03d} FHD\nhttps://example.org/{i}.m3u8\n' for i in range(125))
        rows=parse_m3u(m3u)
        for i in range(6):
            rows.append(dict(name=f'Film de test {i}',kind='movie',url=str(ROOT/'assets/demo.mp4') if i==0 else f'https://example.org/movie/{i}.mp4',group_name='Cinéma',tvg_id='',logo=artwork(f'Film{i}',True),genre='Aventure, Drame',year=2020+i,rating=6+i*.5,plot='Synopsis fictif pour vérifier la fiche détaillée.',cast='Actrice A, Acteur B',director='Réalisatrice C',duration_seconds=5400))
        rows.append(dict(name='Série de test',kind='series',url='xtream-series:7',provider_id='7',group_name='Séries',tvg_id='',logo=artwork('Serie',True),genre='Drame',year=2024,rating=8.5))
        source=app.library.import_channels('Source de test',rows)
        series=app.library.channels(view='series')[0];fixture['series']=series
        second=Path(data)/'second.mp4';second.write_bytes((ROOT/'assets/demo.mp4').read_bytes())
        episodes=app.library.store_episodes(series['id'],[
            dict(name=f'Série de test · S01E{number:02} · Épisode {number}',kind='episode',url=str(path),provider_id=str(41+number),season=1,episode_num=number,group_name='Séries',tvg_id='',logo=series['logo'])
            for number,path in [(1,ROOT/'assets/demo.mp4'),(2,second)]])
        fixture['episode'],fixture['following']=episodes
        fixture['source']=source;app.changed();app.navigate('home')
        GLib.timeout_add(500,discovery);return False
    def discovery():
        assert not app.category_panel.get_visible(),'Discover must not show categories'
        assert [section['key'] for section in app.catalog_data['sections']]==['movies','series','trends']
        capture('01-home')
        for view in ['live','movie','series','favorites','history','guide','sources','settings']:
            app.navigate(view);assert app.content.get_children(),view
        app.navigate('live');app.change_page(1);assert app.page==1
        app.change_page(1);assert app.page==2
        app.change_source(str(fixture['source']));assert app.page==0 and app.source_id==fixture['source']
        GLib.timeout_add(500,live);return False
    def live():
        assert len(app.category_store)>0,'Category menu did not load'
        app.workspace.set_position(300)
        assert app.category_width==300,'Category width did not change'
        app.toggle_sidebar();assert app.sidebar_collapsed and not app.brand_title.get_visible()
        capture('02-live');app.change_page(1)
        GLib.timeout_add(800,navigation_roundtrip);return False
    def navigation_roundtrip():
        assert app.page==1 and app.catalog_ready,'Second catalogue page did not finish'
        adjustment=app.scroll.get_vadjustment()
        adjustment.set_value(min(320,max(0,adjustment.get_upper()-adjustment.get_page_size())))
        fixture['offset']=adjustment.get_value()
        app.navigate('sources');app.navigate('live')
        GLib.timeout_add(600,restored);return False
    def restored():
        assert app.page==1,'Returning to catalogue lost the page'
        assert abs(app.scroll.get_vadjustment().get_value()-fixture['offset'])<2,'Returning lost scroll position'
        assert app.catalog_reader.lookup(app.active_catalog_request) is not None,'Catalogue cache unavailable'
        assert app.workspace.get_position()==300 and app.category_width==300,'Category width was not retained'
        capture('02b-navigation-restored');app.navigate('movie');app.advanced_open=True
        app.set_filter('min_rating',8);GLib.timeout_add(500,movies);return False
    def movies():
        capture('03-posters-and-filters');app.set_filter('min_rating',None)
        app.change_display('list');GLib.timeout_add(500,listing);return False
    def listing():
        capture('04-list');app.change_display('grid')
        app.open_details(app.library.channels(view='movie',limit=1)[0])
        GLib.timeout_add(500,details);return False
    def details():
        assert app.view=='details' and app.library.channel(app.detail_id)['cast']
        capture('05-details')
        movie=app.library.channel(app.detail_id);app.library.watched(movie['id'],10)
        def resume_choice():
            dialogs=[w for w in Gtk.Window.list_toplevels() if isinstance(w,Gtk.Dialog) and w.get_title()=='Reprendre la lecture']
            assert len(dialogs)==1 and app.resume_prompt_open
            dialog=dialogs[0];w,h=dialog.get_size()
            Gdk.pixbuf_get_from_window(dialog.get_window(),0,0,w,h).savev(str(out/'05b-resume-choice.png'),'png',[],[])
            fixture['resume_choice']=True;dialog.response(1);return False
        GLib.timeout_add(100,resume_choice);app.play(movie)
        assert fixture.get('resume_choice') and app.current['position']==0,'Start-over choice was not applied'
        app.series_id=fixture['series']['id'];app.navigate('episodes')
        GLib.timeout_add(500,episodes);return False
    def episodes():
        capture('06-series');app.play(fixture['episode']);GLib.timeout_add(2500,player);return False
    def player():
        assert app.player and app.player.get('width')=='1280','Video did not load'
        assert_embedded(app)
        assert not app.header.get_visible() and not app.bottom.get_visible(),'Player should hide global header/footer'
        assert not app.sidebar.get_visible(),'Cinema player should use the full width'
        assert app.now_playing_title.get_text()==fixture['episode']['name']
        assert app.player_kind.get_text()=='SÉRIE'
        assert app.player_browser.get_visible() and len(app.browser_store)==2
        assert app.player_next_name.get_text()==fixture['following']['name']
        assert not app.player_prev_button.get_sensitive()
        app.command('cycle','pause');app.tick()
        assert app.pause_visual and 'Reprendre' in app.pause_button.get_tooltip_text()
        app.command('cycle','pause');app.tick();assert not app.pause_visual
        app.change_aspect('4:3')
        assert abs(float(app.player.get('video-aspect-override'))-4/3)<.001
        capture('07-player')
        app.browser_dragging=True;app.player_split.set_position(app.player_split.get_allocated_width()-350-6);app.browser_dragging=False
        app.window.resize(1080,700);GLib.timeout_add(400,small_player);return False
    def small_player():
        assert not app.player_browser.get_visible() and app.browser_open,'Small player did not fold the browser'
        assert app.browser_width==350,'Automatic folding overwrote user width'
        capture('07-small-player');app.window.resize(1380,900)
        GLib.timeout_add(400,wide_player);return False
    def wide_player():
        assert app.player_browser.get_visible() and app.browser_width==350,'Wide player did not restore the browser'
        app.player_browser_root();GLib.timeout_add(400,browser_series);return False
    def browser_series():
        assert app.current['id']==fixture['episode']['id'],'Browsing interrupted playback'
        assert fixture['series']['id'] in app.browser_rows
        capture('07a-series-in-player')
        path=app.browser_store.get_path(app.browser_store.get_iter_first())
        app.player_browser_activate(app.browser_tree,path,None)
        GLib.timeout_add(400,browser_episodes);return False
    def browser_episodes():
        assert len(app.browser_store)==2 and app.current['id']==fixture['episode']['id']
        capture('07b-episodes-in-player')
        app.command('seek',2,'absolute')
        app.player_settings_button.set_active(True)
        GLib.timeout_add(350,settings_open);return False
    def settings_open():
        assert app.player_settings.get_visible(),'Playback settings menu did not open'
        app.check_player_idle();assert app.controls_visible
        app.diagnostic_expander.set_expanded(True);app.refresh_diagnostics(force=True)
        assert '1280 × 720' in app.diagnostic_label.get_text()
        fixture['video_size']=(app.video.get_allocated_width(),app.video.get_allocated_height())
        capture('07c-player-settings');app.player_settings.popdown()
        GLib.timeout_add(5500,idle_hidden);return False
    def idle_hidden():
        assert not app.controls_visible and not app.player_hud.get_visible(),'HUD did not hide after inactivity'
        assert app.video.get_allocated_height()>fixture['video_size'][1],'Hidden HUD left reserved space below video'
        capture('08-idle-player')
        app.player_activity();GLib.timeout_add(300,awake_player);return False
    def awake_player():
        assert app.controls_visible and app.player_hud.get_visible()
        assert (app.video.get_allocated_width(),app.video.get_allocated_height())==fixture['video_size'],'Video did not restore when HUD returned'
        capture('09-awake-player')
        app.player.command('seek',11.8,'absolute');GLib.timeout_add(1000,next_offer);return False
    def next_offer():
        assert app.next_episode.pending,'Next episode was not offered at EOF'
        assert (app.video.get_allocated_width(),app.video.get_allocated_height())==fixture['video_size'],'Next-episode notice resized video'
        capture('10-next-episode');app.cancel_next();assert not app.next_episode.pending
        app.play(fixture['following']);GLib.timeout_add(700,following);return False
    def following():
        assert app.current['id']==fixture['following']['id'] and app.media_loaded
        assert_embedded(app)
        capture('11-following-player');app.navigate('live');assert app.return_button.get_visible()
        app.navigate('player');app.playback_back_button.clicked()
        assert app.current is None and app.view=='episodes' and not app.next_episode.pending
        assert app.series_id==fixture['series']['id'],'Playback return lost parent series'
        assert app.sidebar.get_visible(),'Return must restore navigation'
        capture('12-back-to-episodes')
        app.stop_playback();assert app.current is None and app.view=='home'
        app.close();return False
    GLib.timeout_add(1000,home)
    def timeout():errors.append('Timeout');app.close();return False
    GLib.timeout_add_seconds(35,timeout)
    app.run(['tunplayer-ui-test'])
    app.writes.pool.shutdown(wait=True)
    if errors:raise SystemExit('\n'.join(errors))
    print(f'UI smoke test OK. Captures : {out}')
