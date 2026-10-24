from pathlib import Path
import tempfile
import threading
import unittest
from tunplayer.core import Library
from tunplayer.jobs import CatalogReader


def entry(name,kind,url,**extra):
    return dict(dict(name=name,kind=kind,url=url,group_name='Exemple',tvg_id='',logo=''),**extra)

class Discovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.library=Library(Path(self.tmp.name)/'db.sqlite3')
    def tearDown(self):self.library.close();self.tmp.cleanup()

    def test_home_has_only_latest_movies_series_and_source_rated_trends(self):
        self.library.import_channels('Source',[
            entry('Ancien film','movie','https://example.org/m1',added=100,rating=9),
            entry('Nouveau film','movie','https://example.org/m2',added=200,rating=6),
            entry('Ancienne série','series','xtream-series:1',added=110,rating=7),
            entry('Nouvelle série','series','xtream-series:2',added=210,rating=8),
            entry('TV','live','https://example.org/live',added=999,rating=10)])
        reader=CatalogReader(self.library.path)
        data=reader.snapshot(dict(view='all',discovery=True,search='',page_size=60),threading.Event())
        self.assertEqual([s['key'] for s in data['sections']],['movies','series','trends'])
        self.assertEqual(data['groups'],[])
        self.assertEqual(data['sections'][0]['rows'][0]['name'],'Nouveau film')
        self.assertEqual(data['sections'][1]['rows'][0]['name'],'Nouvelle série')
        self.assertEqual(data['sections'][2]['rows'][0]['name'],'Ancien film')
        self.assertTrue(all(row['kind'] in ('movie','series') for s in data['sections'] for row in s['rows']))

    def test_each_home_section_honors_search_and_is_bounded(self):
        self.library.import_channels('Films',[entry(f'Film {i}','movie',f'https://example.org/{i}',added=i+1) for i in range(40)])
        sections=self.library.discovery(limit=12)
        self.assertEqual(len(sections[0]['rows']),12)
        self.assertEqual(sections[0]['rows'][0]['name'],'Film 39')
        filtered=self.library.discovery(search='film 39')
        self.assertEqual([row['name'] for row in filtered[0]['rows']],['Film 39'])
        self.assertFalse(filtered[1]['rows'])

    def test_first_seen_timestamp_survives_source_refresh(self):
        source=self.library.import_channels('Films',[entry('Un film','movie','https://example.org/m')])
        old=self.library.channels()[0]
        self.assertGreater(old['imported_at'],0)
        self.library.refresh_source(source,[entry('Film renommé','movie','https://example.org/m')])
        self.assertEqual(self.library.channel(old['id'])['imported_at'],old['imported_at'])

if __name__=='__main__':unittest.main()
