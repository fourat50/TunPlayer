import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tunplayer.core import Library, SourceError, parse_m3u, xtream, load_series
from tunplayer.catalog import metadata


def entry(name='Film',kind='movie',url='https://example.org/film.mp4',**extra):
    return dict(dict(name=name,kind=kind,url=url,group_name='Cinéma',tvg_id='',logo=''),**extra)

class Catalogue(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.library=Library(Path(self.tmp.name)/'db.sqlite3')
    def tearDown(self):self.library.close();self.tmp.cleanup()

    def test_m3u_logos_language_and_series_classification(self):
        rows=parse_m3u('''#EXTM3U
#EXTINF:-1 tvg-logo="/logos/tv.png" tvg-language="FR",News FHD
https://example.org/live/a.ts
#EXTINF:-1 tvg-logo="https://example.org/poster.jpg" genre="Drame" year="2024",Série S01E02
https://example.org/video.mp4
''','https://example.org/list.m3u')
        self.assertEqual(rows[0]['logo'],'https://example.org/logos/tv.png')
        self.assertEqual((rows[0]['quality'],rows[0]['language']),('FHD','fr'))
        self.assertEqual((rows[1]['kind'],rows[1]['year'],rows[1]['genre']),('series',2024,'Drame'))

    def test_metadata_is_optional_and_never_makes_up_quality(self):
        self.assertEqual(metadata({'name':'Sans métadonnées'})['quality'],'')
        self.assertEqual(metadata({'name':'Film (2021) UHD','rating':'8,2'})['year'],2021)
        self.assertEqual(metadata({'rating':'NaN'})['rating'],0)
        self.assertEqual(metadata({'rating':'Infinity'})['rating'],0)

    def test_combined_filters_count_matches_rows_and_no_wildcard_expansion(self):
        self.library.import_channels('TV',[
            entry(name='Évasion 4K (2024)',year=2024,genre='Drame, Action',rating=8.2,language='FR',logo='https://example.org/poster.jpg'),
            entry(name='Évasion HD (2022)',year=2022,genre='Action',rating=6.2,language='EN',url='https://example.org/other.mp4'),
            entry(name='TV',kind='live',url='https://example.org/live.ts')])
        identity=self.library.channels(search='2024')[0]['id'];self.library.favorite(identity)
        filters=dict(search='evasion action',view='movie',quality='UHD',language='fr',year=2024,genre='drame',min_rating=8,favorites=True,has_artwork=True)
        self.assertEqual(self.library.channel_count(**filters),1)
        self.assertEqual(self.library.channels(**filters)[0]['id'],identity)
        self.library.watched(identity,4)
        self.assertEqual(self.library.channel_count(**filters,unwatched=True),0)
        self.assertEqual(self.library.channel_count(search='%'),0)

    def test_artwork_filter_cannot_bypass_other_filters(self):
        self.library.import_channels('TV',[entry(logo='https://example.org/p.jpg'),entry(name='TV',kind='live',url='https://example.org/live.ts',logo='https://example.org/logo.png')])
        self.assertEqual(self.library.channel_count(view='movie',has_artwork=True),1)
        self.assertFalse(self.library.channels(search='missing',has_artwork=True))

    def test_sort_choices_and_genre_facets(self):
        self.library.import_channels('Films',[entry(name='B',year=2022,rating=9,added=5,genre='Action / Drame'),entry(name='A',url='https://example.org/a',year=2024,rating=7,added=10,genre='Action')])
        self.assertEqual([x['name'] for x in self.library.channels(sort='name')],['A','B'])
        self.assertEqual(self.library.channels(sort='rating')[0]['name'],'B')
        self.assertEqual(self.library.channels(sort='year')[0]['name'],'A')
        self.assertEqual(self.library.channels(sort='added')[0]['name'],'A')
        self.assertEqual(self.library.facets()['genre'],['Action','Drame'])
        with self.assertRaises(SourceError):self.library.channels(sort='DROP TABLE channels')

    def test_refresh_updates_poster_metadata_and_search_without_losing_favorite(self):
        source=self.library.import_channels('Films',[entry()]);old=self.library.channels()[0];self.library.favorite(old['id'])
        self.library.refresh_source(source,[entry(name='Nouveau',genre='Science-fiction',year=2025,rating=8,logo='https://example.org/new.jpg')])
        self.assertEqual(self.library.channels(search='science-fiction',year=2025)[0]['id'],old['id'])
        self.assertEqual(self.library.channels(view='favorites')[0]['logo'],'https://example.org/new.jpg')

    def test_series_episode_resume_survives_catalogue_and_episode_refresh(self):
        config=dict(type='xtream',server='https://example.org',username='u',password='p')
        parent=entry(name='Série',kind='series',url='xtream-series:7',provider_id='7',logo='https://example.org/s.jpg')
        source=self.library.import_channels('TV',[parent],config=config)
        series=self.library.channels(view='series')[0]
        ep=entry(name='Pilote',kind='episode',url='https://example.org/series/u/p/11.mp4',provider_id='11',season=1,episode_num=1,parent_id=series['id'])
        episode=self.library.store_episodes(series['id'],[ep])[0];self.library.watched(episode['id'],124)
        self.library.favorite(episode['id'])
        self.assertEqual(self.library.channels(view='favorites')[0]['id'],episode['id'])
        self.assertEqual(self.library.channel_count(),1)
        self.assertEqual(self.library.channels(view='history')[0]['id'],episode['id'])
        self.library.refresh_source(source,[dict(parent,name='Série HD')])
        self.assertEqual(self.library.channel(episode['id'])['position'],124)
        self.library.store_episodes(series['id'],[dict(ep,url='https://example.org/new/11.mp4')])
        self.assertEqual(self.library.episodes(series['id'])[0]['id'],episode['id'])
        self.assertEqual(self.library.episodes(series['id'])[0]['position'],124)
        self.assertEqual(self.library.sources()[0]['count'],1)
        self.library.delete_source(source);self.assertIsNone(self.library.channel(episode['id']))

    def test_failed_episode_response_keeps_loaded_episodes(self):
        self.library.import_channels('TV',[entry(kind='series',url='xtream-series:7')]);series=self.library.channels()[0]
        rows=[entry(kind='episode',provider_id='1')]
        self.library.store_episodes(series['id'],rows)
        for invalid in [[],[entry(kind='movie',provider_id='1')],[entry(kind='episode',provider_id='1'),entry(kind='episode',provider_id='1',url='https://other.example.org/video')]]:
            with self.assertRaises(SourceError):self.library.store_episodes(series['id'],invalid)
            self.assertEqual(len(self.library.episodes(series['id'])),1)

    @patch('tunplayer.core.read_resource')
    def test_xtream_imports_series_covers_and_metadata(self,resource):
        resource.side_effect=['[]','[]','[]','[]',json.dumps([{'category_id':'2','category_name':'Drame'}]),json.dumps([{'series_id':7,'name':'Une série','cover':'https://example.org/cover.jpg','category_id':'2','genre':'Drama','rating':'8.5','releaseDate':'2023-01-01'}])]
        rows=xtream('https://example.org','u','p')
        self.assertEqual((rows[0]['kind'],rows[0]['url']),('series','xtream-series:7'))
        self.assertEqual((rows[0]['logo'],rows[0]['year'],rows[0]['rating']),('https://example.org/cover.jpg',2023,8.5))

    @patch('tunplayer.core.read_resource')
    def test_series_details_create_safe_playable_episode_urls(self,resource):
        resource.return_value=json.dumps({'episodes':{'2':[{'id':'42','episode_num':3,'title':'Le retour','container_extension':'mkv','info':{'movie_image':'https://example.org/ep.jpg'}}]}})
        rows=load_series(dict(type='xtream',server='https://example.org',username='a/b',password='p?ss'),dict(id='parent',name='Série',group_name='Drame',provider_id='7',logo=''))
        self.assertEqual(rows[0]['url'],'https://example.org/series/a%2Fb/p%3Fss/42.mkv')
        self.assertEqual((rows[0]['season'],rows[0]['episode_num']),(2,3))
        self.assertIn('S02E03',rows[0]['name'])

if __name__=='__main__':unittest.main()
