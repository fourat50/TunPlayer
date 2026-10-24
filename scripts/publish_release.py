#!/usr/bin/env python3
"""Build, verify and publish the frozen Linux release through authenticated gh."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
REPOSITORY='fourat50/TunPlayer'


def run(args,capture=False,check=True):
    result=subprocess.run([str(arg) for arg in args],cwd=ROOT,text=True,capture_output=capture,check=False)
    if check and result.returncode:
        raise RuntimeError((result.stderr if capture else '') or f'Commande echouee : {args[0]} ({result.returncode})')
    return result


def publish(tag,push_source=False):
    if not re.fullmatch(r'v\d+\.\d+\.\d+',tag):raise ValueError('Le tag doit avoir le format vX.Y.Z.')
    version=tag[1:];notes=ROOT/'packaging/releases'/f'{tag}.md'
    if not notes.is_file():raise RuntimeError(f'Notes de version absentes : {notes}')
    run(['/usr/bin/python3',ROOT/'scripts/build_deb.py','--ref',tag])
    package=ROOT/'dist'/f'tunplayer_{version}_all.deb';checksums=ROOT/'dist/SHA256SUMS'
    run(['/usr/bin/python3',ROOT/'scripts/verify_deb.py',package,'--install-test'])
    if not shutil.which('gh'):raise RuntimeError('GitHub CLI manque dans cet environnement. Executez ce script depuis le terminal connecte avec gh.')
    run(['gh','auth','status'],capture=True)
    if push_source:
        origin=run(['git','remote','get-url','origin'],capture=True).stdout.strip()
        allowed={f'https://github.com/{REPOSITORY}.git',f'https://github.com/{REPOSITORY}',f'git@github.com:{REPOSITORY}.git',f'ssh://git@github.com/{REPOSITORY}.git'}
        if origin not in allowed:raise RuntimeError('origin ne pointe pas vers le depot de publication attendu.')
        run(['git','push','-u','origin','main'])
    local=run(['git','rev-parse',tag+'^{commit}'],capture=True).stdout.strip()
    remote=run(['gh','api',f'repos/{REPOSITORY}/commits/{tag}','--jq','.sha'],capture=True).stdout.strip()
    if local!=remote:raise RuntimeError('Le tag local differe du tag GitHub : publication annulee.')
    query=run(['gh','release','view',tag,'--repo',REPOSITORY,'--json','isDraft,assets,url'],capture=True,check=False)
    if query.returncode:
        run(['gh','release','create',tag,'--repo',REPOSITORY,'--verify-tag','--draft','--title',f'TunPlayer {version} — Linux','--notes-file',notes])
        query=run(['gh','release','view',tag,'--repo',REPOSITORY,'--json','isDraft,assets,url'],capture=True)
    release=json.loads(query.stdout);existing={asset['name'] for asset in release['assets']}
    for asset in (package,checksums):
        if asset.name not in existing:run(['gh','release','upload',tag,asset,'--repo',REPOSITORY])
    with tempfile.TemporaryDirectory(prefix='tunplayer-release-check-') as directory:
        run(['gh','release','download',tag,'--repo',REPOSITORY,'--pattern',package.name,'--pattern','SHA256SUMS','--dir',directory])
        downloaded=Path(directory)/package.name
        if hashlib.sha256(downloaded.read_bytes()).digest()!=hashlib.sha256(package.read_bytes()).digest():
            raise RuntimeError('Le paquet GitHub differe du paquet valide ; aucun fichier existant n’a ete remplace.')
        if (Path(directory)/'SHA256SUMS').read_bytes()!=checksums.read_bytes():raise RuntimeError('Le SHA256SUMS publie ne correspond pas au paquet.')
    if release['isDraft']:run(['gh','release','edit',tag,'--repo',REPOSITORY,'--draft=false','--latest'])
    url=run(['gh','release','view',tag,'--repo',REPOSITORY,'--json','url','--jq','.url'],capture=True).stdout.strip()
    print('Release publiee et telechargements verifies : '+url)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag',default='v1.0.0')
    parser.add_argument('--push-source',action='store_true',help='Pousser aussi les outils de construction sur main avant la release')
    args=parser.parse_args()
    try:publish(args.tag,args.push_source)
    except (RuntimeError,ValueError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
