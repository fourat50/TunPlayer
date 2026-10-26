"""Source account panels and background subscription checks."""
import time
from gi.repository import Gtk, GLib, Pango
from .core import Library
from .jobs import LatestTask
from .source_info import account_connection,account_fields,fetch_account,subscription,date_text


class SourceMixin:
    def source_summary(self):
        sources=self.library.sources()
        if self.source_id is not None:
            selected=[s for s in sources if s['id']==self.source_id]
            if selected:sources=selected
        return [(s,self.library.source_account(s['id'])) for s in sources]

    def update_source_status(self):
        if not hasattr(self,'subscription_label'):return
        signature=(self.source_id,self.data_revision,getattr(self,'source_status_revision',0),int(time.time()//60))
        if signature==getattr(self,'source_status_signature',None):return
        self.source_status_signature=signature
        from .app import clear,label,box
        entries=self.source_summary()
        clear(self.subscription_list)
        for source,account in entries:
            item=box(True,4)
            title=label(source['name'],'subscription-name');title.set_ellipsize(Pango.EllipsizeMode.END);title.set_max_width_chars(22)
            item.pack_start(title,False,False,0)
            text,style=subscription(account)
            badge=label(text,'subscription-'+style,True);badge.set_max_width_chars(24)
            item.pack_start(badge,False,False,0)
            if account.get('error'):item.pack_start(label('Vérification indisponible','muted',True),False,False,0)
            item.set_tooltip_text(source['name']+'\n'+text+'\nVérifié : '+date_text(account.get('checked_at')))
            self.subscription_list.pack_start(item,False,False,0)
        if not entries:self.subscription_list.pack_start(label('Aucune source connectée','muted',True),False,False,0)
        self.subscription_list.show_all()
        self.subscription_label.set_visible(bool(entries))
        if entries:
            source,account=min(entries,key=lambda pair:pair[1].get('expires_at') or float('inf'))
            text,style=subscription(account)
            self.subscription_label.set_text(source['name']+' · '+text)
            self.subscription_label.set_ellipsize(Pango.EllipsizeMode.END)
            self.subscription_label.set_max_width_chars(44)
            context=self.subscription_label.get_style_context()
            for name in ('active','soon','expired','unknown'):context.remove_class('subscription-'+name)
            context.add_class('subscription-'+style)
            self.subscription_label.set_tooltip_text(source['name']+'\n'+text+'\nHeure locale · vérifié : '+date_text(account.get('checked_at')))

    def refresh_main_source(self):
        from .app import label
        if self.busy:self.notify('Attendez la fin de l’opération en cours.');return
        sources=self.library.sources()
        if not sources:self.navigate('sources');self.notify('Ajoutez votre première source dans Mes sources.');return
        source=next((s for s in sources if s['id']==self.source_id),None)
        if source is None and len(sources)==1:source=sources[0]
        if source is None:
            dialog=Gtk.Dialog(title='Actualiser une source',transient_for=self.window,modal=True)
            dialog.add_buttons('Annuler',Gtk.ResponseType.CANCEL,'Actualiser',Gtk.ResponseType.OK)
            area=dialog.get_content_area();area.set_border_width(20);area.set_spacing(14)
            area.pack_start(label('Choisissez la source à actualiser.'),False,False,0)
            choice=Gtk.ComboBoxText()
            for item in sources:choice.append(str(item['id']),item['name'])
            choice.set_active(0);area.pack_start(choice,False,False,0);dialog.show_all()
            response=dialog.run();identity=choice.get_active_id();dialog.destroy()
            if response!=Gtk.ResponseType.OK:return
            source=next(s for s in sources if str(s['id'])==identity)
        self.refresh_source(source)

    def refresh_source_accounts(self,automatic=False,source_ids=None,force=False):
        if self.closing:return False
        if getattr(self,'source_accounts_loading',False):return False
        snapshots=[]
        for source in self.library.sources():
            if source_ids is not None and source['id'] not in source_ids:continue
            config=self.library.source_config(source['id']);account=self.library.source_account(source['id'])
            checked=max(account.get('attempted_at',0),account.get('checked_at',0))
            if account_connection(config) and (force or not automatic or time.time()-checked>6*3600):
                snapshots.append((source['id'],config,account))
        if not snapshots:
            if not automatic:self.notify('Aucun compte à vérifier : cette playlist ne fournit pas d’API de compte.')
            return False
        if not hasattr(self,'source_account_tasks'):self.source_account_tasks=LatestTask()
        self.source_accounts_loading=True
        if not automatic:self.notify('Vérification des abonnements en cours…')
        def work(cancel):
            errors=0
            for identity,config,previous in snapshots:
                if cancel.is_set():break
                account=fetch_account(config,previous)
                if account.get('error'):errors+=1
                if cancel.is_set():break
                library=Library(self.library.path,migrate=False)
                try:library.save_source_account(identity,account,config)
                finally:library.close()
            return errors
        def done(errors):
            self.source_accounts_loading=False
            if self.closing:return
            self.source_status_revision=getattr(self,'source_status_revision',0)+1
            self.update_source_status()
            if self.view in ('sources','settings'):self.render()
            if not automatic:self.notify('Abonnements vérifiés.' if not errors else 'Certaines informations sont indisponibles. Les dernières données sont conservées.',bool(errors))
        def failed(_):
            self.source_accounts_loading=False
            if not self.closing and not automatic:self.notify('Vérification des abonnements impossible. Réessayez.',True)
        self.source_account_tasks.submit(work,done,failed)
        return False

    def source_status_tick(self):
        if self.closing:return False
        self.update_source_status()
        return True

    def source_information(self,source,expanded=False):
        from .app import label
        config=self.library.source_config(source['id']);account=self.library.source_account(source['id'])
        expander=Gtk.Expander(label='Informations de la source et de l’abonnement')
        expander.set_expanded(expanded)
        grid=Gtk.Grid(column_spacing=24,row_spacing=12);grid.set_margin_top(16)
        fields=account_fields(config,account,self.library.source_counts(source['id']))
        fields.append(('Dernière actualisation du catalogue',date_text(source.get('updated_at'))))
        for index,(name,value) in enumerate(fields):
            title=label(name,'muted',True);title.set_valign(Gtk.Align.START);title.set_max_width_chars(24)
            text=label(value,None,True);text.set_selectable(True);text.set_max_width_chars(58);text.set_hexpand(True)
            grid.attach(title,0,index,1,1);grid.attach(text,1,index,1,1)
        if account.get('error'):
            grid.attach(label(account['error'],'error',True),0,len(fields),2,1)
        expander.add(grid)
        return expander

    def source_settings_panel(self):
        from .app import box,label,button,space
        panel=box(True,16,'panel');heading=box(spacing=12)
        heading.pack_start(label('Sources & abonnements','section-title'),False,False,0);heading.pack_start(space(),True,True,0)
        heading.pack_start(button('Vérifier les abonnements',self.refresh_source_accounts,'ghost',symbol='refresh'),False,False,0)
        panel.pack_start(heading,False,False,0)
        panel.pack_start(label('Dates affichées dans votre heure locale. Informations fournies par votre opérateur, conservées pour consultation hors ligne.','muted',True),False,False,0)
        for source in self.library.sources():
            panel.pack_start(label(source['name'],'source-name'),False,False,0)
            panel.pack_start(self.source_information(source,expanded=True),False,False,0)
        panel.pack_start(button('Gérer / ajouter une source',lambda:self.navigate('sources'),'ghost',symbol='sources'),False,False,0)
        return panel
