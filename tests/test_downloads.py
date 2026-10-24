import io
import json
from pathlib import Path
import tempfile
import threading
import time
import shutil
import subprocess
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from tunplayer.downloads import DownloadManager,DownloadError,plan,safe_name


def movie(**extra):
    return dict(dict(id='movie-1',kind='movie',name='Un film',url='https://example.org/movie.mp4'),**extra)


class Response(io.BytesIO):
    def __init__(self,data,status=200,**headers):super().__init__(data);self.status=status;self.headers=headers


class Downloads(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.calls=[]
        self.content=b'test-video-content'*30
        self.manager=DownloadManager(self.root/'profile/downloads.json',self.opener)

    def tearDown(self):self.manager.close(wait=True);self.tmp.cleanup()

    def opener(self,request,timeout):
        self.calls.append(request)
        return Response(self.content,**{'Content-Type':'video/mp4','Content-Length':str(len(self.content)),'ETag':'"v1"'})

    def wait(self,predicate):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.01)
        self.fail('Transfer timed out: '+repr(self.manager.snapshot()))

    def add(self,channel=None):
        rows=plan([channel or movie()],self.root/'videos');self.manager.enqueue(rows);return rows[0]

    def state(self):return self.manager.snapshot()[0]['state']

    def test_download_finishes_without_exposing_a_partial_final_file(self):
        row=self.add();self.wait(lambda:self.state()=='done')
        self.assertEqual(Path(row['path']).read_bytes(),self.content)
        self.assertFalse(self.manager._part(row).exists())
        self.assertEqual(self.manager.journal.stat().st_mode&0o777,0o600)
        self.assertNotIn('url',self.manager.snapshot()[0])

    def test_existing_user_file_is_never_overwritten(self):
        row=plan([movie()],self.root/'videos')[0];path=Path(row['path']);path.parent.mkdir();path.write_bytes(b'keep')
        self.manager.enqueue([row]);self.wait(lambda:self.state()=='error')
        self.assertEqual(path.read_bytes(),b'keep');self.assertEqual(self.calls,[])

    def test_repeated_download_request_is_deduplicated(self):
        row=self.add();self.wait(lambda:self.state()=='done')
        self.assertEqual(self.manager.enqueue([row]),0);self.assertEqual(len(self.calls),1)

    def test_incomplete_download_is_not_marked_as_finished(self):
        with patch.object(self.manager,'opener',return_value=Response(b'half',**{'Content-Type':'video/mp4','Content-Length':'100','ETag':'"v1"'})):
            row=self.add();self.wait(lambda:self.state()=='error')
        self.assertFalse(Path(row['path']).exists());self.assertEqual(self.manager._part(row).read_bytes(),b'half')

    def test_error_page_is_not_saved_as_a_film(self):
        with patch.object(self.manager,'opener',return_value=Response(b'<html>Error</html>',**{'Content-Type':'text/html'})):
            row=self.add();self.wait(lambda:self.state()=='error')
        self.assertFalse(Path(row['path']).exists())

    def test_http_refusal_is_reported_without_exposing_the_source_url(self):
        error=HTTPError('https://example.org/private-password',403,'Forbidden',{},None)
        with patch.object(self.manager,'opener',side_effect=error):
            row=self.add();self.wait(lambda:self.state()=='error')
        message=self.manager.snapshot()[0]['error']
        self.assertIn('403',message);self.assertNotIn('private-password',message);self.assertFalse(Path(row['path']).exists())

    def test_unwritable_journal_does_not_crash_the_transfer_queue(self):
        blocked=self.root/'blocked';blocked.write_text('not a directory');self.manager.journal=blocked/'journal.json'
        row=self.add();self.wait(lambda:self.state()=='done')
        self.assertEqual(Path(row['path']).read_bytes(),self.content);self.assertTrue(self.manager.persistence_error)

    def test_weak_etag_never_resumes_by_concatenating_old_bytes(self):
        row=plan([movie()],self.root/'videos')[0];row.update(state='paused',etag='W/"v1"')
        part=self.manager._part(row);part.parent.mkdir();part.write_bytes(b'old-prefix')
        self.manager.enqueue([row]);self.wait(lambda:self.manager.idle);self.manager.resume(row['id']);self.wait(lambda:self.state()=='done')
        self.assertIsNone(self.calls[0].get_header('Range'));self.assertEqual(Path(row['path']).read_bytes(),self.content)

    def test_pause_and_resume_validate_http_range_and_etag(self):
        gate=threading.Event();first=Response(self.content,**{'Content-Type':'video/mp4','Content-Length':str(len(self.content)),'ETag':'"v1"'})
        original=first.read;reads=[0];requests=[]
        def read(size):
            reads[0]+=1
            if reads[0]==1:return original(5)
            gate.wait(3);return original(size)
        first.read=read
        def fetch(request,timeout):
            requests.append(request)
            if len(requests)==1:return first
            return Response(self.content[5:],206,**{'Content-Type':'video/mp4','Content-Range':f'bytes 5-{len(self.content)-1}/{len(self.content)}','ETag':'"v1"'})
        with patch.object(self.manager,'opener',side_effect=fetch):
            row=self.add();self.wait(lambda:self.manager.snapshot()[0]['downloaded']==5)
            self.manager.pause(row['id']);gate.set();self.wait(lambda:self.state()=='paused')
            self.assertEqual(self.manager._part(row).read_bytes(),self.content[:5])
            self.manager.resume(row['id']);self.wait(lambda:self.state()=='done')
        self.assertEqual(requests[1].get_header('Range'),'bytes=5-');self.assertEqual(requests[1].get_header('If-range'),'"v1"')
        self.assertEqual(Path(row['path']).read_bytes(),self.content)

    def test_invalid_content_range_never_corrupts_the_partial_file(self):
        row=plan([movie()],self.root/'videos')[0];row.update(state='paused',etag='"v1"')
        part=self.manager._part(row);part.parent.mkdir();part.write_bytes(b'first')
        self.manager.enqueue([row]);self.wait(lambda:self.manager.idle)
        with patch.object(self.manager,'opener',return_value=Response(b'bad',206,**{'Content-Type':'video/mp4','Content-Range':'bytes 0-2/8'})):
            self.manager.resume(row['id']);self.wait(lambda:self.state()=='error')
        self.assertEqual(part.read_bytes(),b'first');self.assertFalse(Path(row['path']).exists())

    def test_server_ignoring_range_restarts_without_appending(self):
        row=plan([movie()],self.root/'videos')[0];row.update(state='paused',etag='"old"')
        part=self.manager._part(row);part.parent.mkdir();part.write_bytes(b'old-prefix')
        self.manager.enqueue([row]);self.wait(lambda:self.manager.idle);self.manager.resume(row['id']);self.wait(lambda:self.state()=='done')
        self.assertEqual(Path(row['path']).read_bytes(),self.content)

    def test_restart_restores_interrupted_jobs_as_paused(self):
        row=plan([movie()],self.root/'videos')[0];row['state']='running'
        self.manager.journal.parent.mkdir();self.manager.journal.write_text(json.dumps([row]))
        other=DownloadManager(self.manager.journal,self.opener)
        try:self.assertEqual(other.snapshot()[0]['state'],'paused');self.assertEqual(self.calls,[])
        finally:other.close(wait=True)

    def test_season_plan_contains_every_episode_and_safe_paths(self):
        series=dict(id='series-1',name='../../Une série')
        episodes=[movie(id=f'e-{i}',kind='episode',name=f'../../Episode {i}',season=2,episode_num=i,url=f'https://example.org/{i}.mp4') for i in range(1,71)]
        result=plan(episodes,self.root,series)
        self.assertEqual(len(result),70);self.assertEqual(len({row['path'] for row in result}),70)
        for row in result:
            self.assertTrue(Path(row['path']).is_relative_to(self.root));self.assertIn('Saison 02',row['path']);self.assertNotIn('..',Path(row['path']).parts)

    def test_live_radio_and_command_urls_are_rejected(self):
        for channel in (movie(kind='live'),movie(radio=True),movie(url='file:///etc/passwd'),movie(url='exec:run')):
            with self.subTest(channel=channel),self.assertRaises(DownloadError):plan([channel],self.root)

    def test_filename_is_bounded_and_has_no_path_separators(self):
        name=safe_name('../é'*300)
        self.assertNotIn('/',name);self.assertLessEqual(len(name.encode()),120)

    def test_cancel_removes_only_the_owned_partial_file(self):
        row=plan([movie()],self.root/'videos')[0];row['state']='paused'
        part=self.manager._part(row);part.parent.mkdir();part.write_bytes(b'partial')
        unrelated=part.parent/'other.mp4';unrelated.write_bytes(b'keep')
        self.manager.enqueue([row]);self.wait(lambda:self.manager.idle)
        self.manager.pause(row['id'],cancel=True)
        self.assertEqual(self.state(),'cancelled');self.assertFalse(part.exists());self.assertEqual(unrelated.read_bytes(),b'keep')

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required for the real segmented-media pipeline')
    def test_segmented_transfer_uses_real_ffmpeg_and_keeps_the_video_playable(self):
        playlist=self.root/'fixture.m3u8'
        media=Path(__file__).resolve().parents[1]/'assets/demo.mp4'
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-i',str(media),'-t','1','-c','copy',
            '-hls_time','1','-hls_list_size','0',str(playlist)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        original=subprocess.Popen;commands=[]
        def local_fixture(arguments,**kwargs):
            commands.append(list(arguments));arguments=list(arguments)
            # Only the test substitutes a local playlist for the remote source;
            # production continues to restrict segmented inputs to network URLs.
            arguments[arguments.index('-i')+1]=str(playlist)
            at=arguments.index('-protocol_whitelist')+1;arguments[at]+=',file'
            return original(arguments,**kwargs)
        with patch('tunplayer.downloads.subprocess.Popen',side_effect=local_fixture):
            row=self.add(movie(url='https://example.org/fixture.m3u8'))
            self.wait(lambda:self.state() in ('done','error'))
        self.assertEqual(self.state(),'done',self.manager.snapshot())
        self.assertEqual(Path(row['path']).suffix,'.mkv');self.assertIn('-n',commands[0]);self.assertNotIn('-y',commands[0])
        subprocess.run(['ffmpeg','-v','error','-i',row['path'],'-frames:v','1','-f','null','-'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
