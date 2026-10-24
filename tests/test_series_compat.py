from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tunplayer.core import Library,load_series_catalog,load_series,SourceError

CONFIG=dict(type='xtream',server='https://example.org',username='u',password='p')
SERIES=dict(id='parent',provider_id='7',name='Série',group_name='Drame',logo='')

class SeriesCompatibility(unittest.TestCase):
    @patch('tunplayer.core.request_xtream')
    def test_wrapped_numeric_series_response(self,request):
        request.side_effect=[{'data':[{'category_id':'1','category_name':'Drame'}]},
            {'data':{'12':{'series_id':7,'name':'Une série','category_id':'1','cover':'https://example.org/a.jpg'}}}]
        rows=load_series_catalog(CONFIG)
        self.assertEqual((rows[0]['provider_id'],rows[0]['group_name']),('7','Drame'))
        self.assertEqual([call.args[1] for call in request.call_args_list],['get_series_categories','get_series'])

    @patch('tunplayer.core.request_xtream')
    def test_auth_error_is_not_mistaken_for_empty_series(self,request):
        request.side_effect=[[],{'user_info':{'auth':0}}]
        with self.assertRaises(SourceError):load_series_catalog(CONFIG)

    @patch('tunplayer.core.request_xtream')
    def test_flat_episodes_and_dot_prefixed_extension(self,request):
        request.return_value={'episodes':[{'id':'42','season':2,'episode_num':3,'info':None,'container_extension':'.mkv'}]}
        rows=load_series(CONFIG,SERIES)
        self.assertEqual((rows[0]['season'],rows[0]['episode_num']),(2,3))
        self.assertTrue(rows[0]['url'].endswith('/42.mkv'))

    @patch('tunplayer.core.request_xtream')
    def test_nested_episode_lists_and_wrapped_response(self,request):
        request.return_value={'data':{'episodes':[[],[{'id':42,'episode_num':1,'info':[]}]]}}
        rows=load_series(CONFIG,SERIES)
        self.assertEqual((rows[0]['season'],rows[0]['episode_num']),(1,1))

    def test_series_only_refresh_preserves_live_movies_and_viewing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            library=Library(Path(directory)/'db.sqlite3')
            try:
                base=dict(name='Contenu',group_name='Groupe',tvg_id='',logo='')
                live=dict(base,kind='live',url='https://example.org/live')
                movie=dict(base,kind='movie',url='https://example.org/movie')
                first=dict(base,kind='series',url='xtream-series:1',provider_id='1')
                source=library.import_channels('TV',[live,movie,first],config=CONFIG)
                old=library.channels(view='movie')[0];library.favorite(old['id']);library.watched(old['id'],123)
                library.refresh_series_catalog(source,[dict(base,kind='series',url='xtream-series:2',provider_id='2')])
                self.assertEqual(library.channel(old['id'])['position'],123)
                self.assertEqual(library.channel(old['id'])['favorite'],1)
                self.assertEqual(library.sources()[0]['count'],3)
                library.refresh_series_catalog(source,[])
                self.assertEqual(library.channel_count(view='series'),1)
            finally:library.close()

if __name__=='__main__':unittest.main()
