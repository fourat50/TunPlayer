#!/usr/bin/env python3
"""Verify relocation, ELF closure and isolated installation of the real bundle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_standalone import SYSTEM


def run(args,**kwargs):
    try:return subprocess.check_output(list(map(str,args)),stderr=subprocess.PIPE,**kwargs)
    except subprocess.CalledProcessError as error:
        detail=error.stderr if isinstance(error.stderr,str) else error.stderr.decode(errors='replace')
        raise RuntimeError(f'{args[0]} a echoue : {detail}') from error


def verify(package):
    package=Path(package).resolve()
    for line in (package.parent/'Standalone-SHA256SUMS').read_text().splitlines():
        expected,name=line.split('  ',1)
        assert Path(name).name==name,'Nom de fichier inattendu dans les empreintes'
        assert hashlib.sha256((package.parent/name).read_bytes()).hexdigest()==expected,'Empreinte incorrecte : '+name
    fields=run(['dpkg-deb','-f',package,'Package','Version','Architecture','Depends'],text=True)
    assert 'Package: tunplayer\n' in fields and 'Architecture: amd64\n' in fields
    assert 'Depends: libc6 (>= ' in fields
    assert not any(name in fields for name in ('python3','libmpv','ffmpeg','gtk'))
    with tempfile.TemporaryDirectory(prefix='TunPlayer autonome é espaces ') as directory:
        root=Path(directory)/'root'
        run(['dpkg-deb','-x',package,root])
        bundle=root/'opt/tunplayer'
        env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','LD_','GI_','GTK_','GDK_'))}
        env.update(XDG_CACHE_HOME=str(Path(directory)/'cache'),PATH='/usr/bin:/bin',LD_LIBRARY_PATH=str(bundle/'runtime/lib'))
        binaries=[bundle/'runtime/bin/python3',bundle/'runtime/bin/ffmpeg',
            *list((bundle/'runtime/lib').glob('*.so*')),
            *list((bundle/'runtime/lib/python3.12').rglob('*.so')),
            *list((bundle/'runtime/python-packages').rglob('*.so')),
            *list((bundle/'runtime/pixbuf-loaders').glob('*.so')),
            *list((bundle/'runtime/gio-modules').glob('*.so'))]
        for binary in binaries:
            result=run(['ldd',binary],env=env,text=True)
            assert 'not found' not in result,str(binary)
            for path in re.findall(r'=> (/.+?) \(0x[0-9a-fA-F]+\)',result):
                assert str(bundle) in path or SYSTEM.fullmatch(Path(path).name),'Dependance externe : '+path
        print(f'Dependances ELF verifiees : {len(binaries)} fichiers.',flush=True)
        result=run([bundle/'AppRun','--self-test'],env=env,text=True,timeout=45)
        report=json.loads(result.strip().splitlines()[-1]);assert report['ok']
        assert '--data-dir' in run([bundle/'AppRun','--help'],env=env,text=True,timeout=30)
        version=json.loads((bundle/'build-info.json').read_text())['version']
        portable=package.parent/f'TunPlayer-{version}-linux-x86_64-standalone.tar.gz'
        extracted=Path(directory)/'portable'
        with tarfile.open(portable,'r:gz') as stream:stream.extractall(extracted,filter='data')
        portable_root=extracted/f'TunPlayer-{version}-linux-x86_64'
        run([portable_root/'AppRun','--self-test'],env=env,timeout=45)
        print('Paquet et archive portables : GTK, SVG, HTTPS, FFmpeg et mpv OK.',flush=True)
        if shutil.which('desktop-file-validate'):
            run(['desktop-file-validate',root/'usr/share/applications/tn.tunplayer.desktop'])
        # Exercise dpkg without touching the real system database or /opt.
        installed=Path(directory)/'installed';database=installed/'var/lib/dpkg'
        database.mkdir(parents=True);(database/'status').write_text('')
        isolated=dict(env,FAKEROOTDONTTRYCHOWN='1',TAR_OPTIONS='--no-same-owner',PATH='/usr/sbin:/usr/bin:/sbin:/bin')
        # dpkg/fakeroot are host tools; only AppRun uses the private libraries.
        isolated.pop('LD_LIBRARY_PATH',None)
        command=['fakeroot','dpkg','--root='+str(installed),'--log='+str(Path(directory)/'dpkg.log'),'--force-not-root']
        run([*command,'--force-depends','--install',package],env=isolated)
        assert run(['dpkg-query','--admindir='+str(database),'-W','-f=${db:Status-Status}','tunplayer'],text=True)=='installed'
        run([installed/'opt/tunplayer/AppRun','--self-test'],env=env,timeout=45)
        run([*command,'--remove','tunplayer'],env=isolated)
        assert not (installed/'opt/tunplayer/AppRun').exists()
        report.update(elf_files_checked=len(binaries),relocated=True,portable_archive=True,isolated_install_remove=True,
            installer_sha256=hashlib.sha256(package.read_bytes()).hexdigest(),graphical_test=False)
    destination=package.parent/'standalone-verification.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Runtime prive, fermeture des dependances ELF, relocation, SVG, HTTPS, FFmpeg, mpv et installation/suppression isolees : OK.')
    print('Rapport : '+str(destination))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('package',type=Path)
    verify(parser.parse_args().package)
