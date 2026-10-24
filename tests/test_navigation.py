import argparse
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gi.repository import GLib
from tunplayer.app import App
from tunplayer.core import Library
from tunplayer.jobs import CatalogReader,SnapshotCache
from tunplayer.navigation import NavigationMemory


class SmartCatalog(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.library=Library(Path(self.tmp.name)/'db.sqlite3')
        self.library.import_channels('Films',[
            dict(name=f'Film {i:04}',kind='movie',group_name='Cinéma',url=f'https://example.org/{i}.mp4',tvg_id='',logo='')
            for i in range(135)])
        self.reader=CatalogReader(self.library.path);self.cancel=threading.Event()
        self.request=dict(view='movie',page_size=60,page=0,search='',filters={},revision=0)

    def tearDown(self):self.library.close();self.tmp.cleanup()

    def test_prefetched_page_avoids_sql_and_reuses_count(self):
        count=Library.channel_count
        with patch.object(Library,'channel_count',autospec=True,side_effect=count) as counted:
            first=self.reader.snapshot(self.request,self.cancel)
            next_request=self.reader.next_request(self.request,first)
            prefetched=self.reader.snapshot(next_request,self.cancel)
            self.assertEqual(counted.call_count,1)
            with patch('tunplayer.jobs.Library',side_effect=AssertionError('Cached navigation opened SQLite')):
                self.assertEqual(self.reader.lookup(next_request),prefetched)
                self.assertEqual(self.reader.snapshot(next_request,self.cancel),prefetched)
        self.assertTrue(set(r['id'] for r in first['rows']).isdisjoint(r['id'] for r in prefetched['rows']))
        last_request=self.reader.next_request(next_request,prefetched)
        last=self.reader.snapshot(last_request,self.cancel)
        self.assertEqual(len(last['rows']),15)
        self.assertIsNone(self.reader.next_request(last_request,last))

    def test_revision_invalidates_favorites_and_count(self):
        request=dict(self.request,view='favorites')
        self.assertEqual(self.reader.snapshot(request,self.cancel)['total'],0)
        identity=self.library.channels(limit=1)[0]['id'];self.library.favorite(identity)
        revised=dict(request,revision=1)
        self.assertIsNone(self.reader.lookup(revised))
        result=self.reader.snapshot(revised,self.cancel)
        self.assertEqual(result['total'],1);self.assertEqual(result['rows'][0]['id'],identity)

    def test_mutating_cached_result_cannot_poison_future_navigation(self):
        data=self.reader.snapshot(self.request,self.cancel)
        data['rows'][0]['name']='corrupted';data['rows'].clear()
        cached=self.reader.lookup(self.request)
        self.assertEqual(len(cached['rows']),60)
        cached['rows'][0]['name']='also corrupted'
        self.assertEqual(self.reader.lookup(self.request)['rows'][0]['name'],'Film 0000')

    def test_cancelled_prefetch_does_not_open_database_or_publish_result(self):
        self.cancel.set()
        with patch('tunplayer.jobs.Library',side_effect=AssertionError('Cancelled request opened SQLite')):
            self.assertIsNone(self.reader.snapshot(self.request,self.cancel))
        self.assertIsNone(self.reader.lookup(self.request))

    def test_snapshot_expiry_and_lru_bound(self):
        now=[0];cache=SnapshotCache(limit=2,ttl=15,clock=lambda:now[0])
        cache.put({'page':0},'first');cache.put({'page':1},'second')
        self.assertEqual(cache.get({'page':0}),'first')
        cache.put({'page':2},'third')
        self.assertIsNone(cache.get({'page':1}));self.assertEqual(len(cache.items),2)
        now[0]=15;self.assertIsNone(cache.get({'page':0}))

    def test_discovery_does_not_prefetch_another_page(self):
        self.assertIsNone(self.reader.next_request(dict(self.request,discovery=True),{'page':0,'total':100}))


class NavigationState(unittest.TestCase):
    def wait(self,predicate):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            while GLib.MainContext.default().iteration(False):pass
            if predicate():return
            time.sleep(.002)
        self.fail('Controller operation timed out')

    def test_scroll_survives_revision_but_is_separate_for_each_search_and_page(self):
        memory=NavigationMemory(limit=2)
        request=dict(view='movie',page=2,search='cinema',revision=0,advanced=False)
        memory.remember(request,730)
        self.assertEqual(memory.position(dict(request,revision=9,advanced=True)),730)
        self.assertEqual(memory.position(dict(request,page=3)),0)
        self.assertEqual(memory.position(dict(request,search='sport')),0)
        memory.remember(dict(request,page=3),100)
        memory.remember(dict(request,page=4),200)
        self.assertEqual(len(memory.positions),2);self.assertEqual(memory.position(request),0)

    def test_category_width_is_saved_and_restored_without_hidden_layout_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            app=App(argparse.Namespace(data_dir=directory,screenshot=None));app.view='live'
            visible=[True];position=[300]
            app.category_panel=SimpleNamespace(get_visible=lambda:visible[0])
            paned=SimpleNamespace(get_mapped=lambda:True,get_position=lambda:position[0],set_position=lambda value:position.__setitem__(0,value))
            try:
                app.category_width_changed(paned)
                position[0]=340;app.category_width_changed(paned)
                self.wait(lambda:app.library.setting('category_width')=='340')
                visible[0]=False;position[0]=0;app.category_width_changed(paned)
                self.assertEqual(app.category_width,340)
                other=App(argparse.Namespace(data_dir=directory,screenshot=None))
                try:self.assertEqual(other.category_width,340)
                finally:other.catalog_tasks.close();other.detail_tasks.close();other.writes.close();other.library.close()
                visible[0]=True;position[0]=700;app.category_width_changed(paned)
                self.wait(lambda:app.library.setting('category_width')=='480')
                self.assertEqual(position[0],480)
            finally:
                if app.category_width_timer:GLib.source_remove(app.category_width_timer)
                self.wait(lambda:app.writes.idle)
                app.catalog_tasks.close();app.detail_tasks.close();app.writes.close();app.library.close()

    def test_opening_a_fiche_and_returning_restores_page_and_query(self):
        with tempfile.TemporaryDirectory() as directory:
            app=App(argparse.Namespace(data_dir=directory,screenshot=None))
            sink=lambda *args:None
            widget=SimpleNamespace(set_visible=sink,set_text=sink)
            app.search=widget;app.heading=widget;app.heading_subtitle=widget;app.playback=widget
            app.scroll=SimpleNamespace(set_visible=sink,get_vadjustment=lambda:SimpleNamespace(get_value=lambda:720))
            app.workspace=widget;app.category_panel=widget;app.return_button=widget;app.nav={}
            app.set_player_chrome=sink;app.render=sink
            app.view='movie';app.page=3;app.query='aventure';app.group='Cinéma'
            request=app.catalog_request();app.painted_request=request;app.catalog_ready=True
            try:
                app.navigate('details');app.catalog_ready=False
                app.navigate('movie')
                self.assertEqual((app.page,app.query,app.group),(3,'aventure','Cinéma'))
                self.assertEqual(app.navigation.position(request),720)
            finally:
                app.catalog_tasks.close();app.detail_tasks.close();app.writes.close();app.library.close()

    def test_stale_layout_callback_cannot_scroll_or_prefetch_new_view(self):
        with tempfile.TemporaryDirectory() as directory:
            app=App(argparse.Namespace(data_dir=directory,screenshot=None))
            app.render_generation=2
            app.scroll=SimpleNamespace(get_vadjustment=lambda:self.fail('Stale callback accessed the new view'))
            try:
                app.catalog_finished(1)
                while GLib.MainContext.default().iteration(False):pass
                self.assertFalse(app.catalog_ready)
            finally:
                app.catalog_tasks.close();app.detail_tasks.close();app.writes.close();app.library.close()

    def test_favorite_updates_duplicate_cards_without_rebuilding_catalogue(self):
        with tempfile.TemporaryDirectory() as directory:
            app=App(argparse.Namespace(data_dir=directory,screenshot=None))
            app.library.import_channels('Films',[dict(name='Film',kind='movie',group_name='Films',url='https://example.org/1.mp4',tvg_id='',logo='')])
            row=app.library.channels()[0];copy=dict(row);changes=[]
            context=SimpleNamespace(add_class=lambda name:changes.append(name),remove_class=lambda name:changes.append('-'+name))
            image=SimpleNamespace(set_from_pixbuf=lambda _:None)
            widget=SimpleNamespace(get_style_context=lambda:context,set_tooltip_text=lambda _:None,
                get_accessible=lambda:SimpleNamespace(set_name=lambda _:None),
                get_child=lambda:SimpleNamespace(get_children=lambda:[image]))
            app.favorite_widgets[row['id']]=[(widget,row),(widget,copy)]
            app.view='movie';app.render=lambda:self.fail('A favorite rebuilt the entire catalogue')
            try:
                with patch('tunplayer.app.icon',return_value=SimpleNamespace(get_pixbuf=lambda:None)):
                    app.toggle_favorite(row);self.wait(lambda:app.data_revision==1)
                    self.assertEqual((row['favorite'],copy['favorite']),(1,1))
                    app.toggle_favorite(row);self.wait(lambda:app.data_revision==2)
                    self.assertEqual((row['favorite'],copy['favorite']),(0,0))
                self.assertEqual(changes,['selected','selected','-selected','-selected'])
                renders=[];app.view='favorites';app.render=lambda:renders.append(True)
                app.toggle_favorite(row);self.wait(lambda:app.data_revision==3)
                self.assertEqual(renders,[True])
            finally:
                self.wait(lambda:app.writes.idle)
                app.catalog_tasks.close();app.detail_tasks.close();app.writes.close();app.library.close()

    def test_scroll_during_page_construction_takes_precedence_over_restoration(self):
        with tempfile.TemporaryDirectory() as directory:
            app=App(argparse.Namespace(data_dir=directory,screenshot=None));values=[]
            adjustment=SimpleNamespace(get_lower=lambda:0,get_upper=lambda:2000,get_page_size=lambda:500,set_value=values.append)
            app.scroll=SimpleNamespace(get_vadjustment=lambda:adjustment)
            request=dict(view='movie',page=0,page_size=60,filters={},search='',revision=0)
            app.active_catalog_request=request;app.painted_request=request
            app.catalog_data={'page':0,'total':0};app.navigation.remember(request,720)
            try:
                app.catalog_scroll_event();app.catalog_finished(0)
                self.wait(lambda:app.catalog_ready);self.assertEqual(values,[])
                app.catalog_ready=False;app.catalog_interacted=False;app.catalog_finished(0)
                self.wait(lambda:app.catalog_ready);self.assertEqual(values,[720])
            finally:
                app.catalog_tasks.close();app.detail_tasks.close();app.writes.close();app.library.close()


if __name__=='__main__':unittest.main()
