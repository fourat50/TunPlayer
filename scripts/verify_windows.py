#!/usr/bin/env python3
"""Test the real installed EXE with a clean PATH, Unicode path and embedded HWND."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def verify(installer,output):
    if sys.platform!='win32':raise RuntimeError('Le test de l’installateur necessite Windows.')
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\TunPlayer'):pass
    except FileNotFoundError:pass
    else:raise RuntimeError('Une installation TunPlayer existe deja : test isole annule pour la conserver.')
    installer=Path(installer).resolve();output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    if installer.read_bytes()[:2]!=b'MZ':raise RuntimeError('Le fichier n’est pas un executable Windows.')
    env={k:v for k,v in os.environ.items() if k not in ('MSYSTEM','MINGW_PREFIX','PYTHONHOME','PYTHONPATH','GI_TYPELIB_PATH','GDK_PIXBUF_MODULE_FILE','GTK_DATA_PREFIX','XDG_DATA_DIRS')}
    system=Path(os.environ['WINDIR']);env['PATH']=str(system/'System32')+os.pathsep+str(system)
    with tempfile.TemporaryDirectory(prefix='TunPlayer installation espace ete-') as directory:
        target=Path(directory)/'application avec espaces é'
        # NSIS /D must be the final raw command-line tail, without quotes around it.
        command=f'"{installer}" /S /D={target}'
        try:
            subprocess.run(command,executable=str(installer),check=True,timeout=180,env=env)
            executable=target/'TunPlayer.exe'
            if not executable.is_file():raise RuntimeError('L’installateur n’a pas cree le lanceur.')
            result=subprocess.run([str(executable),'--smoke-test',str(output)],timeout=90,env=env)
            if not output.is_file():raise RuntimeError('Le lanceur n’a pas produit son rapport de verification.')
            report=json.loads(output.read_text(encoding='utf-8'))
            if result.returncode or not report.get('ok'):raise RuntimeError(json.dumps(report,ensure_ascii=False))
            report['installer_sha256']=hashlib.sha256(installer.read_bytes()).hexdigest()
            report['relocated_without_msys2']=True
        finally:
            uninstall=target/'Uninstall.exe'
            if uninstall.exists():
                subprocess.run([str(uninstall),'/S'],check=True,timeout=120,env=env)
                deadline=time.monotonic()+45
                while target.exists() and time.monotonic()<deadline:time.sleep(.2)
                if target.exists():raise RuntimeError('La desinstallation n’a pas termine le nettoyage.')
    report['install_uninstall']=True
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Installation, Python/GTK autonome, mpv integre, episode suivant et desinstallation : OK')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer',type=Path)
    parser.add_argument('--report',type=Path,default=Path('dist/windows-verification.json'))
    args=parser.parse_args();verify(args.installer,args.report)


if __name__=='__main__':main()
