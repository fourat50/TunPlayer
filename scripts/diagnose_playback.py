#!/usr/bin/env python3
"""Time actual playback on the desktop, without logging stream URLs or credentials."""
import argparse
import functools
import importlib
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-path',type=Path,default=Path('/opt/tunplayer/app') if Path('/opt/tunplayer/app/tunplayer').is_dir() else ROOT)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/playback-diagnostic.json')
    args=parser.parse_args();sys.path.insert(0,str(args.app_path))
    module=importlib.import_module('tunplayer.app')
    from tunplayer import __version__
    from tunplayer.subtitles import private_json
    report={'version':__version__,'app_path':str(args.app_path),'sessions':[],'slow_calls':[]}
    active=None;start=0
    def save():private_json(args.output,report)
    original_play=module.App.play
    @functools.wraps(original_play)
    def play(self,channel,*a,**kw):
        nonlocal active,start
        start=time.monotonic();active={'kind':channel.get('kind') if channel else None,'phases':[]}
        report['sessions'].append(active);save()
        print('Ouverture : '+str(active['kind']),flush=True)
        return original_play(self,channel,*a,**kw)
    module.App.play=play
    def wrap(name):
        original=getattr(module.App,name)
        @functools.wraps(original)
        def measured(self,*a,**kw):
            before=time.monotonic();session=active
            try:return original(self,*a,**kw)
            finally:
                duration=time.monotonic()-before
                if session is not None and name not in ('tick','update_source_status'):
                    session['phases'].append({'name':name,'at_s':round(before-start,4),'duration_s':round(duration,4)})
                    save()
                if duration>.1:
                    report['slow_calls'].append({'name':name,'duration_s':round(duration,4)})
                    report['slow_calls']=report['slow_calls'][-100:]
                    print(f'  Appel lent : {name} · {duration:.3f} s',flush=True);save()
                if name=='tick' and session is not None and self.media_loaded and 'loaded_s' not in session:
                    session['loaded_s']=round(time.monotonic()-start,4)
                    print(f'  Média chargé en {session["loaded_s"]:.3f} s',flush=True);save()
                if name=='tick' and session is not None and self.media_loaded and self.position>0 and 'playing_s' not in session:
                    session['playing_s']=round(time.monotonic()-start,4);save()
        setattr(module.App,name,measured)
    for name in ('configure_player_browser','update_player_identity','navigate','open_current_stream','load_current_stream','ensure_player','tick','update_source_status','open_series','open_details'):
        if hasattr(module.App,name):wrap(name)
    print(f'Diagnostic de lecture · TunPlayer {__version__}',flush=True)
    print('Ouvrez une chaîne, un film, puis un épisode ; fermez ensuite TunPlayer.',flush=True)
    sys.argv=[sys.argv[0]]
    try:return module.main()
    finally:
        save();print('Rapport sans URL ni identifiants : '+str(args.output),flush=True)


if __name__=='__main__':raise SystemExit(main())
