import contextlib
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from scripts import publish_standalone


class StandalonePublication(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.directory=self.root/'dist';self.directory.mkdir()
        self.package=self.directory/'tunplayer_1.0.0+standalone1_amd64.deb';self.package.write_bytes(b'validated-package')
        self.archive=self.directory/'TunPlayer-1.0.0-linux-x86_64-standalone.tar.gz'
        info=dict(version='1.0.0',source_commit='source-commit')
        bundle=self.directory/'TunPlayer-1.0.0-linux-x86_64';bundle.mkdir()
        (bundle/'build-info.json').write_text(json.dumps(info))
        with tarfile.open(self.archive,'w:gz') as stream:stream.add(bundle,arcname=bundle.name)
        sums=self.directory/'Standalone-SHA256SUMS'
        sums.write_text(''.join(publish_standalone.digest(p)+'  '+p.name+'\n' for p in (self.package,self.archive)))
        self.report=dict(ok=True,relocated=True,portable_archive=True,isolated_install_remove=True,installer_sha256=publish_standalone.digest(self.package))
        recipe=self.root/'packaging/standalone';recipe.mkdir(parents=True);(recipe/'README.txt').write_text('Standalone instructions')
        self.body='Original Linux notes';self.existing=['tunplayer_1.0.0_all.deb','SHA256SUMS']
        self.commands=[];self.wrong_tag=False;self.corrupt=False;self.notes=None

    def tearDown(self):self.temporary.cleanup()

    def command(self,arguments):
        args=list(map(str,arguments));self.commands.append(args)
        if args[:2]==['gh','api']:return 'other' if self.wrong_tag else 'source-commit'
        if args[:3]==['gh','release','view']:
            return json.dumps(dict(assets=[dict(name=n) for n in self.existing],body=self.body,isDraft=False,url='release'))
        if args[:3]==['gh','release','download']:
            name=args[args.index('--pattern')+1];directory=Path(args[args.index('--dir')+1]);directory.mkdir(parents=True,exist_ok=True)
            source=self.root/'packaging/standalone/README.txt' if name=='Standalone-README.txt' else self.directory/name
            (directory/name).write_bytes(b'corrupt' if self.corrupt else source.read_bytes())
        if args[:3]==['gh','release','edit']:self.notes=Path(args[args.index('--notes-file')+1]).read_text()
        return ''

    def publish(self):
        (self.directory/'standalone-verification.json').write_text(json.dumps(self.report))
        with patch.object(publish_standalone,'ROOT',self.root),patch.object(publish_standalone,'run',side_effect=self.command),contextlib.redirect_stdout(io.StringIO()):
            publish_standalone.publish(self.directory)

    def test_verified_assets_are_attached_without_overwriting_original_linux_release(self):
        self.publish()
        uploads=[Path(a[4]).name for a in self.commands if a[:3]==['gh','release','upload']]
        self.assertEqual(set(uploads),{self.package.name,self.archive.name,'Standalone-SHA256SUMS','Standalone-README.txt'})
        self.assertTrue(self.notes.startswith('Original Linux notes'))
        self.assertFalse(any('--clobber' in a for a in self.commands))

    def test_incomplete_validation_prevents_network_calls(self):
        self.report['isolated_install_remove']=False
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.commands,[])

    def test_modified_package_prevents_network_calls(self):
        self.package.write_bytes(b'modified')
        with self.assertRaises(ValueError):self.publish()
        self.assertEqual(self.commands,[])

    def test_wrong_source_tag_prevents_uploads(self):
        self.wrong_tag=True
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(any(a[:3]==['gh','release','upload'] for a in self.commands))

    def test_different_existing_asset_stops_before_any_upload(self):
        self.existing.append(self.package.name);self.corrupt=True
        with self.assertRaises(ValueError):self.publish()
        self.assertFalse(any(a[:3]==['gh','release','upload'] for a in self.commands))
        self.assertIsNone(self.notes)

    def test_failed_download_verification_prevents_release_note_edit(self):
        self.corrupt=True
        with self.assertRaises(ValueError):self.publish()
        self.assertIsNone(self.notes)
