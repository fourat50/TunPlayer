#!/usr/bin/env python3
"""Inspect, extract and optionally install/remove a package in a private root."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def run(args,**kwargs):
    result=subprocess.run([str(arg) for arg in args],capture_output=True,check=False,**kwargs)
    if result.returncode:
        error=result.stderr if isinstance(result.stderr,str) else result.stderr.decode(errors='replace')
        raise RuntimeError(f'{args[0]} a echoue ({result.returncode}) :\n{error}')
    return result.stdout


def verify(package,install=False):
    package=Path(package).resolve()
    fields=run(['dpkg-deb','-f',package,'Package','Version','Architecture'],text=True)
    if 'Package: tunplayer\n' not in fields or 'Architecture: all\n' not in fields:raise ValueError('Metadonnees inattendues.')
    payload=run(['dpkg-deb','--fsys-tarfile',package])
    with tarfile.open(fileobj=io.BytesIO(payload),mode='r:') as archive:
        files=[]
        for member in archive:
            path=Path(member.name)
            if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk():raise ValueError('Chemin non sur dans le paquet.')
            if member.uid!=0 or member.gid!=0:raise ValueError('Proprietaire du paquet different de root.')
            if member.isfile():
                if member.mode not in (0o644,0o755):raise ValueError('Permissions inattendues.')
                if '__pycache__' in path.parts or path.suffix in ('.sqlite3','.db','.pyc'):raise ValueError('Donnees locales dans le paquet.')
                files.append(path.as_posix().lstrip('./'))
    required={'usr/bin/tunplayer','usr/share/tunplayer/run.py','usr/share/applications/tn.tunplayer.desktop','usr/share/icons/hicolor/scalable/apps/tunplayer.svg'}
    if not required.issubset(files):raise ValueError('Fichiers installables manquants.')
    with tempfile.TemporaryDirectory(prefix='tunplayer-verify-') as directory:
        root=Path(directory)/'root';root.mkdir()
        run(['dpkg-deb','-x',package,root])
        control=Path(directory)/'control';run(['dpkg-deb','-e',package,control])
        for line in (control/'md5sums').read_text().splitlines():
            expected,name=line.split('  ',1)
            if hashlib.md5((root/name).read_bytes(),usedforsecurity=False).hexdigest()!=expected:raise ValueError('Somme de controle invalide.')
        if shutil.which('desktop-file-validate'):
            run(['desktop-file-validate',root/'usr/share/applications/tn.tunplayer.desktop'])
        run(['sh','-n',root/'usr/bin/tunplayer'])
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        help_text=run(['/usr/bin/python3','-B',root/'usr/share/tunplayer/run.py','--help'],cwd=directory,env=env,text=True)
        if '--data-dir' not in help_text:raise ValueError('Le programme extrait ne demarre pas.')
        if install:
            if not shutil.which('fakeroot'):raise RuntimeError('fakeroot est necessaire pour le test isole.')
            isolated=Path(directory)/'installed';database=isolated/'var/lib/dpkg'
            database.mkdir(parents=True);(database/'status').write_text('')
            # Only this private dpkg database is touched. It deliberately has no system
            # dependencies registered; dependency resolution is checked separately by APT.
            base=['fakeroot','dpkg','--root='+str(isolated),'--log='+str(Path(directory)/'dpkg.log'),'--force-not-root']
            isolated_env=dict(env,FAKEROOTDONTTRYCHOWN='1',TAR_OPTIONS='--no-same-owner')
            run([*base,'--force-depends','--install',package],text=True,env=isolated_env)
            status=run(['dpkg-query','--admindir='+str(database),'-W','-f=${db:Status-Status}','tunplayer'],text=True)
            if status!='installed':raise ValueError('Installation isolee incomplete.')
            run(['/usr/bin/python3','-B',isolated/'usr/share/tunplayer/run.py','--help'],cwd=directory,env=env,text=True)
            run([*base,'--remove','tunplayer'],text=True,env=isolated_env)
            if (isolated/'usr/bin/tunplayer').exists() or (isolated/'usr/share/tunplayer/run.py').exists():raise ValueError('Suppression isolee incomplete.')
    print(f'Paquet verifie : {len(files)} fichiers, chemins, proprietaires, MD5, lanceur et demarrage --help OK.')
    if install:print('Installation et desinstallation dans une racine temporaire : OK.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path)
    parser.add_argument('--install-test',action='store_true')
    args=parser.parse_args();verify(args.package,args.install_test)


if __name__=='__main__':main()
