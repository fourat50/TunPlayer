"""Native paths and window handles; Windows support does not require X11."""
import ctypes as C
import ctypes.util
import os
from pathlib import Path
import sys


def data_directory():
    if sys.platform=='win32':return Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')/'TunPlayer'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'tunplayer'


def cache_directory():
    if sys.platform=='win32':return data_directory()/'Cache'
    return Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))/'tunplayer'


def bundled_binary(name):
    if sys.platform=='win32':
        directory=Path(os.environ.get('TUNPLAYER_RUNTIME_BIN') or Path(sys.executable).parent)
        path=directory/(name+'.exe')
        if path.is_file():return str(path)
    import shutil
    return shutil.which(name)


def mpv_library():
    if sys.platform=='win32':
        directory=Path(os.environ.get('TUNPLAYER_RUNTIME_BIN') or Path(sys.executable).parent)
        for name in ('libmpv-2.dll','mpv-2.dll'):
            path=directory/name
            if path.is_file():return str(path)
    return ctypes.util.find_library('mpv') or ctypes.util.find_library('mpv-2')


def capsule_pointer(capsule):
    get_name=C.pythonapi.PyCapsule_GetName;get_name.argtypes=[C.py_object];get_name.restype=C.c_char_p
    get_pointer=C.pythonapi.PyCapsule_GetPointer;get_pointer.argtypes=[C.py_object,C.c_char_p];get_pointer.restype=C.c_void_p
    return get_pointer(capsule,get_name(capsule))


def win32_window_id(window):
    """Use GDK's exported HWND API, including GTK3 builds without GI annotations."""
    directory=Path(os.environ.get('TUNPLAYER_RUNTIME_BIN') or Path(sys.executable).parent)
    library=directory/'libgdk-3-0.dll'
    if not library.is_file():raise RuntimeError('La bibliotheque GDK Windows est introuvable.')
    capsule=getattr(window,'__gpointer__',None)
    if capsule is None:raise RuntimeError('La zone video native Windows est indisponible.')
    gdk=C.CDLL(str(library));get_handle=gdk.gdk_win32_window_get_handle
    get_handle.argtypes=[C.c_void_p];get_handle.restype=C.c_void_p
    handle=get_handle(capsule_pointer(capsule))
    user32=C.WinDLL('user32',use_last_error=True)
    user32.IsWindow.argtypes=[C.c_void_p];user32.IsWindow.restype=C.c_int
    if not handle or not user32.IsWindow(handle):raise RuntimeError('La fenetre video Windows est invalide.')
    # mpv explicitly interprets Windows handles as uint32_t, even on x64.
    result=int(handle)&0xffffffff
    if not result:raise RuntimeError('Identifiant video Windows nul.')
    return result
