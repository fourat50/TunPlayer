import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import cairo
from gi.repository import GLib
from tunplayer.artwork import ArtworkCache, ArtworkLoader, MAX_IMAGE, decode_image


def png(width=40,height=60):
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,width,height)
    cr=cairo.Context(surface);cr.set_source_rgb(.2,.6,.4);cr.paint()
    stream=io.BytesIO();surface.write_to_png(stream);return stream.getvalue()

class Response(io.BytesIO):
    def geturl(self):return 'https://example.org/image.png'

class Images(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.tmp.cleanup()

    def test_decode_real_png_and_reduce_large_image(self):
        image=decode_image(png(1440,2160))
        self.assertEqual((image.get_width(),image.get_height()),(720,1080))

    def test_reject_corrupt_oversized_and_non_raster_content(self):
        for data in [b'<svg/>',b'not an image',b'\x89PNG\r\n\x1a\nBAD',b'x'*(MAX_IMAGE+1)]:
            with self.assertRaises((ValueError,GLib.Error)):decode_image(data)

    @patch('tunplayer.artwork.urllib.request.urlopen')
    def test_download_once_then_decode_from_cache(self,request):
        request.side_effect=lambda *a,**k:Response(png())
        cache=ArtworkCache(self.tmp.name)
        url='https://example.org/image?token=private'
        self.assertEqual(cache.load(url).get_height(),60)
        self.assertEqual(cache.load(url).get_height(),60)
        self.assertEqual(request.call_count,1)
        files=list(Path(self.tmp.name).glob('*.image'))
        self.assertEqual(len(files),1);self.assertNotIn('private',files[0].name)
        self.assertEqual(files[0].stat().st_mode&0o777,0o600)

    @patch('tunplayer.artwork.urllib.request.urlopen')
    def test_bad_cached_image_is_replaced(self,request):
        request.side_effect=lambda *a,**k:Response(png())
        cache=ArtworkCache(self.tmp.name);url='https://example.org/logo.png'
        cache.path_for(url).write_bytes(b'bad data')
        self.assertEqual(cache.load(url).get_width(),40)
        self.assertEqual(request.call_count,1)

    @patch('tunplayer.artwork.urllib.request.urlopen')
    def test_cache_budget_evicts_oldest_image(self,request):
        data=png();request.side_effect=lambda *a,**k:Response(data)
        cache=ArtworkCache(self.tmp.name,budget=len(data)+1)
        cache.load('https://example.org/first');cache.load('https://example.org/second')
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.image'))),1)
        self.assertTrue(cache.path_for('https://example.org/second').exists())

    @patch('tunplayer.artwork.urllib.request.urlopen')
    def test_no_files_or_commands_from_provider_image_urls(self,request):
        cache=ArtworkCache(self.tmp.name)
        for url in ['file:///etc/passwd','av://lavfi:testsrc','data:image/png;base64,abc']:
            self.assertIsNone(cache.load(url))
        request.assert_not_called()

    def wait(self,predicate):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            while GLib.MainContext.default().iteration(False):pass
            if predicate():return
            time.sleep(.01)
        self.fail('Artwork delivery timed out')

    def test_async_duplicate_requests_share_download_and_deliver_on_main_thread(self):
        loader=ArtworkLoader(self.tmp.name);received=[];main_thread=threading.get_ident();release=threading.Event()
        def work(url):release.wait(2);return decode_image(png())
        try:
            with patch.object(loader.cache,'load',side_effect=work) as fetch:
                callback=lambda image:received.append((image.get_width(),threading.get_ident()))
                loader.request('https://example.org/logo',callback)
                loader.request('https://example.org/logo',callback)
                release.set();self.wait(lambda:len(received)==2)
                self.assertEqual(fetch.call_count,1)
                self.assertEqual(received,[(40,main_thread),(40,main_thread)])
        finally:release.set();loader.close()

    def test_page_change_drops_stale_image_callbacks(self):
        loader=ArtworkLoader(self.tmp.name);release=threading.Event();started=threading.Event();received=[]
        def work(url):started.set();release.wait(2);return decode_image(png())
        try:
            with patch.object(loader.cache,'load',side_effect=work):
                loader.request('https://example.org/logo',lambda image:received.append('stale'))
                self.assertTrue(started.wait(1));loader.retire()
                loader.request('https://example.org/logo',lambda image:received.append('current'))
                release.set();self.wait(lambda:not loader.pending)
                self.assertEqual(received,['current'])
        finally:release.set();loader.close()

if __name__=='__main__':unittest.main()
