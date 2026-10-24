"""VOD download actions and transfer status without rebuilding the GTK page."""
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib,Gio
from .downloads import DownloadManager,DownloadError,plan,ACTIVE


def amount(value):
    for unit in ('o','Ko','Mo','Go','To'):
        if value<1024 or unit=='To':return f'{value:.1f} {unit}'
        value/=1024


class DownloadMixin:
    def init_downloads(self):
        self.download_manager=None;self.download_widgets={};self.download_signature=None
        self.download_timer=None;self.stream_start_timer=None;self.stream_generation=0

    def transfers(self):
        if self.download_manager is None:self.download_manager=DownloadManager(self.library.path.parent/'downloads.json')
        return self.download_manager

    def choose_download_folder(self):
        dialog=Gtk.FileChooserDialog(title='Dossier des téléchargements',transient_for=self.window,action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons('Annuler',Gtk.ResponseType.CANCEL,'Télécharger ici',Gtk.ResponseType.OK)
        previous=self.library.setting('download_directory','')
        if previous and Path(previous).is_dir():dialog.set_current_folder(previous)
        folder=dialog.get_filename() if dialog.run()==Gtk.ResponseType.OK else None;dialog.destroy()
        if folder:self.persist_setting('download_directory',folder)
        return folder

    def download_content(self,channel):
        if not self.ensure_access(channel):return
        if channel.get('kind')=='series' and channel.get('url','').startswith('xtream-series:'):
            self.open_series(channel);return
        folder=self.choose_download_folder()
        if not folder:return
        parent=self.library.channel(channel.get('parent_id')) if channel.get('parent_id') else None
        self.queue_downloads([channel],folder,parent)

    def download_season(self):
        if self.season is None:self.notify('Choisissez une saison avant de la télécharger.');return
        series=self.library.channel(self.series_id)
        if not series:return
        if not self.ensure_access(series):return
        # Download the entire selected season, not just the filtered/current page.
        episodes=self.library.episodes(series['id'],self.season)
        if not episodes:self.notify('Aucun épisode disponible dans cette saison.',True);return
        folder=self.choose_download_folder()
        if folder:self.queue_downloads(episodes,folder,series)

    def queue_downloads(self,channels,folder,series=None):
        for channel in channels:
            if not self.ensure_access(channel):return
        try:
            count=self.transfers().enqueue(plan(channels,folder,series))
            self.notify(f'{count} téléchargement(s) ajouté(s). Suivez la progression dans Téléchargements.' if count else
                        'Ces contenus figurent déjà dans Téléchargements. Vous pouvez les reprendre ou les lire depuis cette rubrique.')
        except (OSError,ValueError):self.notify('Impossible d’ajouter le téléchargement. Vérifiez le dossier et le lien vidéo.',True)

    def download_button(self,channel,compact=False):
        from .app import button
        widget=button('' if compact else 'Télécharger',lambda:self.download_content(channel),'icon-button' if compact else 'ghost',
                      symbol='download',tooltip='Télécharger cet épisode' if channel['kind']=='episode' else 'Télécharger ce film')
        if not channel['url'].startswith(('http://','https://')):
            widget.set_sensitive(False);widget.set_tooltip_text('Le téléchargement nécessite un lien vidéo HTTP(S).')
        return widget

    def download_action(self,identity,action):
        manager=self.transfers()
        try:
            if action=='resume':
                rows=[r for r in manager.snapshot() if r['id']==identity]
                if not self.ensure_download_access(rows):return
                manager.resume(identity)
            else:manager.pause(identity,cancel=action=='cancel')
        except (OSError,ValueError):self.notify('Impossible de modifier le téléchargement. Vérifiez le dossier.',True)
        self.download_tick()

    def pause_downloads(self):
        for row in self.transfers().snapshot():
            if row['state'] in ACTIVE:self.transfers().pause(row['id'])
        self.download_tick()

    def resume_downloads(self):
        rows=[r for r in self.transfers().snapshot() if r['state'] in ('paused','error')]
        if not self.ensure_download_access(rows):return
        for row in rows:
            if row['state'] in ('paused','error'):self.transfers().resume(row['id'])
        self.download_tick()

    def render_downloads(self):
        from .app import box,label,button
        rows=self.transfers().snapshot();self.download_signature=tuple(r['id'] for r in rows)
        self.download_widgets={}
        title=box(spacing=12);title.pack_start(label('Vos contenus à emporter','section-title'),True,True,0)
        title.pack_start(button('Reprendre tout',self.resume_downloads,'small',symbol='play'),False,False,0)
        title.pack_start(button('Tout mettre en pause',self.pause_downloads,'small',symbol='pause'),False,False,0)
        self.content.pack_start(title,False,False,0)
        self.content.pack_start(label('Un transfert à la fois · fichiers conservés sur cet ordinateur · reprise HTTP si le serveur le permet.','muted',True),False,False,0)
        if self.download_manager.persistence_error:
            self.content.pack_start(label('L’historique des téléchargements n’a pas pu être enregistré. Vérifiez l’espace libre du profil.','error',True),False,False,0)
        if not rows:
            self.content.pack_start(label('Aucun téléchargement. Ouvrez un film ou une saison pour commencer.','muted',True),False,False,0)
            return
        self.page=min(self.page,max(0,(len(rows)-1)//self.page_size))
        for row in list(reversed(rows))[self.page*self.page_size:(self.page+1)*self.page_size]:
            protected=self.content_locked(self.download_channel(row))
            panel=box(True,9,'panel');name=label('🔒 Contenu verrouillé' if protected else row['name'],'channel-name');name.set_ellipsize(3);name.set_max_width_chars(65)
            panel.pack_start(name,False,False,0)
            path=label('Catégorie protégée par PIN' if protected else row['path'],'muted');path.set_ellipsize(3);path.set_max_width_chars(80)
            path.set_tooltip_text(None if protected else row['path'])
            panel.pack_start(path,False,False,0)
            progress=Gtk.ProgressBar();panel.pack_start(progress,False,False,0)
            status=label('','muted',True);panel.pack_start(status,False,False,0)
            actions=box(spacing=8)
            pause=button('Pause',lambda i=row['id']:self.download_action(i,'pause'),'small',symbol='pause')
            resume=button('Reprendre',lambda i=row['id']:self.download_action(i,'resume'),'small',symbol='play')
            cancel=button('Annuler',lambda i=row['id']:self.download_action(i,'cancel'),'small',symbol='close')
            play=button('Lire',lambda r=row:self.play_download(r),'primary',symbol='play')
            folder=button('Dossier',lambda r=row:self.open_download_folder(r),'small',symbol='folder')
            for action in (pause,resume,cancel,play,folder):actions.pack_start(action,False,False,0)
            panel.pack_start(actions,False,False,0);self.content.pack_start(panel,False,False,0)
            self.download_widgets[row['id']]=(progress,status,pause,resume,cancel,play,path)
        self.pagination(len(rows));self.download_tick()

    def download_tick(self):
        if self.closing:self.download_timer=None;return False
        if self.view!='downloads' or self.download_manager is None:return True
        rows=self.download_manager.snapshot()
        if tuple(r['id'] for r in rows)!=self.download_signature:self.render();return True
        names=dict(queued='En attente',running='Téléchargement en cours',pausing='Mise en pause…',paused='En pause',
                   cancelling='Annulation…',cancelled='Annulé',done='Terminé',error='Échec')
        for row in rows:
            widgets=self.download_widgets.get(row['id'])
            if not widgets:continue
            progress,status,pause,resume,cancel,play,path=widgets
            total=row.get('total',0);count=row.get('downloaded',0);state=row['state']
            if state=='done':progress.set_fraction(1)
            elif total:progress.set_fraction(min(1,count/total))
            elif state=='running':progress.pulse()
            else:progress.set_fraction(0)
            text=names.get(state,state)+' · '+amount(count)+((' / '+amount(total)) if total else '')
            if state=='paused' and count>0 and not row.get('resume_supported'):text+=' · ce flux reprendra depuis le début'
            if row.get('error'):text+=' · '+row['error']
            status.set_text(text);pause.set_sensitive(state in ('queued','running'))
            resume.set_sensitive(state in ('paused','error','cancelled'));cancel.set_sensitive(state not in ('done','cancelled','cancelling'))
            play.set_sensitive(state=='done' and Path(row['path']).is_file())
            protected=self.content_locked(self.download_channel(row))
            path.set_text('Catégorie protégée par PIN' if protected else row['path']);path.set_tooltip_text(None if protected else row['path'])
        return True

    def open_download_folder(self,row):
        if not self.ensure_download_access([row]):return
        try:Gio.AppInfo.launch_default_for_uri(Path(row['path']).parent.as_uri(),None)
        except GLib.Error:self.notify('Impossible d’ouvrir ce dossier.',True)

    def play_download(self,row):
        current=next((r for r in self.transfers().snapshot() if r['id']==row['id']),row)
        if current['state']!='done' or not Path(current['path']).is_file():self.notify('Le fichier téléchargé est introuvable.',True);return
        if not self.ensure_download_access([current]):return
        original=self.library.channel(current['channel_id'])
        channel=dict(original or dict(id=current['channel_id'],name=current['name'],kind='movie',source_id=None,
            group_name='Téléchargements',parent_id=None,position=0,logo='',tvg_id=''))
        channel.update(url=current['path'],local_download=True)
        if current.get('category_kind'):
            channel.update(lock_scope=current['category_kind'],lock_group=current.get('category_name',''))
        elif original is None:channel['orphan_download']=True
        self.play(channel)
