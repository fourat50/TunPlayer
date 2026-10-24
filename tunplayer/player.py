"""Minimal typed libmpv binding; no third-party Python package required."""
import ctypes as C
import ctypes.util
import json
import locale
import os
from pathlib import Path
import sys
from .playback_ui import ASPECT_MODES
from .platform_support import mpv_library

class Event(C.Structure):
    _fields_ = [('event_id', C.c_int), ('error', C.c_int), ('reply_userdata', C.c_uint64), ('data', C.c_void_p)]

class EndFile(C.Structure):
    _fields_ = [('reason', C.c_int), ('error', C.c_int)]

class Player:
    def __init__(self, window_id=None, headless=False):
        if not headless and (isinstance(window_id,bool) or not isinstance(window_id,int) or window_id<=0):
            raise RuntimeError('La zone vidéo intégrée est indisponible. Relancez TunPlayer dans votre session graphique.')
        locale.setlocale(locale.LC_NUMERIC, 'C')
        path=mpv_library()
        if not path:
            raise RuntimeError('libmpv introuvable. Installez libmpv2 (Linux) ou mpv-2.dll (Windows).')
        self._dll_directory=None
        if sys.platform=='win32' and hasattr(os,'add_dll_directory') and Path(path).is_file():
            self._dll_directory=os.add_dll_directory(str(Path(path).parent))
        try:self.lib=C.CDLL(path)
        except OSError:
            if self._dll_directory:self._dll_directory.close()
            raise
        signatures = {
            'mpv_create': (C.c_void_p, []),
            'mpv_initialize': (C.c_int, [C.c_void_p]),
            'mpv_set_option_string': (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
            'mpv_set_property_string': (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
            'mpv_get_property_string': (C.c_void_p, [C.c_void_p, C.c_char_p]),
            'mpv_command': (C.c_int, [C.c_void_p, C.POINTER(C.c_char_p)]),
            'mpv_wait_event': (C.POINTER(Event), [C.c_void_p, C.c_double]),
            'mpv_error_string': (C.c_char_p, [C.c_int]),
            'mpv_free': (None, [C.c_void_p]),
            'mpv_terminate_destroy': (None, [C.c_void_p]),
        }
        for name,(restype,args) in signatures.items():
            f = getattr(self.lib,name); f.restype = restype; f.argtypes = args
        self.handle = self.lib.mpv_create()
        if not self.handle:
            raise RuntimeError('Impossible de créer le lecteur mpv.')
        options = {'hwdec':'auto-safe', 'keep-open':'yes', 'idle':'yes', 'terminal':'no',
                   'input-default-bindings':'no', 'osc':'no', 'cache':'yes', 'demuxer-max-bytes':'134217728',
                   'network-timeout':'20', 'volume':'75','cursor-autohide':'no'}
        if headless:options.update({'vo':'null','ao':'null'})
        else:
            options['wid']=str(window_id)
            if sys.platform.startswith('linux'):
                # Automatic selection can pick a Wayland VO which cannot embed an X11 wid.
                # No trailing comma: never fall back to an unrelated windowing backend.
                options.update({'vo':'gpu,x11','gpu-context':'x11egl','gpu-api':'opengl'})
            elif sys.platform=='win32':
                options.update({'vo':'gpu','gpu-context':'d3d11','d3d11-warp':'auto'})
        try:
            for key,value in options.items():
                self.check(self.lib.mpv_set_option_string(self.handle,key.encode(),value.encode()))
            self.check(self.lib.mpv_initialize(self.handle))
        except Exception:
            self.close(); raise

    def check(self, code):
        if code < 0:
            raise RuntimeError(self.lib.mpv_error_string(code).decode())

    def command(self, *args):
        values = [str(x).encode() for x in args] + [None]
        self.check(self.lib.mpv_command(self.handle, (C.c_char_p * len(values))(*values)))

    def set(self, name, value):
        self.check(self.lib.mpv_set_property_string(self.handle,name.encode(),str(value).encode()))

    def get(self, name, default=''):
        data = self.lib.mpv_get_property_string(self.handle, name.encode())
        if not data: return default
        try: return C.string_at(data).decode('utf-8', errors='replace')
        finally: self.lib.mpv_free(data)

    def events(self):
        result = []
        for _ in range(64):
            event = self.lib.mpv_wait_event(self.handle, 0).contents
            if event.event_id == 0: break
            if event.event_id == 7 and event.data:
                end = C.cast(event.data, C.POINTER(EndFile)).contents
                if end.reason == 4:
                    result.append(('error', self.lib.mpv_error_string(end.error).decode()))
                elif end.reason==0:result.append(('ended','eof'))
            if event.event_id == 8: result.append(('loaded',''))
        return result

    def tracks(self):
        return json.loads(self.get('track-list','[]'))

    def set_aspect(self,mode):
        if mode not in ASPECT_MODES:raise ValueError('Format d’image invalide.')
        _,ratio,keepaspect,panscan=ASPECT_MODES[mode]
        self.set('video-aspect-override',ratio)
        self.set('keepaspect',keepaspect)
        self.set('panscan',panscan)

    def close(self):
        if self.handle:
            self.lib.mpv_terminate_destroy(self.handle)
            self.handle = None
        if self._dll_directory:self._dll_directory.close();self._dll_directory=None
