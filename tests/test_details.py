import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tunplayer.core import Library,load_vod_details,load_series,SourceError
from tunplayer.catalog import metadata


def entry(kind='movie',url='https://example.org/movie',**extra):
    return dict(dict(name='Un titre',kind=kind,url=url,group_name='Cinéma',tvg_id='',logo='',provider_id='7'),**extra)

class MediaDetails(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.lib=Library(Path(self.tmp.name)/'db.sqlite3')
    def tearDown(self):self.lib.close();self.tmp.cleanup()
    @patch('tunplayer.core.request_xtream')
    def test_vod_details_parse_cast_duration_and_cover(self,request):
        request.return_value={'movie_data':{'year':2024},'info':{'plot':'Le synopsis','cast':[{'name':'Actrice A'},'Acteur B'],
            'director':'Réalisatrice C','duration_secs':9120,'movie_image':'https://example.org/poster.jpg'}}
        details=load_vod_details(dict(type='xtream'),entry())
        self.assertEqual((details['cast'],details['director'],details['duration_seconds']),('Actrice A, Acteur B','Réalisatrice C',9120))
        self.assertEqual(details['logo'],'https://example.org/poster.jpg')
        self.assertEqual(details['year'],2024)
        self.assertEqual(request.call_args.kwargs,{'vod_id':'7'})
    def test_formatted_duration_and_episode_minutes(self):
        self.assertEqual(metadata({'duration':'02:32:00'})['duration_seconds'],9120)
        self.assertEqual(metadata({'episode_run_time':45})['duration_seconds'],2700)
    def test_full_details_survive_catalogue_refresh_and_do_not_change_identity(self):
        source=self.lib.import_channels('Films',[entry()]);old=self.lib.channels()[0]
        self.lib.favorite(old['id']);self.lib.watched(old['id'],123)
        self.lib.update_details(old['id'],dict(plot='Synopsis enrichi',cast='Actrice A',duration_seconds=9120,genre='Aventure'))
        self.lib.refresh_source(source,[entry(name='Titre actualisé')])
        current=self.lib.channel(old['id'])
        self.assertEqual((current['plot'],current['cast'],current['duration_seconds']),('Synopsis enrichi','Actrice A',9120))
        self.assertEqual((current['position'],current['favorite']),(123,1))
        self.assertGreater(current['details_loaded_at'],0)
    def test_completed_episode_selects_next_across_seasons(self):
        self.lib.import_channels('Séries',[entry(kind='series',url='xtream-series:7')]);parent=self.lib.channels()[0]
        rows=[entry(kind='episode',url=f'https://example.org/ep{i}',provider_id=str(i),season=season,episode_num=number) for i,season,number in [(1,1,1),(2,1,2),(3,2,1)]]
        episodes=self.lib.store_episodes(parent['id'],rows);first,second,third=episodes
        self.lib.watched(second['id'],30)
        self.assertEqual(self.lib.continue_episode(parent['id'])['id'],second['id'])
        self.lib.finish_media(second['id'])
        self.assertEqual((self.lib.channel(second['id'])['completed'],self.lib.channel(second['id'])['position']),(1,0))
        self.assertEqual(self.lib.continue_episode(parent['id'])['id'],third['id'])
        self.assertEqual(self.lib.next_episode(first['id'])['id'],second['id'])
        self.assertIsNone(self.lib.next_episode(third['id']))
    @patch('tunplayer.core.request_xtream')
    def test_series_response_supplies_details_and_numbered_episodes(self,request):
        request.return_value={'info':{'plot':'Une aventure','cast':'A, B','episode_run_time':42},'episodes':{'1':[{'id':42,'title':'Pilote','info':{'duration':'00:42:00'}}]}}
        data=load_series(dict(type='xtream',server='https://example.org',username='u',password='p'),dict(entry(kind='series'),id='parent'),with_details=True)
        self.assertEqual(data['details']['cast'],'A, B')
        self.assertEqual(data['episodes'][0]['episode_num'],1)
        self.assertEqual(data['episodes'][0]['duration_seconds'],2520)
    @patch('tunplayer.core.request_xtream',return_value={'user_info':{'auth':0}})
    def test_bad_details_are_not_stored(self,request):
        with self.assertRaises(SourceError):load_vod_details(dict(type='xtream'),entry())

if __name__=='__main__':unittest.main()
