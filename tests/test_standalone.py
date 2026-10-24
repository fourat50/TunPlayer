from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scripts.build_standalone import SYSTEM,dependencies


class StandaloneDependencies(unittest.TestCase):
    def test_only_glibc_stays_a_system_dependency(self):
        for name in ('libc.so.6','libm.so.6','libpthread.so.0','ld-linux-x86-64.so.2','libresolv.so.2'):
            with self.subTest(name=name):self.assertIsNotNone(SYSTEM.fullmatch(name))
        for name in ('libmpv.so.2','libgtk-3.so.0','libmount.so.1','libavcodec.so.60','libcairo.so.2','libssl.so.3'):
            with self.subTest(name=name):self.assertIsNone(SYSTEM.fullmatch(name))

    def test_missing_native_dependency_stops_packaging(self):
        with patch('scripts.build_standalone.subprocess.run',return_value=SimpleNamespace(stdout='libavcodec.so => not found',returncode=0)):
            with self.assertRaises(RuntimeError):dependencies(Path('/sample'))

    def test_dependency_paths_come_from_loader_resolution(self):
        with patch('scripts.build_standalone.subprocess.run',return_value=SimpleNamespace(stdout='libmpv.so.2 => /lib/x86_64-linux-gnu/libmpv.so.2 (0x123)\n',returncode=0)):
            self.assertEqual(dependencies(Path('/sample')),[Path('/lib/x86_64-linux-gnu/libmpv.so.2')])

    def test_dependency_paths_preserve_spaces_and_accents(self):
        with patch('scripts.build_standalone.subprocess.run',return_value=SimpleNamespace(stdout='libmpv.so.2 => /tmp/app été/runtime/lib/libmpv.so.2 (0x123)\n',returncode=0)):
            self.assertEqual(dependencies(Path('/sample')),[Path('/tmp/app été/runtime/lib/libmpv.so.2')])
