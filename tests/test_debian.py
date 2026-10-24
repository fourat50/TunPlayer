"""Binary package checks against the frozen 1.0.0 tag, without system installation."""
import hashlib
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
AVAILABLE=bool(shutil.which('git') and shutil.which('dpkg-deb'))
if AVAILABLE:
    AVAILABLE=subprocess.run(['git','-C',str(ROOT),'rev-parse','--verify','refs/tags/v1.0.0'],capture_output=True).returncode==0


@unittest.skipUnless(AVAILABLE,'Construction Debian : git, dpkg-deb et tag v1.0.0 requis')
class DebianPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='tunplayer-package-test-')
        cls.outputs=[Path(cls.tmp.name)/name for name in ('first','second')]
        for directory in cls.outputs:
            result=subprocess.run(['/usr/bin/python3',str(ROOT/'scripts/build_deb.py'),'--ref','v1.0.0','--output-dir',str(directory)],capture_output=True,text=True)
            if result.returncode:raise RuntimeError(result.stderr)
        cls.package=cls.outputs[0]/'tunplayer_1.0.0_all.deb'

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_reproducible_frozen_source_and_installable_layout(self):
        self.assertEqual(self.package.read_bytes(),(self.outputs[1]/self.package.name).read_bytes())
        digest=hashlib.sha256(self.package.read_bytes()).hexdigest()
        self.assertEqual((self.outputs[0]/'SHA256SUMS').read_text(),f'{digest}  {self.package.name}\n')
        data=subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(self.package)])
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as archive:
            files={m.name.removeprefix('./'):m for m in archive if m.isfile()}
            self.assertIn('usr/bin/tunplayer',files)
            self.assertIn('usr/share/applications/tn.tunplayer.desktop',files)
            self.assertTrue(all(m.uid==m.gid==0 for m in files.values()))
            self.assertEqual(files['usr/bin/tunplayer'].mode,0o755)
            source=subprocess.check_output(['git','-C',str(ROOT),'show','v1.0.0:tunplayer/app.py'])
            self.assertEqual(archive.extractfile(files['usr/share/tunplayer/tunplayer/app.py']).read(),source)
            self.assertFalse(any('__pycache__' in name or name.endswith(('.sqlite3','.db','.pyc')) for name in files))

    @unittest.skipUnless(shutil.which('fakeroot'),'fakeroot requis pour la racine privee')
    def test_verification_installation_and_removal_in_private_root(self):
        result=subprocess.run(['/usr/bin/python3',str(ROOT/'scripts/verify_deb.py'),str(self.package),'--install-test'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('racine temporaire : OK',result.stdout)


if __name__=='__main__':unittest.main()
