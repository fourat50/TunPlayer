"""GTK subtitle search, provider configuration, local reuse and timing controls."""
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
from .jobs import LatestTask
from .subtitles import (SubtitleError,SubtitleService,SubtitleStore,OpenSubtitles,SubtitleHTTP,
                        PROVIDERS,media_query,validate_query,private_json,read_json)
from .subtitle_languages import LANGUAGES


def refresh_source_checks(checks,before,after):
    """A newly entered API key must enable its source in an already open search."""
    for name,key in (('opensubtitles','api_key'),('subdl','subdl_api_key')):
        if name not in checks:continue
        if not after.get(key):checks[name].set_active(False)
        elif after.get(key)!=before.get(key):checks[name].set_active(True)


def connection_message(result):
    parts=['Clé SubDL validée · configuration enregistrée']
    for key,caption in (('search_remaining','Recherches restantes'),('download_remaining','Téléchargements restants')):
        value=result.get(key)
        if value is not None:parts.append(f'{caption} : {value}'+(' (quota épuisé)' if value==0 else ''))
    return '\n'.join(parts)


class SubtitleMixin:
    def init_subtitles(self):
        self.subtitle_store=SubtitleStore(self.library.path.parent/'subtitles')
        self.subtitle_settings_path=self.library.path.parent/'subtitle-providers.json'
        self.subtitle_dialogs={};self.active_subtitle=None

    def subtitle_context(self):
        if not self.current or self.current.get('radio') or self.current['kind'] not in ('movie','episode','series'):return None
        if self.content_locked(self.current):return None
        return self.current['id'],self.stream_generation

    def activate_subtitle(self,context,path,delay=0):
        if self.closing or context!=self.subtitle_context() or not self.player:return False
        try:
            tracks=self.player.tracks() if hasattr(self.player,'tracks') else []
            loaded=next((track for track in tracks if track.get('type')=='sub' and track.get('external-filename')==str(path)),None)
            if loaded:self.player.set('sid',loaded['id'])
            else:self.player.command('sub-add',str(path),'select')
            self.player.set('sub-delay',delay);self.player.set('sub-visibility','yes')
            self.active_subtitle=Path(path)
            self.subtitle_store.select(self.current['id'],path,delay)
            return True
        except (RuntimeError,OSError,ValueError):self.notify('Le sous-titre n’a pas pu être activé ou mémorisé.',True);return False

    def restore_subtitles(self):
        self.active_subtitle=None
        try:self.player.set('sub-delay',0)
        except RuntimeError:pass
        context=self.subtitle_context()
        if context:
            selected=self.subtitle_store.selected(context[0])
            if selected:self.activate_subtitle(context,*selected)

    def subtitle_delay(self,value):
        if not self.player:return
        try:
            self.player.set('sub-delay',value)
            if self.current and self.active_subtitle:self.subtitle_store.select(self.current['id'],self.active_subtitle,value)
        except (RuntimeError,OSError,ValueError):self.notify('Impossible de modifier le décalage.',True)
        self.player_activity()

    def disable_subtitles(self):
        if self.current:
            index=read_json(self.subtitle_store.root/'selected.json');index.pop(str(self.current['id']),None)
            try:private_json(self.subtitle_store.root/'selected.json',index)
            except OSError:self.notify('Le choix de sous-titres n’a pas pu être mémorisé.',True)
        self.active_subtitle=None

    def subtitle_settings_panel(self):
        from .app import box,label,button
        panel=box(True,12,'panel');panel.pack_start(label('Sous-titres en ligne','section-title'),False,False,0)
        panel.pack_start(label('Recherchez et activez des sous-titres depuis « Audio et sous-titres » pendant un film ou un épisode. Podnapisi fonctionne sans compte ; OpenSubtitles.com et SubDL nécessitent chacun leur clé API.','muted',True),False,False,0)
        panel.pack_start(button('Configurer les sources',self.configure_subtitle_sources,'ghost',symbol='subtitles'),False,False,0)
        return panel

    def configure_subtitle_sources(self):
        from .app import label,button
        settings=read_json(self.subtitle_settings_path)
        dialog=Gtk.Dialog(title='Sources de sous-titres',transient_for=self.window,modal=True)
        dialog.add_buttons('Fermer',Gtk.ResponseType.CLOSE,'Enregistrer',Gtk.ResponseType.APPLY)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        dialog.get_content_area().pack_start(scroll,True,True,0)
        area=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);area.set_border_width(20);scroll.add(area)
        area.pack_start(label('OpenSubtitles.com','section-title'),False,False,0)
        area.pack_start(label('La clé API est requise. La connexion au compte est facultative et permet d’utiliser son quota. Le mot de passe n’est pas enregistré.','muted',True),False,False,0)
        link=Gtk.LinkButton.new_with_label('https://www.opensubtitles.com/en/consumers','Créer une clé API OpenSubtitles.com')
        area.pack_start(link,False,False,0)
        entries={}
        for key,caption,secret in [('api_key','Clé API',True),('username','Nom d’utilisateur (facultatif)',False),('password','Mot de passe (pour se connecter)',True)]:
            entry=Gtk.Entry();entry.set_placeholder_text(caption);entry.set_visibility(not secret);entry.set_text(str(settings.get(key,'')))
            entry.get_accessible().set_name(caption);entries[key]=entry;area.pack_start(entry,False,False,0)
        status=label('Compte mémorisé : '+str(settings.get('username','')) if settings.get('token') else 'Connexion facultative.','muted',True)
        area.pack_start(status,False,False,0);task=LatestTask();subdl_task=LatestTask();self.subtitle_dialogs[dialog]=(task,subdl_task)
        def snapshot():
            value={k:entries[k].get_text().strip() for k in ('api_key','username','subdl_api_key')}
            if value['api_key']==settings.get('api_key') and value['username']==settings.get('username'):
                for key in ('token','expires','base_url'):
                    if key in settings:value[key]=settings[key]
            return value
        def save(value):
            value=dict(value,subdl_api_key=entries['subdl_api_key'].get_text().strip())
            try:private_json(self.subtitle_settings_path,value)
            except OSError:status.set_text('Impossible d’enregistrer la configuration.');return False
            settings.clear();settings.update(value);return True
        def login():
            value=snapshot();password=entries['password'].get_text()
            if not value['api_key'] or not value['username'] or not password:status.set_text('Saisissez la clé API, le nom et le mot de passe.');return
            connect.set_sensitive(False);status.set_text('Connexion…')
            def done(value):
                connect.set_sensitive(True);entries['password'].set_text('')
                if save(value):status.set_text('Compte connecté. Le quota de ce compte sera utilisé.')
            def failed(error):connect.set_sensitive(True);entries['password'].set_text('');status.set_text(str(error) if isinstance(error,SubtitleError) else 'Connexion impossible.')
            task.submit(lambda cancel:OpenSubtitles(SubtitleHTTP(),value).login(value['username'],password),done,failed)
        connect=button('Connecter le compte',login,'ghost');area.pack_start(connect,False,False,0)
        def logout():
            task.cancel();connect.set_sensitive(True)
            value=snapshot()
            for key in ('token','expires','base_url'):value.pop(key,None)
            if save(value):status.set_text('Session locale déconnectée.');entries['password'].set_text('')
        area.pack_start(button('Déconnecter le compte',logout,'small'),False,False,0)
        area.pack_start(label('SubDL','section-title'),False,False,0)
        area.pack_start(label('Ajoutez la clé API de votre compte SubDL pour rechercher des films et des épisodes.','muted',True),False,False,0)
        area.pack_start(Gtk.LinkButton.new_with_label('https://subdl.com/panel/api','Obtenir une clé API SubDL'),False,False,0)
        subdl_key=Gtk.Entry();subdl_key.set_visibility(False);subdl_key.set_placeholder_text('Clé API SubDL')
        subdl_key.get_accessible().set_name('Clé API SubDL');subdl_key.set_text(str(settings.get('subdl_api_key','')))
        entries['subdl_api_key']=subdl_key;area.pack_start(subdl_key,False,False,0)
        subdl_status=label('Connexion SubDL non vérifiée. Testez la clé pour confirmer l’accès au compte.','muted',True)
        area.pack_start(subdl_status,False,False,0);verified=[None]
        def key_changed(*_):
            subdl_task.cancel();verified[0]=None;test_subdl.set_sensitive(True)
            subdl_status.set_text('Clé modifiée : connexion à vérifier.')
        def test_connection():
            from .subtitle_subdl import SubDL
            value=snapshot();key=value.get('subdl_api_key','')
            if not key:subdl_status.set_text('Saisissez votre clé API SubDL.');return
            test_subdl.set_sensitive(False);subdl_status.set_text('Vérification du compte SubDL…')
            def done(result):
                test_subdl.set_sensitive(True)
                if subdl_key.get_text().strip()!=key:return
                if save(snapshot()):verified[0]=key;subdl_status.set_text(connection_message(result))
                else:subdl_status.set_text('Clé valide, mais la configuration n’a pas pu être enregistrée.')
            def failed(error):
                verified[0]=None;test_subdl.set_sensitive(True)
                subdl_status.set_text('Échec du test : '+(str(error) if isinstance(error,SubtitleError) else 'Impossible de vérifier le compte.'))
            subdl_task.submit(lambda cancel:SubDL(SubtitleHTTP(),value).connection(),done,failed)
        test_subdl=button('Tester la connexion SubDL',test_connection,'ghost')
        test_subdl.set_tooltip_text('Vérifie la clé auprès de SubDL et enregistre la configuration uniquement si le test réussit.')
        area.pack_start(test_subdl,False,False,0);subdl_key.connect('changed',key_changed)
        from .subtitle_subliminal import SubliminalProvider
        area.pack_start(label('Podnapisi : disponible sans compte.\nSubliminal : '+('installé, sources supplémentaires disponibles.' if SubliminalProvider.available() else 'extension facultative absente ; les sources intégrées restent disponibles.'),'muted',True),False,False,0)
        dialog.set_default_size(600,620);dialog.show_all()
        try:
            while dialog.run()==Gtk.ResponseType.APPLY:
                task.cancel();connect.set_sensitive(True)
                subdl_task.cancel();test_subdl.set_sensitive(True)
                if save(snapshot()):
                    status.set_text('Configuration enregistrée. Les quotas et langues dépendent de chaque source.')
                    if verified[0]!=subdl_key.get_text().strip():subdl_status.set_text('Clé enregistrée ; utilisez le test pour vérifier la connexion.')
        finally:
            task.close();subdl_task.close();self.subtitle_dialogs.pop(dialog,None);entries['password'].set_text('');dialog.destroy()

    def post_subtitle_progress(self,dialog,task,serial,callback,result):
        def deliver():
            if not self.closing and dialog in self.subtitle_dialogs and not task.closed and serial==task.serial:callback(result)
            return False
        GLib.idle_add(deliver)

    def search_subtitles(self):
        from .app import box,label,button
        context=self.subtitle_context()
        if context is None:self.notify('La recherche de sous-titres est disponible pendant un film ou un épisode.');return
        channel=dict(self.current);parent=self.library.channel(channel['parent_id']) if channel.get('parent_id') else None
        query=media_query(channel,parent);query['language']=self.library.setting('subtitle_language','fr')
        dialog=Gtk.Dialog(title='Rechercher des sous-titres',transient_for=self.window,modal=True)
        dialog.add_button('Fermer',Gtk.ResponseType.CLOSE);dialog.set_default_size(850,610)
        area=dialog.get_content_area();area.set_border_width(18);area.set_spacing(12)
        area.pack_start(label('Sous-titres pour ce contenu','section-title'),False,False,0)
        title=Gtk.Entry();title.set_text(query['title']);title.set_placeholder_text('Titre du film ou de la série');title.get_accessible().set_name('Titre à rechercher')
        area.pack_start(title,False,False,0);filters=box(spacing=12);numbers={}
        for key,caption,maximum in [('year','Année',2100),('season','Saison',999),('episode','Épisode',9999)]:
            column=box(True,5);column.pack_start(label(caption,'muted'),False,False,0)
            field=Gtk.SpinButton.new_with_range(0,maximum,1);field.set_value(query[key]);field.get_accessible().set_name(caption)
            field.set_sensitive(key=='year' or query['kind']=='episode');numbers[key]=field;column.pack_start(field,False,False,0);filters.pack_start(column,False,False,0)
        languages=Gtk.ComboBoxText.new_with_entry()
        languages.append('all','Toutes les langues')
        for code,name in LANGUAGES:languages.append(code,name+' · '+code)
        languages.set_active_id(query['language'])
        if languages.get_active()<0:languages.get_child().set_text(query['language'])
        languages.get_child().get_accessible().set_name('Langue des sous-titres ou code ISO')
        language_box=box(True,5);language_box.pack_start(label('Langue · code ISO accepté','muted'),False,False,0)
        language_box.pack_start(languages,False,False,0);filters.pack_start(language_box,True,True,0);area.pack_start(filters,False,False,0)
        sources=box(spacing=12);checks={}
        available=SubtitleService().providers()
        for key,caption in PROVIDERS.items():
            settings=read_json(self.subtitle_settings_path)
            check=Gtk.CheckButton(label=caption);check.set_active(key=='podnapisi' or key=='opensubtitles' and bool(settings.get('api_key')) or key=='subdl' and bool(settings.get('subdl_api_key')))
            check.set_sensitive(key in available);checks[key]=check;sources.pack_start(check,False,False,0)
        def configure_sources():
            cancel_search();before=read_json(self.subtitle_settings_path)
            self.configure_subtitle_sources()
            refresh_source_checks(checks,before,read_json(self.subtitle_settings_path))
            rows.clear();store.clear();download.set_sensitive(False)
            status.set_text('Sources actualisées. Cliquez sur Rechercher pour utiliser la configuration enregistrée.')
        sources.pack_start(button('Configurer',configure_sources,'small'),False,False,0);area.pack_start(sources,False,False,0)
        status=label('La recherche démarre avec le titre et la langue sélectionnés. Vous pouvez modifier les filtres puis relancer la recherche.','muted',True)
        area.pack_start(status,False,False,0);store=Gtk.ListStore(str,str,str,str,int)
        tree=Gtk.TreeView(model=store);tree.set_headers_visible(True)
        for index,caption in enumerate(('Langue','Source','Version / fichier','Correspondance')):
            renderer=Gtk.CellRendererText();renderer.set_property('ellipsize',3)
            column=Gtk.TreeViewColumn(caption,renderer,text=index);column.set_resizable(True)
            if index==2:column.set_expand(True)
            tree.append_column(column)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC);scroll.add(tree);area.pack_start(scroll,True,True,0)
        actions=box(spacing=12);busy=Gtk.Spinner();rows=[];task=LatestTask(workers=2);self.subtitle_dialogs[dialog]=(task,);downloading=[False]
        def fail(error):
            busy.stop();downloading[0]=False;search.set_sensitive(True);cancel.set_sensitive(False);download.set_sensitive(bool(rows))
            status.set_text(str(error) if isinstance(error,SubtitleError) else 'Opération impossible. Réessayez ou choisissez une autre source.')
        def paint(result):
            selected=None;model,it=tree.get_selection().get_selected()
            if it is not None:
                old=rows[model[it][4]];selected=(old['provider'],old['id'],old['language'])
            rows[:]=result['rows'];store.clear()
            for index,row in enumerate(rows):
                badges=(' · Malentendants' if row['hearing'] else '')+(' · Traduction automatique' if row['machine'] else '')
                if row.get('warning'):badges+=' · '+row['warning']
                match='Titre concordant' if row['score']>=60 else 'À vérifier'
                it=store.append([row['language'],row.get('source',PROVIDERS[row['provider']]),row['release']+badges,match,index])
                if selected==(row['provider'],row['id'],row['language']):tree.get_selection().select_iter(it)
            pending=result.get('pending',[])
            errors=' · '.join(PROVIDERS[k]+' : '+v for k,v in result['errors'].items())
            text=f'{len(rows)} résultat(s).'
            if pending:text+=' Recherche en cours : '+', '.join(PROVIDERS[k] for k in pending)+'.'
            elif not rows:text='Aucun résultat. Essayez le titre original ou « Toutes les langues ».'
            info=result.get('diagnostics',{}).get('subdl')
            if info is not None:
                text+=f' SubDL : {info["received"]} fichier(s) reçu(s), {info["kept"]} retenu(s).'
                if not rows and info['received']:
                    reasons=[caption for key,caption in (('language','langue'),('episode','épisode'),('pack','pack non détaillé'),('link','lien absent')) if info.get(key)]
                    if reasons:text+=' Filtres : '+', '.join(reasons)+'.'
            status.set_text(text+(' '+errors if errors else ''));download.set_sensitive(bool(rows))
            if not pending:busy.stop();search.set_sensitive(True);cancel.set_sensitive(False)
        def search_now():
            if not search.get_sensitive():return
            if self.subtitle_context()!=context:status.set_text('Le contenu a changé. Fermez cette fenêtre et relancez la recherche.');return
            value=dict(query,title=title.get_text(),language=languages.get_active_id() or languages.get_child().get_text().strip().lower(),**{k:w.get_value_as_int() for k,w in numbers.items()})
            try:value=validate_query(value)
            except SubtitleError as error:status.set_text(str(error));return
            enabled=[k for k,w in checks.items() if w.get_active() and w.get_sensitive()]
            if not enabled:status.set_text('Sélectionnez au moins une source de sous-titres.');return
            service=SubtitleService(read_json(self.subtitle_settings_path));rows.clear();store.clear();download.set_sensitive(False);busy.start()
            search.set_sensitive(False);cancel.set_sensitive(True)
            status.set_text('Recherche dans les sources sélectionnées…');self.persist_setting('subtitle_language',value['language'])
            serial=task.serial+1
            def progress(result):self.post_subtitle_progress(dialog,task,serial,paint,result)
            task.submit(lambda cancel:service.search(value,enabled,cancel,progress=progress),paint,fail)
        def cancel_search():
            task.cancel();busy.stop();downloading[0]=False;search.set_sensitive(True);cancel.set_sensitive(False)
            download.set_sensitive(bool(rows));status.set_text('Opération annulée. Vous pouvez relancer la recherche.')
        def download_now(*_):
            if downloading[0]:return
            model,it=tree.get_selection().get_selected()
            if it is None:status.set_text('Sélectionnez un sous-titre dans la liste.');return
            row=rows[model[it][4]];service=SubtitleService(read_json(self.subtitle_settings_path))
            downloading[0]=True;search.set_sensitive(False);download.set_sensitive(False);cancel.set_sensitive(True);busy.start();status.set_text('Téléchargement du sous-titre…')
            def work(cancel):
                data,filename=service.download(row)
                if cancel.is_set():return None
                return self.subtitle_store.save(context[0],row,data,filename)
            def done(path):
                busy.stop();downloading[0]=False;search.set_sensitive(True);download.set_sensitive(True);cancel.set_sensitive(False)
                if path and self.activate_subtitle(context,path):status.set_text('Sous-titre téléchargé et activé. Il sera proposé automatiquement à la prochaine lecture.')
                else:status.set_text('Sous-titre conservé localement. Le contenu a changé ou n’est plus disponible pour activation.')
            task.submit(work,done,fail)
        search=button('Rechercher',search_now,'ghost',symbol='search');download=button('Télécharger et activer',download_now,'primary',symbol='download')
        cancel=button('Annuler',cancel_search,'small');cancel.set_sensitive(False)
        download.set_sensitive(False);actions.pack_start(search,False,False,0);actions.pack_start(download,False,False,0);actions.pack_start(cancel,False,False,0);actions.pack_start(busy,False,False,0)
        tree.connect('row-activated',download_now);title.connect('activate',lambda _:search_now());area.pack_start(actions,False,False,0)
        dialog.show_all()
        # "Search online" should immediately populate the results window using
        # the prefilled title/episode and preferred language.
        automatic=[None];automatic_serial=task.serial
        def start_search():
            automatic[0]=None
            if not self.closing and dialog in self.subtitle_dialogs and not task.closed and task.serial==automatic_serial:search_now()
            return False
        automatic[0]=GLib.idle_add(start_search)
        try:dialog.run()
        finally:
            if automatic[0] is not None:GLib.source_remove(automatic[0])
            task.close();self.subtitle_dialogs.pop(dialog,None);dialog.destroy();self.player_activity()

    def close_subtitle_dialogs(self):
        for dialog,tasks in list(self.subtitle_dialogs.items()):
            for task in tasks:task.close()
            dialog.response(Gtk.ResponseType.CLOSE)
