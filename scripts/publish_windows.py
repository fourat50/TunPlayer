#!/usr/bin/env python3
"""Attach only Windows-verified assets; preserve the existing Linux release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

REPO='fourat50/TunPlayer'


def gh(*args):return subprocess.check_output(['gh',*map(str,args)],text=True)


def publish(directory,expected_commit):
    directory=Path(directory)
    report=json.loads((directory/'windows-verification.json').read_text(encoding='utf-8'))
    for key in ('ok','embedded','next_episode','relocated_without_msys2','install_uninstall'):
        if report.get(key) is not True:raise RuntimeError('Verification Windows incomplete : '+key)
    if report.get('source_commit')!=expected_commit:raise RuntimeError('Le rapport ne correspond pas au commit de cette construction.')
    version=report['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Version invalide')
    tag='v'+version;installer=directory/f'TunPlayer-{version}-windows-x64-setup.exe'
    checksum=hashlib.sha256(installer.read_bytes()).hexdigest()
    if installer.read_bytes()[:2]!=b'MZ' or report.get('installer_sha256')!=checksum:raise RuntimeError('Installateur different de celui teste.')
    sums=directory/'Windows-SHA256SUMS'
    if sums.read_text(encoding='utf-8')!=f'{checksum}  {installer.name}\n':raise RuntimeError('Somme de controle Windows incorrecte.')
    release=json.loads(gh('release','view',tag,'--repo',REPO,'--json','assets,body,url,isDraft'))
    existing={asset['name'] for asset in release['assets']}
    assets=(installer,sums,directory/'Windows-README.md')
    for asset in assets:
        if asset.name not in existing:gh('release','upload',tag,asset,'--repo',REPO)
    with tempfile.TemporaryDirectory(prefix='tunplayer-windows-asset-') as temporary:
        for asset in assets:
            gh('release','download',tag,'--repo',REPO,'--pattern',asset.name,'--dir',temporary)
            if hashlib.sha256((Path(temporary)/asset.name).read_bytes()).digest()!=hashlib.sha256(asset.read_bytes()).digest():
                raise RuntimeError('Un fichier Windows distant differe ; aucun fichier existant n’a ete ecrase.')
        marker='<!-- tunplayer-windows-'+version+' -->'
        if marker not in release['body']:
            body=release['body']+'\n\n'+marker+'\n## Windows 10 / 11 x64\n\n'+\
                f'Installeur **`{installer.name}`** : Python, GTK, mpv et FFmpeg inclus.\n\n'+\
                'Consultez `Windows-README.md` et verifiez `Windows-SHA256SUMS`. Installateur non signe.\n\n'+\
                f'Construction Windows et tests d’installation, de video integree et de desinstallation : commit `{expected_commit}`.\n'+\
                'Le paquet Linux et son tag original restent inchanges.\n'
            notes=Path(temporary)/'release.md';notes.write_text(body,encoding='utf-8')
            gh('release','edit',tag,'--repo',REPO,'--notes-file',notes)
    print('Fichiers Windows publies et verifies : '+release['url'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path('dist'))
    parser.add_argument('--expected-commit',default=os.environ.get('GITHUB_SHA'))
    args=parser.parse_args()
    if not args.expected_commit:parser.error('--expected-commit requis hors de GitHub Actions')
    publish(args.directory,args.expected_commit)


if __name__=='__main__':main()
