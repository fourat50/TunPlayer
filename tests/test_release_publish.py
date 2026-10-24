import hashlib
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import publish_release


class ReleasePublication(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'packaging/releases').mkdir(parents=True);(self.root/'packaging/releases/v1.0.0.md').write_text('Notes')
        (self.root/'dist').mkdir();self.package=b'validated-package'
        (self.root/'dist/tunplayer_1.0.0_all.deb').write_bytes(self.package)
        self.sum=(hashlib.sha256(self.package).hexdigest()+'  tunplayer_1.0.0_all.deb\n').encode()
        (self.root/'dist/SHA256SUMS').write_bytes(self.sum)
        self.commands=[];self.created=False;self.bad_download=False;self.tag_mismatch=False

    def tearDown(self):self.tmp.cleanup()

    def command(self,args,**kwargs):
        args=[str(arg) for arg in args];self.commands.append(args)
        result=SimpleNamespace(returncode=0,stdout='',stderr='')
        if args[:2]==['git','rev-parse']:result.stdout='source-sha\n'
        elif args[:2]==['gh','api']:result.stdout='other-sha\n' if self.tag_mismatch else 'source-sha\n'
        elif args[:3]==['gh','release','create']:self.created=True
        elif args[:3]==['gh','release','view']:
            if not self.created:result.returncode=1
            elif '--jq' in args:result.stdout='https://github.com/fourat50/TunPlayer/releases/tag/v1.0.0\n'
            else:result.stdout=json.dumps(dict(isDraft=True,assets=[],url='release'))
        elif args[:3]==['gh','release','download']:
            directory=Path(args[args.index('--dir')+1])
            (directory/'tunplayer_1.0.0_all.deb').write_bytes(b'different' if self.bad_download else self.package)
            (directory/'SHA256SUMS').write_bytes(self.sum)
        return result

    def publish(self):
        with patch.object(publish_release,'ROOT',self.root),patch.object(publish_release,'run',side_effect=self.command),patch('scripts.publish_release.shutil.which',return_value='/usr/bin/gh'):
            with contextlib.redirect_stdout(io.StringIO()):publish_release.publish('v1.0.0')

    def test_draft_published_only_after_upload_and_download_verification(self):
        self.publish()
        actions=[args[2] for args in self.commands if args[:2]==['gh','release']]
        self.assertLess(actions.index('create'),actions.index('upload'))
        self.assertEqual(actions.count('upload'),2)
        self.assertLess(actions.index('download'),actions.index('edit'))
        create=next(args for args in self.commands if args[:3]==['gh','release','create'])
        self.assertIn('--draft',create);self.assertIn('--verify-tag',create)

    def test_wrong_uploaded_package_is_never_published_or_overwritten(self):
        self.bad_download=True
        with self.assertRaises(RuntimeError):self.publish()
        self.assertFalse(any(args[:3]==['gh','release','edit'] for args in self.commands))
        self.assertFalse(any('--clobber' in args for args in self.commands))

    def test_tag_mismatch_prevents_any_release_creation(self):
        self.tag_mismatch=True
        with self.assertRaises(RuntimeError):self.publish()
        self.assertFalse(any(args[:2]==['gh','release'] for args in self.commands))


if __name__=='__main__':unittest.main()
