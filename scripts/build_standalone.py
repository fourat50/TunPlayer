#!/usr/bin/env python3
"""Bundle the tagged Linux app, Python/GTK/mpv/FFmpeg and their ELF closure."""
import argparse
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
RECIPE=ROOT/'packaging/standalone'
# glibc and vendor GPU drivers belong to the target operating system.
SYSTEM=re.compile(r'^(?:ld-linux.*|lib(?:c|m|pthread|rt|dl|resolv|anl|util|nss_\w+)\.so(?:\..*)?)$')


def output(*args):return subprocess.check_output(list(map(str,args)),text=True)


def copy(source,target):
    source=Path(source);target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)


def dependencies(path):
    result=subprocess.run(['ldd',str(path)],capture_output=True,text=True)
    if 'not found' in result.stdout:raise RuntimeError(f'Dependance absente pour {path}: {result.stdout}')
    return [Path(p) for p in re.findall(r'=> (/.+?) \(0x[0-9a-fA-F]+\)',result.stdout)]


def build(ref,destination):
    if sys.platform!='linux' or platform.machine()!='x86_64':raise RuntimeError('Construction Linux x86_64 requise.')
    if sys.version_info[:2]!=(3,12):raise RuntimeError('Cette recette cible Python 3.12 et Ubuntu 24.04 / Mint 22.')
    from scripts.build_deb import read_version
    import gi,cairo
    commit=output('git','-C',ROOT,'rev-parse','--verify','--end-of-options',ref+'^{commit}').strip()
    def blob(name):return subprocess.check_output(['git','-C',str(ROOT),'show',commit+':'+name])
    version=read_version(blob('tunplayer/__init__.py'))
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    bundle=destination/f'TunPlayer-{version}-linux-x86_64'
    if bundle.exists():raise RuntimeError(f'Dossier deja present : {bundle}. Utilisez un nouveau dossier de sortie.')
    bundle.mkdir();runtime=bundle/'runtime';binary=runtime/'bin';binary.mkdir(parents=True)
    provenance={};roots=[]
    def native(source,target):
        copy(source,target);provenance[str(target.relative_to(bundle))]=str(Path(source).resolve());roots.append(Path(source))
    native(Path(sys.executable).resolve(),binary/'python3')
    native(shutil.which('ffmpeg'),binary/'ffmpeg')
    query=Path('/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders')
    native(query,binary/query.name)
    ignore=shutil.ignore_patterns('__pycache__','*.pyc','test','tests','idlelib','tkinter','ensurepip')
    shutil.copytree('/usr/lib/python3.12',runtime/'lib/python3.12',ignore=ignore)
    for module in (gi,cairo):shutil.copytree(Path(module.__file__).parent,runtime/'python-packages'/module.__name__,ignore=ignore)
    for path in (runtime/'lib/python3.12').rglob('*.so'):roots.append(path)
    for path in (runtime/'python-packages').rglob('*.so'):roots.append(path)
    for path in Path('/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders').glob('*.so'):
        native(path,runtime/'pixbuf-loaders'/path.name)
    for name in ('libgiognutls.so',):
        native(Path('/usr/lib/x86_64-linux-gnu/gio/modules')/name,runtime/'gio-modules'/name)
    shutil.copytree('/usr/lib/x86_64-linux-gnu/girepository-1.0',runtime/'lib/girepository-1.0')
    shutil.copytree('/usr/share/glib-2.0/schemas',runtime/'share/glib-2.0/schemas')
    copy('/etc/ssl/certs/ca-certificates.crt',runtime/'share/ca-certificates.crt')
    copy('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',runtime/'share/fonts/DejaVuSans.ttf')
    libraries={}
    for line in output('ldconfig','-p').splitlines():
        if ' => /' in line:
            name=line.split()[0];libraries.setdefault(name,Path(line.split(' => ')[1]))
    library_paths=set()
    for name in ('libmpv.so.2','libgtk-3.so.0','libgdk-3.so.0','libgirepository-1.0.so.1','librsvg-2.so.2','libcairo-gobject.so.2'):
        if name not in libraries:raise RuntimeError('Bibliotheque absente : '+name)
        roots.append(libraries[name]);library_paths.add(libraries[name])
    seen=set()
    while roots:
        path=roots.pop()
        if path in seen:continue
        seen.add(path)
        if path in library_paths and not SYSTEM.fullmatch(path.name):
            copy(path,runtime/'lib'/path.name);provenance['runtime/lib/'+path.name]=str(path.resolve())
        for dependency in dependencies(path):
            if not SYSTEM.fullmatch(dependency.name):
                roots.append(dependency);library_paths.add(dependency)
    names=output('git','-C',ROOT,'ls-tree','-r','--name-only',commit).splitlines()
    for name in names:
        if name=='run.py' or name in ('assets/style.css','assets/tunplayer.svg','assets/demo.mp4') or (name.startswith('tunplayer/') and name.endswith('.py')):
            target=bundle/'app'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(blob(name))
    for name in ('AppRun','bootstrap.py','README.txt'):copy(RECIPE/name,bundle/name)
    (bundle/'README.txt').write_text((RECIPE/'README.txt').read_text().format(version=version,source_commit=commit),encoding='utf-8')
    (bundle/'AppRun').chmod(0o755)
    # Include distribution copyright/license notices and exact package versions.
    packages={'python3.12-minimal','libpython3.12-minimal','libpython3.12-stdlib','python3-gi','python3-gi-cairo','python3-cairo','gir1.2-gtk-3.0','fonts-dejavu-core','ca-certificates'}
    paths=sorted(set(provenance.values())|{str(p.resolve()) for p in Path('/usr/lib/x86_64-linux-gnu/girepository-1.0').glob('*.typelib')})
    found=subprocess.run(['dpkg-query','-S',*paths,*[p.replace('/usr/lib/','/lib/',1) for p in paths if p.startswith('/usr/lib/')]],capture_output=True,text=True)
    for line in found.stdout.splitlines():
        if ': /' in line:
            for package in line.split(': /',1)[0].split(', '):
                if re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?',package):packages.add(package)
    inventory=[]
    for package in sorted(packages):
        record=output('dpkg-query','-W','-f=${binary:Package}\t${Version}\n',package).strip();inventory.append(record)
        copyright=Path('/usr/share/doc')/package.split(':')[0]/'copyright'
        if not copyright.exists():raise RuntimeError('Notice de licence absente : '+package)
        copy(copyright,bundle/'licenses'/package.replace(':','_')/'copyright')
    shutil.copytree('/usr/share/common-licenses',bundle/'licenses/common-licenses')
    info=dict(version=version,source_commit=commit,architecture='amd64',build_os=Path('/etc/os-release').read_text(),
        required_glibc=platform.libc_ver()[1],packages=inventory,native_files=provenance,
        source_packages='https://archive.ubuntu.com/ubuntu/pool/',validation='scripts/verify_standalone.py')
    (bundle/'build-info.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
    with tempfile.TemporaryDirectory(prefix='tunplayer-prepackage-') as cache:
        subprocess.run([str(bundle/'AppRun'),'--self-test'],check=True,env=dict(os.environ,XDG_CACHE_HOME=cache),timeout=45)
    # Keep the conventional package name, so installation upgrades the thin .deb.
    stage=destination/'deb-root';stage.mkdir()
    target=stage/'opt/tunplayer';target.parent.mkdir(parents=True);shutil.copytree(bundle,target)
    launcher=stage/'usr/bin/tunplayer';launcher.parent.mkdir(parents=True)
    launcher.write_text('#!/bin/sh\nexec /opt/tunplayer/AppRun "$@"\n');launcher.chmod(0o755)
    copy(ROOT/'packaging/debian/tn.tunplayer.desktop',stage/'usr/share/applications/tn.tunplayer.desktop')
    copy(bundle/'app/assets/tunplayer.svg',stage/'usr/share/icons/hicolor/scalable/apps/tunplayer.svg')
    control=stage/'DEBIAN/control';control.parent.mkdir()
    size=(sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())+1023)//1024
    control.write_text(f'Package: tunplayer\nVersion: {version}+standalone1\nArchitecture: amd64\nSection: video\nPriority: optional\nMaintainer: fourat50 <30878197+fourat50@users.noreply.github.com>\nInstalled-Size: {size}\nDepends: libc6 (>= {info["required_glibc"]})\nRecommends: xwayland\nHomepage: https://github.com/fourat50/TunPlayer\nDescription: TunPlayer avec Python GTK mpv et FFmpeg embarques\n Version autonome Linux x86_64 pour Ubuntu 24.04 et Mint 22.\n')
    deb=destination/f'tunplayer_{version}+standalone1_amd64.deb'
    subprocess.run(['dpkg-deb','--root-owner-group','-Zzstd','-z3','--build',str(stage),str(deb)],check=True,env=dict(os.environ,DPKG_DEB_THREADS_MAX='2'))
    archive=destination/f'{bundle.name}-standalone.tar.gz'
    with tarfile.open(archive,'w:gz',compresslevel=3) as stream:stream.add(bundle,arcname=bundle.name)
    sums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in (deb,archive))
    (destination/'Standalone-SHA256SUMS').write_text(sums)
    shutil.rmtree(stage)
    print(f'Paquet : {deb}\nArchive : {archive}\n'+sums)
    return bundle


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref',default='v1.0.0')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'dist/standalone')
    args=parser.parse_args()
    sys.path.insert(0,str(ROOT))
    build(args.ref,args.output_dir)
