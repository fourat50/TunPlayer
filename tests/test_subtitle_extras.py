import json
from pathlib import Path
import tempfile
from types import SimpleNamespace,ModuleType
import unittest
from unittest.mock import patch
from scripts.build_standalone import bundle_python_extras
from tunplayer.subtitle_subliminal import SubliminalProvider
from test_subtitles import QUERY,SRT
import threading


class OptionalSubtitles(unittest.TestCase):
    def test_extra_bundle_requires_the_pinned_distribution_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir();target=root/'target'
            with self.assertRaises(RuntimeError):bundle_python_extras(source,target)
            metadata=source/'subliminal-2.8.0.dist-info';metadata.mkdir()
            (metadata/'METADATA').write_text('Metadata-Version: 2.1\nName: subliminal\nVersion: 2.8.0\n')
            (metadata/'LICENSE').write_text('MIT test fixture');(source/'subliminal.py').write_text('test=True\n')
            inventory=bundle_python_extras(source,target)
            self.assertEqual(inventory,{'subliminal':'2.8.0'});self.assertTrue((target/'subliminal-2.8.0.dist-info/LICENSE').is_file())

    def test_adapter_constructs_an_episode_from_metadata_without_a_stream_url(self):
        calls=[];pool_names=[]
        subtitle=SimpleNamespace(id='1',info='Saga S01E02',hearing_impaired=False,provider_name='gestdown',text=SRT.decode(),
            get_matches=lambda video:{'series','season','episode','year'})
        class Pool:
            def __init__(self,providers,**kwargs):pool_names.extend(providers)
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def list_subtitles_provider(self,name,video,languages):
                return SimpleNamespace(failure=lambda:False,outage=lambda:False,subtitles=[subtitle] if name=='gestdown' else [])
            def download_subtitle(self,value):return value is subtitle
        def episode(*args,**kwargs):calls.append((args,kwargs));return SimpleNamespace()
        modules={}
        for name in ('subliminal','subliminal.cache','babelfish'):modules[name]=ModuleType(name)
        modules['subliminal'].Movie=lambda *a,**k:None;modules['subliminal'].Episode=episode;modules['subliminal'].ProviderPool=Pool
        modules['subliminal.cache'].region=SimpleNamespace(is_configured=True)
        modules['babelfish'].Language=SimpleNamespace(fromietf=lambda value:value)
        with patch.dict('sys.modules',modules):
            rows=SubliminalProvider().search(QUERY,threading.Event());data,_=SubliminalProvider().download(rows[0])
        self.assertEqual(calls[0][0],('TunPlayer.mkv','Saga',1,2));self.assertEqual(data,SRT)
        self.assertEqual(rows[0]['score'],100);self.assertNotIn('opensubtitlescom',pool_names)
