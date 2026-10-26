"""PIN prompts and shared authorization for browsing, playback and downloads."""
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk
from .parental import CategoryLocks,category_key,PinError,KINDS


class AccessMixin:
    def category_tooltip(self,tree,x,y,keyboard,tooltip):
        context=tree.get_tooltip_context(x,y,keyboard)
        if not context or not context[0]:return False
        _,model,path,it=context
        tooltip.set_text(model[it][0])
        tree.set_tooltip_row(tooltip,path)
        return True

    def init_access(self):
        self.category_locks=CategoryLocks(self.library.path.parent/'parental.json')
        self.parent_categories={}

    def access_keys(self,channel):
        policy=self.category_locks
        if not policy.configured or (not policy.locks and not policy.invalid) or channel.get('demo'):return set()
        if channel.get('radio'):
            return {category_key('radio',tag) for tag in channel.get('tags',[]) or [channel.get('group_name','')]}
        if channel.get('lock_scope') in KINDS:return {category_key(channel['lock_scope'],channel.get('lock_group',''))}
        kind=channel.get('kind');group=channel.get('group_name','')
        if kind=='episode':
            kind='series';parent=channel.get('parent_id')
            if parent:
                key=(parent,self.data_revision)
                if key not in self.parent_categories:
                    if len(self.parent_categories)>256:self.parent_categories.clear()
                    row=self.library.channel(parent);self.parent_categories[key]=row['group_name'] if row else None
                group=self.parent_categories[key]
            if not parent or group is None:return {key for key,row in policy.locks.items() if row['kind']=='series'} or {category_key('series','')}
        if kind not in KINDS:return set()
        if channel.get('orphan_download') and policy.locks:return set(policy.locks)
        return {category_key(kind,group)}

    def content_locked(self,channel):return bool(self.category_locks.pending(self.access_keys(channel)))

    def ask_pin(self,title='Déverrouiller cette catégorie'):
        from .app import label
        if self.category_locks.invalid:
            self.notify('La configuration du PIN est illisible. Restaurez le fichier parental.json de votre profil.',True);return None
        dialog=Gtk.Dialog(title=title,transient_for=self.window,modal=True)
        dialog.add_buttons('Annuler',Gtk.ResponseType.CANCEL,'Valider',Gtk.ResponseType.OK)
        area=dialog.get_content_area();area.set_spacing(12);area.set_border_width(20)
        area.pack_start(label('Code PIN','channel-name'),False,False,0)
        entry=Gtk.Entry();entry.set_visibility(False);entry.set_max_length(8);entry.set_input_purpose(Gtk.InputPurpose.PIN)
        entry.set_activates_default(True);dialog.set_default_response(Gtk.ResponseType.OK);area.pack_start(entry,False,False,0)
        error=label('','error',True);area.pack_start(error,False,False,0);dialog.show_all();entry.grab_focus()
        try:
            while dialog.run()==Gtk.ResponseType.OK:
                pin=entry.get_text()
                try:accepted=self.category_locks.verify(pin)
                except OSError:accepted=False;error.set_text('Le profil n’a pas pu être enregistré.');continue
                if accepted:return pin
                wait=self.category_locks.remaining()
                error.set_text(f'Trop de tentatives. Réessayez dans {wait} secondes.' if wait else 'PIN incorrect. Réessayez.')
                entry.set_text('');entry.grab_focus()
            return None
        finally:entry.set_text('');dialog.destroy()

    def authorize(self,keys,title='Déverrouiller cette catégorie'):
        pending=self.category_locks.pending(keys)
        if not pending:return True
        if self.ask_pin(title) is None:return False
        self.category_locks.grants.update(pending)
        if hasattr(self,'category_tree'):self.category_tree.queue_draw()
        return True

    def ensure_access(self,channel):return self.authorize(self.access_keys(channel))

    def ensure_category_access(self,kind,name):
        return self.authorize({category_key(kind,name)}) if kind in KINDS else True

    def category_protected(self,kind,name):return kind in KINDS and self.category_locks.locked(kind,name)

    def locked_media_card(self,channel):
        from .app import box,label,button
        from .visuals import icon
        panel=box(True,12,'panel');panel.set_size_request(190,130)
        panel.pack_start(icon('lock',30,'#c4f478'),False,False,0)
        panel.pack_start(label('Contenu verrouillé','channel-name'),False,False,0)
        panel.pack_start(button('Déverrouiller',lambda:self.open_media(channel),'small',symbol='lock'),False,False,0)
        return panel

    def render_access_gate(self,channel):
        from .app import label,button
        self.content.pack_start(label('Cette catégorie est protégée par un PIN.','section-title',True),False,False,0)
        def unlock():
            if self.ensure_access(channel):self.render()
        self.content.pack_start(button('Déverrouiller',unlock,'primary',symbol='lock'),False,False,0)

    def category_cell(self,column,cell,model,it,_=None):
        text=model[it][0];protected=not model[it][3] and self.category_protected(self.view,text)
        unlocked=protected and category_key(self.view,text) in self.category_locks.grants
        cell.set_property('text',('🔓 ' if unlocked else '🔒 ' if protected else '')+text)

    def update_category_lock(self):
        if not hasattr(self,'category_lock_button'):return
        available=self.view in KINDS and self.group is not None
        locked=available and self.category_protected(self.view,self.group)
        self.category_lock_button.set_sensitive(available)
        self.category_lock_button.get_child().get_children()[1].set_text('Retirer verrou' if locked else 'Verrouiller')
        self.category_lock_button.set_tooltip_text(('Retirer la protection de cette catégorie avec le PIN' if locked else 'Protéger la catégorie sélectionnée avec un PIN') if available else 'Sélectionnez une catégorie dans Télévision, Films, Séries ou Radio')

    def configure_pin(self):
        from .app import label
        current=self.ask_pin('Modifier le PIN actuel') if self.category_locks.configured else None
        if self.category_locks.configured and current is None:return None
        dialog=Gtk.Dialog(title='Choisir un PIN',transient_for=self.window,modal=True)
        dialog.add_buttons('Annuler',Gtk.ResponseType.CANCEL,'Enregistrer',Gtk.ResponseType.OK)
        area=dialog.get_content_area();area.set_spacing(10);area.set_border_width(20)
        fields=[]
        for title in ('Nouveau PIN (4 à 8 chiffres)','Confirmer le PIN'):
            area.pack_start(label(title,'muted'),False,False,0)
            entry=Gtk.Entry();entry.set_visibility(False);entry.set_max_length(8);entry.set_input_purpose(Gtk.InputPurpose.PIN)
            fields.append(entry);area.pack_start(entry,False,False,0)
        error=label('','error',True);area.pack_start(error,False,False,0);dialog.show_all()
        try:
            while dialog.run()==Gtk.ResponseType.OK:
                pin=fields[0].get_text()
                if pin!=fields[1].get_text():error.set_text('Les deux PIN ne correspondent pas.');continue
                try:self.category_locks.set_pin(pin,current)
                except (OSError,PinError) as failure:error.set_text(str(failure) if isinstance(failure,PinError) else 'Impossible d’enregistrer le PIN.');continue
                self.enforce_locks();return pin
            return None
        finally:
            for entry in fields:entry.set_text('')
            dialog.destroy()

    def toggle_category_lock(self):
        if self.view not in KINDS or self.group is None:return
        pin=self.ask_pin('Modifier le verrou de cette catégorie') if self.category_locks.configured else self.configure_pin()
        if pin is None:return
        try:self.category_locks.protect(self.view,self.group,pin,not self.category_protected(self.view,self.group))
        except (OSError,PinError):self.notify('La protection n’a pas pu être modifiée.',True);return
        self.enforce_locks();self.render()

    def enforce_locks(self):
        if self.current and self.content_locked(self.current):
            if self.recording:self.stop_record()
            channel=self.current
            destination='downloads' if channel.get('local_download') else 'radio' if channel.get('radio') else 'series' if channel['kind']=='episode' else channel['kind']
            self.stop_playback(destination=destination)
        if self.download_manager:
            for row in self.download_manager.snapshot():
                if row['state'] in ('queued','running') and self.content_locked(self.download_channel(row)):self.download_manager.pause(row['id'])
        if hasattr(self,'category_tree'):self.category_tree.queue_draw()

    def relock_categories(self):
        self.category_locks.relock();self.enforce_locks();self.render()

    def download_channel(self,row):
        original=self.library.channel(row['channel_id'])
        value=dict(original or dict(kind='movie',group_name='',orphan_download=True))
        if row.get('category_kind') in KINDS:value.update(lock_scope=row['category_kind'],lock_group=row.get('category_name',''))
        return value

    def ensure_download_access(self,rows):
        keys=set()
        for row in rows:keys.update(self.access_keys(self.download_channel(row)))
        return self.authorize(keys,'Déverrouiller les téléchargements protégés')

    def security_settings(self):
        from .app import box,label,button
        panel=box(True,12,'panel');panel.pack_start(label('Protection des catégories','section-title'),False,False,0)
        panel.pack_start(label('Choisissez une catégorie, puis « Verrouiller ». Le déverrouillage reste valable jusqu’au reverrouillage ou à la fermeture.','muted',True),False,False,0)
        actions=box(spacing=10)
        def configure():
            if self.configure_pin() is not None:self.render()
        actions.pack_start(button('Modifier le PIN' if self.category_locks.configured else 'Créer un PIN',configure,'ghost',symbol='lock'),False,False,0)
        actions.pack_start(button('Reverrouiller maintenant',self.relock_categories,'small'),False,False,0)
        def disable():
            pin=self.ask_pin('Désactiver le PIN et tous les verrous')
            if pin is not None:
                try:self.category_locks.disable(pin);self.render()
                except (OSError,PinError):self.notify('Impossible de désactiver le PIN.',True)
        if self.category_locks.configured:actions.pack_start(button('Désactiver la protection',disable,'small'),False,False,0)
        panel.pack_start(actions,False,False,0)
        for row in self.category_locks.locks.values():panel.pack_start(label('🔒 '+{'live':'Télévision','movie':'Films','series':'Séries','radio':'Radio'}[row['kind']]+' · '+(row['name'] or 'Sans catégorie'),'muted'),False,False,0)
        return panel
