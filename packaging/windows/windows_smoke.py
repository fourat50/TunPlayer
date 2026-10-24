"""Run inside the installed bundle, with no MSYS2 environment on PATH."""
import argparse
import ctypes as C
import json
import platform
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path


def run(report,bundle):
    from tunplayer.app import App,GLib,Gdk
    from tunplayer.platform_support import win32_window_id,bundled_binary
    from tunplayer.player_catalog import neighbors
    state={'ok':False,'platform':platform.platform(),'python':sys.version}
    manifest=json.loads((bundle/'build-manifest.json').read_text())
    state.update(source_commit=manifest['source_commit'],version=manifest['version'])
    errors=[];phase=[0];engine=[None];app=None
    with tempfile.TemporaryDirectory(prefix='tunplayer-test-ete-') as directory:
        try:
            assert ssl.create_default_context().cert_store_stats()['x509_ca']>0,'No HTTPS trust store'
            subprocess.run([bundled_binary('ffmpeg'),'-version'],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            app=App(argparse.Namespace(data_dir=directory,screenshot=None))
            source=app.library.import_channels('Test',[dict(name='Serie locale',kind='series',url='xtream-series:1',provider_id='1',group_name='Tests',logo='',tvg_id='')])
            parent=app.library.channels(view='series',source_id=source)[0]
            second=Path(directory)/'episode-two.mp4';shutil.copyfile(bundle/'app/assets/demo.mp4',second)
            episodes=app.library.store_episodes(parent['id'],[dict(name=f'Episode {i}',kind='episode',url=str(path),provider_id=str(i),season=1,episode_num=i,group_name='Tests',logo='',tvg_id='') for i,path in ((1,bundle/'app/assets/demo.mp4'),(2,second))])
            original_hook=sys.excepthook
            def failure(kind,error,tb):
                errors.append(''.join(traceback.format_exception(kind,error,tb)))
                app.close()
            sys.excepthook=failure
            started=time.monotonic()
            def probe():
                if time.monotonic()-started>50:raise RuntimeError('Windows player smoke timed out')
                if not app.player or not app.media_loaded:return True
                app.tick()
                if phase[0]==0:
                    host=win32_window_id(app.video.get_window())
                    assert app.player.get('wid')==str(host),'Video detached from GTK host'
                    if app.player.get('width')!='1280':return True
                    user32=C.WinDLL('user32');user32.GetWindow.argtypes=[C.c_void_p,C.c_uint];user32.GetWindow.restype=C.c_void_p
                    user32.GetParent.argtypes=[C.c_void_p];user32.GetParent.restype=C.c_void_p
                    child=user32.GetWindow(host,5)
                    if not child:return True
                    assert user32.GetParent(child)==host,'No embedded mpv child HWND'
                    app.change_aspect('4:3');assert abs(float(app.player.get('video-aspect-override'))-4/3)<.001
                    app.command('cycle','pause');app.tick();assert app.player.get('pause')=='yes'
                    app.command('cycle','pause');app.command('seek',2,'absolute')
                    state.update(width=app.player.get('width'),height=app.player.get('height'),mpv=app.player.get('mpv-version'),video_output=app.player.get('current-vo'),embedded=True)
                    engine[0]=app.player;app.player_neighbors=neighbors(app.library,episodes[0]['id']);app.play_neighbor('next');phase[0]=1
                elif phase[0]==1:
                    assert app.current['id']==episodes[1]['id'] and app.player is engine[0],'Next episode replaced the embedded engine'
                    assert app.player.get('wid')==str(win32_window_id(app.video.get_window())),'Next episode detached video'
                    w,h=app.window.get_size();pix=Gdk.pixbuf_get_from_window(app.window.get_window(),0,0,w,h)
                    if pix:pix.savev(str(report.with_suffix('.png')),'png',[],[])
                    app.back_from_playback();assert app.current is None and app.view=='episodes'
                    state['ok']=True;state['next_episode']=True;app.close();return False
                return True
            def begin():app.play(episodes[0]);GLib.timeout_add(100,probe);return False
            GLib.timeout_add(700,begin)
            def timeout():errors.append('Timeout');app.close();return False
            GLib.timeout_add_seconds(65,timeout)
            try:app.run(['TunPlayer-Windows-Smoke'])
            finally:sys.excepthook=original_hook
            if errors:raise RuntimeError('\n'.join(errors))
            if not state['ok']:raise RuntimeError('Windows smoke stopped without completion')
        except BaseException:
            state.update(ok=False,error=traceback.format_exc())
        finally:
            if app:
                if not app.closing:app.close()
                for queue in (app.catalog_tasks,app.detail_tasks,app.writes):queue.pool.shutdown(wait=True)
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if state['ok'] else 1
