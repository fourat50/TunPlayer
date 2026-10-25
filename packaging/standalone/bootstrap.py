"""Configure the private Linux runtime without changing the tagged application."""
import ctypes.util
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'runtime'


def prepare():
    if Path(sys.prefix).resolve()!=RUNTIME.resolve():raise RuntimeError('Python ne provient pas du runtime prive.')
    sys.path.insert(0,str(RUNTIME/'python-packages'))
    sys.path.insert(0,str(ROOT/'app'))
    # find_library normally consults the host ldconfig cache, which may lack mpv.
    original=ctypes.util.find_library
    ctypes.util.find_library=lambda name: str(RUNTIME/'lib/libmpv.so.2') if name=='mpv' else original(name)
    cache=Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))/'tunplayer/standalone'
    cache.mkdir(parents=True,exist_ok=True)
    identity=hashlib.sha256((str(ROOT)+(ROOT/'build-info.json').read_text()).encode()).hexdigest()[:20]
    loaders=sorted((RUNTIME/'pixbuf-loaders').glob('*.so'))
    module_file=cache/f'pixbuf-{identity}.cache'
    if not module_file.exists():
        result=subprocess.run([str(RUNTIME/'bin/gdk-pixbuf-query-loaders'),*map(str,loaders)],capture_output=True,check=True)
        temporary=module_file.with_suffix(f'.{os.getpid()}.tmp')
        temporary.write_bytes(result.stdout);os.replace(temporary,module_file)
    os.environ['GDK_PIXBUF_MODULE_FILE']=str(module_file)
    os.environ['GDK_PIXBUF_MODULEDIR']=str(RUNTIME/'pixbuf-loaders')
    config=cache/f'fonts-{identity}.conf'
    font_cache=cache/'fonts';font_cache.mkdir(exist_ok=True)
    config.write_text('<?xml version="1.0"?><fontconfig><dir>'+escape(str(RUNTIME/'share/fonts'))+
        '</dir><dir>/usr/share/fonts</dir><cachedir>'+escape(str(font_cache))+'</cachedir></fontconfig>',encoding='utf-8')
    os.environ['FONTCONFIG_FILE']=str(config)
    os.environ['FONTCONFIG_PATH']=str(RUNTIME/'share')


def check():
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('GdkPixbuf','2.0')
    from gi.repository import Gtk,GdkPixbuf
    import cairo
    import ssl
    from tunplayer.player import Player
    assert str(RUNTIME) in gi.__file__ and str(RUNTIME) in cairo.__file__
    assert ssl.create_default_context().cert_store_stats()['x509_ca']>0
    pix=GdkPixbuf.Pixbuf.new_from_file(str(ROOT/'app/assets/tunplayer.svg'))
    assert pix.get_width()>0
    if (ROOT/'app/tunplayer/visuals.py').exists():
        from tunplayer.visuals import ICONS,icon_pixbuf
        for name in ICONS:assert icon_pixbuf(name).get_width()>0,'Icone invalide : '+name
    subtitle_sources=[]
    if (ROOT/'app/tunplayer/subtitles.py').exists():
        from tunplayer.subtitles import SubtitleService,subtitle_text
        from tunplayer.subtitle_languages import LANGUAGES
        assert len(LANGUAGES)>=184
        assert subtitle_text(b'1\n00:00:00,000 --> 00:00:01,000\nTest\n','test.srt')[1]=='.srt'
        subtitle_sources=list(SubtitleService().providers())
        assert {'podnapisi','opensubtitles'}.issubset(subtitle_sources)
        if (ROOT/'app/tunplayer/subtitle_subdl.py').exists():assert 'subdl' in subtitle_sources
        if 'subliminal' in json.loads((ROOT/'build-info.json').read_text()).get('python_extras',{}):
            assert 'subliminal' in subtitle_sources,'Extension Subliminal incomplete'
    subprocess.run([str(RUNTIME/'bin/ffmpeg'),'-version'],check=True,stdout=subprocess.DEVNULL)
    subprocess.run([str(RUNTIME/'bin/ffmpeg'),'-v','error','-i',str(ROOT/'app/assets/demo.mp4'),
        '-frames:v','1','-f','null','-'],check=True,stdout=subprocess.DEVNULL,timeout=20)
    player=Player(headless=True)
    try:
        player.command('loadfile',str(ROOT/'app/assets/demo.mp4'))
        deadline=time.monotonic()+10
        while time.monotonic()<deadline and player.get('width')!='1280':
            player.events();time.sleep(.03)
        assert player.get('width')=='1280','Decodage mpv absent'
        player.set_aspect('4:3')
        assert abs(float(player.get('video-aspect-override'))-4/3)<.001
        player.command('cycle','pause');assert player.get('pause')=='yes'
        libraries={line.split(None,5)[-1] for line in Path('/proc/self/maps').read_text().splitlines() if '.so' in line}
        private=[p for p in libraries if str(RUNTIME) in p]
        drivers=[p for p in libraries if re.fullmatch(r'lib(?:cuda\.so.*|nvidia-.*)',Path(p).name)]
        external=[p for p in libraries if str(RUNTIME) not in p and p not in drivers and not re.fullmatch(
            r'(?:ld-linux.*|lib(?:c|m|pthread|rt|dl|resolv|anl|util|nss_\w+)\.so(?:\..*)?)',Path(p).name)]
        assert not external,'Bibliotheques externes imprevues : '+repr(external)
        for component in ('libmpv.so','libgtk-3.so','libgirepository','libavcodec.so'):
            assert any(component in p for p in private),component+' non charge depuis le runtime'
        print(json.dumps(dict(ok=True,python=sys.executable,prefix=sys.prefix,gtk=Gtk.get_major_version(),
            mpv=player.get('mpv-version'),width=player.get('width'),private_libraries=len(private),
            host_driver_libraries=sorted(drivers),subtitle_sources=subtitle_sources),ensure_ascii=False))
    finally:player.close()


if __name__=='__main__':
    prepare()
    if sys.argv[1:]==['--self-test']:check()
    else:
        from tunplayer.app import main
        main()
