import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_windows, publish_windows


class RuntimeSelection(unittest.TestCase):
    def test_native_runtime_keeps_extensions_typelibs_loaders_and_licenses(self):
        for name in ('bin/libmpv-2.dll','bin/pythonw.exe','bin/ffmpeg.exe',
                     'lib/python3.14/site-packages/gi/_gi.pyd',
                     'lib/girepository-1.0/Gtk-3.0.typelib',
                     'lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.dll',
                     'share/licenses/mpv/LICENSE','share/glib-2.0/schemas/gschemas.compiled'):
            with self.subTest(name=name):self.assertTrue(build_windows.runtime_file(Path(name)))
        for name in ('bin/gcc.exe','lib/libmpv.a','include/mpv/client.h',
                     'lib/python3.14/test/test_os.py',
                     'lib/python3.14/site-packages/gi/__pycache__/test.pyc',
                     'lib/gdk-pixbuf-2.0/2.10.0/loaders.cache'):
            with self.subTest(name=name):self.assertFalse(build_windows.runtime_file(Path(name)))


class WindowsPublication(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.installer='TunPlayer-1.0.0-windows-x64-setup.exe'
        content=b'MZtest-installer';digest=hashlib.sha256(content).hexdigest()
        (self.root/self.installer).write_bytes(content)
        (self.root/'Windows-SHA256SUMS').write_text(f'{digest}  {self.installer}\n')
        (self.root/'Windows-README.md').write_text('Windows instructions')
        self.report=dict(ok=True,embedded=True,next_episode=True,relocated_without_msys2=True,
            install_uninstall=True,source_commit='source-commit',version='1.0.0',installer_sha256=digest)
        self.commands=[];self.existing=[];self.corrupt=False;self.notes=None

    def tearDown(self):self.temporary.cleanup()

    def github(self,*arguments):
        args=list(map(str,arguments));self.commands.append(args)
        if args[:2]==['release','view']:
            return json.dumps(dict(assets=[dict(name=n) for n in self.existing],body='Linux release notes',url='release',isDraft=False))
        if args[:2]==['release','download']:
            name=args[args.index('--pattern')+1];destination=Path(args[args.index('--dir')+1])/name
            destination.write_bytes(b'corrupt' if self.corrupt else (self.root/name).read_bytes())
        if args[:2]==['release','edit']:
            self.notes=Path(args[args.index('--notes-file')+1]).read_text()
        return ''

    def publish(self):
        (self.root/'windows-verification.json').write_text(json.dumps(self.report))
        with patch.object(publish_windows,'gh',side_effect=self.github),contextlib.redirect_stdout(io.StringIO()):
            publish_windows.publish(self.root,'source-commit')

    def test_only_windows_assets_are_attached_after_native_validation(self):
        self.existing=['tunplayer_1.0.0_all.deb','SHA256SUMS'];self.publish()
        uploads=[args[3] for args in self.commands if args[:2]==['release','upload']]
        self.assertEqual({Path(p).name for p in uploads},{self.installer,'Windows-SHA256SUMS','Windows-README.md'})
        self.assertTrue(self.notes.startswith('Linux release notes'))
        self.assertIn('source-commit',self.notes)
        self.assertFalse(any('--clobber' in args for args in self.commands))

    def test_incomplete_windows_checks_prevent_all_github_calls(self):
        for key in ('ok','embedded','next_episode','relocated_without_msys2','install_uninstall'):
            with self.subTest(key=key):
                self.report[key]=False
                with self.assertRaises(RuntimeError):self.publish()
                self.assertEqual(self.commands,[])
                self.report[key]=True

    def test_wrong_source_commit_prevents_publication(self):
        self.report['source_commit']='other'
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual(self.commands,[])

    def test_changed_installer_after_test_prevents_publication(self):
        (self.root/self.installer).write_bytes(b'MZdifferent')
        with self.assertRaises(RuntimeError):self.publish()
        self.assertEqual(self.commands,[])

    def test_existing_windows_assets_are_verified_without_overwriting(self):
        self.existing=[self.installer,'Windows-SHA256SUMS','Windows-README.md'];self.publish()
        self.assertFalse(any(args[:2]==['release','upload'] for args in self.commands))
        self.assertEqual(sum(args[:2]==['release','download'] for args in self.commands),3)

    def test_mismatched_remote_asset_prevents_release_notes_update(self):
        self.corrupt=True
        with self.assertRaises(RuntimeError):self.publish()
        self.assertIsNone(self.notes)


if __name__=='__main__':unittest.main()
