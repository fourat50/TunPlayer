from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from tunplayer.core import Library
from tunplayer.player_catalog import PlayerCatalog,neighbors


def item(name,kind='live',group='Actualités',**extra):
    return dict(name=name,kind=kind,group_name=group,url=f'https://example.org/{kind}/{name}',tvg_id='',logo='',**extra)


class PlayerBrowsing(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.library=Library(Path(self.tmp.name)/'db.sqlite3')
        self.source=self.library.import_channels('Source',[item('Alpha'),item('Bravo'),item('Charlie'),item('Sport',group='Sport'),item('Film','movie')])
        self.current=self.library.channels(view='live',search='Bravo')[0]
        self.reader=PlayerCatalog(self.library.path);self.cancel=threading.Event()
        self.request=dict(current_id=self.current['id'],opened=True,kind='live',source_id=self.source,group='Actualités',search='',page=0)

    def tearDown(self):self.library.close();self.tmp.cleanup()

    def series(self):
        source=self.library.import_channels('Séries',[item('Saga','series',group='Drame')])
        parent=self.library.channels(view='series',source_id=source)[0]
        episodes=self.library.store_episodes(parent['id'],[
            item(f'Épisode {s}-{e}','episode',group='Drame',season=s,episode_num=e,provider_id=f'{s}-{e}') for s,e in [(1,1),(1,2),(2,1)]])
        return parent,episodes

    def test_live_neighbors_stay_in_source_category_and_type(self):
        self.library.import_channels('Autre source',[item('Blanc')])
        data=neighbors(self.library,self.current['id'])
        self.assertEqual((data['previous']['name'],data['next']['name']),('Alpha','Charlie'))
        self.assertIsNone(neighbors(self.library,data['previous']['id'])['previous'])
        self.assertIsNone(neighbors(self.library,data['next']['id'])['next'])

    def test_category_browsing_does_not_change_current_neighbors(self):
        data=self.reader.snapshot(dict(self.request,group='Sport'),self.cancel)
        self.assertEqual([r['name'] for r in data['rows']],['Sport'])
        self.assertEqual(data['neighbors']['next']['name'],'Charlie')
        self.assertEqual(self.library.channel(self.current['id'])['watched'],0)

    def test_movie_browser_only_returns_movies(self):
        movie=self.library.channels(view='movie')[0]
        data=self.reader.snapshot(dict(self.request,current_id=movie['id'],kind='movie',group=None),self.cancel)
        self.assertEqual([r['kind'] for r in data['rows']],['movie'])

    def test_movie_neighbors_exclude_other_categories(self):
        source=self.library.import_channels('Cinéma',[
            item('Aube','movie',group='Drame'),item('Midi','movie',group='Drame'),
            item('Soir','movie',group='Drame'),item('Mer','movie',group='Comédie')])
        current=self.library.channels(view='movie',source_id=source,search='Midi')[0]
        data=neighbors(self.library,current['id'])
        self.assertEqual((data['previous']['name'],data['next']['name']),('Aube','Soir'))

    def test_series_neighbors_cross_seasons_but_never_cross_parent(self):
        parent,episodes=self.series()
        self.library.import_channels('Autre série',[item('Autre','series')])
        data=neighbors(self.library,episodes[1]['id'])
        self.assertEqual(data['previous']['id'],episodes[0]['id']);self.assertEqual(data['next']['id'],episodes[2]['id'])
        self.assertIsNone(neighbors(self.library,episodes[2]['id'])['next'])

    def test_series_categories_and_episode_search_are_separate(self):
        parent,episodes=self.series()
        request=dict(self.request,current_id=episodes[1]['id'],source_id=parent['source_id'],kind='series',group='Drame')
        roots=self.reader.snapshot(request,self.cancel)
        self.assertEqual([r['id'] for r in roots['rows']],[parent['id']])
        data=self.reader.snapshot(dict(request,series_id=parent['id'],search='2-1'),self.cancel)
        self.assertEqual(data['parent']['id'],parent['id']);self.assertEqual([r['id'] for r in data['rows']],[episodes[2]['id']])
        self.assertEqual(data['neighbors']['previous']['id'],episodes[0]['id'])

    def test_foreign_parent_is_not_exposed_in_this_source(self):
        parent,episodes=self.series()
        data=self.reader.snapshot(dict(self.request,series_id=parent['id']),self.cancel)
        self.assertIsNone(data['parent']);self.assertEqual(data['total'],3)

    def test_large_category_focus_and_paging_remain_bounded(self):
        source=self.library.import_channels('Gros catalogue',[item(f'Canal {i:03}') for i in range(125)])
        current=self.library.channels(source_id=source,offset=104,limit=1)[0]
        request=dict(self.request,current_id=current['id'],source_id=source,focus=True)
        data=self.reader.snapshot(request,self.cancel)
        self.assertEqual((data['total'],data['page'],len(data['rows'])),(125,2,40))
        self.assertIn(current['id'],[r['id'] for r in data['rows']])
        last=self.reader.snapshot(dict(request,focus=False,page=999),self.cancel)
        self.assertEqual((last['page'],len(last['rows'])),(3,5))

    def test_hidden_browser_reads_only_neighbors_and_no_category_counts(self):
        with patch.object(Library,'group_counts',side_effect=AssertionError('Hidden browser counted categories')):
            data=self.reader.snapshot(dict(self.request,opened=False),self.cancel)
        self.assertEqual(data['rows'],[]);self.assertEqual(data['neighbors']['next']['name'],'Charlie')

    def test_cancelled_request_does_not_open_database(self):
        self.cancel.set()
        with patch('tunplayer.player_catalog.Library',side_effect=AssertionError('Cancelled request opened SQLite')):
            self.assertIsNone(self.reader.snapshot(self.request,self.cancel))

    def test_group_cache_reused_across_searches_and_revision_invalidates_it(self):
        self.reader.snapshot(self.request,self.cancel)
        with patch.object(Library,'group_counts',side_effect=AssertionError('Repeated category counts')):
            data=self.reader.snapshot(dict(self.request,search='Alpha'),self.cancel)
        self.assertEqual(data['total'],1)
        original=Library.group_counts
        with patch.object(Library,'group_counts',autospec=True,side_effect=original) as counted:
            self.reader.snapshot(dict(self.request,revision=1),self.cancel)
            self.assertEqual(counted.call_count,1)


if __name__=='__main__':unittest.main()
