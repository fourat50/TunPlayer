#!/usr/bin/env python3
"""Assemble a native UCRT64 Python/GTK runtime and an NSIS x64 installer."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
RECIPE=ROOT/'packaging/windows'


def run(args,**kwargs):return subprocess.run([str(v) for v in args],check=True,**kwargs)


def runtime_file(relative):
    parts=relative.parts
    if '__pycache__' in parts or relative.suffix in ('.pyc','.a','.h','.la'):return False
    if parts[0]=='bin':return relative.suffix.lower()=='.dll' or relative.name in ('python.exe','pythonw.exe','ffmpeg.exe','gdk-pixbuf-query-loaders.exe')
    if parts[0]=='lib':
        if len(parts)>1 and parts[1].startswith('python3'):
            return not any(p in ('test','tests','idlelib','tkinter','ensurepip') for p in parts)
        return len(parts)>1 and parts[1] in ('girepository-1.0','gdk-pixbuf-2.0','gtk-3.0','gio') and relative.suffix not in ('.cache',)
    if parts[0]=='share':return len(parts)>1 and parts[1] in ('glib-2.0','icons','themes','licenses','fontconfig','fonts')
    if parts[0]=='etc':return len(parts)>1 and parts[1]=='fonts'
    return False


def make_icon(source,destination):
    import gi
    gi.require_version('GdkPixbuf','2.0')
    from gi.repository import GdkPixbuf
    images=[]
    for size in (32,48,128,256):
        pix=GdkPixbuf.Pixbuf.new_from_file_at_scale(str(source),size,size,False)
        ok,data=pix.save_to_bufferv('png',[],[])
        if not ok:raise RuntimeError('Conversion de l’icone impossible.')
        images.append((size,bytes(data)))
    offset=6+16*len(images);entries=[]
    for size,data in images:
        entries.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(data),offset));offset+=len(data)
    destination.write_bytes(struct.pack('<HHH',0,1,len(images))+b''.join(entries)+b''.join(data for _,data in images))


def version():
    for node in ast.parse((ROOT/'tunplayer/__init__.py').read_text()).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in node.targets):return ast.literal_eval(node.value)
    raise ValueError('Version absente')


def build(prefix,output):
    if sys.platform!='win32':raise RuntimeError('La construction necessite Windows avec MSYS2 UCRT64.')
    dirty=subprocess.check_output(['git','status','--porcelain','--untracked-files=normal','--','tunplayer','assets','run.py','packaging/windows','scripts/build_windows.py','scripts/verify_windows.py'],cwd=ROOT,text=True)
    if dirty:raise RuntimeError('Commitez les sources et la recette avant de construire une version publiable.')
    prefix=Path(prefix).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    bundle=output/'windows-bundle'
    if bundle.exists():shutil.rmtree(bundle)
    bundle.mkdir();runtime=bundle/'runtime'
    for directory in ('bin','lib','share','etc'):
        source=prefix/directory
        if not source.is_dir():continue
        for path in source.rglob('*'):
            if path.is_file() and runtime_file(path.relative_to(prefix)):
                target=runtime/path.relative_to(prefix);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    certs=[prefix/'etc/ssl/cert.pem',prefix/'etc/ssl/certs/ca-bundle.crt',prefix.parent/'usr/ssl/certs/ca-bundle.crt',prefix.parent/'etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem']
    for path in certs:
        if path.is_file() and b'-----BEGIN CERTIFICATE-----' in path.read_bytes():
            target=runtime/'etc/ssl/cert.pem';target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target);break
    else:raise RuntimeError('Certificats HTTPS MSYS2 introuvables.')
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    for name in tracked:
        if name=='run.py' or (name.startswith('tunplayer/') and name.endswith('.py')) or name in ('assets/style.css','assets/tunplayer.svg','assets/demo.mp4'):
            target=bundle/'app'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    support=bundle/'support';support.mkdir()
    shutil.copyfile(RECIPE/'windows_smoke.py',support/'windows_smoke.py')
    shutil.copyfile(RECIPE/'bootstrap.py',bundle/'bootstrap.py')
    shutil.copyfile(RECIPE/'Windows-README.md',bundle/'Windows-README.md')
    required=['bin/pythonw.exe','bin/python.exe','bin/libmpv-2.dll','bin/libgdk-3-0.dll','bin/ffmpeg.exe','bin/gdk-pixbuf-query-loaders.exe','lib/girepository-1.0/Gtk-3.0.typelib']
    for name in required:
        if not (runtime/name).is_file():raise RuntimeError('Fichier du runtime absent : '+name)
    packages=subprocess.check_output(['pacman','-Q'],text=True).splitlines()
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifest=dict(version=version(),source_commit=commit,platform='windows-x64-ucrt',python=sys.version,
        packages=[line for line in sorted(packages) if line.startswith('mingw-w64-ucrt-x86_64-') or line.startswith('ca-certificates ')],
        package_source='https://packages.msys2.org',rebuild='scripts/build_windows.py')
    (bundle/'build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    make_icon(ROOT/'assets/tunplayer.svg',bundle/'tunplayer.ico')
    resource=output/'launcher.rc'
    resource.write_text(f'1 ICON "{(bundle/"tunplayer.ico").as_posix()}"\n1 24 "{(RECIPE/"launcher.manifest").as_posix()}"\n',encoding='utf-8')
    obj=output/'launcher-res.o';run([prefix/'bin/windres.exe',resource,'-O','coff','-o',obj])
    run([prefix/'bin/gcc.exe','-O2','-s','-municode','-mwindows','-static-libgcc','-Wl,--no-insert-timestamp',RECIPE/'launcher.c',obj,'-lshell32','-o',bundle/'TunPlayer.exe'])
    installer=output/f'TunPlayer-{manifest["version"]}-windows-x64-setup.exe'
    run([prefix/'bin/makensis.exe',f'/DVERSION={manifest["version"]}',f'/DBUNDLE_ROOT={bundle.as_posix()}',f'/DOUTPUT={installer.as_posix()}',RECIPE/'installer.nsi'])
    digest=hashlib.sha256(installer.read_bytes()).hexdigest()
    (output/'Windows-SHA256SUMS').write_text(f'{digest}  {installer.name}\n',encoding='utf-8')
    shutil.copyfile(RECIPE/'Windows-README.md',output/'Windows-README.md')
    print(f'Installateur : {installer}\nSHA256 : {digest}\nSource : {commit}')
    return installer


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',type=Path,default=Path(sys.executable).resolve().parent.parent)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'dist')
    args=parser.parse_args();build(args.prefix,args.output_dir)


if __name__=='__main__':main()
