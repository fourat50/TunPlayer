from __future__ import annotations
import argparse
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

# Embedding mpv uses X11. XWayland is supported on Wayland desktops.
if sys.platform.startswith('linux'):
    os.environ['GDK_BACKEND']='x11'
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Gio
from .core import Library, SourceError, load_source, load_series, load_series_catalog, load_vod_details, parse_xmltv, read_resource
from .player import Player
from . import __version__
from .visuals import MediaArt, icon
from .artwork import ArtworkLoader
from .jobs import LatestTask, CatalogReader, WriteQueue
from .catalog import fold
from .playback_ui import ASPECT_MODES, PlaybackIdle,browser_layout,offers_resume,escape_action
from .playback_flow import ReconnectPolicy, NextEpisodeCountdown, remote_stream
from .navigation import NavigationMemory
from .player_catalog import PlayerCatalog

ROOT = Path(__file__).resolve().parent.parent

def box(vertical=False, spacing=0, css=None):
    w = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)
    if css: w.get_style_context().add_class(css)
    return w

def label(text='', css=None, wrap=False):
    w = Gtk.Label(label=text, xalign=0)
    if css: w.get_style_context().add_class(css)
    w.set_line_wrap(wrap)
    return w

def button(text, callback, css=None, symbol=None, tooltip=None, icon_color=None):
    w = Gtk.Button()
    row=box(spacing=9); row.set_halign(Gtk.Align.CENTER)
    if symbol: row.pack_start(icon(symbol,color=icon_color or ('#17200f' if css=='primary' else '#b7c0ce')),False,False,0)
    if text: row.pack_start(label(text),False,False,0)
    w.add(row)
    if css: w.get_style_context().add_class(css)
    if tooltip: w.set_tooltip_text(tooltip)
    w.get_accessible().set_name(tooltip or text)
    w.connect('clicked', lambda _: callback())
    return w

def space():
    w = Gtk.Box(); w.set_hexpand(True); return w

def clear(container):
    for child in container.get_children(): child.destroy()

