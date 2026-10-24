#!/usr/bin/env python3
"""Build a reproducible Debian package from a frozen Git ref, without root."""
import argparse
import ast
import gzip
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
RECIPE=ROOT/'packaging/debian'


def git(*args):return subprocess.check_output(['git','-C',str(ROOT),*args])


def read_version(data):
    for node in ast.parse(data.decode('utf-8')).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in node.targets):
            version=ast.literal_eval(node.value)
            if isinstance(version,str) and re.fullmatch(r'\d+\.\d+\.\d+',version):return version
    raise ValueError('Version stable x.y.z introuvable.')


def put(root,name,data,mode=0o644):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data);path.chmod(mode)


def build(ref,output):
    if not shutil.which('dpkg-deb'):raise RuntimeError('dpkg-deb est necessaire.')
    commit=git('rev-parse','--verify','--end-of-options',ref+'^{commit}').decode().strip()
    version=read_version(git('show',commit+':tunplayer/__init__.py'))
    epoch=int(git('show','-s','--format=%ct',commit))
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    target=output/f'tunplayer_{version}_all.deb'
    with tempfile.TemporaryDirectory(prefix='tunplayer-deb-') as directory:
        root=Path(directory)/'package';root.mkdir()
        names=git('ls-tree','-r','--name-only','-z',commit).decode().split('\0')
        required={'run.py','assets/style.css','assets/tunplayer.svg','assets/demo.mp4'}
        runtime=[name for name in names if name in required or (name.startswith('tunplayer/') and name.endswith('.py'))]
        if not required.issubset(runtime):raise RuntimeError('Ressources du lecteur incompletes.')
        for name in runtime:
            if '..' in Path(name).parts:raise ValueError('Chemin invalide dans la source.')
            put(root,'usr/share/tunplayer/'+name,git('show',commit+':'+name))
        put(root,'usr/bin/tunplayer',(RECIPE/'tunplayer').read_bytes(),0o755)
        put(root,'usr/share/applications/tn.tunplayer.desktop',(RECIPE/'tn.tunplayer.desktop').read_bytes())
        put(root,'usr/share/icons/hicolor/scalable/apps/tunplayer.svg',git('show',commit+':assets/tunplayer.svg'))
        for name in ('copyright','README.Debian'):put(root,'usr/share/doc/tunplayer/'+name,(RECIPE/name).read_bytes())
        for name in ('README.md','CHANGELOG.md'):
            put(root,'usr/share/doc/tunplayer/'+name+'.gz',gzip.compress(git('show',commit+':'+name),mtime=epoch))
        recipe_files=[Path(__file__).resolve(),*sorted(RECIPE.iterdir())]
        digest=hashlib.sha256()
        for path in recipe_files:digest.update(path.name.encode());digest.update(path.read_bytes())
        put(root,'usr/share/doc/tunplayer/build-info',f'Version: {version}\nSource-Commit: {commit}\nSource-Date-Epoch: {epoch}\nRecipe-SHA256: {digest.hexdigest()}\n'.encode())
        payload=sorted(path for path in root.rglob('*') if path.is_file())
        installed_size=math.ceil(sum(path.stat().st_size for path in payload)/1024)
        control=(RECIPE/'control.in').read_text().format(version=version,installed_size=installed_size)
        put(root,'DEBIAN/control',control.encode())
        md5=''.join(hashlib.md5(path.read_bytes(),usedforsecurity=False).hexdigest()+'  '+path.relative_to(root).as_posix()+'\n' for path in payload)
        put(root,'DEBIAN/md5sums',md5.encode())
        for path in sorted(root.rglob('*')):
            if path.is_dir():path.chmod(0o755)
            os.utime(path,(epoch,epoch))
        os.utime(root,(epoch,epoch))
        env=dict(os.environ,SOURCE_DATE_EPOCH=str(epoch),DPKG_DEB_THREADS_MAX='1',TZ='UTC',LC_ALL='C')
        temporary=Path(directory)/target.name
        subprocess.run(['dpkg-deb','--root-owner-group','--uniform-compression','-Zxz','-z9','--build',str(root),str(temporary)],check=True,env=env)
        shutil.copyfile(temporary,target)
    checksum=hashlib.sha256(target.read_bytes()).hexdigest()
    (output/'SHA256SUMS').write_text(f'{checksum}  {target.name}\n')
    print(f'Paquet : {target}\nSHA256 : {checksum}\nSource : {commit}')
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref',default='v1.0.0',help='Tag ou commit de la version a empaqueter')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'dist')
    args=parser.parse_args();build(args.ref,args.output_dir)


if __name__=='__main__':main()
