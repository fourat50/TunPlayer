"""Measure actual MPEG-TS startup with paced local input, without a provider."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from tunplayer.player import Player


@unittest.skipUnless(hasattr(os,'mkfifo') and shutil.which('ffmpeg'),'FIFO and FFmpeg required')
class StartupLatency(unittest.TestCase):
    def test_live_probe_needs_less_input_while_retaining_audio_and_video(self):
        with tempfile.TemporaryDirectory(prefix='tunplayer-startup-') as folder:
            root=Path(folder);media=root/'sample.ts'
            subprocess.run(['ffmpeg','-v','error','-stream_loop','1','-i',str(Path(__file__).resolve().parents[1]/'assets/demo.mp4'),
                            '-t','15','-c','copy','-f','mpegts',str(media)],check=True,timeout=10)
            payload=media.read_bytes();results=[]
            for fast in (False,True):
                fifo=root/('fast.ts' if fast else 'normal.ts');os.mkfifo(fifo)
                stop=threading.Event();consumed=[0];player=Player(headless=True)
                if fast:player.prepare_stream({'kind':'live','url':'https://example.org/live.ts'})
                def write():
                    try:
                        with open(fifo,'wb',buffering=0) as stream:
                            for offset in range(0,len(payload),1316):
                                if stop.is_set():break
                                chunk=payload[offset:offset+1316];stream.write(chunk);consumed[0]+=len(chunk)
                                stop.wait(1316/(len(payload)/15))
                    except (BrokenPipeError,OSError):pass
                writer=threading.Thread(target=write,daemon=True);writer.start();start=time.monotonic()
                try:
                    player.command('loadfile',str(fifo))
                    loaded=False
                    while time.monotonic()-start<10:
                        events=player.events()
                        self.assertFalse([e for e in events if e[0]=='error'])
                        if any(e[0]=='loaded' for e in events):loaded=True;break
                        time.sleep(.01)
                    self.assertTrue(loaded)
                    results.append({'bytes':consumed[0],'seconds':time.monotonic()-start})
                    self.assertTrue({'audio','video'}.issubset({track['type'] for track in player.tracks()}))
                finally:stop.set();player.close();writer.join(1)
            self.assertLess(results[1]['bytes'],results[0]['bytes']*.9,results)