def clock(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def navigation(text, symbol, callback):
    w=Gtk.Button(); w.get_style_context().add_class('nav')
    row=box(spacing=12)
    row.pack_start(icon(symbol),False,False,0)
    row.pack_start(label(text),True,True,0)
    w.add(row); w.connect('clicked',lambda _:callback())
    w.get_accessible().set_name(text)
    return w

class App(Gtk.Application):
    def __init__(self, args):
        super().__init__(application_id='tn.tunplayer.desktop', flags=Gio.ApplicationFlags.NON_UNIQUE if args.data_dir else Gio.ApplicationFlags.FLAGS_NONE)
        self.args = args
        data = Path(args.data_dir) if args.data_dir else Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'tunplayer'
        self.library = Library(data/'library.sqlite3')
        self.view = 'home'; self.group = None; self.query = ''; self.current = None
        self.source_id = None; self.page = 0; self.closing = False
        self.filter_options={};self.view_filters={};self.view_queries={};self.sort=None
        self.display_mode=self.library.setting('display_mode','grid')
        if self.display_mode not in ('grid','list'):self.display_mode='grid'
        self.compact=self.library.setting('compact','0')=='1'
        try:self.volume=max(0,min(1,float(self.library.setting('volume','0.75'))))
        except ValueError:self.volume=.75
        try:self.page_size=int(self.library.setting('page_size','60'))
        except ValueError:self.page_size=60
        if self.page_size not in (30,60,120):self.page_size=60
        self.render_generation=0;self.series_id=None;self.season=None;self.episode_query=''
        self.artwork=None
        self.catalog_tasks=LatestTask();self.catalog_reader=CatalogReader(self.library.path)
        self.detail_tasks=LatestTask(workers=2);self.detail_id=None;self.detail_loading=False;self.detail_message=''
        self.player_catalog=PlayerCatalog(self.library.path)
        self.browser_open=self.library.setting('player_browser_open','1')=='1'
        try:self.browser_width=max(240,min(460,int(self.library.setting('player_browser_width','310'))))
        except ValueError:self.browser_width=310
        self.browser_auto_collapsed=False;self.browser_manual_narrow=False;self.browser_dragging=False
        self.browser_width_timer=None;self.browser_layout_updating=False
        self.resume_prompt_open=False;self.last_playback_error='';self.diagnostic_updated=0
        self.browser_kind='live';self.browser_source=None;self.browser_group=None;self.browser_series=None
        self.browser_page=0;self.browser_query='';self.browser_updating=False;self.browser_rows={}
        self.player_neighbors={'previous':None,'next':None}
        self.writes=WriteQueue(self.library.path,self.write_error)
        self.data_revision=0;self.catalog_data=None;self.recent_item=[]
        self.navigation=NavigationMemory();self.painted_request=None;self.catalog_ready=False
        self.catalog_restore_timer=None;self.active_catalog_request=None
        self.favorite_widgets={};self.catalog_interacted=False
        self.series_attempted=set();self.series_syncing=False;self.series_message=''
        self.sidebar_collapsed=self.library.setting('sidebar_collapsed','0')=='1'
        try:self.category_width=max(150,min(480,int(self.library.setting('category_width','195'))))
        except ValueError:self.category_width=195
        self.category_width_timer=None
        self.render_timer=None;self.paint_timer=None;self.category_query='';self.category_scope=None
        self.player = None; self.recording = None; self.busy = False; self.fullscreen = False
        self.aspect_mode=self.library.setting('aspect_ratio','auto')
        if self.aspect_mode not in ASPECT_MODES:self.aspect_mode='auto'
        self.player_idle=PlaybackIdle();self.controls_visible=True;self.idle_timer=None
        self.reconnect=ReconnectPolicy();self.next_episode=NextEpisodeCountdown()
        self.auto_reconnect=self.library.setting('auto_reconnect','1')=='1'
        self.autoplay=self.library.setting('autoplay','1')=='1'
        self.accepting_load=False;self.completed_current=False;self.eof_handled=False
        self.load_deadline=None;self.buffering_since=None;self.duration_saved=False;self.user_paused=False
        self.last_pointer=None;self.pointer_inside=False
        self.position = 0.; self.duration = 0.; self.seeking = False; self.tick_count = 0
        self.media_loaded = False; self.resume_target = None; self.resume_deadline = 0
        self.connect('activate',self.activate)

    def write_error(self,_):
        if hasattr(self,'toast_label'):self.notify('La modification n’a pas pu être enregistrée. Réessayez.',True)

    def changed(self,_=None):self.data_revision+=1

    def persist_setting(self,key,value):
        self.writes.submit(lambda library:library.set_setting(key,value),key=('setting',key))

    def mark_watched(self,identity,position=None):
        self.writes.submit(lambda library:library.watched(identity,position),self.changed,key=('watched',identity))

    def activate(self, *_):
        if hasattr(self,'window'):
            self.window.present(); return
        provider = Gtk.CssProvider(); provider.load_from_path(str(ROOT/'assets/style.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        settings = Gtk.Settings.get_default(); settings.set_property('gtk-application-prefer-dark-theme', True)
        self.window = Gtk.ApplicationWindow(application=self, title='TunPlayer — Votre télévision, autrement')
        self.window.set_default_size(1380,900); self.window.set_size_request(1080,700)
        self.window.set_icon_from_file(str(ROOT/'assets/tunplayer.svg'))
        self.window.connect('delete-event',self.close)
        self.window.connect('key-press-event',self.key)
        self.window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK|Gdk.EventMask.SCROLL_MASK)
        self.window.connect('button-press-event',self.player_activity)
        self.window.connect('scroll-event',self.player_activity)
        root = box(True); self.window.add(root)
        body = box(); root.pack_start(body,True,True,0)
        self.sidebar = box(True,4,'sidebar'); self.sidebar.set_size_request(202,-1); body.pack_start(self.sidebar,False,False,0)
        branding = box(spacing=10)
        brand_icon=box(css='brand-icon'); brand_icon.pack_start(icon('play',22,'#19240e'),False,False,0)
        branding.pack_start(brand_icon,False,False,0)
        self.brand_title=label('tunplayer','brand');branding.pack_start(self.brand_title,False,False,0)
        self.sidebar.pack_start(branding,False,False,0)
        subtitle = label('VOTRE MONDE À L’ÉCRAN','caption'); subtitle.set_margin_top(12); subtitle.set_margin_bottom(28)
        self.sidebar.pack_start(subtitle,False,False,0)
        self.sidebar_extras=[subtitle]
        section=box(spacing=4);self.space_caption=label('VOTRE ESPACE','caption')
        section.pack_start(self.space_caption,True,True,0)
        self.sidebar_toggle=button('',self.toggle_sidebar,'icon-button',symbol='back',tooltip='Réduire ou agrandir Votre espace')
        section.pack_start(self.sidebar_toggle,False,False,0);self.sidebar.pack_start(section,False,False,2)
        self.nav = {}
        for view,text,symbol in [('home','Découvrir','home'),('live','Télévision','live'),('movie','Films','movie'),('series','Séries','series'),('guide','Guide TV','guide'),('favorites','Favoris','heart'),('history','Historique','history')]:
            b = navigation(text,symbol,lambda v=view:self.navigate(v))
            self.sidebar.pack_start(b,False,False,0); self.nav[view]=b
        self.sidebar.pack_start(Gtk.Separator(),False,False,18)
        library_caption=label('BIBLIOTHÈQUE','caption');self.sidebar.pack_start(library_caption,False,False,6)
        self.sidebar_extras.append(library_caption)
        for view,text,symbol in [('sources','Mes sources','sources'),('settings','Préférences','settings')]:
            b = navigation(text,symbol,lambda v=view:self.navigate(v))
            self.sidebar.pack_start(b,False,False,0); self.nav[view]=b
        spacer = Gtk.Box(); self.sidebar.pack_start(spacer,True,True,0)
        state = box(True,10,'source-status')
        state_top=box(spacing=8);state_top.pack_start(icon('shield',16,'#c4f478'),False,False,0)
        state_top.pack_start(label('Juste vous. Et vos envies.','muted'),False,False,0)
        state.pack_start(state_top,False,False,0)
        state.pack_start(label('Votre bibliothèque privée,\ntoujours à portée de clic.','muted'),False,False,0)
        self.sidebar.pack_start(state,False,False,0)
        version = label(f'TunPlayer  /  {__version__}','muted'); version.set_margin_top(16); self.sidebar.pack_start(version,False,False,0)
        self.sidebar_extras.extend([state,version])
        right = box(True); body.pack_start(right,True,True,0)
        header = box(spacing=18,css='header'); self.header=header; right.pack_start(header,False,False,0)
        titles=box(True,5)
        self.heading = label('Découvrir','title'); titles.pack_start(self.heading,False,False,0)
        self.heading_subtitle=label('Votre prochain bon moment.','header-subtitle');titles.pack_start(self.heading_subtitle,False,False,0)
        header.pack_start(titles,False,False,0); header.pack_start(space(),True,True,0)
        self.catalog_spinner=Gtk.Spinner();self.catalog_spinner.set_tooltip_text('Chargement des contenus…')
        header.pack_start(self.catalog_spinner,False,False,0)
        self.search = Gtk.SearchEntry(); self.search.set_placeholder_text('Chaîne, film ou série…'); self.search.get_style_context().add_class('search')
        self.search.set_tooltip_text('Rechercher dans votre bibliothèque · Ctrl + K')
        self.search.connect('search-changed',self.search_changed); header.pack_start(self.search,False,False,0)
        self.add_button = button('Ajouter une source',self.add_source,'primary',symbol='plus'); header.pack_start(self.add_button,False,False,0)
        self.toast_label = label('','toast'); right.pack_start(self.toast_label,False,False,0)
        self.scroll = Gtk.ScrolledWindow(); self.scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        self.scroll.connect('scroll-event',self.catalog_scroll_event)
        self.workspace=Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.workspace.set_wide_handle(True);self.workspace.get_style_context().add_class('category-split')
        right.pack_start(self.workspace,True,True,0)
        self.category_panel=box(True,14,'category-panel');self.category_panel.set_size_request(150,-1)
        self.category_panel.pack_start(label('CATÉGORIES','caption'),False,False,0)
        self.category_search=Gtk.SearchEntry();self.category_search.set_placeholder_text('Une catégorie…')
        self.category_search.set_width_chars(8)
        self.category_search.connect('search-changed',self.filter_categories)
        self.category_panel.pack_start(self.category_search,False,False,0)
        self.category_store=Gtk.ListStore(str,int,str,bool)
        self.category_filter=self.category_store.filter_new()
        self.category_filter.set_visible_func(lambda model,it,_:model[it][3] or fold(self.category_query) in model[it][2])
        self.category_tree=Gtk.TreeView(model=self.category_filter);self.category_tree.set_headers_visible(False)
        self.category_tree.get_style_context().add_class('category-list');self.category_tree.set_tooltip_column(0)
        name_renderer=Gtk.CellRendererText();name_renderer.set_property('ellipsize',3);name_renderer.set_property('ypad',10)
        name_renderer.set_property('max-width-chars',22)
        name_column=Gtk.TreeViewColumn('Catégorie',name_renderer,text=0);name_column.set_expand(True)
        self.category_tree.append_column(name_column)
        count_renderer=Gtk.CellRendererText();count_renderer.set_property('xalign',1.0);count_renderer.set_property('scale',.8)
        self.category_tree.append_column(Gtk.TreeViewColumn('Contenus',count_renderer,text=1))
        self.category_tree.get_selection().connect('changed',self.category_selected)
        category_scroll=Gtk.ScrolledWindow();category_scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        category_scroll.add(self.category_tree);self.category_panel.pack_start(category_scroll,True,True,0)
        self.workspace.pack1(self.category_panel,resize=False,shrink=False)
        self.content = box(True,22,'content'); self.scroll.add(self.content)
        self.workspace.pack2(self.scroll,resize=True,shrink=True)
        self.workspace.set_position(self.category_width)
        self.workspace.connect('notify::position',self.category_width_changed)
        self.playback = box(True,css='video-player'); right.pack_start(self.playback,True,True,0)
        stage=Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL);self.player_split=stage
        stage.set_wide_handle(True);stage.get_style_context().add_class('player-split')
        self.playback.pack_start(stage,True,True,0)
        self.video = Gtk.DrawingArea(); self.video.set_size_request(640,320); self.video.set_hexpand(True); self.video.set_vexpand(True)
        self.video.set_has_window(True)
        self.video.set_can_focus(True)
        stage.pack1(self.video,resize=True,shrink=False)
        self.player_browser=self.build_player_browser();stage.pack2(self.player_browser,resize=False,shrink=False)
        stage.connect('size-allocate',self.resize_player_browser)
        stage.connect('notify::position',self.player_browser_width_changed)
        stage.connect('button-press-event',self.player_browser_drag_start)
        stage.connect('button-release-event',self.player_browser_drag_end)
        self.player_hud=box(True,css='player-console');self.playback.pack_start(self.player_hud,False,False,0)
        self.player_info_stack=Gtk.Stack();self.player_info_stack.set_vhomogeneous(True);self.player_info_stack.set_hhomogeneous(False)
        self.player_hud.pack_start(self.player_info_stack,False,False,0)
        self.reconnect_bar=box(spacing=12,css='playback-notice')
        self.reconnect_label=label('','muted');self.reconnect_bar.pack_start(self.reconnect_label,True,True,0)
        self.reconnect_bar.pack_start(button('Annuler',self.cancel_reconnect,'small'),False,False,0)
        self.player_info_stack.add_named(self.reconnect_bar,'reconnect')
        self.next_bar=box(spacing=12,css='playback-notice')
        self.next_label=label('','muted');self.next_label.set_ellipsize(3);self.next_label.set_max_width_chars(65)
        self.next_bar.pack_start(self.next_label,True,True,0)
        self.next_bar.pack_start(button('Lire maintenant',self.play_next_now,'primary'),False,False,0)
        self.next_bar.pack_start(button('Annuler',self.cancel_next,'small'),False,False,0)
        self.player_info_stack.add_named(self.next_bar,'next')
        info=box(spacing=16,css='player-info');self.player_info=info
        self.playback_back_button=button('',self.back_from_playback,'player-back',symbol='back',
            tooltip='Arrêter la lecture et revenir aux chaînes, aux épisodes ou à la fiche du film')
        info.pack_start(self.playback_back_button,False,False,0)
        identity=box(True,5)
        self.now_playing_title=label('Votre prochaine séance','player-title')
        self.now_playing_title.set_ellipsize(3);self.now_playing_title.set_max_width_chars(48)
        identity.pack_start(self.now_playing_title,False,False,0)
        self.player_status = label('Prêt à lire votre contenu.','muted')
        self.player_status.get_style_context().add_class('player-status')
        self.player_status.set_ellipsize(3);self.player_status.set_max_width_chars(55)
        identity.pack_start(self.player_status,False,False,0);info.pack_start(identity,True,True,0)
        self.player_kind=label('LECTURE','player-kind');self.player_kind.set_valign(Gtk.Align.CENTER)
        info.pack_start(self.player_kind,False,False,0)
        self.player_browse_button=button('Parcourir',self.toggle_player_browser,'player-tool',symbol='guide',tooltip='Afficher ou masquer les contenus du lecteur')
        info.pack_start(self.player_browse_button,False,False,0)
        self.player_info_stack.add_named(info,'identity')
        self.player_info_stack.set_visible_child_name('identity')
        self.player_prev_button,self.player_prev_name=self.neighbor_button('previous')
        self.player_next_button,self.player_next_name=self.neighbor_button('next')
        timeline_row=box(spacing=16,css='player-timeline')
        self.timeline = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
        self.timeline.set_draw_value(False); self.timeline.set_hexpand(True)
        self.timeline.set_tooltip_text('Position de lecture · glissez pour avancer ou reculer')
        self.timeline.get_accessible().set_name('Position de lecture')
        self.timeline.connect('button-press-event',lambda *_:self.seek_begin())
        self.timeline.connect('button-release-event',self.seek_end)
        timeline_row.pack_start(self.timeline,True,True,0)
        self.time_label = label('DIRECT','player-time')
        timeline_row.pack_start(self.time_label,False,False,0)
        self.player_hud.pack_start(timeline_row,False,False,0)
        controls=Gtk.Grid();controls.set_column_homogeneous(True)
        controls.get_style_context().add_class('player-controls')
        self.player_hud.pack_start(controls,False,False,0)
        controls.attach(self.player_prev_button,0,0,1,1)
        volume=Gtk.VolumeButton();volume.set_value(self.volume)
        volume.get_style_context().add_class('player-tool')
        volume.set_tooltip_text('Volume');volume.get_accessible().set_name('Volume')
        volume.connect('value-changed',self.volume_changed)
        transport=box(spacing=8,css='player-transport')
        transport.set_halign(Gtk.Align.CENTER);transport.set_valign(Gtk.Align.CENTER)
        controls.attach(transport,1,0,1,1)
        transport.pack_start(button('10',lambda:self.command('seek',-10),'player-seek',symbol='rewind',tooltip='Reculer de 10 secondes · flèche gauche'),False,False,0)
        self.pause_button=Gtk.Button();self.pause_button.get_style_context().add_class('player-toggle')
        self.pause_image=icon('pause',24,'#111318');self.pause_button.add(self.pause_image);self.pause_visual=None
        self.pause_button.set_tooltip_text('Pause / lecture · Espace');self.pause_button.get_accessible().set_name('Pause / lecture')
        self.pause_button.connect('clicked',lambda _:self.command('cycle','pause'))
        transport.pack_start(self.pause_button,False,False,0)
        transport.pack_start(button('10',lambda:self.command('seek',10),'player-seek',symbol='forward',tooltip='Avancer de 10 secondes · flèche droite'),False,False,0)
        transport.pack_start(button('',self.back_from_playback,'player-tool',symbol='stop',
            tooltip='Arrêter la lecture et revenir aux chaînes, aux épisodes ou à la fiche du film'),False,False,0)
        tools=box(spacing=8,css='player-tools');tools.set_halign(Gtk.Align.END)
        controls.attach(self.player_next_button,2,0,1,1)
        tools.pack_start(volume,False,False,0);info.pack_start(tools,False,False,0)
        tools.pack_start(button('',self.tracks_dialog,'player-tool',symbol='subtitles',tooltip='Pistes audio et sous-titres'),False,False,0)
        self.player_settings_button=Gtk.MenuButton();self.player_settings_button.add(icon('settings',20,'#e4e7ed'))
        self.player_settings_button.get_style_context().add_class('player-tool')
        self.player_settings_button.set_tooltip_text('Réglages de lecture')
        self.player_settings_button.get_accessible().set_name('Réglages de lecture')
        self.player_settings_button.set_direction(Gtk.ArrowType.UP)
        self.player_settings=Gtk.Popover();self.player_settings.get_style_context().add_class('player-settings')
        self.player_settings.set_no_show_all(True)
        settings=box(True,14,css='player-settings-content');settings.set_size_request(260,-1)
        settings.pack_start(label('Réglages de lecture','settings-title'),False,False,0)
        image_format=box(True,7)
        image_format.pack_start(label('FORMAT D’IMAGE','caption'),False,False,0)
        self.aspect_selector=Gtk.ComboBoxText();self.aspect_selector.get_style_context().add_class('player-aspect')
        for mode,(title,*_) in ASPECT_MODES.items():self.aspect_selector.append(mode,title)
        self.aspect_selector.set_active_id(self.aspect_mode)
        self.aspect_selector.set_tooltip_text('Format de l’image · A pour parcourir les formats')
        self.aspect_selector.get_accessible().set_name('Format de l’image')
        self.aspect_selector.connect('changed',lambda w:self.change_aspect(w.get_active_id()))
        image_format.pack_start(self.aspect_selector,False,False,0);settings.pack_start(image_format,False,False,0)
        settings.pack_start(Gtk.Separator(),False,False,0)
        settings.pack_start(button('Recharger le flux',lambda:self.player_setting_action(self.retry_playback),'player-setting-action',symbol='refresh'),False,False,0)
        self.record_button = button('REC',lambda:self.player_setting_action(self.toggle_record),'record',symbol='record',icon_color='#f0a3aa',tooltip='Enregistrer le contenu en cours')
        self.record_text=self.record_button.get_child().get_children()[1]
        settings.pack_start(self.record_button,False,False,0)
        self.diagnostic_expander=Gtk.Expander(label='Diagnostic de lecture')
        self.diagnostic_label=label('','diagnostic-text',True);self.diagnostic_label.set_selectable(True)
        self.diagnostic_label.set_max_width_chars(36);self.diagnostic_expander.add(self.diagnostic_label)
        self.diagnostic_expander.connect('notify::expanded',lambda *_:self.refresh_diagnostics(force=True))
        settings.pack_start(self.diagnostic_expander,False,False,0)
        self.player_settings.add(settings);settings.show_all()
        self.player_settings_button.set_popover(self.player_settings)
        self.player_settings.connect('closed',self.player_activity)
        tools.pack_start(self.player_settings_button,False,False,0)
        self.fullscreen_button=button('',self.toggle_fullscreen,'player-tool',symbol='fullscreen',tooltip='Plein écran · F')
        self.fullscreen_image=self.fullscreen_button.get_child().get_children()[0]
        tools.pack_start(self.fullscreen_button,False,False,0)
        tools.set_valign(Gtk.Align.CENTER)
        for child in transport.get_children()+tools.get_children():child.set_valign(Gtk.Align.CENTER)
        self.bottom = box(spacing=12,css='footer'); root.pack_start(self.bottom,False,False,0)
        self.bottom.pack_start(icon('play',14,'#b9e77d'),False,False,0)
        self.bottom_title = label('Tout votre univers. Un seul lecteur.','footer-title')
        self.bottom_title.set_ellipsize(3);self.bottom_title.set_max_width_chars(60)
        self.bottom.pack_start(self.bottom_title,False,False,0)
        self.bottom.pack_start(space(),True,True,0)
        self.return_button = button('Retour au lecteur',lambda:self.navigate('player'),'small',symbol='play')
        self.bottom.pack_start(self.return_button,False,False,0)
        self.bottom.pack_start(label('M3U · XTREAM · XMLTV','caption'),False,False,0)
        self.window.show_all();self.player_info_stack.set_visible_child_name('identity')
        self.apply_sidebar(); self.toast_label.hide(); self.playback.hide(); self.return_button.hide(); self.navigate('home')
        GLib.timeout_add(500,self.tick)
        self.idle_timer=GLib.timeout_add(100,self.check_player_idle)
        if self.args.screenshot: GLib.timeout_add(900,self.screenshot)

    def notify(self, text, error=False):
        self.toast_label.set_text(text); self.toast_label.show()
        ctx = self.toast_label.get_style_context()
        ctx.add_class('error') if error else ctx.remove_class('error')
        if getattr(self,'toast_timer',None): GLib.source_remove(self.toast_timer)
        self.toast_timer = GLib.timeout_add_seconds(9,self.hide_toast)

    def hide_toast(self):
        self.toast_label.hide(); self.toast_timer = None; return False

    def navigate(self, view):
        if self.view=='player' and view!='player':self.detail_tasks.cancel()
        self.remember_catalog_position()
        self.player_idle.reset();self.set_player_chrome(True);self.last_pointer=None;self.pointer_inside=False
        if view not in ('details','episodes'):
            self.detail_tasks.cancel();self.detail_loading=False
        if view!='player':self.cancel_next()
        if self.view in ('home','live','movie','series','favorites','history'):
            self.navigation.pages[self.view]=self.page
            self.view_filters[self.view]=(self.group,self.source_id,dict(self.filter_options),self.sort)
            self.view_queries[self.view]=self.query
        elif self.view=='episodes':self.navigation.pages['episodes']=self.page
        self.view=view;self.page=self.navigation.pages.get(view,0)
        self.query=self.view_queries.get(view,'');self.search.set_text(self.query)
        self.group,self.source_id,options,self.sort=self.view_filters.get(view,(None,None,{},None))
        self.filter_options=dict(options)
        if view != 'player' and self.fullscreen:
            self.toggle_fullscreen()
        for name,b in self.nav.items():
            ctx=b.get_style_context(); ctx.add_class('active') if name==view else ctx.remove_class('active')
        self.heading.set_text({'home':'Découvrir','live':'Télévision','movie':'Films','series':'Séries','episodes':'Saisons & épisodes','details':'Fiche du contenu','guide':'Guide TV','favorites':'Vos favoris','history':'Reprendre le fil','sources':'Mes sources','settings':'Préférences','player':'À l’écran'}.get(view,view))
        self.heading_subtitle.set_text({'home':'Votre prochain bon moment.','live':'Le monde en direct, à votre rythme.',
            'movie':'Le cinéma s’invite chez vous.','series':'Une nouvelle histoire, épisode après épisode.','episodes':'Choisissez votre prochaine séance.','guide':'Choisissez la suite de votre soirée.',
            'details':'Synopsis, distribution et reprise de lecture.',
            'favorites':'Votre sélection, toujours à portée de main.','history':'Retrouvez ce que vous avez aimé.',
            'sources':'Toutes vos playlists au même endroit.','settings':'Un espace à votre image.',
            'player':'Installez-vous. Profitez du moment.'}.get(view,''))
        self.playback.set_visible(view=='player'); self.scroll.set_visible(view!='player')
        self.workspace.set_visible(view!='player')
        if hasattr(self,'header'):self.header.set_visible(view!='player' and not self.fullscreen)
        if hasattr(self,'bottom'):self.bottom.set_visible(view!='player' and not self.fullscreen)
        if hasattr(self,'sidebar'):self.sidebar.set_visible(view!='player' and not self.fullscreen)
        if view!='player' and hasattr(self,'player_settings'):self.player_settings.popdown()
        self.category_panel.set_visible(view in ('live','movie','series','favorites','history'))
        if view in ('live','movie','series','favorites','history') and hasattr(self.workspace,'set_position'):
            self.workspace.set_position(self.category_width)
        self.return_button.set_visible(self.current is not None and view != 'player')
        if view!='player': self.render()
        else:
            self.render_generation+=1;self.catalog_tasks.cancel()
            if self.render_timer:GLib.source_remove(self.render_timer);self.render_timer=None
            if self.paint_timer:GLib.source_remove(self.paint_timer);self.paint_timer=None
            if self.catalog_restore_timer:GLib.source_remove(self.catalog_restore_timer);self.catalog_restore_timer=None
            if self.artwork:self.artwork.retire()
            self.catalog_spinner.stop();self.catalog_spinner.hide()
            self.refresh_player_catalog(focus=True)
        if view=='series':self.ensure_series_catalog()

    def toggle_sidebar(self):
        self.sidebar_collapsed=not self.sidebar_collapsed
        self.persist_setting('sidebar_collapsed','1' if self.sidebar_collapsed else '0');self.apply_sidebar()

    def category_width_changed(self,paned,*_):
        if self.closing or self.view not in ('live','movie','series','favorites','history'):return
        if not self.category_panel.get_visible() or not paned.get_mapped():return
        position=paned.get_position()
        if position<=0:return
        width=max(150,min(480,position))
        if width!=position:
            paned.set_position(width)
        if width==self.category_width:return
        self.category_width=width
        if self.category_width_timer:GLib.source_remove(self.category_width_timer)
        self.category_width_timer=GLib.timeout_add(250,self.save_category_width)

    def save_category_width(self):
        self.category_width_timer=None
        self.persist_setting('category_width',self.category_width)
        return False

    def apply_sidebar(self):
        collapsed=self.sidebar_collapsed;context=self.sidebar.get_style_context()
        context.add_class('compact') if collapsed else context.remove_class('compact')
        self.sidebar.set_size_request(66 if collapsed else 202,-1)
        self.brand_title.set_visible(not collapsed);self.space_caption.set_visible(not collapsed)
        for widget in self.sidebar_extras:widget.set_visible(not collapsed)
        for key,nav in self.nav.items():
            text=nav.get_child().get_children()[1];text.set_visible(not collapsed)
            nav.set_tooltip_text(nav.get_accessible().get_name() if collapsed else None)
        image=self.sidebar_toggle.get_child().get_children()[0]
        image.set_from_pixbuf(icon('arrow' if collapsed else 'back').get_pixbuf())

    def filter_categories(self, widget):
        self.category_query=widget.get_text();self.category_filter.refilter()

    def category_selected(self, selection):
        if getattr(self,'category_updating',False):return
        model,it=selection.get_selected()
        if it is not None:
            group=None if model[it][3] else model[it][0]
            if group!=self.group:self.change_group(group)

    def populate_categories(self, groups):
        self.category_updating=True
        try:
            signature=(self.view,self.source_id,tuple((g['group_name'],g['count']) for g in groups))
            if signature!=self.category_scope:
                self.category_scope=signature;self.category_store.clear()
                self.category_store.append(['Tout afficher',sum(g['count'] for g in groups),'',True])
                for group in groups:self.category_store.append([group['group_name'],group['count'],fold(group['group_name']),False])
            for row in self.category_filter:
                if (self.group is None and row[3]) or (not row[3] and row[0]==self.group):
                    self.category_tree.get_selection().select_path(row.path);break
        finally:self.category_updating=False

    def search_changed(self, widget):
        query=widget.get_text().strip()
        if query==self.query:return
        self.query=query
        self.page=0
        if self.view not in ('home','live','movie','series','favorites','history','guide'):
            self.navigate('home');self.query=query;self.search.set_text(query);self.render()
        # Gtk.SearchEntry already coalesces typing for 150 ms; do not add another delay.
        else: self.render(delay=0)

    def demos(self):
        return [{'id':f'demo-{i}','name':name,'group_name':group,'kind':'live','favorite':0,'tvg_id':'','position':0,
                 'url':str(ROOT/'assets/demo.mp4'),'demo':True}
                for i,(name,group) in enumerate([('TUN CINÉMA','Cinéma'),('HORIZON','Découverte'),('STUDIO JAZZ','Musique'),('ARENA','Sport'),('VOYAGE','Évasion'),('CULTURE +','Culture')])]

    def remember_catalog_position(self):
        if self.catalog_ready and self.painted_request is not None and hasattr(self,'scroll'):
            self.navigation.remember(self.painted_request,self.scroll.get_vadjustment().get_value())

    def catalog_scroll_event(self,*_):
        self.catalog_interacted=True
        return False

    def catalog_request(self):
        return dict(view=self.view if self.view!='home' else 'all',source_id=self.source_id,
            search=self.query,group=self.group,filters=dict(self.filter_options),sort=self.sort,
            page_size=self.page_size,page=self.page,advanced=getattr(self,'advanced_open',False),revision=self.data_revision,
            discovery=self.view=='home')

    def render(self,delay=70):
        self.remember_catalog_position();self.catalog_ready=False
        self.render_generation+=1;generation=self.render_generation
        self.catalog_tasks.cancel()
        if self.render_timer:GLib.source_remove(self.render_timer);self.render_timer=None
        if self.paint_timer:GLib.source_remove(self.paint_timer);self.paint_timer=None
        if self.catalog_restore_timer:GLib.source_remove(self.catalog_restore_timer);self.catalog_restore_timer=None
        if self.artwork:self.artwork.retire()
        if self.view not in ('home','live','movie','series','favorites','history'):
            self.catalog_spinner.stop();self.catalog_spinner.hide()
            self.favorite_widgets.clear()
            clear(self.content)
            if self.view=='sources':self.render_sources()
            elif self.view=='settings':self.render_settings()
            elif self.view=='guide':self.render_guide()
            elif self.view=='episodes':self.render_series()
            elif self.view=='details':self.render_details()
            self.content.show_all();return
        self.active_catalog_request=self.catalog_request()
        cached=self.catalog_reader.lookup(self.active_catalog_request)
        if cached is not None:
            self.paint_catalog(cached,generation);return
        if self.catalog_data is None or self.catalog_data.get('_context')!=self.view:
            clear(self.content);self.content.pack_start(label('Chargement des contenus…','muted'),False,False,0);self.content.show_all()
        self.catalog_spinner.show();self.catalog_spinner.start()
        self.render_timer=GLib.timeout_add(delay,self.request_catalog,generation)

    def request_catalog(self,generation):
        self.render_timer=None
        if self.closing or generation!=self.render_generation:return False
        request=self.active_catalog_request
        self.catalog_tasks.submit(lambda cancel:self.catalog_reader.snapshot(request,cancel),
            lambda data:self.paint_catalog(data,generation),lambda _:self.catalog_failed(generation))
        return False

    def catalog_failed(self,generation):
        if self.closing or generation!=self.render_generation:return
        self.catalog_spinner.stop();self.catalog_spinner.hide()
        self.notify('Impossible de charger les contenus. Réessayez.',True)
        if self.catalog_data is None or self.catalog_data.get('_context')!=self.view:
            clear(self.content)
            self.content.pack_start(label('Le catalogue n’a pas pu être chargé.','muted'),False,False,0)
            self.content.pack_start(button('Réessayer',self.render,'ghost',symbol='refresh'),False,False,0)
            self.content.show_all()

    def paint_catalog(self,data,generation):
        if self.closing or generation!=self.render_generation:return
        self.catalog_spinner.stop();self.catalog_spinner.hide()
        self.catalog_data=dict(data,_context=self.view);self.recent_item=data.get('recent',[])
        self.favorite_widgets.clear();self.catalog_interacted=False
        self.painted_request=dict(self.active_catalog_request,page=data['page'])
        self.scroll.get_vadjustment().set_value(0)
        if self.view=='home':self.paint_discovery(data,generation);return
        self.page=data['page'];rows=data['rows'];total=data['total'];demo=data.get('demo',False)
        clear(self.content);self.populate_categories(data['groups'])
        view=self.view if self.view!='home' else 'all'
        top=box(spacing=12)
        text='À explorer' if demo else {'live':'Vos chaînes en direct','movie':'Votre cinéma','series':'Vos séries','favorites':'Votre sélection','history':'Reprendre la suite'}.get(self.view,'Toute votre bibliothèque')
        top.pack_start(label(text,'section-title'),False,False,0);top.pack_start(label(str(total),'section-count'),False,False,0)
        top.pack_start(space(),True,True,0)
        if self.view=='series':
            refresh=button('Chargement…' if self.series_syncing else 'Actualiser les séries',lambda:self.ensure_series_catalog(force=True),'ghost',symbol='refresh')
            refresh.set_sensitive(not self.series_syncing);top.pack_start(refresh,False,False,0)
        if demo:top.pack_start(label('Démonstration · sans abonnement','section-subtitle'),False,False,0)
        self.content.pack_start(top,False,False,0)
        if not demo:self.render_filters(view)
        if rows:
            if self.display_mode=='list':
                listing=box(True,10)
                self.content.pack_start(listing,False,False,0)
                self.build_cards(rows,listing,None,generation)
            else:
                flow=Gtk.FlowBox();flow.set_selection_mode(Gtk.SelectionMode.NONE)
                flow.set_column_spacing(14 if self.compact else 18);flow.set_row_spacing(18)
                flow.set_min_children_per_line(2)
                flow.set_max_children_per_line(6 if self.compact else 5 if self.view in ('movie','series') else 4)
                flow.set_homogeneous(True)
                self.content.pack_start(flow,False,False,0)
                self.build_cards(rows,None,flow,generation)
            if not demo:self.pagination(total)
        else:
            title,copy={
                'favorites':('Vos coups de cœur commencent ici.','Utilisez le cœur d’une chaîne, d’un film ou d’une série pour composer votre sélection.'),
                'history':('La suite vous attend.','Vos contenus apparaîtront ici après votre première lecture.'),
                'movie':('Préparez votre prochaine séance.','Connectez une source proposant des films ou actualisez votre source.'),
                'series':('Votre prochaine série vous attend.','Actualisez votre compte Xtream pour importer ses séries et leurs affiches.')
            }.get(self.view,('Votre écran attend ses premières histoires.','Connectez une playlist pour retrouver vos contenus.'))
            if self.query or self.group or self.source_id or any(self.filter_options.values()):
                title='Aucun résultat pour cette sélection.';copy='Modifiez vos filtres ou réinitialisez-les pour retrouver tous les contenus.'
            self.empty(title,copy)
        self.content.show_all()
        if self.view=='series' and self.series_message:
            note=label(self.series_message,'muted',True);self.content.pack_start(note,False,False,0);note.show()
        if not rows:self.catalog_finished(generation)

    def catalog_finished(self,generation):
        """Restore after GTK has laid out the completed page, then prepare one successor."""
        def restore():
            self.catalog_restore_timer=None
            if self.closing or generation!=self.render_generation:return False
            adjustment=self.scroll.get_vadjustment()
            maximum=max(adjustment.get_lower(),adjustment.get_upper()-adjustment.get_page_size())
            desired=self.navigation.position(self.painted_request)
            if desired>0 and not self.catalog_interacted:adjustment.set_value(min(maximum,desired))
            self.catalog_ready=True
            request=CatalogReader.next_request(self.active_catalog_request,self.catalog_data)
            if request and self.catalog_reader.lookup(request) is None:
                self.catalog_tasks.submit(lambda cancel:self.catalog_reader.snapshot(request,cancel),lambda _:None,lambda _:None)
            return False
        self.catalog_restore_timer=GLib.idle_add(restore)

    def build_cards(self,rows,listing,flow,generation,targets=None):
        position=0
        def append():
            nonlocal position
            if self.closing or generation!=self.render_generation:self.paint_timer=None;return False
            start=time.monotonic();count=0
            while position<len(rows) and count<4 and time.monotonic()-start<.004:
                channel=rows[position];target=targets[position] if targets is not None else None
                position+=1;count+=1
                widget=self.list_card(channel) if listing is not None and targets is None else self.card(channel)
                if targets is not None:
                    widget.set_size_request(170,-1);target.pack_start(widget,False,False,0);widget.show_all()
                elif listing is not None:
                    listing.pack_start(widget,False,False,0);widget.show_all()
                else:
                    flow.add(widget);widget.get_parent().show_all()
            if position>=len(rows):
                self.paint_timer=None;self.catalog_finished(generation);return False
            return True
        self.paint_timer=GLib.timeout_add(8,append,priority=GLib.PRIORITY_DEFAULT_IDLE)

    def combo(self, choices, selected, callback, tooltip=None):
        widget=Gtk.ComboBoxText()
        if str(selected) not in {str(identity) for identity,_ in choices}:
            choices=[*choices,(str(selected),str(selected)+' · actif')]
        for identity,title in choices:widget.append(str(identity),str(title))
        widget.set_active_id(str(selected))
        cells=widget.get_cells()
        if cells:
            cells[0].set_property('ellipsize',3);cells[0].set_property('max-width-chars',24)
        if tooltip:widget.set_tooltip_text(tooltip)
        widget.connect('changed',lambda w:callback(w.get_active_id()))
        return widget

    def render_filters(self, view):
        panel=box(True,12,'filters');top=box(spacing=10)
        sources=[('all','Toutes les sources')]+[(s['id'],s['name']) for s in self.catalog_data['sources']]
        top.pack_start(self.combo(sources,self.source_id if self.source_id is not None else 'all',self.change_source),True,True,0)
        sorts=[('name','Titre A–Z'),('name_desc','Titre Z–A'),('added','Ajouts récents'),('watched','Derniers regardés')]
        if view!='live':sorts.extend([('rating','Mieux notés'),('year','Année décroissante')])
        top.pack_start(self.combo(sorts,self.sort or ('watched' if view=='history' else 'name'),self.change_sort),False,False,0)
        top.pack_start(button('',self.reset_filters,'icon-button',symbol='refresh',tooltip='Réinitialiser les filtres et la recherche'),False,False,0)
        panel.pack_start(top,False,False,0)
        display=box(spacing=10)
        if view in ('all','favorites','history'):
            display.pack_start(self.combo([('all','Tous les contenus'),('live','Direct'),('movie','Films'),('series','Séries')],self.filter_options.get('kind') or 'all',lambda value:self.set_filter('kind',None if value=='all' else value)),False,False,0)
        display.pack_start(space(),True,True,0)
        for mode,title,symbol in [('grid','Grille','grid'),('list','Liste','list')]:
            b=button('',lambda m=mode:self.change_display(m),'view-toggle',symbol=symbol,tooltip=title)
            if self.display_mode==mode:b.get_style_context().add_class('selected')
            display.pack_start(b,False,False,0)
        density=Gtk.CheckButton(label='Compact');density.set_active(self.compact);density.set_sensitive(self.display_mode=='grid')
        density.connect('toggled',lambda w:self.change_density(w.get_active()));display.pack_start(density,False,False,0)
        display.pack_start(self.combo([(30,'30 par page'),(60,'60 par page'),(120,'120 par page')],self.page_size,self.change_page_size),False,False,0)
        more=Gtk.ToggleButton(label='Plus de filtres');more.set_active(getattr(self,'advanced_open',False))
        display.pack_start(more,False,False,0);panel.pack_start(display,False,False,0)
        reveal=Gtk.Revealer();reveal.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        reveal.set_reveal_child(getattr(self,'advanced_open',False))
        more.connect('toggled',lambda w:self.reveal_filters(w.get_active(),reveal))
        extra=box(True,14);grid=Gtk.Grid();grid.set_column_spacing(14);grid.set_row_spacing(12);grid.set_column_homogeneous(True)
        facets=self.catalog_data.get('facets') or dict(genre=[],year=[],language=[],quality=[])
        fields=[('genre','Genre','Tous les genres',facets['genre']),('year','Année','Toutes les années',list(reversed(facets['year']))),
                ('language','Langue','Toutes les langues',facets['language']),('quality','Qualité','Toutes les qualités',facets['quality']),
                ('min_rating','Note minimale','Toutes les notes',[6,7,8,9])]
        for index,(field,title,empty,values) in enumerate(fields):
            col=box(True,6);col.pack_start(label(title,'caption'),False,False,0)
            choices=[('all',empty)]+[(str(value),f'{value} / 10 et plus' if field=='min_rating' else str(value).upper() if field=='language' else str(value)) for value in values]
            control=self.combo(choices,self.filter_options.get(field) or 'all',lambda value,k=field:self.set_filter(k,None if value=='all' else int(value) if k in ('year','min_rating') else value))
            if field!='min_rating' and not values and not self.filter_options.get(field):
                control.set_sensitive(False);control.set_tooltip_text('Cette métadonnée n’est pas fournie par vos sources.')
            col.pack_start(control,False,False,0);grid.attach(col,index%3,index//3,1,1)
        extra.pack_start(grid,False,False,0);checks=box(spacing=18)
        for key,title in [('favorites','Favoris uniquement'),('unwatched','Jamais regardés'),('has_artwork','Avec un visuel fourni')]:
            control=Gtk.CheckButton(label=title);control.set_active(bool(self.filter_options.get(key)))
            if key=='favorites' and view=='favorites':control.set_active(True);control.set_sensitive(False)
            control.connect('toggled',lambda w,k=key:self.set_filter(k,w.get_active()));checks.pack_start(control,False,False,0)
        extra.pack_start(checks,False,False,0)
        extra.pack_start(label('Années, notes, genres et qualités : selon les données de votre fournisseur.','section-subtitle'),False,False,0)
        reveal.add(extra);panel.pack_start(reveal,False,False,0);self.content.pack_start(panel,False,False,0)
        active=[]
        for key,value in self.filter_options.items():
            if value:active.append({'favorites':'Favoris','unwatched':'Jamais regardés','has_artwork':'Avec visuel',
                'min_rating':f'Note ≥ {value}', 'year':f'Année {value}', 'quality':f'Qualité {value}',
                'language':f'Langue {str(value).upper()}'}.get(key,str(value)))
        if active:
            summary=label('Filtres actifs  ·  '+'  ·  '.join(active),'active-filters',True)
            summary.set_max_width_chars(95);self.content.pack_start(summary,False,False,0)

    def reveal_filters(self, active, reveal):
        self.advanced_open=active;reveal.set_reveal_child(active)
        if active and not (self.catalog_data or {}).get('facets'):self.render()
    def set_filter(self, key, value):
        if value is None or value is False:self.filter_options.pop(key,None)
        else:self.filter_options[key]=value
        self.page=0;self.render()
    def change_sort(self, value):self.sort=value;self.page=0;self.render()
    def change_display(self, mode):
        self.display_mode=mode;self.persist_setting('display_mode',mode);self.render()
    def change_density(self, compact):
        self.compact=compact;self.persist_setting('compact','1' if compact else '0');self.render()
    def change_page_size(self, value):
        self.page_size=int(value);self.persist_setting('page_size',self.page_size);self.page=0;self.render()
    def reset_filters(self):
        self.group=None;self.source_id=None;self.filter_options={};self.sort=None;self.page=0;self.query=''
        self.search.set_text('');self.render()

    def pagination(self, total):
        if total <= self.page_size: return
        controls=box(spacing=12,css='pagination')
        previous=button('Précédent',lambda:self.change_page(-1),'ghost',symbol='back')
        previous.set_sensitive(self.page>0); controls.pack_start(previous,False,False,0)
        start=self.page*self.page_size+1; end=min(total,start+self.page_size-1)
        controls.pack_start(label(f'{start}–{end} sur {total}  ·  Page {self.page+1} / {math.ceil(total/self.page_size)}','muted'),True,True,0)
        next_button=button('Suivant',lambda:self.change_page(1),'ghost',symbol='arrow')
        next_button.set_sensitive(end<total); controls.pack_start(next_button,False,False,0)
        self.content.pack_start(controls,False,False,0)

    def change_page(self, delta):
        self.page=max(0,self.page+delta); self.render()
        self.scroll.get_vadjustment().set_value(0)

    def change_group(self, group):
        self.group=group; self.page=0; self.render()

    def change_source(self, source_id):
        self.source_id=int(source_id) if source_id and source_id!='all' else None
        self.group=None; self.page=0; self.render()

    def paint_discovery(self,data,generation):
        clear(self.content);rows=[];targets=[]
        for section in data['sections']:
            heading=box(spacing=10)
            heading.pack_start(label(section['title'],'section-title'),False,False,0)
            heading.pack_start(space(),True,True,0)
            if section['view']:
                heading.pack_start(button('Tout voir',lambda v=section['view'],s=section['sort']:self.open_discovery_section(v,s),'small',symbol='arrow'),False,False,0)
            rail=Gtk.ScrolledWindow();rail.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.NEVER)
            rail.set_propagate_natural_height(True)
            items=box(spacing=18);rail.add(items)
            for direction,symbol,title in [(-1,'back','Précédent'),(1,'arrow','Suivant')]:
                move=button('',lambda d=direction,r=rail:self.move_rail(r,d),'icon-button',symbol=symbol,tooltip=title+' · '+section['title'])
                def update(adjust,b=move,d=direction):
                    low=adjust.get_lower();high=max(low,adjust.get_upper()-adjust.get_page_size())
                    b.set_sensitive(adjust.get_value()>low+.5 if d<0 else adjust.get_value()<high-.5)
                rail.get_hadjustment().connect('changed',update);rail.get_hadjustment().connect('value-changed',update)
                update(rail.get_hadjustment());heading.pack_start(move,False,False,0)
            self.content.pack_start(heading,False,False,0)
            if section['key']=='trends':
                caption='Les mieux notés de vos sources' if any(item.get('rating') for item in section['rows']) else 'Sélection récente · notes non fournies par la source'
                self.content.pack_start(label(caption,'section-subtitle'),False,False,0)
            elif section['rows'] and not any(item.get('added') for item in section['rows']):
                caption='Selon leur arrivée dans votre bibliothèque' if any(item.get('imported_at') for item in section['rows']) else 'Dates d’ajout indisponibles · actualisez la source'
                self.content.pack_start(label(caption,'section-subtitle'),False,False,0)
            if section['rows']:
                rail.set_min_content_height(300 if self.compact else 360)
                self.content.pack_start(rail,False,False,0)
                rows.extend(section['rows']);targets.extend([items]*len(section['rows']))
            else:
                text='Aucun résultat pour cette recherche.' if self.query else 'Les contenus apparaîtront ici après la connexion ou l’actualisation de vos sources.'
                note=label(text,'muted',True);note.set_margin_bottom(18);self.content.pack_start(note,False,False,0)
        if rows:self.build_cards(rows,None,None,generation,targets=targets)
        else:self.catalog_finished(generation)
        self.content.show_all()

    def move_rail(self,rail,direction):
        adjustment=rail.get_hadjustment()
        value=adjustment.get_value()+direction*max(190,adjustment.get_page_size()*.8)
        high=max(adjustment.get_lower(),adjustment.get_upper()-adjustment.get_page_size())
        adjustment.set_value(max(adjustment.get_lower(),min(high,value)))

    def open_discovery_section(self,view,sort):
        query=self.query;self.navigate(view)
        self.group=None;self.source_id=None;self.filter_options={};self.sort=sort
        self.query=query;self.search.set_text(query);self.page=0;self.render()

    def media_art(self, channel, compact=False, width=None, height=None):
        art=MediaArt(channel['name'],channel['group_name'],'logo' if channel['kind']=='live' else 'poster',compact)
        art.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        def clicked(widget,event):
            if event.button==1:self.open_media(channel);return True
            return False
        art.connect('button-press-event',clicked)
        art.set_tooltip_text('Ouvrir la fiche' if channel['kind'] in ('movie','series') else self.content_action(channel))
        if width is not None:art.set_size_request(width,height)
        url=channel.get('logo') or ''
        if url.startswith(('https://','http://')):
            if self.artwork is None:
                directory=self.library.path.parent/'artwork-cache' if self.args.data_dir else Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))/'tunplayer'/'artwork'
                self.artwork=ArtworkLoader(directory)
            generation=self.render_generation
            def ready(pixbuf):
                if not self.closing and generation==self.render_generation:art.set_pixbuf(pixbuf)
            self.artwork.request(url,ready)
        return art

    def favorite_button(self, channel):
        b=button('',lambda:self.toggle_favorite(channel),'favorite',symbol='heart',
            tooltip='Retirer des favoris' if channel['favorite'] else 'Ajouter aux favoris',
            icon_color='#17200f' if channel['favorite'] else '#e2e8ef')
        if channel['favorite']:b.get_style_context().add_class('selected')
        self.favorite_widgets.setdefault(channel['id'],[]).append((b,channel))
        return b

    def content_metadata(self, channel):
        values=[]
        if channel.get('year'):values.append(str(channel['year']))
        if channel.get('rating'):values.append(f'★ {channel["rating"]:g}/10')
        if channel.get('quality'):values.append(channel['quality'])
        if channel.get('language'):values.append(channel['language'].upper())
        return '  ·  '.join(values)

    def content_action(self, channel):
        return 'Saisons & épisodes' if channel['kind']=='series' and channel['url'].startswith('xtream-series:') else 'Regarder'

    def card(self, channel):
        poster=channel['kind']!='live'
        card=box(True,0,'card');card.set_size_request(144 if poster else 188 if self.compact else 210,-1)
        if poster:card.get_style_context().add_class('poster-card')
        cover=Gtk.Overlay();cover.add(self.media_art(channel,self.compact))
        overlay=box(spacing=8);overlay.set_valign(Gtk.Align.START)
        overlay.set_margin_start(8);overlay.set_margin_end(8);overlay.set_margin_top(8)
        badge_text='DÉMO' if channel.get('demo') else {'live':'● DIRECT','movie':'FILM','series':'SÉRIE','episode':'ÉPISODE'}[channel['kind']]
        badge=label(badge_text,'badge');badge.set_valign(Gtk.Align.START)
        badge.get_style_context().add_class('demo' if channel.get('demo') else 'live' if not poster else 'vod')
        overlay.pack_start(badge,False,False,0);overlay.pack_start(space(),True,True,0)
        if not channel.get('demo'):overlay.pack_start(self.favorite_button(channel),False,False,0)
        cover.add_overlay(overlay);card.pack_start(cover,False,False,0)
        body=box(True,8,'card-body')
        name=label(channel['name'],'channel-name');name.set_ellipsize(3);name.set_max_width_chars(24)
        name.set_tooltip_text(channel['name']);body.pack_start(name,False,False,4)
        info=self.content_metadata(channel)
        if info:body.pack_start(label(info,'media-metadata'),False,False,0)
        category=label(channel.get('genre') or channel['group_name'],'card-category');category.set_ellipsize(3);category.set_max_width_chars(28)
        body.pack_start(category,False,False,0)
        now=channel.get('_now')
        if now:
            title=label(now['title'],'card-description');title.set_ellipsize(3);title.set_max_width_chars(28)
            title.set_tooltip_text(now['title']);body.pack_start(title,False,False,0)
            progress=Gtk.ProgressBar();progress.set_fraction(min(1,max(0,(time.time()-now['start'])/(now['stop']-now['start']))))
            body.pack_start(progress,False,False,0)
        elif channel.get('demo'):body.pack_start(label('Extrait local · 12 secondes','card-description'),False,False,0)
        if channel.get('plot'):card.set_tooltip_text(channel['plot'][:600])
        play=button(self.content_action(channel),lambda:self.play(channel),'small',symbol='series' if channel['kind']=='series' else 'play')
        actions=box(spacing=6);actions.pack_start(play,True,True,0)
        if channel['kind'] in ('movie','series') and not channel.get('demo'):
            actions.pack_start(button('',lambda:self.open_details(channel),'icon-button',symbol='info',tooltip='Voir la fiche'),False,False,0)
        body.pack_start(actions,False,False,5);card.pack_start(body,False,False,0)
        return card

    def list_card(self, channel):
        row=box(spacing=16,css='list-card');poster=channel['kind']!='live'
        row.pack_start(self.media_art(channel,width=62 if poster else 108,height=92 if poster else 72),False,False,0)
        details=box(True,7);details.set_valign(Gtk.Align.CENTER)
        name=label(channel['name'],'channel-name');name.set_ellipsize(3);name.set_max_width_chars(50);name.set_tooltip_text(channel['name'])
        details.pack_start(name,False,False,0)
        text=self.content_metadata(channel)
        if text:details.pack_start(label(text,'media-metadata'),False,False,0)
        category=label(channel.get('genre') or channel['group_name'],'muted');category.set_ellipsize(3);category.set_max_width_chars(50)
        details.pack_start(category,False,False,0)
        if channel.get('completed'):details.pack_start(label('✓  Terminé','episode-progress'),False,False,0)
        elif channel.get('position',0)>0:
            details.pack_start(label(f'Reprise à {clock(channel["position"])}','episode-progress'),False,False,0)
        row.pack_start(details,True,True,0)
        if channel['kind'] in ('movie','series') and not channel.get('demo'):
            row.pack_start(button('',lambda:self.open_details(channel),'icon-button',symbol='info',tooltip='Voir la fiche'),False,False,0)
        if not channel.get('demo'):row.pack_start(self.favorite_button(channel),False,False,0)
        row.pack_start(button(self.content_action(channel),lambda:self.play(channel),'small',symbol='play'),False,False,0)
        return row

    def open_media(self,channel):
        if not channel.get('demo') and channel['kind'] in ('movie','series'):self.open_details(channel)
        else:self.play(channel)

    def open_details(self,channel):
        if self.view=='details' and self.detail_id==channel['id'] and self.detail_loading:return
        self.detail_tasks.cancel();self.detail_loading=False
        fresh=self.library.channel(channel['id'])
        if not fresh:self.notify('Ce contenu a été retiré de la bibliothèque.',True);return
        if fresh['kind']=='series' and fresh['url'].startswith('xtream-series:'):
            self.open_series(fresh);return
        self.detail_id=fresh['id'];self.detail_message='';self.navigate('details')
        if not fresh['details_loaded_at'] or time.time()-fresh['details_loaded_at']>86400:self.refresh_details(fresh)

    def refresh_details(self,channel):
        identity=channel['id'];config=self.library.source_config(channel['source_id'])
        self.detail_loading=True;self.detail_message='Chargement des informations…'
        def work(cancel):
            details=load_vod_details(config,channel)
            if cancel.is_set():return None
            library=Library(self.library.path,migrate=False)
            try:return library.update_details(identity,details)
            finally:library.close()
        def done(updated):
            self.detail_loading=False;self.detail_message='';self.changed()
            if updated and self.view=='details' and self.detail_id==identity:self.render()
        def failed(error):
            self.detail_loading=False
            self.detail_message=str(error) if isinstance(error,SourceError) else 'Les informations complémentaires sont indisponibles. Vous pouvez utiliser la fiche enregistrée et lancer la lecture.'
            if self.view=='details' and self.detail_id==identity:self.render()
        self.detail_tasks.submit(work,done,failed)
        if self.view=='details':self.render()

    def detail_copy(self,channel):
        col=box(True,13)
        title=label(channel['name'],'detail-title',True);title.set_max_width_chars(45)
        col.pack_start(title,False,False,0)
        metadata=self.content_metadata(channel)
        duration=channel.get('duration_seconds',0)
        if duration:
            minutes=max(1,round(duration/60));metadata+=('  ·  ' if metadata else '')+(f'{minutes//60} h {minutes%60:02} min' if minutes>=60 else f'{minutes} min')
        col.pack_start(label(metadata or channel['group_name'],'media-metadata',True),False,False,0)
        genre=channel.get('genre') or channel['group_name'];col.pack_start(label(genre,'muted',True),False,False,0)
        plot=label(channel.get('plot') or 'Synopsis non renseigné par la source.','detail-plot',True)
        plot.set_max_width_chars(75);col.pack_start(plot,False,False,0)
        for field,title in [('cast','Distribution'),('director','Réalisation')]:
            value=channel.get(field)
            if value:
                line=label(f'{title} : {value}','muted',True);line.set_max_width_chars(75)
                col.pack_start(line,False,False,0)
        return col

    def render_details(self):
        channel=self.library.channel(self.detail_id) if self.detail_id else None
        if not channel:self.empty('Ce contenu n’est plus disponible.','Choisissez un autre titre dans votre bibliothèque.');return
        destination='series' if channel['kind']=='series' else 'movie'
        back=button('Retour aux séries' if destination=='series' else 'Retour aux films',lambda:self.navigate(destination),'ghost',symbol='back')
        back.set_halign(Gtk.Align.START);self.content.pack_start(back,False,False,0)
        panel=box(spacing=26,css='media-detail')
        panel.pack_start(self.media_art(channel,width=210,height=315),False,False,0)
        info=self.detail_copy(channel);actions=box(spacing=10)
        text='Revoir' if channel.get('completed') else 'Reprendre' if channel.get('position',0)>0 else 'Regarder'
        actions.pack_start(button(text,lambda:self.play(channel),'primary',symbol='play'),False,False,0)
        actions.pack_start(self.favorite_button(channel),False,False,0)
        refresh=button('Actualiser la fiche',lambda:self.refresh_details(channel),'ghost',symbol='refresh')
        refresh.set_sensitive(not self.detail_loading);actions.pack_start(refresh,False,False,0)
        info.pack_start(actions,False,False,5)
        position=channel.get('position',0);duration=channel.get('duration_seconds',0)
        if position>0 and not channel.get('completed'):
            info.pack_start(label(f'Reprise à {clock(position)}','muted'),False,False,0)
            if duration>0:
                progress=Gtk.ProgressBar();progress.set_fraction(min(1,position/duration));info.pack_start(progress,False,False,0)
        elif channel.get('completed'):info.pack_start(label('✓  Déjà regardé','live'),False,False,0)
        panel.pack_start(info,True,True,0);self.content.pack_start(panel,False,False,0)
        if self.detail_message:self.content.pack_start(label(self.detail_message,'muted',True),False,False,0)

    def continue_series(self,series_id):
        current=self.current
        if current and current.get('parent_id')==series_id:
            if not self.completed_current:return self.library.channel(current['id'])
            following=self.library.next_episode(current['id'])
            if following:return following
        return self.library.continue_episode(series_id)

    def open_series(self, channel, force=False):
        self.detail_tasks.cancel();self.detail_loading=False
        if self.series_id!=channel['id']:
            self.episode_query='';self.navigation.pages.pop('episodes',None)
        self.series_id=channel['id'];self.season=None;self.navigate('episodes')
        if self.busy:self.notify('Actualisation en cours. Les épisodes déjà chargés restent accessibles.');return
        config=self.library.source_config(channel['source_id'])
        cached=self.library.episodes(channel['id'])
        if cached and not force and (config.get('type')!='xtream' or (channel['details_loaded_at'] and time.time()-channel['details_loaded_at']<3600)):return
        def work():
            payload=load_series(config,channel,with_details=True)
            rows=payload['episodes'] if isinstance(payload,dict) else payload
            library=Library(self.library.path,migrate=False)
            try:
                stored=library.store_episodes(channel['id'],rows)
                if isinstance(payload,dict):library.update_details(channel['id'],payload['details'])
            finally:library.close()
            return len(stored)
        def done(count):
            if self.view=='episodes' and self.series_id==channel['id']:self.render()
            self.notify(f'{count} épisodes disponibles.')
        self.run_job(work,done,'Chargement des saisons et des épisodes…')

    def render_series(self):
        series=self.library.channel(self.series_id) if self.series_id else None
        if not series:
            self.empty('Cette série n’est plus disponible.','Actualisez la source ou choisissez une autre série.');return
        panel=box(spacing=22,css='series-detail')
        panel.pack_start(self.media_art(series,width=180,height=270),False,False,0)
        details=self.detail_copy(series)
        actions=box(spacing=10)
        episode=self.continue_series(series['id'])
        if episode:
            text='Revoir' if episode.get('completed') else 'Continuer la série' if episode.get('watched') or episode.get('position') else 'Commencer la série'
            actions.pack_start(button(text,lambda:self.play(self.continue_series(series['id'])),'primary',symbol='play'),False,False,0)
        actions.pack_start(button('Actualiser',lambda:self.open_series(series,force=True),'ghost',symbol='refresh'),False,False,0)
        actions.pack_start(button('Toutes les séries',lambda:self.navigate('series'),'ghost',symbol='back'),False,False,0)
        details.pack_start(actions,False,False,0);panel.pack_start(details,True,True,0);self.content.pack_start(panel,False,False,0)
        all_episodes=self.library.episodes(series['id']);seasons=sorted({episode['season'] for episode in all_episodes})
        if seasons:
            completed=sum(1 for episode in all_episodes if episode.get('completed'))
            self.content.pack_start(label(f'{len(seasons)} saisons · {len(all_episodes)} épisodes · {completed} terminés','muted'),False,False,0)
            choices=[('all','Toutes les saisons')]+[(str(s),f'Saison {s}') for s in seasons]
            tools=box(spacing=14)
            tools.pack_start(self.combo(choices,self.season if self.season is not None else 'all',self.change_season),False,False,0)
            search=Gtk.SearchEntry();search.set_placeholder_text('Rechercher un épisode…');search.set_text(self.episode_query)
            self.episode_search=search
            search.connect('search-changed',lambda w:self.search_episodes(w.get_text(),w.get_position()))
            tools.pack_start(search,True,True,0);self.content.pack_start(tools,False,False,0)
            rows=self.library.episodes(series['id'],self.season)
            terms=self.episode_query.casefold().split()
            if terms:rows=[episode for episode in rows if all(term in episode['name'].casefold() for term in terms)]
            self.page=min(self.page,max(0,(len(rows)-1)//self.page_size))
            total=len(rows)
            for episode in rows[self.page*self.page_size:(self.page+1)*self.page_size]:
                self.content.pack_start(self.list_card(episode),False,False,0)
            self.pagination(total)
            if not rows:self.content.pack_start(label('Aucun épisode ne correspond à cette recherche.','muted'),False,False,0)
        else:self.content.pack_start(label('Les épisodes apparaîtront ici après le chargement.','muted'),False,False,0)

    def change_season(self, value):
        self.season=None if value=='all' else int(value);self.page=0;self.render()

    def search_episodes(self, query, cursor=None):
        if query==self.episode_query:return
        self.episode_query=query;self.page=0;self.render()
        self.episode_search.grab_focus()
        if cursor is not None:self.episode_search.set_position(cursor)

    def toggle_favorite(self, channel):
        identity=channel['id']
        def work(library):
            library.favorite(identity)
            return library.channel(identity)
        def done(updated):
            self.changed()
            if updated is None:return
            if self.view=='favorites' or self.filter_options.get('favorites'):
                self.render();return
            for widget,row in self.favorite_widgets.get(identity,[]):
                active=bool(updated['favorite']);row['favorite']=updated['favorite']
                context=widget.get_style_context()
                context.add_class('selected') if active else context.remove_class('selected')
                text='Retirer des favoris' if active else 'Ajouter aux favoris'
                widget.set_tooltip_text(text);widget.get_accessible().set_name(text)
                image=widget.get_child().get_children()[0]
                image.set_from_pixbuf(icon('heart',color='#17200f' if active else '#e2e8ef').get_pixbuf())
        self.writes.submit(work,done)

    def empty(self, title, text):
        panel=box(True,16,'empty-panel');panel.set_margin_top(8)
        medallion=box(css='panel-icon');medallion.set_halign(Gtk.Align.START)
        medallion.pack_start(icon('spark',26,'#c4f478'),False,False,0);panel.pack_start(medallion,False,False,0)
        panel.pack_start(label(title,'empty-title'),False,False,0)
        copy=label(text,'muted',True);copy.set_max_width_chars(65);panel.pack_start(copy,False,False,0)
        if not self.library.sources():
            b=button('Connecter ma première source',self.add_source,'primary',symbol='plus')
        elif self.view in ('home','live','movie','series','favorites','history') and (self.query or self.group or self.source_id or any(self.filter_options.values())):
            b=button('Réinitialiser les filtres',self.reset_filters,'primary',symbol='refresh')
        elif self.view=='favorites':
            b=button('Explorer mes chaînes',lambda:self.navigate('live'),'primary',symbol='heart')
        else:
            b=button('Gérer mes sources',lambda:self.navigate('sources'),'ghost',symbol='sources')
        b.set_halign(Gtk.Align.START);panel.pack_start(b,False,False,5)
        self.content.pack_start(panel,False,False,0)

    def run_job(self, work, done, message='Chargement en cours…',failed=None):
        if self.busy:
            self.notify('Une opération est déjà en cours.'); return
        self.busy=True; self.add_button.set_sensitive(False); self.notify(message)
        def worker():
            try: result=work(); GLib.idle_add(finish,result,None)
            except Exception as exc:
                # Do not expose provider URLs, which can contain passwords.
                safe = str(exc) if isinstance(exc,SourceError) else 'Impossible de lire la source. Vérifiez le chemin, la connexion et vos identifiants.'
                GLib.idle_add(finish,None,safe)
        def finish(result,error):
            if self.closing: return False
            self.busy=False; self.add_button.set_sensitive(True)
            if error:
                self.notify(error,True)
                if failed:failed(error)
            else:
                try: done(result)
                except Exception: self.notify('Import impossible. Le format des données est invalide.',True)
            return False
        threading.Thread(target=worker,daemon=True).start()

    def ensure_series_catalog(self,force=False):
        if self.series_syncing or self.busy:return
        candidates=[]
        for source in self.library.sources():
            if self.source_id is not None and source['id']!=self.source_id:continue
            if not force and (source['series_checked'] or source['id'] in self.series_attempted):continue
            config=self.library.source_config(source['id'])
            if config.get('type')=='xtream':candidates.append((source['id'],config))
        if not candidates:return
        self.series_attempted.update(identity for identity,_ in candidates)
        self.series_syncing=True;self.series_message='Récupération du catalogue des séries…'
        def work():
            loaded=0;errors=0
            for identity,config in candidates:
                try:
                    rows=load_series_catalog(config);library=Library(self.library.path,migrate=False)
                    try:
                        library.refresh_series_catalog(identity,rows)
                        loaded+=library.channel_count(view='series',source_id=identity)
                    finally:library.close()
                except Exception:errors+=1
            return loaded,errors
        def done(result):
            count,errors=result;self.series_syncing=False;self.changed()
            self.series_message=(f'{count} séries disponibles. ' if count else 'Aucune série reçue. ')
            if errors:self.series_message+='Le catalogue de certaines sources est inaccessible. Utilisez Actualiser les séries pour réessayer.'
            elif not count:self.series_message+='Vérifiez que votre compte fournisseur propose un catalogue de séries.'
            if self.view=='series':self.render()
            self.notify(self.series_message,bool(errors))
        def failed(message):
            self.series_syncing=False;self.series_message=message
            if self.view=='series':self.render()
        self.run_job(work,done,'Chargement des séries, sans réimporter les chaînes ni les films…',failed=failed)

    def source_job(self, name, config, source=None):
        self.save_position()
        def work():
            channels=load_source(config)
            # A separate connection keeps SQLite work off the GTK event loop.
            library=Library(self.library.path,migrate=False)
            try:
                if source is not None:
                    return library.refresh_source(source['id'],channels,config=config,name=name)
                identity=library.import_channels(name,channels,config=config)
                return {'total':library.channel_count(source_id=identity)}
            finally:
                library.close()
        def done(result):
            self.changed()
            # A token rotation may also change the current channel's URL.
            if self.current and not self.current.get('demo'):
                current=self.library.channel(self.current['id'])
                if current: self.current=current
            self.navigate('sources' if source is not None else 'live')
            if source is None: self.notify(f'{result["total"]} contenus importés. Bienvenue dans votre bibliothèque.')
            else: self.notify(f'Source actualisée : {result["added"]} ajoutés, {result["retained"]} conservés, {result["removed"]} retirés.')
        self.run_job(work,done,'Actualisation de votre source…' if source is not None else 'Connexion à votre source…')

    def refresh_source(self, source):
        if self.busy: self.notify('Attendez la fin de l’opération en cours.'); return
        config=self.library.source_config(source['id'])
        if not config: self.add_source(source); return
        self.source_job(source['name'],config,source)

    def choose_file(self, title, save=False):
        d=Gtk.FileChooserDialog(title=title, transient_for=self.window, action=Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN)
        d.add_buttons('Annuler',Gtk.ResponseType.CANCEL,'Choisir',Gtk.ResponseType.OK)
        if save: d.set_do_overwrite_confirmation(True)
        path=d.get_filename() if d.run()==Gtk.ResponseType.OK else None; d.destroy(); return path

    def add_source(self, source=None):
        if self.busy: self.notify('Attendez la fin de l’import en cours.'); return
        d=Gtk.Dialog(title='Connecter votre bibliothèque',transient_for=self.window,modal=True)
        d.set_default_size(540,400); d.add_buttons('Annuler',Gtk.ResponseType.CANCEL,'Importer',Gtk.ResponseType.OK)
        area=d.get_content_area(); form=box(True,14); form.set_margin_start(18); form.set_margin_end(18); area.pack_start(form,True,True,12)
        form.pack_start(label('Vos contenus, votre source.','section-title'),False,False,0)
        form.pack_start(label('M3U / M3U8 ou Xtream Codes : direct, films et séries.','muted'),False,False,0)
        name=Gtk.Entry(); name.set_placeholder_text('Nom de la source'); form.pack_start(name,False,False,0)
        mode=Gtk.ComboBoxText(); mode.append_text('Playlist M3U · URL ou fichier'); mode.append_text('Compte Xtream Codes'); mode.set_active(0); form.pack_start(mode,False,False,0)
        location=Gtk.Entry(); location.set_placeholder_text('https://…/playlist.m3u ou chemin local'); form.pack_start(location,False,False,0)
        local=button('Parcourir les fichiers…',lambda: self.fill_file(location)); form.pack_start(local,False,False,0)
        credentials=box(True,12); user=Gtk.Entry(); user.set_placeholder_text('Identifiant'); password=Gtk.Entry(); password.set_placeholder_text('Mot de passe'); password.set_visibility(False)
        credentials.pack_start(user,False,False,0); credentials.pack_start(password,False,False,0); form.pack_start(credentials,False,False,0)
        mode.connect('changed',lambda w:(credentials.set_visible(w.get_active()==1),local.set_visible(w.get_active()==0)))
        form.pack_start(label('Les adresses des flux sont conservées dans une base locale.\nUtilisez uniquement des sources auxquelles vous avez accès.','muted'),False,False,0)
        form_error=label('','error',True); form.pack_start(form_error,False,False,0)
        config=self.library.source_config(source['id']) if source else {}
        if source: name.set_text(source['name'])
        is_xtream=config.get('type')=='xtream'
        mode.set_active(1 if is_xtream else 0)
        location.set_text(config.get('server','') if is_xtream else config.get('location',''))
        user.set_text(config.get('username','')); password.set_text(config.get('password',''))
        d.show_all(); credentials.set_visible(is_xtream); local.set_visible(not is_xtream); form_error.hide()
        while d.run()==Gtk.ResponseType.OK:
            source_name=name.get_text().strip(); url=location.get_text().strip(); account=user.get_text(); secret=password.get_text(); is_xtream=mode.get_active()==1
            if source_name and url and (not is_xtream or (account and secret)): break
            form_error.set_text('Renseignez le nom et tous les champs de votre source.'); form_error.show()
        else: d.destroy(); return
        d.destroy()
        config={'type':'xtream','server':url,'username':account,'password':secret} if is_xtream else {'type':'m3u','location':url}
        self.source_job(source_name,config,source)

    def fill_file(self, entry):
        path=self.choose_file('Choisir une playlist M3U')
        if path: entry.set_text(path)

    def render_sources(self):
        self.content.pack_start(label('Une place pour toutes vos playlists.','section-title'),False,False,0)
        for source in self.library.sources():
            row=box(True,14,'panel')
            heading=box(spacing=14)
            mark=box(css='panel-icon');mark.pack_start(icon('sources',22,'#c4f478'),False,False,0)
            heading.pack_start(mark,False,False,0)
            heading.pack_start(label(source['name'],'source-name'),True,True,0)
            heading.pack_start(label(f'{source["count"]} contenus','section-count'),False,False,0)
            row.pack_start(heading,False,False,0)
            date=datetime.fromtimestamp(source['updated_at']).strftime('%d/%m/%Y à %H:%M') if source['updated_at'] else 'version précédente'
            row.pack_start(label(f'Dernière mise à jour : {date}','muted'),False,False,0)
            actions=box(spacing=10)
            actions.pack_start(button('Actualiser' if source['refreshable'] else 'Reconnecter',lambda s=source:self.refresh_source(s),'primary',symbol='refresh'),False,False,0)
            actions.pack_start(button('Modifier',lambda s=source:self.add_source(s),'ghost',symbol='edit'),False,False,0)
            actions.pack_start(space(),True,True,0)
            actions.pack_start(button('Supprimer',lambda s=source:self.delete_source(s),'danger',symbol='trash'),False,False,0)
            row.pack_start(actions,False,False,0); self.content.pack_start(row,False,False,0)
        if not self.library.sources(): self.empty('Connectez votre première source','Votre fournisseur vous remet une URL M3U ou des identifiants Xtream.')
        panel=box(True,12,'panel'); panel.pack_start(label('Une soirée qui se prépare.','section-title'),False,False,0)
        panel.pack_start(label('Ajoutez votre guide XMLTV pour voir les programmes en cours et ceux qui suivent.','muted',True),False,False,0)
        actions=box(spacing=12); actions.pack_start(button('Importer un guide',self.import_epg,symbol='guide'),False,False,0)
        actions.pack_start(button('Depuis une URL',lambda:self.import_epg(remote=True),'ghost',symbol='plus'),False,False,0)
        panel.pack_start(actions,False,False,0); self.content.pack_start(panel,False,False,0)

    def delete_source(self, source):
        if self.busy: self.notify('Attendez la fin de l’opération en cours.'); return
        d=Gtk.MessageDialog(transient_for=self.window,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=f'Supprimer « {source["name"]} » ?')
        d.format_secondary_text('Les contenus, favoris et positions associés seront retirés de cette bibliothèque.')
        response=d.run(); d.destroy()
        if response==Gtk.ResponseType.OK:
            def done(_):self.changed();self.render();self.notify('Source supprimée.')
            self.writes.submit(lambda library:library.delete_source(source['id']),done)

    def import_epg(self, remote=False):
        if remote:
            d=Gtk.Dialog(title='URL du guide XMLTV',transient_for=self.window,modal=True); d.add_buttons('Annuler',Gtk.ResponseType.CANCEL,'Importer',Gtk.ResponseType.OK)
            entry=Gtk.Entry(); entry.set_placeholder_text('https://…/guide.xml'); entry.set_size_request(430,-1); d.get_content_area().pack_start(entry,False,False,10); d.show_all()
            response=d.run(); path=entry.get_text().strip() if response==Gtk.ResponseType.OK else None; d.destroy()
            if path and not path.startswith(('http://','https://')): self.notify('Saisissez une URL HTTP ou HTTPS.',True); return
        else: path=self.choose_file('Choisir le guide XMLTV')
        if path:
            def work():
                rows=parse_xmltv(read_resource(path)); library=Library(self.library.path,migrate=False)
                try: library.import_epg(rows)
                finally: library.close()
                return len(rows)
            def done(count): self.navigate('guide'); self.notify(f'{count} programmes importés.')
            self.run_job(work,done,'Lecture du guide XMLTV…')

    def render_guide(self):
        self.content.pack_start(label(datetime.now().strftime('AUJOURD’HUI · %d / %m / %Y'),'eyebrow'),False,False,0)
        self.content.pack_start(label('En ce moment et ensuite','section-title'),False,False,0)
        count=self.library.guide_count(self.query)
        self.page=min(self.page,max(0,(count-1)//self.page_size))
        for channel in self.library.guide_channels(self.query,limit=self.page_size,offset=self.page*self.page_size):
            programmes=self.library.programmes(channel['tvg_id']) if channel['tvg_id'] else []
            if not programmes: continue
            row=box(spacing=22,css='panel'); left=box(True,8); left.set_size_request(165,-1)
            left.pack_start(label(channel['name'],'channel-name',True),False,False,0); left.pack_start(button('▶  Regarder',lambda c=channel:self.play(c),'small'),False,False,0); row.pack_start(left,False,False,0)
            events=box(True,12)
            for p in programmes[:3]:
                start=datetime.fromtimestamp(p['start']).strftime('%H:%M'); end=datetime.fromtimestamp(p['stop']).strftime('%H:%M')
                events.pack_start(label(f'{start} – {end}   {p["title"]}',wrap=True),False,False,0)
                if p['description']:
                    desc=label(p['description'][:180],'muted',True); events.pack_start(desc,False,False,0)
            row.pack_start(events,True,True,0); self.content.pack_start(row,False,False,0)
        self.pagination(count)
        if count==0:
            panel=box(True,16,'empty-panel')
            panel.pack_start(icon('guide',30,'#c4f478'),False,False,0)
            panel.pack_start(label('Votre soirée, en un coup d’œil.','empty-title'),False,False,0)
            panel.pack_start(label('Ajoutez le guide XMLTV de vos chaînes pour découvrir ce qui passe maintenant et ensuite.','muted',True),False,False,0)
            add=button('Ajouter mon guide TV',self.import_epg,'primary',symbol='plus');add.set_halign(Gtk.Align.START)
            panel.pack_start(add,False,False,0);self.content.pack_start(panel,False,False,0)

    def render_settings(self):
        self.content.pack_start(label('Faites comme chez vous.','section-title'),False,False,0)
        automation=box(True,12,'panel')
        automation.pack_start(label('Une lecture qui continue','section-title'),False,False,0)
        for title,active,callback,copy in [
            ('Reconnexion automatique',self.auto_reconnect,self.set_auto_reconnect,'Jusqu’à quatre tentatives espacées, avec conservation de la position des vidéos.'),
            ('Enchaîner les épisodes',self.autoplay,self.set_autoplay,'À la fin d’un épisode, cinq secondes pour annuler le lancement du suivant.')]:
            check=Gtk.CheckButton(label=title);check.set_active(active)
            check.connect('toggled',lambda w,callback=callback:callback(w.get_active()))
            automation.pack_start(check,False,False,0);automation.pack_start(label(copy,'muted',True),False,False,0)
        self.content.pack_start(automation,False,False,0)
        grid=Gtk.Grid();grid.set_column_spacing(18);grid.set_row_spacing(18);grid.set_column_homogeneous(True)
        sections=[
            ('Une lecture à votre rythme','audio','Choisissez le format d’image, les pistes audio et les sous-titres dans le lecteur. Après cinq secondes d’inactivité, les commandes et le curseur se masquent. Un mouvement de souris les réaffiche.'),
            ('Quelques touches suffisent','spark','Espace : pause ou lecture\nF : plein écran · B : liste des contenus\nÉchap : fermer le menu, puis la liste, puis le plein écran\nPage ↑ / ↓ : précédent / suivant hors de la liste\nA : format d’image · ← / → : déplacement de 10 s\nCtrl + K : rechercher'),
            ('Gardez les bons moments','record','Le bouton REC enregistre le contenu en cours. Choisissez le dossier à chaque enregistrement, puis cliquez sur Arrêter REC pour terminer.'),
            ('Un espace qui vous appartient','shield','Vos sources, vos favoris et votre historique restent sur cet ordinateur. Aucun compte TunPlayer n’est nécessaire. Les identifiants de vos sources sont conservés localement, sans chiffrement.')
        ]
        for index,(title,symbol,copy) in enumerate(sections):
            panel=box(True,15,'panel');panel.set_hexpand(True);panel.set_valign(Gtk.Align.FILL)
            mark=box(css='panel-icon');mark.set_halign(Gtk.Align.START)
            mark.pack_start(icon(symbol,23,'#c4f478'),False,False,0);panel.pack_start(mark,False,False,0)
            heading=label(title,'channel-name',True);panel.pack_start(heading,False,False,0)
            description=label(copy,'muted',True);description.set_max_width_chars(40)
            panel.pack_start(description,False,False,0);grid.attach(panel,index%2,index//2,1,1)
        self.content.pack_start(grid,False,False,0)
        about=box(spacing=12,css='panel')
        about.pack_start(label(f'TunPlayer {__version__}','channel-name'),False,False,0)
        about.pack_start(space(),True,True,0)
        about.pack_start(button('Gérer mes sources',lambda:self.navigate('sources'),'ghost',symbol='sources'),False,False,0)
        self.content.pack_start(about,False,False,0)

    def build_player_browser(self):
        panel=box(True,10,'player-browser');panel.set_size_request(240,-1)
        heading=box(spacing=8);heading.pack_start(label('PARCOURIR','caption'),True,True,0)
        heading.pack_start(button('',self.toggle_player_browser,'player-tool',symbol='close',tooltip='Masquer la liste'),False,False,0)
        panel.pack_start(heading,False,False,0)
        self.browser_current_name=label('','browser-current');self.browser_current_name.set_ellipsize(3)
        self.browser_current_name.set_max_width_chars(30);panel.pack_start(self.browser_current_name,False,False,0)
        self.browser_categories=Gtk.ComboBoxText()
        for cell in self.browser_categories.get_cells():
            cell.set_property('ellipsize',3);cell.set_property('max-width-chars',28)
        self.browser_categories.set_tooltip_text('Changer de catégorie sans interrompre la lecture')
        self.browser_categories.get_accessible().set_name('Catégorie dans le lecteur')
        self.browser_categories.connect('changed',self.player_browser_category_changed)
        panel.pack_start(self.browser_categories,False,False,0)
        self.browser_groups=[];self.browser_group_signature=None
        self.browser_parent=button('Toutes les séries',self.player_browser_root,'player-setting-action',symbol='back')
        self.browser_parent.set_no_show_all(True);panel.pack_start(self.browser_parent,False,False,0)
        self.browser_parent_name=label('','channel-name',True);self.browser_parent_name.set_max_width_chars(27)
        panel.pack_start(self.browser_parent_name,False,False,0)
        self.browser_search=Gtk.SearchEntry();self.browser_search.set_width_chars(10)
        self.browser_search.set_placeholder_text('Rechercher dans cette catégorie…')
        self.browser_search.set_tooltip_text('Rechercher dans le lecteur · Ctrl + K')
        self.browser_search.connect('search-changed',self.player_browser_search_changed)
        panel.pack_start(self.browser_search,False,False,0)
        self.browser_status=label('Choisissez un contenu.','muted',True);panel.pack_start(self.browser_status,False,False,0)
        self.browser_store=Gtk.ListStore(str,str,str)
        self.browser_tree=Gtk.TreeView(model=self.browser_store);self.browser_tree.set_headers_visible(False)
        self.browser_tree.set_activate_on_single_click(True);self.browser_tree.get_style_context().add_class('player-browser-list')
        name=Gtk.CellRendererText();name.set_property('ellipsize',3);name.set_property('ypad',11);name.set_property('max-width-chars',27)
        col=Gtk.TreeViewColumn('Contenu',name,text=1);col.set_expand(True);self.browser_tree.append_column(col)
        state=Gtk.CellRendererText();state.set_property('foreground','#c4f478')
        self.browser_tree.append_column(Gtk.TreeViewColumn('État',state,text=2))
        self.browser_tree.set_tooltip_column(1);self.browser_tree.connect('row-activated',self.player_browser_activate)
        self.browser_tree.get_accessible().set_name('Contenus de la catégorie, activer pour lire')
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);scroll.add(self.browser_tree)
        panel.pack_start(scroll,True,True,0)
        paging=box(spacing=8)
        self.browser_previous=button('',lambda:self.player_browser_page(-1),'player-tool',symbol='back',tooltip='Page précédente')
        self.browser_next=button('',lambda:self.player_browser_page(1),'player-tool',symbol='arrow',tooltip='Page suivante')
        self.browser_page_label=label('','muted')
        paging.pack_start(self.browser_previous,False,False,0);paging.pack_start(self.browser_page_label,True,True,0)
        paging.pack_start(self.browser_next,False,False,0);panel.pack_start(paging,False,False,0)
        panel.show_all();panel.set_no_show_all(True);panel.set_visible(self.browser_open)
        return panel

    def neighbor_button(self,direction):
        previous=direction=='previous'
        widget=Gtk.Button();widget.get_style_context().add_class('player-neighbor')
        row=box(spacing=10);text=box(True,3)
        caption=label('PRÉCÉDENT' if previous else 'SUIVANT','neighbor-caption')
        title=label('Aucun contenu','neighbor-name');title.set_ellipsize(3);title.set_max_width_chars(36)
        text.pack_start(caption,False,False,0);text.pack_start(title,False,False,0)
        if previous:row.pack_start(icon('previous',19),False,False,0)
        else:caption.set_xalign(1);title.set_xalign(1)
        row.pack_start(text,True,True,0)
        if not previous:row.pack_start(icon('next',19),False,False,0)
        widget.add(row);widget.set_sensitive(False)
        widget.set_valign(Gtk.Align.CENTER)
        widget.connect('clicked',lambda _:self.play_neighbor(direction))
        return widget,title

    def play_neighbor(self,direction):
        target=self.player_neighbors.get(direction)
        if target:self.play(target)

    def toggle_player_browser(self):
        if self.browser_open and self.browser_auto_collapsed:
            self.browser_auto_collapsed=False;self.browser_manual_narrow=True
        else:
            self.browser_open=not self.browser_open
            if self.browser_open:self.browser_manual_narrow=True
        self.player_activity()
        self.persist_setting('player_browser_open','1' if self.browser_open else '0')
        self.player_browser.set_visible(self.player_browser_visible())
        if hasattr(self,'player_split'):self.resize_player_browser(self.player_split,self.player_split.get_allocation())
        self.refresh_player_catalog(focus=True)

    def player_browser_visible(self):return self.browser_open and not self.browser_auto_collapsed

    def resize_player_browser(self,paned,allocation):
        if self.closing or self.view!='player' or allocation.width<640:return
        narrow,width=browser_layout(allocation.width,self.browser_width)
        was_visible=self.player_browser.get_visible()
        if not narrow:self.browser_manual_narrow=False
        self.browser_auto_collapsed=narrow and not self.browser_manual_narrow
        visible=self.player_browser_visible();self.player_browser.set_visible(visible)
        if visible and not self.browser_dragging:
            position=allocation.width-width-6
            if hasattr(paned,'get_property'):
                lower=paned.get_property('min-position');upper=paned.get_property('max-position')
                if upper>0:position=max(lower,min(upper,position))
            if position!=paned.get_position():
                self.browser_layout_updating=True
                try:paned.set_position(position)
                finally:self.browser_layout_updating=False
        if visible!=was_visible:self.refresh_player_catalog(focus=True)

    def player_browser_drag_start(self,paned,event):
        if event.window==paned.get_handle_window():self.browser_dragging=True;self.player_activity()
        return False

    def player_browser_drag_end(self,paned,*_):
        self.browser_dragging=False
        self.resize_player_browser(paned,paned.get_allocation())
        return False

    def player_browser_width_changed(self,paned,*_):
        if self.closing or self.browser_layout_updating or not self.player_browser_visible():return
        if not self.browser_dragging and not paned.get_property('has-focus'):return
        width=max(240,min(460,paned.get_allocated_width()-paned.get_position()-6))
        if width==self.browser_width:return
        self.browser_width=width
        if self.browser_width_timer:GLib.source_remove(self.browser_width_timer)
        self.browser_width_timer=GLib.timeout_add(250,self.save_player_browser_width)

    def save_player_browser_width(self):
        self.browser_width_timer=None;self.persist_setting('player_browser_width',self.browser_width)
        return False

    def configure_player_browser(self,channel):
        self.player_neighbors={'previous':None,'next':None}
        self.browser_kind='series' if channel['kind'] in ('series','episode') else channel['kind']
        self.browser_source=channel.get('source_id');self.browser_group=channel.get('group_name')
        self.browser_series=channel.get('parent_id') if channel['kind']=='episode' else None
        if self.browser_series:
            parent=self.library.channel(self.browser_series)
            if parent:self.browser_group=parent['group_name']
        self.browser_query='';self.browser_page=0
        if hasattr(self,'browser_search'):self.browser_search.set_text('')
        self.paint_player_neighbors()

    def paint_player_neighbors(self):
        if not hasattr(self,'player_prev_button'):return
        for direction,widget,title in [('previous',self.player_prev_button,self.player_prev_name),('next',self.player_next_button,self.player_next_name)]:
            target=self.player_neighbors.get(direction)
            text=target['name'] if target else 'Aucun contenu précédent' if direction=='previous' else 'Aucun contenu suivant'
            title.set_text(text);widget.set_sensitive(target is not None)
            description=('Lire le précédent : ' if direction=='previous' else 'Lire le suivant : ')+text if target else text
            if target:description+=' · '+('Page ↑' if direction=='previous' else 'Page ↓')
            widget.set_tooltip_text(description);widget.get_accessible().set_name(description)

    def refresh_player_catalog(self,focus=False):
        if self.closing or self.view!='player' or not self.current or not hasattr(self,'browser_store'):return
        if self.current.get('demo'):return
        identity=self.current['id']
        request=dict(current_id=identity,opened=self.player_browser_visible(),kind=self.browser_kind,source_id=self.browser_source,
            group=self.browser_group,series_id=self.browser_series,search=self.browser_query,page=self.browser_page,focus=focus,revision=self.data_revision)
        if self.player_browser_visible():
            self.browser_rows={};self.browser_store.clear();self.browser_status.set_text('Chargement…')
        def done(data):
            if self.view!='player' or not self.current or self.current['id']!=identity:return
            self.player_neighbors=data['neighbors'];self.paint_player_neighbors()
            if request['opened'] and self.player_browser_visible():self.paint_player_browser(data,focus)
        def failed(_):
            if self.view=='player':self.browser_status.set_text('Chargement impossible. Changez de catégorie ou rouvrez la liste pour réessayer.')
        self.detail_tasks.submit(lambda cancel:self.player_catalog.snapshot(request,cancel),done,failed)

    def paint_player_browser(self,data,focus=False):
        self.browser_updating=True
        try:
            signature=(self.browser_kind,self.browser_source,tuple((g['group_name'],g['count']) for g in data['groups']))
            if signature!=self.browser_group_signature:
                self.browser_group_signature=signature;self.browser_categories.remove_all()
                self.browser_groups=[None]+[g['group_name'] for g in data['groups']]
                self.browser_categories.append_text('Toutes les catégories')
                for group in data['groups']:self.browser_categories.append_text(f'{group["group_name"] or "Sans catégorie"} ({group["count"]})')
            self.browser_categories.set_active(self.browser_groups.index(self.browser_group) if self.browser_group in self.browser_groups else 0)
            parent=data['parent'];self.browser_parent.set_visible(parent is not None)
            self.browser_current_name.set_text('En cours : '+self.current['name'])
            self.browser_current_name.set_tooltip_text(self.current['name'])
            self.browser_parent_name.set_text(parent['name'] if parent else {'live':'Chaînes en direct','movie':'Films','series':'Séries'}[self.browser_kind])
            self.browser_search.set_placeholder_text('Rechercher un épisode…' if parent else 'Rechercher dans cette catégorie…')
            self.browser_store.clear();self.browser_rows={row['id']:row for row in data['rows']}
            for row in data['rows']:
                playing=self.current and row['id'] in (self.current['id'],self.current.get('parent_id'))
                state='▶' if playing else '›' if row['url'].startswith('xtream-series:') else ''
                it=self.browser_store.append([row['id'],row['name'],state])
                if playing:
                    self.browser_tree.get_selection().select_iter(it)
                    if focus:self.browser_tree.scroll_to_cell(self.browser_store.get_path(it),None,True,.5,0)
            self.browser_page=data['page'];total=data['total']
            self.browser_status.set_text(f'{total} '+('épisodes' if parent else 'contenus') if total else 'Aucun résultat dans cette sélection.')
            self.browser_page_label.set_text(f'{self.browser_page+1} / {max(1,math.ceil(total/40))}')
            self.browser_previous.set_sensitive(self.browser_page>0);self.browser_next.set_sensitive((self.browser_page+1)*40<total)
        finally:self.browser_updating=False

    def player_browser_category_changed(self,combo):
        if self.browser_updating or combo.get_active()<0:return
        self.browser_group=self.browser_groups[combo.get_active()];self.browser_series=None;self.browser_page=0
        self.browser_query='';self.browser_search.set_text('');self.player_activity();self.refresh_player_catalog()

    def player_browser_search_changed(self,entry):
        query=entry.get_text().strip()
        if self.browser_updating or query==self.browser_query:return
        self.browser_query=query;self.browser_page=0;self.player_activity();self.refresh_player_catalog()

    def player_browser_page(self,delta):
        self.browser_page=max(0,self.browser_page+delta);self.player_activity();self.refresh_player_catalog()

    def player_browser_root(self):
        self.browser_series=None;self.browser_page=0;self.browser_query='';self.browser_search.set_text('')
        self.player_activity();self.refresh_player_catalog()

    def player_browser_activate(self,tree,path,column):
        row=self.browser_rows.get(self.browser_store[path][0])
        if not row:return
        if not row['url'].startswith('xtream-series:'):self.play(row);return
        self.player_activity();self.browser_status.set_text('Chargement des épisodes…')
        config=self.library.source_config(row['source_id'])
        def work(cancel):
            library=Library(self.library.path,migrate=False)
            try:
                cached=library.db.execute('SELECT 1 FROM channels WHERE parent_id=? LIMIT 1',(row['id'],)).fetchone()
                if not cached:
                    payload=load_series(config,row,with_details=True)
                    if cancel.is_set():return
                    library.store_episodes(row['id'],payload['episodes']);library.update_details(row['id'],payload['details'])
            finally:library.close()
        def done(_):
            if self.view!='player':return
            self.browser_series=row['id'];self.browser_page=0;self.browser_query='';self.browser_search.set_text('')
            self.changed();self.refresh_player_catalog()
        def failed(_):self.browser_status.set_text('Les épisodes sont indisponibles. Sélectionnez une autre série ou réessayez.')
        self.detail_tasks.submit(work,done,failed)

    def ensure_player(self):
        if not self.player:
            self.video.realize();window=self.video.get_window()
            if window is None:raise RuntimeError('La zone vidéo intégrée n’est pas encore disponible. Réessayez la lecture.')
            if sys.platform.startswith('linux'):
                gi.require_version('GdkX11','3.0')
                from gi.repository import GdkX11
                if not isinstance(window,GdkX11.X11Window):
                    raise RuntimeError('La lecture intégrée nécessite X11 ou XWayland. Relancez TunPlayer avec son lanceur.')
                window_id=window.get_xid()
            else:
                raise RuntimeError('L’intégration vidéo native de ce système n’est pas encore disponible.')
            player=Player(window_id=window_id)
            try:
                player.set('volume',self.volume*100);player.set_aspect(self.aspect_mode)
            except RuntimeError:
                player.close();raise
            self.player=player

    def change_aspect(self,mode):
        self.player_activity()
        if mode not in ASPECT_MODES or mode==self.aspect_mode:return
        try:
            if self.player:self.player.set_aspect(mode)
        except (ValueError,RuntimeError) as error:
            self.notify(f'Format d’image indisponible : {error}',True)
            if hasattr(self,'aspect_selector'):self.aspect_selector.set_active_id(self.aspect_mode)
            return
        self.aspect_mode=mode;self.persist_setting('aspect_ratio',mode)
        if hasattr(self,'aspect_selector') and self.aspect_selector.get_active_id()!=mode:
            self.aspect_selector.set_active_id(mode)

    def cycle_aspect(self):
        modes=list(ASPECT_MODES);self.change_aspect(modes[(modes.index(self.aspect_mode)+1)%len(modes)])

    def player_activity(self,*_):
        if self.view=='player':
            self.player_idle.activity();self.set_player_chrome(True)
        return False

    def update_player_identity(self,channel):
        if not hasattr(self,'now_playing_title'):return
        self.now_playing_title.set_text(channel['name']);self.now_playing_title.set_tooltip_text(channel['name'])
        kind=channel['kind'];live=kind=='live'
        self.player_kind.set_text('● DIRECT' if live else 'SÉRIE' if kind in ('episode','series') else 'FILM')
        context=self.player_kind.get_style_context()
        context.add_class('on-air') if live else context.remove_class('on-air')
        if hasattr(self,'player_browse_button'):
            title='Épisodes' if kind=='episode' else 'Chaînes' if live else 'Séries' if kind=='series' else 'Films'
            self.player_browse_button.get_child().get_children()[1].set_text(title)
            description='Afficher ou masquer les '+title.lower()
            self.player_browse_button.set_tooltip_text(description)
            self.player_browse_button.get_accessible().set_name(description)

    def update_pause_visual(self,paused):
        if not hasattr(self,'pause_image') or self.pause_visual==paused:return
        self.pause_visual=paused
        self.pause_image.set_from_pixbuf(icon('play' if paused else 'pause',24,'#111318').get_pixbuf())
        text='Reprendre la lecture · Espace' if paused else 'Mettre en pause · Espace'
        self.pause_button.set_tooltip_text(text);self.pause_button.get_accessible().set_name(text)

    def update_record_visual(self,active):
        if not hasattr(self,'record_text'):return
        self.record_text.set_text('Stop REC' if active else 'REC')
        context=self.record_button.get_style_context()
        context.add_class('active') if active else context.remove_class('active')
        text='Terminer l’enregistrement' if active else 'Enregistrer le contenu en cours'
        self.record_button.set_tooltip_text(text);self.record_button.get_accessible().set_name(text)
        if hasattr(self,'player_settings_button'):
            context=self.player_settings_button.get_style_context()
            context.add_class('recording') if active else context.remove_class('recording')
            text='Enregistrement en cours · Réglages' if active else 'Réglages de lecture'
            self.player_settings_button.set_tooltip_text(text);self.player_settings_button.get_accessible().set_name(text)

    def player_setting_action(self,callback):
        self.player_settings.popdown();self.player_activity();callback()

    def refresh_diagnostics(self,force=False):
        if not self.player or not hasattr(self,'diagnostic_expander') or not self.diagnostic_expander.get_expanded():return
        if not self.player_settings.get_visible():return
        now=time.monotonic()
        if not force and now-self.diagnostic_updated<2:return
        self.diagnostic_updated=now
        fields=[('Vidéo',self.player.get('video-codec','—')),
            ('Audio',self.player.get('audio-codec','—')),
            ('Résolution',self.player.get('width','—')+' × '+self.player.get('height','—')),
            ('Images / seconde',self.player.get('estimated-vf-fps','—')),
            ('Tampon (secondes)',self.player.get('demuxer-cache-duration','—')),
            ('Remplissage du tampon (%)',self.player.get('cache-buffering-state','—')),
            ('Images perdues',self.player.get('frame-drop-count','0')),
            ('Sortie vidéo',self.player.get('current-vo','—'))]
        self.diagnostic_label.set_text('\n'.join(f'{name} : {value}' for name,value in fields)+
            ('\nDernière erreur : '+self.last_playback_error if self.last_playback_error else ''))

    def set_player_chrome(self,visible):
        if visible==self.controls_visible:return
        self.controls_visible=visible
        if hasattr(self,'player_hud'):self.player_hud.set_visible(visible)
        if hasattr(self,'window'):
            cursor=None if visible else Gdk.Cursor.new_for_display(self.window.get_display(),Gdk.CursorType.BLANK_CURSOR)
            windows=[self.window.get_window()]
            if hasattr(self,'video'):windows.append(self.video.get_window())
            for window in windows:
                if window:window.set_cursor(cursor)
        if self.player:
            try:self.player.set('cursor-autohide','no' if visible else 'always')
            except RuntimeError:pass

    def poll_player_pointer(self):
        # mpv owns a native child window: GTK motion events alone miss its pointer.
        if not hasattr(self,'window') or not self.window.get_window():return
        seat=self.window.get_display().get_default_seat()
        pointer=seat.get_pointer() if seat else None
        if pointer is None:return
        _,x,y=pointer.get_position();origin=self.window.get_window().get_origin();ox,oy=origin[-2:]
        width,height=self.window.get_size();inside=ox<=x<ox+width and oy<=y<oy+height
        position=(x,y)
        if inside and (position!=self.last_pointer or not self.pointer_inside):self.player_activity()
        self.last_pointer=position;self.pointer_inside=inside

    def check_player_idle(self):
        if self.closing:self.idle_timer=None;return False
        active=self.view=='player' and self.media_loaded
        if active:self.poll_player_pointer()
        settings_open=hasattr(self,'player_settings') and self.player_settings.get_visible()
        held=active and (self.seeking or self.next_episode.pending or self.buffering_since is not None or self.resume_prompt_open or settings_open or Gtk.grab_get_current() is not None)
        hidden=self.player_idle.update(active,held=held)
        self.set_player_chrome(not hidden)
        return True

    def choose_resume(self,channel):
        if not hasattr(self,'window'):return 'resume'
        self.cancel_next();self.player_activity();self.resume_prompt_open=True
        dialog=Gtk.Dialog(title='Reprendre la lecture',transient_for=self.window,modal=True)
        dialog.set_destroy_with_parent(True);dialog.set_resizable(False)
        dialog.get_style_context().add_class('resume-dialog')
        dialog.add_button('Annuler',Gtk.ResponseType.CANCEL)
        dialog.add_button('Depuis le début',1)
        dialog.add_button('Reprendre à '+clock(channel['position']),Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        content=dialog.get_content_area();content.set_spacing(12)
        title=label(channel['name'],'channel-name',True);title.set_max_width_chars(48)
        content.pack_start(title,False,False,0)
        content.pack_start(label('Vous avez déjà commencé ce contenu. Choisissez où poursuivre.','muted',True),False,False,0)
        try:
            dialog.show_all();response=dialog.run()
            return 'resume' if response==Gtk.ResponseType.ACCEPT else 'start' if response==1 else None
        finally:
            dialog.destroy();self.resume_prompt_open=False
            if not self.closing:self.player_activity()

    def play(self, channel,resume='ask'):
        if not channel:self.notify('Aucun épisode disponible. Actualisez la série.',True);return
        if self.recording:
            self.notify('Arrêtez l’enregistrement avant de changer de contenu.',True);return
        local_position=None
        if self.current and self.current['id']==channel['id']:
            if self.completed_current:local_position=0
            elif self.media_loaded:local_position=self.position
            elif self.current['kind']!='live':local_position=self.current.get('position',self.position)
        self.save_position()
        if not channel.get('demo'):
            channel=self.library.channel(channel['id'])
            if channel is None:self.notify('Ce contenu a été retiré de la source.',True);return
        if channel['kind']=='series' and channel['url'].startswith('xtream-series:'):
            self.open_series(channel);return
        if local_position is not None:channel['position']=local_position
        elif channel.get('completed'):channel['position']=0
        if resume=='start':channel['position']=0
        elif resume=='ask' and offers_resume(channel):
            choice=self.choose_resume(channel)
            if choice is None or self.closing:return
            if choice=='start':channel['position']=0
        self.cancel_next();self.reconnect.reset()
        self.current=channel;self.position=0.;self.duration=0.;self.user_paused=False
        self.last_playback_error='';self.diagnostic_updated=0
        self.configure_player_browser(channel)
        self.update_player_identity(channel);self.update_pause_visual(False)
        self.completed_current=False;self.eof_handled=False;self.duration_saved=False
        self.media_loaded=False;self.resume_target=None;self.buffering_since=None
        self.navigate('player')
        self.bottom_title.set_text(('DÉMONSTRATION LOCALE · ' if channel.get('demo') else 'À L’ÉCRAN · ')+channel['name'])
        self.player_status.set_text('Connexion…')
        self.open_current_stream()

    def open_current_stream(self):
        if not self.current or self.closing:return
        self.accepting_load=True;self.media_loaded=False;self.load_deadline=time.monotonic()+25
        try:
            self.ensure_player();self.player.events()
            self.player.command('loadfile',self.current['url'],'replace')
            self.player.set('pause','yes' if self.user_paused else 'no')
        except (RuntimeError,OSError) as error:self.handle_playback_failure(str(error))

    def retry_playback(self):
        if self.current:self.play(self.current,resume='auto')

    def handle_playback_failure(self,message):
        if not self.current or self.closing:return
        if not self.accepting_load and not self.media_loaded:return
        self.last_playback_error=message
        self.save_position()
        if self.current['kind']!='live' and not self.completed_current:
            if self.media_loaded and self.resume_target is None:self.current['position']=self.position
            elif self.position>0:self.current['position']=self.position
        self.accepting_load=False;self.media_loaded=False;self.resume_target=None;self.load_deadline=None
        self.buffering_since=None;self.cancel_next();self.player_activity()
        eligible=self.auto_reconnect and remote_stream(self.current['url']) and not self.current.get('demo')
        if eligible and self.reconnect.failure():
            self.update_playback_banners()
        else:
            self.reconnect.cancel()
            self.player_status.set_text('Lecture interrompue. Réessayez ou choisissez un autre contenu.')
            self.notify(f'Lecture indisponible : {message}',True)
            self.update_playback_banners()

    def cancel_reconnect(self):
        self.reconnect.cancel();self.accepting_load=False;self.media_loaded=False;self.load_deadline=None
        if self.player:
            try:self.player.command('stop')
            except RuntimeError:pass
        self.player_status.set_text('Reconnexion annulée. Réessayez depuis Réglages.')
        self.player_activity();self.update_playback_banners()

    def update_playback_banners(self):
        waiting=self.reconnect.pending or self.reconnect.inflight
        if waiting:
            text=f'Reconnexion {self.reconnect.attempts}/{len(self.reconnect.delays)}'
            text+=' en cours…' if self.reconnect.inflight else f' dans {self.reconnect.remaining()} s…'
            self.player_status.set_text(text)
            if hasattr(self,'reconnect_label'):self.reconnect_label.set_text(text)
        if hasattr(self,'reconnect_bar') and not hasattr(self,'player_info_stack'):
            if waiting:
                for child in self.reconnect_bar.get_children():child.show_all()
            self.reconnect_bar.set_visible(waiting)
        if self.next_episode.pending and hasattr(self,'next_label'):
            self.next_label.set_text(f'Épisode suivant dans {self.next_episode.remaining()} s · {self.next_episode.target["name"]}')
        if hasattr(self,'next_bar') and not hasattr(self,'player_info_stack'):
            if self.next_episode.pending:
                for child in self.next_bar.get_children():child.show_all()
            self.next_bar.set_visible(self.next_episode.pending)
        if hasattr(self,'player_info_stack'):
            self.player_info_stack.set_visible_child_name('reconnect' if waiting else 'next' if self.next_episode.pending else 'identity')

    def cancel_next(self):
        self.next_episode.cancel();self.update_playback_banners()

    def play_next_now(self):
        following=self.next_episode.take_due(immediately=True)
        self.update_playback_banners()
        if following:self.play(following,resume='auto')

    def handle_natural_end(self):
        if self.eof_handled or not self.current:return
        self.eof_handled=True;self.completed_current=True;self.reconnect.cancel();self.player_activity()
        channel=self.current
        if not channel.get('demo') and channel['kind']!='live':
            self.writes.submit(lambda library:library.finish_media(channel['id']),self.changed)
        self.player_status.set_text('Lecture terminée.')
        if self.autoplay and not self.resume_prompt_open and self.view=='player' and channel['kind']=='episode' and not self.recording:
            following=self.library.next_episode(channel['id'])
            if following:self.next_episode.schedule(following)
        self.update_playback_banners()

    def back_from_playback(self):
        channel=self.current
        if not self.stop_playback(destination=None):return
        if channel is None:self.navigate('home');return
        if channel['kind']=='live':self.navigate('live')
        elif channel['kind']=='episode':
            parent=self.library.channel(channel.get('parent_id')) if channel.get('parent_id') else None
            if parent:
                if self.series_id!=parent['id']:
                    self.episode_query='';self.season=channel.get('season') or None
                    self.navigation.pages.pop('episodes',None)
                self.series_id=parent['id'];self.navigate('episodes')
            else:self.navigate('series')
        elif channel['kind']=='series':self.navigate('series')
        elif not channel.get('demo') and self.library.channel(channel['id']):self.open_details(channel)
        else:self.navigate('movie')
        # Position writes precede this callback, so the returned fiche shows the final resume point.
        target=(self.view,self.detail_id,self.series_id)
        def updated(_):
            if not self.closing and self.view in ('details','episodes') and target==(self.view,self.detail_id,self.series_id):self.render()
        self.writes.submit(lambda library:None,updated)

    def stop_playback(self,destination='home'):
        if self.recording:
            self.notify('Arrêtez l’enregistrement avant de fermer le contenu.',True);return False
        self.save_position();self.reconnect.cancel();self.cancel_next()
        self.accepting_load=False;self.media_loaded=False;self.resume_target=None;self.load_deadline=None
        if self.player:
            try:self.player.command('stop')
            except RuntimeError:pass
        self.current=None;self.position=0.;self.duration=0.
        self.bottom_title.set_text('Tout votre univers. Un seul lecteur.')
        if destination is not None:self.navigate(destination)
        return True

    def command(self, *args):
        self.player_activity()
        if args and (args[0]=='seek' or args[:2]==('cycle','pause')):self.cancel_next()
        if self.player:
            try:
                if args[:2]==('cycle','pause'):self.user_paused=self.player.get('pause')!='yes'
                self.player.command(*args)
            except RuntimeError as exc: self.notify(str(exc),True)

    def set_auto_reconnect(self,enabled):
        self.auto_reconnect=enabled;self.persist_setting('auto_reconnect','1' if enabled else '0')
        if enabled:self.reconnect.reset()
        elif self.reconnect.pending or self.reconnect.inflight:self.cancel_reconnect()
        else:self.reconnect.cancel()

    def set_autoplay(self,enabled):
        self.autoplay=enabled;self.persist_setting('autoplay','1' if enabled else '0')
        if not enabled:self.cancel_next()

    def seek_begin(self): self.seeking=True;self.player_activity();return False

    def seek_end(self, *_):
        if self.duration>0: self.command('seek',self.timeline.get_value(),'absolute')
        self.seeking=False; return False

    def volume_changed(self, _, value):
        self.player_activity()
        self.volume=value;self.persist_setting('volume',value)
        if self.player:
            try:self.player.set('volume',round(value*100))
            except RuntimeError:pass

    def tracks_dialog(self):
        self.player_activity()
        if not self.player: return
        d=Gtk.Dialog(title='Audio et sous-titres',transient_for=self.window,modal=True); d.add_button('Fermer',Gtk.ResponseType.CLOSE)
        area=d.get_content_area(); area.set_spacing(14); area.set_margin_start(16); area.set_margin_end(16)
        tracks=self.player.tracks()
        for kind,title,prop in [('audio','Piste audio','aid'),('sub','Sous-titres','sid')]:
            area.pack_start(label(title,'channel-name'),False,False,0); combo=Gtk.ComboBoxText(); combo.append('no','Désactivé')
            active='no'
            for t in tracks:
                if t['type']!=kind:continue
                identity=str(t['id']); combo.append(identity,f'{t.get("title", "Piste "+identity)} · {t.get("lang", "indéterminée")}')
                if t.get('selected'):active=identity
            combo.set_active_id(active)
            combo.connect('changed',lambda w,p=prop:self.set_track(p,w.get_active_id())); area.pack_start(combo,False,False,0)
        area.pack_start(button('Charger des sous-titres…',self.add_subtitles),False,False,0); d.show_all(); d.run(); d.destroy()

    def set_track(self, prop, value):
        try:self.player.set(prop,value)
        except RuntimeError as exc:self.notify(str(exc),True)

    def add_subtitles(self):
        path=self.choose_file('Choisir un fichier de sous-titres')
        if path:self.command('sub-add',path,'select')

    def toggle_fullscreen(self):
        self.player_activity()
        self.fullscreen=not self.fullscreen
        self.sidebar.set_visible(not self.fullscreen and self.view!='player'); self.bottom.set_visible(not self.fullscreen and self.view!='player')
        self.header.set_visible(not self.fullscreen and self.view!='player')
        if hasattr(self,'fullscreen_image'):
            self.fullscreen_image.set_from_pixbuf(icon('fullscreen-exit' if self.fullscreen else 'fullscreen').get_pixbuf())
            text='Quitter le plein écran · F / Échap' if self.fullscreen else 'Plein écran · F'
            self.fullscreen_button.set_tooltip_text(text);self.fullscreen_button.get_accessible().set_name(text)
        self.window.fullscreen() if self.fullscreen else self.window.unfullscreen()

    def toggle_record(self):
        self.player_activity()
        if self.recording:
            self.stop_record(); return
        if not self.current or not self.player:return
        self.cancel_next()
        if not shutil.which('ffmpeg'):self.notify('FFmpeg doit être installé pour enregistrer.',True); return
        path=self.choose_file('Enregistrer le flux dans un fichier .mkv',save=True)
        if not path:return
        if not path.lower().endswith('.mkv'):path+='.mkv'
        # -n protects an existing file, including after automatic extension addition.
        try:
            self.record_path=path
            self.recording=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-n','-i',self.current['url'],'-map','0','-c','copy',path],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.update_record_visual(True); self.notify('Enregistrement démarré. Restez sur ce contenu.')
        except OSError:self.notify('Impossible de démarrer FFmpeg.',True)

    def stop_record(self):
        if not self.recording:return
        process=self.recording; self.recording=None
        if process.poll() is None:
            try:process.stdin.write(b'q\n'); process.stdin.flush()
            except (OSError,BrokenPipeError):pass
            def finish():
                try:process.wait(timeout=8)
                except subprocess.TimeoutExpired:process.terminate(); process.wait()
            threading.Thread(target=finish,daemon=True).start()
        self.update_record_visual(False); self.notify('Finalisation de l’enregistrement…')

    def save_position(self):
        if self.media_loaded and self.resume_target is None and not self.completed_current and self.current and not self.current.get('demo'):
            self.mark_watched(self.current['id'],self.position)

    def tick(self):
        if self.closing:return False
        if self.recording and self.recording.poll() is not None:
            code=self.recording.returncode;self.recording=None;self.update_record_visual(False)
            self.notify('Enregistrement terminé.' if code==0 else 'Échec de l’enregistrement. Vérifiez le flux et le dossier.',code!=0)
        if not self.player:return True
        events=self.player.events()
        for index,(kind,message) in enumerate(events):
            if kind=='error':
                if not any(item[0]=='loaded' for item in events[index+1:]):self.handle_playback_failure(message)
            elif kind=='loaded' and self.accepting_load and self.current:
                self.media_loaded=True;self.load_deadline=None;self.reconnect.loaded()
                if not self.current.get('demo'):self.mark_watched(self.current['id'])
                if self.current['kind']!='live' and self.current.get('position',0)>0:
                    self.resume_target=self.current['position'];self.resume_deadline=time.monotonic()+5
                    self.command('seek',self.resume_target,'absolute')
        old_position=self.position
        try:
            position=float(self.player.get('time-pos','0'));duration=float(self.player.get('duration','0'))
            if self.media_loaded:
                self.duration=duration
                if self.resume_target is not None and (position>=self.resume_target-2 or time.monotonic()>=self.resume_deadline):self.resume_target=None
                if self.resume_target is None:self.position=position
        except ValueError:pass
        paused=self.player.get('pause')=='yes';buffering=self.player.get('paused-for-cache')=='yes'
        eof=self.player.get('eof-reached')=='yes'
        if self.media_loaded and self.current:
            if self.duration>0 and not self.duration_saved and self.current['kind']!='live' and not self.current.get('demo'):
                identity=self.current['id'];duration=self.duration
                self.writes.submit(lambda library:library.set_duration(identity,duration),key=('duration',identity))
                self.current['duration_seconds']=duration;self.duration_saved=True
            if eof and not self.eof_handled:
                if self.current['kind']=='live' and remote_stream(self.current['url']):self.handle_playback_failure('Le direct s’est interrompu.')
                elif remote_stream(self.current['url']) and self.duration>0 and self.position<self.duration-3:
                    self.handle_playback_failure('La vidéo s’est interrompue avant sa fin.')
                else:self.handle_natural_end()
            elif not eof and self.eof_handled and not self.next_episode.pending:
                self.eof_handled=False;self.completed_current=False;self.reconnect.reset()
            if buffering and not self.user_paused and self.resume_target is None:
                if self.buffering_since is None:self.buffering_since=time.monotonic()
                elif time.monotonic()-self.buffering_since>=15 and remote_stream(self.current['url']):
                    self.handle_playback_failure('La connexion reste bloquée en mémoire tampon.')
            else:self.buffering_since=None
            self.reconnect.healthy(not paused and not buffering and self.position>old_position)
        if self.accepting_load and not self.media_loaded and self.load_deadline and time.monotonic()>=self.load_deadline:
            try:self.player.command('stop')
            except RuntimeError:pass
            self.handle_playback_failure('Le délai de connexion est dépassé.')
        if self.reconnect.take_due():
            fresh=self.library.channel(self.current['id']) if self.current and not self.current.get('demo') else self.current
            if fresh:
                fresh['position']=self.current.get('position',0);self.current=fresh;self.open_current_stream()
            else:self.cancel_reconnect()
        following=self.next_episode.take_due() if not self.recording else None
        if following:
            self.play(following,resume='auto');return True
        if not self.seeking:
            self.timeline.set_range(0,max(self.duration,1));self.timeline.set_value(self.position)
        self.timeline.set_sensitive(self.duration>0)
        self.time_label.set_text(f'{clock(self.position)} / {clock(self.duration)}' if self.duration else
            '● DIRECT' if self.current and self.current['kind']=='live' else 'Durée indisponible')
        self.update_pause_visual(paused)
        if self.media_loaded and not self.eof_handled and not self.reconnect.pending and self.player.get('idle-active')!='yes':
            self.player_status.set_text('Mise en mémoire tampon…' if buffering else 'Pause' if paused else 'Lecture en cours')
        self.refresh_diagnostics()
        self.update_playback_banners();self.tick_count+=1
        if self.tick_count%20==0:self.save_position()
        return True

    def key(self, _, event):
        self.player_activity()
        name=Gdk.keyval_name(event.keyval)
        settings_open=hasattr(self,'player_settings') and self.player_settings.get_visible()
        if name=='Escape' and (settings_open or self.view=='player'):
            action=escape_action(settings_open,self.player_browser_visible(),self.fullscreen)
            if action=='settings':self.player_settings.popdown()
            elif action=='browser':self.toggle_player_browser()
            elif action=='fullscreen':self.toggle_fullscreen()
            return action is not None
        if settings_open:return False
        if name=='k' and event.state&Gdk.ModifierType.CONTROL_MASK:
            if self.view=='player' and hasattr(self,'browser_search'):
                if not self.player_browser_visible():self.toggle_player_browser()
                self.browser_search.grab_focus()
            else:self.search.grab_focus()
            return True
        if isinstance(self.window.get_focus(),Gtk.Entry):return False
        focus=self.window.get_focus()
        if focus and hasattr(self,'player_split') and focus==self.player_split and name in ('Left','Right','Up','Down','Page_Up','Page_Down','Home','End','Return','KP_Enter'):return False
        if focus and hasattr(self,'player_browser') and focus.is_ancestor(self.player_browser) and name in ('Left','Right','Up','Down','Page_Up','Page_Down','Home','End','Return','KP_Enter'):return False
        if name=='space' and self.view=='player':self.command('cycle','pause');return True
        if self.view=='player' and name in ('Page_Up','Page_Down'):
            self.play_neighbor('previous' if name=='Page_Up' else 'next');return True
        if self.view=='player' and name in ('b','B'):self.toggle_player_browser();return True
        if name in ('f','F') and self.view=='player':self.toggle_fullscreen();return True
        if name in ('a','A') and self.view=='player':self.cycle_aspect();return True
        if self.view=='player' and name in ('Left','Right'):self.command('seek',-10 if name=='Left' else 10);return True
        return False

    def close(self, *_):
        if self.closing: return False
        self.closing=True
        if self.category_width_timer:
            GLib.source_remove(self.category_width_timer);self.save_category_width()
        if self.browser_width_timer:
            GLib.source_remove(self.browser_width_timer);self.save_player_browser_width()
        self.set_player_chrome(True)
        self.save_position(); self.stop_record()
        self.reconnect.cancel();self.cancel_next();self.accepting_load=False
        self.catalog_tasks.close();self.detail_tasks.close()
        if self.render_timer:GLib.source_remove(self.render_timer);self.render_timer=None
        if self.paint_timer:GLib.source_remove(self.paint_timer);self.paint_timer=None
        if self.catalog_restore_timer:GLib.source_remove(self.catalog_restore_timer);self.catalog_restore_timer=None
        if self.idle_timer:GLib.source_remove(self.idle_timer);self.idle_timer=None
        if self.player:self.player.close(); self.player=None
        if self.artwork:self.artwork.close()
        self.writes.close()
        self.library.db.close(); self.quit(); return False

    def screenshot(self):
        win=self.window.get_window(); w,h=self.window.get_size()
        pix=Gdk.pixbuf_get_from_window(win,0,0,w,h); pix.savev(self.args.screenshot,'png',[],[])
        self.close();return False

def main():
    parser=argparse.ArgumentParser(description='TunPlayer — lecteur IPTV de bureau')
    parser.add_argument('--data-dir',help='Dossier de données alternatif (tests / profil isolé)')
    parser.add_argument('--screenshot',help='Capture de l’interface puis fermeture')
    args=parser.parse_args()
    return App(args).run([sys.argv[0]])
