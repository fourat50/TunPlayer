"""Relocatable Windows runtime setup, before importing GTK or the application."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parent
DLL_DIRECTORIES=[]


def prepare():
    runtime=ROOT/'runtime';binary=runtime/'bin'
    local=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')/'TunPlayer'
    cache=local/'Cache/runtime';cache.mkdir(parents=True,exist_ok=True)
    identity=hashlib.sha256((str(ROOT)+str((ROOT/'build-manifest.json').read_bytes())).encode()).hexdigest()[:20]
    os.environ.update({
        'TUNPLAYER_RUNTIME_BIN':str(binary),'GDK_BACKEND':'win32',
        'PATH':str(binary)+os.pathsep+os.environ.get('PATH',''),
        'GI_TYPELIB_PATH':str(runtime/'lib/girepository-1.0'),
        'XDG_DATA_DIRS':str(runtime/'share'),
        'GSETTINGS_SCHEMA_DIR':str(runtime/'share/glib-2.0/schemas'),
        'GSETTINGS_BACKEND':'memory','GTK_DATA_PREFIX':str(runtime),'GTK_EXE_PREFIX':str(runtime),
        'GIO_EXTRA_MODULES':str(runtime/'lib/gio/modules'),
        'SSL_CERT_FILE':str(runtime/'etc/ssl/cert.pem'),
        'PYTHONDONTWRITEBYTECODE':'1',
    })
    if hasattr(os,'add_dll_directory'):DLL_DIRECTORIES.append(os.add_dll_directory(str(binary)))
    loaders=sorted((runtime/'lib/gdk-pixbuf-2.0').glob('*/loaders/*.dll'))
    if not loaders:raise RuntimeError('Les decodeurs des images GTK sont absents.')
    os.environ['GDK_PIXBUF_MODULEDIR']=str(loaders[0].parent)
    module_file=cache/f'pixbuf-{identity}.cache'
    if not module_file.is_file():
        result=subprocess.run([str(binary/'gdk-pixbuf-query-loaders.exe'),*(str(path) for path in loaders)],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,check=True)
        temporary=module_file.with_suffix(f'.{os.getpid()}.tmp');temporary.write_bytes(result.stdout);os.replace(temporary,module_file)
    os.environ['GDK_PIXBUF_MODULE_FILE']=str(module_file)
    fonts=cache/f'fonts-{identity}.conf'
    if not fonts.is_file():
        system_fonts=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'
        font_cache=cache/'fonts';font_cache.mkdir(exist_ok=True)
        fonts.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'+
            '<dir>'+escape(system_fonts.as_posix())+'</dir><cachedir>'+escape(font_cache.as_posix())+'</cachedir></fontconfig>',encoding='utf-8')
    os.environ['FONTCONFIG_FILE']=str(fonts)
    os.environ['FONTCONFIG_PATH']=str(runtime/'etc/fonts')
    sys.path.insert(0,str(ROOT/'app'))


def main():
    smoke='--smoke-test' in sys.argv
    try:
        prepare()
        if smoke:
            sys.path.insert(0,str(ROOT/'support'))
            from windows_smoke import run
            return run(Path(sys.argv[sys.argv.index('--smoke-test')+1]),ROOT)
        from tunplayer.app import main as application
        return application()
    except BaseException as error:
        if isinstance(error,SystemExit):raise
        report={'ok':False,'error':str(error),'traceback':traceback.format_exc()}
        if smoke:
            Path(sys.argv[sys.argv.index('--smoke-test')+1]).write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
        else:
            local=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')/'TunPlayer'
            local.mkdir(parents=True,exist_ok=True);(local/'startup-error.log').write_text(report['traceback'],encoding='utf-8')
            ctypes.windll.user32.MessageBoxW(None,'TunPlayer n’a pas pu demarrer. Consultez startup-error.log dans votre profil TunPlayer.','TunPlayer',0x10)
        return 1


if __name__=='__main__':raise SystemExit(main())
