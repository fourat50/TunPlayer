#!/usr/bin/env python3
"""Publish verified standalone Linux files alongside the original 1.0.0 release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
REPOSITORY='fourat50/TunPlayer'


def run(args):
    result=subprocess.run(list(map(str,args)),cwd=ROOT,capture_output=True,text=True)
    if result.returncode:raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'Echec : {args[0]}')
    return result.stdout


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def publish(directory,push_source=False):
    directory=Path(directory).resolve()
    report=json.loads((directory/'standalone-verification.json').read_text())
    for flag in ('ok','relocated','portable_archive','isolated_install_remove'):
        if report.get(flag) is not True:raise ValueError('Verification incomplete : '+flag)
    info=json.loads((directory/'TunPlayer-1.0.0-linux-x86_64/build-info.json').read_text())
    version=info['version']
    if version!='1.0.0':raise ValueError('Cette publication cible uniquement la version 1.0.0.')
    tag='v'+version
    package=directory/f'tunplayer_{version}+standalone1_amd64.deb'
    archive=directory/f'TunPlayer-{version}-linux-x86_64-standalone.tar.gz'
    sums=directory/'Standalone-SHA256SUMS'
    expected={}
    for line in sums.read_text().splitlines():
        checksum,name=line.split('  ',1)
        if Path(name).name!=name or name in expected or not re.fullmatch('[a-f0-9]{64}',checksum):raise ValueError('Fichier d’empreintes invalide.')
        expected[name]=checksum
    if set(expected)!={package.name,archive.name}:raise ValueError('Les empreintes doivent designer exactement le paquet et l’archive.')
    for asset in (package,archive):
        if digest(asset)!=expected[asset.name]:raise ValueError('Fichier modifie apres construction : '+asset.name)
    if digest(package)!=report.get('installer_sha256'):raise ValueError('Le paquet differe de celui valide.')
    with tarfile.open(archive,'r:gz') as stream:
        manifest=stream.extractfile(f'TunPlayer-{version}-linux-x86_64/build-info.json')
        if manifest is None or json.load(manifest)!=info:raise ValueError('Le manifeste de l’archive differe de celui de la construction.')
    print('Fichiers locaux et rapport de verification : OK.',flush=True)
    run(['gh','auth','status'])
    source=run(['gh','api',f'repos/{REPOSITORY}/commits/{tag}','--jq','.sha']).strip()
    if source!=info['source_commit']:raise ValueError('Le tag GitHub differe du programme embarque.')
    release=json.loads(run(['gh','release','view',tag,'--repo',REPOSITORY,'--json','assets,body,url,isDraft']))
    if release['isDraft']:raise ValueError('La release Linux existante doit etre publiee.')
    if push_source:
        origin=run(['git','remote','get-url','origin']).strip()
        if origin not in (f'https://github.com/{REPOSITORY}.git',f'https://github.com/{REPOSITORY}',f'git@github.com:{REPOSITORY}.git'):
            raise ValueError('Le depot origin est different du depot de publication.')
        if run(['git','status','--porcelain']).strip():raise ValueError('Commitez les changements avant de publier.')
        run(['git','push','origin','main'])
    existing={asset['name'] for asset in release['assets']}
    with tempfile.TemporaryDirectory(prefix='tunplayer-publish-standalone-') as temporary:
        temporary=Path(temporary)
        (temporary/'existing').mkdir();(temporary/'verified').mkdir()
        readme=temporary/'Standalone-README.txt'
        readme.write_bytes((directory/f'TunPlayer-{version}-linux-x86_64/README.txt').read_bytes())
        assets=(package,archive,sums,readme)
        # Check all name collisions before uploading any missing asset.
        for asset in assets:
            if asset.name in existing:
                run(['gh','release','download',tag,'--repo',REPOSITORY,'--pattern',asset.name,'--dir',temporary/'existing'])
                if digest(temporary/'existing'/asset.name)!=digest(asset):raise ValueError('Fichier distant different, aucun ecrasement : '+asset.name)
        for asset in assets:
            if asset.name not in existing:run(['gh','release','upload',tag,asset,'--repo',REPOSITORY])
        for asset in assets:
            run(['gh','release','download',tag,'--repo',REPOSITORY,'--pattern',asset.name,'--dir',temporary/'verified'])
            if digest(temporary/'verified'/asset.name)!=digest(asset):raise ValueError('Verification du telechargement echouee : '+asset.name)
        marker='<!-- tunplayer-linux-standalone-1.0.0 -->'
        # Fetch again to preserve edits made while large files were uploading.
        latest=json.loads(run(['gh','release','view',tag,'--repo',REPOSITORY,'--json','body']))
        if marker not in latest['body']:
            body=latest['body']+'\n\n'+marker+'\n## Version Linux autonome (x86_64)\n\n'+\
                'Python 3.12, GTK 3 / PyGObject / Cairo, mpv, FFmpeg, certificats HTTPS et police inclus.\n\n'+\
                f'- Installateur : `{package.name}` (environ 132 Mo, 344 Mo installes).\n'+\
                f'- Archive portable : `{archive.name}` (environ 139 Mo), extraire puis lancer `./AppRun`.\n'+\
                '- Verification : `Standalone-SHA256SUMS` ; instructions : `Standalone-README.txt`.\n\n'+\
                f'```bash\nsudo apt install ./{package.name}\n```\n\n'+\
                'Cible : Ubuntu 24.04 / Linux Mint 22, x86_64, glibc >= 2.39 ; affichage X11 / XWayland et pilotes fournis par Linux.\n\n'+\
                'Decodage local, GTK/SVG, HTTPS, relocation et installation/suppression isolees verifies. Installation reelle confirmee sous Mint. '+\
                'La lecture graphique complete et les autres distributions restent a valider.\n'
            notes=temporary/'notes.md';notes.write_text(body,encoding='utf-8')
            run(['gh','release','edit',tag,'--repo',REPOSITORY,'--notes-file',notes])
    print('Version autonome publiee et fichiers distants verifies : '+release['url'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'dist/linux-standalone')
    parser.add_argument('--push-source',action='store_true')
    args=parser.parse_args()
    try:publish(args.directory,args.push_source)
    except (RuntimeError,ValueError,OSError) as error:parser.exit(1,str(error)+'\n')
