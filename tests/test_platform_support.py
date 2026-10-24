import ctypes as C
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tunplayer import platform_support
from tunplayer.core import Library


class PlatformSupport(unittest.TestCase):
    def test_windows_profile_and_cache_use_local_app_data(self):
        with patch('tunplayer.platform_support.sys.platform','win32'),patch.dict('os.environ',{'LOCALAPPDATA':'/windows/local'}):
            self.assertEqual(platform_support.data_directory(),Path('/windows/local/TunPlayer'))
            self.assertEqual(platform_support.cache_directory(),Path('/windows/local/TunPlayer/Cache'))

    def test_linux_profile_conventions_are_unchanged(self):
        with patch('tunplayer.platform_support.sys.platform','linux'),patch.dict('os.environ',{'XDG_DATA_HOME':'/data','XDG_CACHE_HOME':'/cache'}):
            self.assertEqual(platform_support.data_directory(),Path('/data/tunplayer'))
            self.assertEqual(platform_support.cache_directory(),Path('/cache/tunplayer'))

    def test_bundled_windows_mpv_and_ffmpeg_are_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            mpv=Path(directory)/'libmpv-2.dll';mpv.write_bytes(b'fixture')
            ffmpeg=Path(directory)/'ffmpeg.exe';ffmpeg.write_bytes(b'fixture')
            with patch('tunplayer.platform_support.sys.platform','win32'),patch.dict('os.environ',{'TUNPLAYER_RUNTIME_BIN':directory}):
                self.assertEqual(platform_support.mpv_library(),str(mpv))
                self.assertEqual(platform_support.bundled_binary('ffmpeg'),str(ffmpeg))

    def test_gobject_capsule_pointer_is_not_truncated(self):
        create=C.pythonapi.PyCapsule_New;create.argtypes=[C.c_void_p,C.c_char_p,C.c_void_p];create.restype=C.py_object
        address=0x123456789ABC if C.sizeof(C.c_void_p)==8 else 0x123456
        capsule=create(address,None,None)
        self.assertEqual(platform_support.capsule_pointer(capsule),address)

    def test_read_only_sqlite_uri_handles_spaces_and_hash_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profil #1 avec espaces.sqlite3';library=Library(path)
            library.set_setting('test','ok');library.close()
            reader=Library(path,read_only=True)
            try:self.assertEqual(reader.setting('test'),'ok')
            finally:reader.close()


if __name__=='__main__':unittest.main()
