import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tunplayer.core import Library, SourceError, load_source


def channel(url='https://example.org/one', name='Une', tvg_id='one', provider_id='', kind='live', group='Actualités'):
    return dict(url=url, name=name, tvg_id=tvg_id, provider_id=provider_id,
                kind=kind, group_name=group, logo='')


class Updates(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.library=Library(Path(self.tmp.name)/'library.sqlite3')

    def tearDown(self):
        self.library.close(); self.tmp.cleanup()

    def test_refresh_preserves_identity_favorite_and_movie_resume(self):
        source=self.library.import_channels('TV',[channel(kind='movie')],config={'type':'m3u','location':'old.m3u'})
        old=self.library.channels()[0]
        self.library.favorite(old['id']); self.library.watched(old['id'],412)
        watched=self.library.channel(old['id'])['watched']
        result=self.library.refresh_source(source,[channel(name='Une HD',kind='movie',group='Cinéma')],name='Films')
        current=self.library.channel(old['id'])
        self.assertEqual(result,dict(added=0,retained=1,removed=0,total=1))
        self.assertEqual((current['name'],current['group_name'],current['favorite'],current['position']),('Une HD','Cinéma',1,412))
        self.assertEqual(current['watched'],watched)
        self.assertEqual(self.library.sources()[0]['name'],'Films')
        self.assertEqual(self.library.source_config(source)['location'],'old.m3u')

    def test_token_rotation_uses_unique_tvg_id(self):
        source=self.library.import_channels('TV',[channel(url='https://example.org/one?token=old')])
        old=self.library.channels()[0]; self.library.favorite(old['id'])
        self.library.refresh_source(source,[channel(url='https://example.org/one?token=new')])
        self.assertEqual(self.library.channels()[0]['id'],old['id'])
        self.assertEqual(self.library.channels()[0]['favorite'],1)
        self.assertTrue(self.library.channels()[0]['url'].endswith('token=new'))

    def test_xtream_provider_id_preserves_state_without_epg(self):
        source=self.library.import_channels('TV',[channel(tvg_id='',provider_id='42')])
        old=self.library.channels()[0];self.library.favorite(old['id'])
        self.library.refresh_source(source,[channel(url='https://new.example.org/42.ts',tvg_id='',provider_id='42')])
        self.assertEqual(self.library.channels(view='favorites')[0]['id'],old['id'])

    def test_ambiguous_tvg_ids_never_merge_two_variants(self):
        source=self.library.import_channels('TV',[channel(url='https://example.org/sd'),channel(url='https://example.org/hd')])
        self.library.favorite(self.library.channels()[0]['id'])
        result=self.library.refresh_source(source,[channel(url='https://example.org/new-sd'),channel(url='https://example.org/new-hd')])
        self.assertEqual((result['added'],result['retained'],result['removed']),(2,0,2))
        self.assertFalse(self.library.channels(view='favorites'))

    def test_exact_matches_reserved_before_metadata_matches(self):
        source=self.library.import_channels('TV',[channel(url='https://example.org/a',tvg_id='shared'),channel(url='https://example.org/b',tvg_id='shared')])
        old={c['url']:c for c in self.library.channels()}
        result=self.library.refresh_source(source,[channel(url='https://example.org/new',tvg_id='shared'),channel(url='https://example.org/b',tvg_id='shared')])
        self.assertEqual(result['retained'],2)
        self.assertEqual(self.library.channel(old['https://example.org/b']['id'])['url'],'https://example.org/b')
        self.assertEqual(self.library.channel(old['https://example.org/a']['id'])['url'],'https://example.org/new')

    def test_removed_new_and_duplicate_entries(self):
        source=self.library.import_channels('TV',[channel(),channel(url='https://example.org/gone',tvg_id='gone')])
        result=self.library.refresh_source(source,[channel(),channel(url='https://example.org/new',tvg_id='new'),channel()])
        self.assertEqual(result,dict(added=1,retained=1,removed=1,total=2))
        self.assertEqual(self.library.sources()[0]['count'],2)

    def test_other_source_cannot_supply_a_match(self):
        first=self.library.import_channels('First',[channel()])
        other=self.library.import_channels('Other',[channel()])
        second=self.library.channels(source_id=other)[0]; self.library.favorite(second['id'])
        self.library.refresh_source(first,[channel(url='https://example.org/new')])
        self.assertEqual(self.library.channel(second['id'])['favorite'],1)
        self.assertEqual(self.library.channel(second['id'])['url'],'https://example.org/one')

    def test_empty_and_malformed_refresh_leave_library_untouched(self):
        source=self.library.import_channels('TV',[channel()])
        before=self.library.channels()
        for rows in [[],[channel(),{}],[channel(name=None)]]:
            with self.assertRaises((ValueError,KeyError)):
                self.library.refresh_source(source,rows,name='Broken',config={'type':'bad'})
            self.assertEqual(self.library.channels(),before)
            self.assertEqual(self.library.sources()[0]['name'],'TV')

    def test_database_failure_rolls_back_deletes_metadata_and_updates(self):
        source=self.library.import_channels('TV',[channel(),channel(url='https://example.org/old',tvg_id='old')])
        before=self.library.channels()
        self.library.db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON channels BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.library.refresh_source(source,[channel(name='Changed'),channel(url='https://example.org/new',tvg_id='new')],name='Broken')
        self.assertEqual(self.library.channels(),before)
        self.assertEqual(self.library.sources()[0]['name'],'TV')

    def test_refresh_of_deleted_source_fails(self):
        with self.assertRaises(SourceError):self.library.refresh_source(999,[channel()])

    def test_source_settings_persist_but_do_not_appear_in_lists(self):
        config={'type':'xtream','server':'https://example.org','username':'u','password':'secret-value'}
        source=self.library.import_channels('TV',[channel()],config=config)
        self.library.close(); self.library=Library(Path(self.tmp.name)/'library.sqlite3')
        self.assertEqual(self.library.source_config(source),config)
        self.assertNotIn('secret-value',json.dumps(self.library.sources()))
        self.assertTrue(self.library.sources()[0]['refreshable'])
        self.assertGreater(self.library.sources()[0]['updated_at'],0)

    def test_background_connection_refresh_visible_to_reader(self):
        source=self.library.import_channels('TV',[channel()])
        errors=[]
        def worker():
            db=Library(self.library.path)
            try:db.refresh_source(source,[channel(name='Nouveau nom')])
            except Exception as exc:errors.append(exc)
            finally:db.close()
        thread=threading.Thread(target=worker);thread.start();thread.join(timeout=5)
        self.assertFalse(thread.is_alive());self.assertFalse(errors)
        self.assertEqual(self.library.channels()[0]['name'],'Nouveau nom')

    def test_paging_no_missing_or_duplicate_rows_with_same_name(self):
        source=self.library.import_channels('Large',[channel(url=f'https://example.org/{i}',name='Même nom',tvg_id=str(i)) for i in range(241)])
        identities=[]
        for offset in range(0,241,60):
            page=self.library.channels(source_id=source,limit=60,offset=offset)
            self.assertLessEqual(len(page),60); identities.extend(c['id'] for c in page)
        self.assertEqual(len(identities),241);self.assertEqual(len(set(identities)),241)
        self.assertEqual(self.library.channel_count(source_id=source),241)
        self.assertFalse(self.library.channels(limit=60,offset=300))

    def test_literal_accent_insensitive_search_count_and_groups(self):
        source=self.library.import_channels('TV',[channel(name='ÉVASION 100%_',group='Découverte'),channel(url='https://example.org/two',name='Evasion classique',group='Films',kind='movie')])
        rows=self.library.channels(search='evasion',source_id=source)
        self.assertEqual(len(rows),2)
        self.assertEqual(self.library.channel_count(search='evasion',view='live',source_id=source),1)
        self.assertEqual(len(self.library.channels(search='%_')),1)
        self.assertEqual(self.library.groups(view='movie',source_id=source),['Films'])
        self.assertEqual(self.library.channel_count(search='decouverte'),1)

    def test_guide_only_counts_channels_with_upcoming_programmes(self):
        self.library.import_channels('TV',[channel(),channel(url='https://example.org/other',tvg_id='other')])
        now=time.time()
        self.library.import_epg([('one',now-60,now+600,'Now',''),('other',now-600,now-60,'Past','')])
        self.assertEqual(self.library.guide_count(),1)
        self.assertEqual(self.library.guide_channels()[0]['tvg_id'],'one')
        self.assertFalse(self.library.guide_channels(offset=1))

    def test_legacy_database_migrates_without_changing_state(self):
        path=Path(self.tmp.name)/'legacy.sqlite3'; db=sqlite3.connect(path)
        db.executescript('''CREATE TABLE sources(id INTEGER PRIMARY KEY,name TEXT,count INTEGER);
        CREATE TABLE channels(id TEXT PRIMARY KEY,source_id INTEGER,name TEXT,group_name TEXT,tvg_id TEXT,logo TEXT,url TEXT,kind TEXT,favorite INTEGER DEFAULT 0,watched REAL DEFAULT 0,position REAL DEFAULT 0);
        INSERT INTO sources VALUES(7,'Legacy',1);
        INSERT INTO channels VALUES('original-id',7,'Une','Actu','one','','https://example.org/one','movie',1,10,123);''')
        db.close(); migrated=Library(path)
        try:
            self.assertFalse(migrated.sources()[0]['refreshable'])
            migrated.refresh_source(7,[channel(kind='movie',name='Une HD')],config={'type':'m3u','location':'new.m3u'})
            current=migrated.channel('original-id')
            self.assertEqual((current['favorite'],current['position']),(1,123))
            self.assertEqual(current['name'],'Une HD')
        finally:migrated.close()


class SourceLoading(unittest.TestCase):
    @patch('tunplayer.core.read_resource',return_value='#EXTM3U\n#EXTINF:-1,News\nstream.m3u8')
    def test_m3u_refresh_resolves_relative_urls_from_stored_source(self,resource):
        rows=load_source({'type':'m3u','location':'https://example.org/list.m3u'})
        self.assertEqual(rows[0]['url'],'https://example.org/stream.m3u8')

    def test_unknown_source_requires_reconnection(self):
        with self.assertRaises(SourceError):load_source({})

if __name__=='__main__':unittest.main()
