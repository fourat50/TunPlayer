"""Minimal typed libmpv binding; no third-party Python package required."""
import ctypes as C
import ctypes.util
import json
import locale
import sys
from .playback_ui import ASPECT_MODES

class Event(C.Structure):
    _fields_ = [('event_id', C.c_int), ('error', C.c_int), ('reply_userdata', C.c_uint64), ('data', C.c_void_p)]

class EndFile(C.Structure):
    _fields_ = [('reason', C.c_int), ('error', C.c_int)]

class ClientMessage(C.Structure):
    _fields_=[('num_args',C.c_int),('args',C.POINTER(C.c_char_p))]

class PropertyChange(C.Structure):
    _fields_=[('name',C.c_char_p),('format',C.c_int),('data',C.c_void_p)]

OBSERVED_PROPERTIES=('time-pos','duration','pause','paused-for-cache','eof-reached','idle-active','metadata/by-key/icy-title')

INPUT_BINDINGS={'MBTN_LEFT_DBL':'fullscreen-double','WHEEL_UP':'volume-up','WHEEL_DOWN':'volume-down',
    'f':'fullscreen','F':'fullscreen','m':'mute','M':'mute','SPACE':'pause','UP':'volume-up','DOWN':'volume-down',
    'LEFT':'seek-back','RIGHT':'seek-forward','ESC':'escape','PGUP':'previous','PGDWN':'next',
    'b':'browser','B':'browser','a':'aspect','A':'aspect','Ctrl+k':'search','Ctrl+q':'quit'}

class Player:
    def __init__(self, window_id=None, headless=False):
        if not headless and (isinstance(window_id,bool) or not isinstance(window_id,int) or window_id<=0):
            raise RuntimeError('La zone vidéo intégrée est indisponible. Relancez TunPlayer dans votre session graphique.')
        locale.setlocale(locale.LC_NUMERIC, 'C')
        path = ctypes.util.find_library('mpv') or ctypes.util.find_library('mpv-2')
        if not path:
            raise RuntimeError('libmpv introuvable. Installez libmpv2 (Linux) ou mpv-2.dll (Windows).')
        self.lib = C.CDLL(path)
        signatures = {
            'mpv_create': (C.c_void_p, []),
            'mpv_initialize': (C.c_int, [C.c_void_p]),
            'mpv_set_option_string': (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
            'mpv_set_property_string': (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
            'mpv_get_property_string': (C.c_void_p, [C.c_void_p, C.c_char_p]),
            'mpv_command': (C.c_int, [C.c_void_p, C.POINTER(C.c_char_p)]),
            'mpv_wait_event': (C.POINTER(Event), [C.c_void_p, C.c_double]),
            'mpv_observe_property': (C.c_int, [C.c_void_p,C.c_uint64,C.c_char_p,C.c_int]),
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
                   'network-timeout':'20', 'volume':'75','cursor-autohide':'no','input-cursor':'yes'}
        if headless:options.update({'vo':'null','ao':'null'})
        else:
            options['wid']=str(window_id)
            if sys.platform.startswith('linux'):
                # Automatic selection can pick a Wayland VO which cannot embed an X11 wid.
                # No trailing comma: never fall back to an unrelated windowing backend.
                options.update({'vo':'gpu,x11','gpu-context':'x11egl','gpu-api':'opengl'})
        try:
            for key,value in options.items():
                self.check(self.lib.mpv_set_option_string(self.handle,key.encode(),value.encode()))
            self.check(self.lib.mpv_initialize(self.handle))
            self.property_values={}
            for index,name in enumerate(OBSERVED_PROPERTIES,1):
                self.check(self.lib.mpv_observe_property(self.handle,index,name.encode(),1))
            for key,action in INPUT_BINDINGS.items():self.command('keybind',key,'script-message tunplayer-input '+action)
        except Exception:
            self.close(); raise

    def check(self, code):
        if code < 0:
            raise RuntimeError(self.lib.mpv_error_string(code).decode())

    def command(self, *args):
        if args and args[0] in ('loadfile','stop'):self.property_values.clear()
        values = [str(x).encode() for x in args] + [None]
        self.check(self.lib.mpv_command(self.handle, (C.c_char_p * len(values))(*values)))

    def set(self, name, value):
        self.check(self.lib.mpv_set_property_string(self.handle,name.encode(),str(value).encode()))

    def get(self, name, default=''):
        data = self.lib.mpv_get_property_string(self.handle, name.encode())
        if not data: return default
        try: return C.string_at(data).decode('utf-8', errors='replace')
        finally: self.lib.mpv_free(data)

    def cached(self,name,default=''):
        """Read event-delivered state without waiting for the playback core."""
        return self.property_values.get(name,default)

    def prepare_stream(self,channel,conservative=False):
        # Keep full probing for VOD, radio and retries. Limit only the initial
        # analysis of remote live TV; stream detection and caching stay enabled.
        fast=channel.get('kind')=='live' and not channel.get('radio') and str(channel.get('url','')).startswith(('http://','https://')) and not conservative
        self.set('demuxer-lavf-analyzeduration','0.5' if fast else '0')

    def events(self):
        result = []
        for _ in range(64):
            event = self.lib.mpv_wait_event(self.handle, 0).contents
            if event.event_id == 0: break
            if event.event_id==22 and event.data:
                change=C.cast(event.data,C.POINTER(PropertyChange)).contents
                if change.name:
                    name=change.name.decode('utf-8',errors='replace')
                    value=C.cast(change.data,C.POINTER(C.c_char_p)).contents.value if change.format==1 and change.data else None
                    if value is None:self.property_values.pop(name,None)
                    else:self.property_values[name]=value.decode('utf-8',errors='replace')
            if event.event_id == 7 and event.data:
                end = C.cast(event.data, C.POINTER(EndFile)).contents
                if end.reason == 4:
                    result.append(('error', self.lib.mpv_error_string(end.error).decode()))
                elif end.reason==0:result.append(('ended','eof'))
            if event.event_id == 8: result.append(('loaded',''))
            if event.event_id==16 and event.data:
                message=C.cast(event.data,C.POINTER(ClientMessage)).contents
                if message.num_args==2 and message.args[0]==b'tunplayer-input':
                    result.append(('input',message.args[1].decode('utf-8',errors='replace')))
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
