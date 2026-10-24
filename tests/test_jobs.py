from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from gi.repository import GLib
from tunplayer.core import Library
from tunplayer.jobs import LatestTask,CatalogReader,WriteQueue


def row(i):
    return dict(name=f'Film {i:04d}',url=f'https://example.org/{i}.mp4',kind='movie',group_name=f'Groupe {i%4}',tvg_id='',logo='',year=2020+i%4)

class BackgroundWork(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.library=Library(Path(self.tmp.name)/'db.sqlite3')
    def tearDown(self):self.library.close();self.tmp.cleanup()
    def wait(self,predicate):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            while GLib.MainContext.default().iteration(False):pass
            if predicate():return
            time.sleep(.002)
        self.fail('Background operation timed out')

    def test_stale_catalogue_response_is_never_displayed(self):
        task=LatestTask();started=threading.Event();seen=[];errors=[]
        def old(cancel):started.set();cancel.wait(2);return 'old'
        try:
            task.submit(old,seen.append,errors.append);self.assertTrue(started.wait(1))
            task.submit(lambda cancel:'new',seen.append,errors.append)
            self.wait(lambda:bool(seen));self.assertEqual(seen,['new']);self.assertFalse(errors)
        finally:task.close()

    def test_main_loop_keeps_ticking_during_background_query(self):
        task=LatestTask();ticks=[];seen=[]
        timer=GLib.timeout_add(5,lambda:ticks.append(time.monotonic()) or True)
        try:
            def work(cancel):time.sleep(.15);return 'done'
            task.submit(work,seen.append,lambda error:self.fail(type(error).__name__))
            self.wait(lambda:bool(seen));self.assertGreaterEqual(len(ticks),8)
        finally:GLib.source_remove(timer);task.close()

    def test_snapshot_category_counts_paging_and_optional_facets(self):
        self.library.import_channels('Films',[row(i) for i in range(245)])
        reader=CatalogReader(self.library.path);cancel=threading.Event()
        request=dict(view='movie',page_size=60,page=2,search='',filters={},revision=0)
        data=reader.snapshot(request,cancel)
        self.assertEqual((data['total'],data['page'],len(data['rows'])),(245,2,60))
        self.assertEqual(sum(g['count'] for g in data['groups']),245)
        self.assertIsNone(data['facets'])
        data=reader.snapshot(dict(request,advanced=True),cancel)
        self.assertEqual(data['facets']['year'],[2020,2021,2022,2023])
        filtered=reader.snapshot(dict(request,group='Groupe 2',page=0),cancel)
        self.assertTrue(all(r['group_name']=='Groupe 2' for r in filtered['rows']))

    def test_worker_writes_do_not_block_ui_on_database_lock(self):
        writes=WriteQueue(self.library.path);ticks=[]
        self.library.db.execute('BEGIN IMMEDIATE')
        try:
            start=time.monotonic();writes.submit(lambda library:library.set_setting('test','saved'))
            self.assertLess(time.monotonic()-start,.1)
            timer=GLib.timeout_add(5,lambda:ticks.append(1) or True)
            release=GLib.timeout_add(80,lambda:self.library.db.rollback() or False)
            try:self.wait(lambda:writes.idle)
            finally:GLib.source_remove(timer)
            self.assertGreaterEqual(len(ticks),5);self.assertEqual(self.library.setting('test'),'saved')
        finally:self.library.db.rollback();writes.close()

    def test_write_queue_coalesces_repeated_preferences(self):
        writes=WriteQueue(self.library.path);started=threading.Event();release=threading.Event();seen=[]
        def blocking(library):started.set();release.wait(2)
        try:
            writes.submit(blocking);self.assertTrue(started.wait(1))
            for value in range(200):
                writes.submit(lambda library,value=value:(seen.append(value),library.set_setting('volume',value)),key='volume')
            release.set();self.wait(lambda:writes.idle)
            self.assertEqual(seen,[199]);self.assertEqual(self.library.setting('volume'),'199')
        finally:release.set();writes.close()

    def test_read_only_connection_cannot_mutate_user_library(self):
        reader=Library(self.library.path,read_only=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):reader.set_setting('unsafe','no')
            self.assertEqual(reader.channel_count(),0)
        finally:reader.close()

if __name__=='__main__':unittest.main()
