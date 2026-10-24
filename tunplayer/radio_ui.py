"""Radio directory and audio presentation integrated with the GTK controller."""
import json
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
from .jobs import LatestTask
from .radio import RadioDirectory,PAGE_SIZE,favorite_rows,stations,filter_summary
from .visuals import icon


class RadioMixin:
    def init_radio(self):
        self.radio_directory=RadioDirectory(self.library.path.parent/'radio-cache')
        self.radio_tasks=LatestTask(workers=2);self.radio_facets_tasks=LatestTask()
        self.radio_rows=[];self.radio_play_rows=[];self.radio_groups=[];self.radio_countries=[]
        self.radio_facets_loading=False;self.radio_facets_ready=False;self.radio_favorites_only=False
        self.radio_country=self.library.setting('radio_country','')
        self.radio_order=self.library.setting('radio_order','popular')
        self.radio_favorites={}
        try:
            saved=json.loads(self.library.setting('radio_favorites','{}'))
            for value in saved.values():
                if not isinstance(value,dict):continue
                rows=stations([dict(value,favicon=value.get('logo',''),tags=','.join(value.get('tags',[])),clickcount=value.get('clicks',0))])
                if rows:self.radio_favorites[rows[0]['id']]=rows[0]
        except (ValueError,AttributeError,TypeError):pass

    def build_radio_country(self):
        from .app import box,label
        self.radio_country_box=box(True,8)
        self.radio_country_box.pack_start(label('PAYS','caption'),False,False,0)
        self.radio_country_combo=Gtk.ComboBoxText();self.radio_country_combo.append('','Tous les pays')
        self.radio_country_combo.set_active(0)
        self.radio_country_combo.set_tooltip_text('Filtrer les radios par pays')
        self.radio_country_combo.get_accessible().set_name('Pays des radios')
        self.radio_country_combo.connect('changed',self.radio_country_changed)
        self.radio_country_box.pack_start(self.radio_country_combo,False,False,0)
        self.radio_country_box.show_all();self.radio_country_box.set_no_show_all(True)
        self.category_panel.pack_start(self.radio_country_box,False,False,0)
        self.category_panel.reorder_child(self.radio_country_box,0);self.radio_country_box.hide()

    def radio_country_changed(self,combo):
        if getattr(self,'radio_country_updating',False) or self.view!='radio':return
        self.radio_country=combo.get_active_id() or '';self.page=0
        self.persist_setting('radio_country',self.radio_country);self.render()

    def load_radio_facets(self):
        if self.radio_facets_loading or self.radio_facets_ready:return
        self.radio_facets_loading=True
        def done(data):
            self.radio_facets_loading=False;self.radio_facets_ready=True
            self.radio_groups=data['groups'];self.radio_countries=data['countries']
            if self.view=='radio':self.paint_radio_facets()
        def failed(_):
            self.radio_facets_loading=False
            if self.view=='radio':self.notify('Liste des pays indisponible. Réessayez avec Actualiser.',True)
        self.radio_facets_tasks.submit(self.radio_directory.facets,done,failed)

    def paint_radio_facets(self):
        self.radio_country_updating=True
        self.radio_country_combo.remove_all();self.radio_country_combo.append('','Tous les pays')
        for country in self.radio_countries:self.radio_country_combo.append(country['code'],country['name'])
        if not self.radio_country_combo.set_active_id(self.radio_country):
            if self.radio_country:self.radio_country_combo.append(self.radio_country,self.radio_country);self.radio_country_combo.set_active_id(self.radio_country)
            else:self.radio_country_combo.set_active(0)
        self.radio_country_updating=False
        groups=list(self.radio_groups)
        if self.group and not any(g['group_name']==self.group for g in groups):groups.append(dict(group_name=self.group,count=0))
        self.populate_categories(groups)
        self.category_tree.set_tooltip_text('Catégories de Radio Browser · choisissez un genre')

    def radio_query(self):
        return dict(text=self.query,country=self.radio_country,tag=self.group or '',order=self.radio_order,page=self.page)

    def render_radio(self,refresh=False):
        from .app import box,label,button,clear
        generation=self.render_generation;self.radio_tasks.cancel()
        self.load_radio_facets();self.paint_radio_facets()
        intro=box(True,7,'radio-intro')
        intro.pack_start(label('Le monde s’écoute.','section-title'),False,False,0)
        intro.pack_start(label('Choisissez un pays et une catégorie, puis écoutez en direct.','muted',True),False,False,0)
        intro.pack_start(label('Annuaire Radio Browser · la même source qu’OpenRadio · sans compte','caption',True),False,False,0)
        self.content.pack_start(intro,False,False,0)
        tools=box(spacing=10)
        order=Gtk.ComboBoxText()
        for value,text in [('popular','Les plus écoutées'),('name','Nom : A → Z'),('country','Pays : A → Z')]:order.append(value,text)
        order.set_active_id(self.radio_order);order.get_accessible().set_name('Trier les radios')
        def changed(combo):
            self.radio_order=combo.get_active_id() or 'popular';self.page=0
            self.persist_setting('radio_order',self.radio_order);self.render()
        order.connect('changed',changed);tools.pack_start(order,False,False,0)
        favorites=Gtk.ToggleButton(label='♥ Mes radios');favorites.set_active(self.radio_favorites_only)
        def favorite_filter(widget):self.radio_favorites_only=widget.get_active();self.page=0;self.render()
        favorites.connect('toggled',favorite_filter);tools.pack_start(favorites,False,False,0)
        tools.pack_start(button('Actualiser',self.refresh_radio,'small',symbol='refresh'),False,False,0)
        self.content.pack_start(tools,False,False,0)
        request=self.radio_query()
        summary=label(filter_summary(request,self.radio_countries,self.radio_favorites_only),'muted',True)
        self.content.pack_start(summary,False,False,0)
        self.radio_result_area=box(True,12);area=self.radio_result_area
        area.pack_start(label('Recherche des stations…','muted'),False,False,0)
        self.content.pack_start(area,True,True,0);self.content.show_all()
        def done(data):
            if self.closing or self.view!='radio' or generation!=self.render_generation:return
            clear(area);self.radio_rows=data['rows']
            if data['stale']:area.pack_start(label('Hors ligne · résultats en cache. Les flux nécessitent une connexion.','muted',True),False,False,0)
            if not data['rows']:
                title='Aucune station compatible sur cette page.' if data['has_next'] or self.page>0 else 'Aucune radio ne correspond à ces filtres.'
                area.pack_start(label(title,'section-title'),False,False,0)
                if request['country']:area.pack_start(button('Chercher dans tous les pays',self.clear_radio_country,'small'),False,False,0)
                if request['tag']:area.pack_start(button('Afficher tous les genres',lambda:self.change_group(None),'small'),False,False,0)
                area.pack_start(button('Afficher toutes les radios',self.reset_radio,'ghost',symbol='radio'),False,False,0)
            flow=Gtk.FlowBox();flow.set_selection_mode(Gtk.SelectionMode.NONE);flow.set_activate_on_single_click(False)
            flow.set_min_children_per_line(1);flow.set_max_children_per_line(3);flow.set_column_spacing(14);flow.set_row_spacing(14)
            area.pack_start(flow,False,False,0)
            index=[0]
            def append():
                if self.closing or generation!=self.render_generation:return False
                for station in data['rows'][index[0]:index[0]+4]:flow.add(self.radio_card(station))
                index[0]+=4;flow.show_all()
                return index[0]<len(data['rows'])
            GLib.idle_add(append,priority=GLib.PRIORITY_DEFAULT_IDLE)
            paging=box(spacing=12)
            previous=button('Précédent',lambda:self.radio_page(-1),'small',symbol='back');previous.set_sensitive(self.page>0)
            following=button('Suivant',lambda:self.radio_page(1),'small',symbol='arrow');following.set_sensitive(data['has_next'])
            paging.pack_start(previous,False,False,0);paging.pack_start(label(f'{len(data["rows"])} stations affichées · Page {self.page+1}','muted'),True,True,0)
            paging.pack_start(following,False,False,0);area.pack_start(paging,False,False,0);area.show_all()
        def failed(_):
            if self.closing or self.view!='radio' or generation!=self.render_generation:return
            clear(area);area.pack_start(label('L’annuaire radio est indisponible. Vos radios favorites restent accessibles.','muted',True),False,False,0)
            area.pack_start(button('Réessayer',self.refresh_radio,'primary',symbol='refresh'),False,False,0);area.show_all()
        if self.radio_favorites_only:done(favorite_rows(self.radio_favorites,request))
        else:self.radio_tasks.submit(lambda cancel:self.radio_directory.search(request,cancel,refresh),done,failed)

    def radio_card(self,station):
        from .app import box,label,button
        card=box(True,12,'radio-card');card.set_size_request(240,-1)
        identity=box(spacing=12);identity.pack_start(self.media_art(station,width=72,height=72),False,False,0)
        description=box(True,5);title=label(station['name'],'channel-name');title.set_ellipsize(3);title.set_max_width_chars(22)
        title.set_tooltip_text(station['name']);description.pack_start(title,False,False,0)
        description.pack_start(label(station['country'],'muted'),False,False,0)
        tags=label(' · '.join(station['tags'][:3]) or 'Radio en direct','caption');tags.set_ellipsize(3);tags.set_max_width_chars(26)
        description.pack_start(tags,False,False,0);identity.pack_start(description,True,True,0);card.pack_start(identity,False,False,0)
        quality=' · '.join(filter(None,[station['codec'],f'{station["bitrate"]} kbit/s' if station['bitrate'] else '',station['language']]))
        detail=label(quality,'muted');detail.set_ellipsize(3);detail.set_max_width_chars(32);card.pack_start(detail,False,False,0)
        actions=box(spacing=8);actions.pack_start(button('Écouter',lambda:self.play_radio_station(station),'primary',symbol='play'),True,True,0)
        saved=station['id'] in self.radio_favorites
        favorite=button('',lambda:self.toggle_radio_favorite(station),'favorite',symbol='heart',tooltip='Retirer de Mes radios' if saved else 'Ajouter à Mes radios')
        if saved:favorite.get_style_context().add_class('selected')
        actions.pack_start(favorite,False,False,0);card.pack_start(actions,False,False,0)
        return card

    def radio_page(self,delta):self.page=max(0,self.page+delta);self.render()

    def clear_radio_country(self):
        self.radio_country='';self.page=0
        self.persist_setting('radio_country','');self.render()

    def refresh_radio(self):
        from .app import clear
        self.radio_facets_ready=False;self.render_generation+=1;clear(self.content);self.render_radio(refresh=True)

    def reset_radio(self):
        self.radio_country='';self.group=None;self.query='';self.page=0;self.radio_favorites_only=False
        self.search.set_text('');self.persist_setting('radio_country','');self.render()

    def toggle_radio_favorite(self,station):
        if station['id'] in self.radio_favorites:self.radio_favorites.pop(station['id'])
        else:self.radio_favorites[station['id']]=dict(station)
        self.persist_setting('radio_favorites',json.dumps(self.radio_favorites,ensure_ascii=False))
        if self.view=='radio':self.render()

    def play_radio_station(self,station):
        self.radio_play_rows=list(self.radio_rows);self.play(station)

    def refresh_radio_player(self,focus=False):
        current=self.current;identity=current['id']
        rows=self.radio_play_rows
        index=next((i for i,r in enumerate(rows) if r['id']==identity),-1)
        self.player_neighbors=dict(previous=rows[index-1] if index>0 else None,next=rows[index+1] if 0<=index<len(rows)-1 else None)
        self.paint_player_neighbors()
        if not self.player_browser_visible():return
        request=dict(text=self.browser_query,country=self.radio_country,tag=self.browser_group or '',order=self.radio_order,page=self.browser_page)
        if hasattr(self,'browser_filter_hint'):
            self.browser_filter_hint.set_text(filter_summary(request,self.radio_countries,self.radio_favorites_only))
            self.browser_filter_hint.set_visible(True)
        self.browser_status.set_text('Recherche des stations…')
        def done(data):
            if self.closing or self.view!='player' or not self.current or self.current['id']!=identity:return
            count=self.browser_page*PAGE_SIZE+len(data['rows'])+int(data['has_next'])
            self.paint_player_browser(dict(rows=data['rows'],groups=self.radio_groups,parent=None,total=count,page=self.browser_page),focus)
            self.browser_status.set_text(f'{len(data["rows"])} stations affichées sur cette page'+(' · cache hors ligne' if data['stale'] else ''))
            self.browser_page_label.set_text(f'Page {self.browser_page+1}')
            self.browser_next.set_sensitive(data['has_next'])
        def failed(_):
            if self.view=='player':self.browser_status.set_text('Annuaire indisponible. La lecture continue.')
        if self.radio_favorites_only:done(favorite_rows(self.radio_favorites,request))
        else:self.detail_tasks.submit(lambda cancel:self.radio_directory.search(request,cancel),done,failed)
