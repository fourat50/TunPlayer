#!/usr/bin/env python3
"""Apply the Linux/Windows repository separation without rewriting history."""
import json
from pathlib import Path
import subprocess

LINUX=Path(__file__).resolve().parents[1]
WINDOWS=LINUX.with_name('TunPlayer Win')
LINUX_REPO='fourat50/TunPlayer'
WINDOWS_REPO='fourat50/TunPlayer-for-Windows'
OLD_BRANCH='windows-build-1.6.1-2460841cd97f'
OLD_COMMIT='2460841cd97f53ec35cefad59b1e12cf8bbfc180'


def run(*args,cwd=LINUX):
    result=subprocess.run(args,cwd=cwd,text=True,capture_output=True)
    if result.returncode:raise RuntimeError(result.stderr.strip() or 'Échec : '+args[0])
    return result.stdout.strip()


def remote_ref(repo,branch):
    result=run('git','ls-remote','https://github.com/'+repo+'.git','refs/heads/'+branch)
    return result.split()[0] if result else None


def archive_old_branch():
    commit=remote_ref(LINUX_REPO,OLD_BRANCH)
    if commit is None:return
    if commit!=OLD_COMMIT:raise RuntimeError('La branche Windows historique a changé ; transfert arrêté.')
    archive='archive/'+OLD_BRANCH
    destination=remote_ref(WINDOWS_REPO,archive)
    if destination and destination!=commit:raise RuntimeError('La branche archive contient un autre commit.')
    if not destination:
        run('git','fetch','https://github.com/'+LINUX_REPO+'.git','refs/heads/'+OLD_BRANCH,cwd=WINDOWS)
        run('git','push','https://github.com/'+WINDOWS_REPO+'.git',commit+':refs/heads/'+archive,cwd=WINDOWS)
    if remote_ref(WINDOWS_REPO,archive)!=commit:raise RuntimeError('Archivage distant non confirmé.')
    # Delete only this exact old branch, and only after preserving it in Windows.
    run('git','push','--force-with-lease=refs/heads/'+OLD_BRANCH+':'+commit,
        'https://github.com/'+LINUX_REPO+'.git',':refs/heads/'+OLD_BRANCH)


def main():
    for folder,repo in ((LINUX,LINUX_REPO),(WINDOWS,WINDOWS_REPO)):
        if run('git','status','--porcelain',cwd=folder):raise RuntimeError('Modifications non commitées : '+str(folder))
        if run('git','remote','get-url','origin',cwd=folder)!='https://github.com/'+repo+'.git':
            raise RuntimeError('Dépôt origin inattendu : '+str(folder))
    if run('git','ls-files','packaging/windows'):
        raise RuntimeError('Recette Windows suivie dans le dépôt Linux.')
    run('gh','auth','status')
    for folder,repo,description in (
        (LINUX,LINUX_REPO,'TunPlayer pour Linux : lecteur IPTV, films, séries et radios. Paquets .deb et archives autonomes.'),
        (WINDOWS,WINDOWS_REPO,'TunPlayer pour Windows : lecteur IPTV, films, séries et radios. Installateur .exe et version portable.')):
        # Ordinary pushes stop on divergence; never force either main branch.
        run('git','push','https://github.com/'+repo+'.git','HEAD:refs/heads/main',cwd=folder)
        run('gh','repo','edit',repo,'--description',description,'--default-branch','main')
        print('Code, branche principale et description mis à jour : '+repo,flush=True)
    archive_old_branch()
    run('gh','release','edit','v1.6.1','--repo',LINUX_REPO,
        '--title','TunPlayer 1.6.1 — Linux autonome','--notes-file',str(LINUX/'packaging/releases/v1.6.1.md'))
    for repo in (LINUX_REPO,WINDOWS_REPO):
        info=json.loads(run('gh','api','repos/'+repo))
        if info['default_branch']!='main':raise RuntimeError('Branche principale non confirmée : '+repo)
    if remote_ref(LINUX_REPO,OLD_BRANCH):raise RuntimeError('La branche Windows est encore présente dans Linux.')
    print('Séparation terminée. L’historique de la branche Windows est conservé dans le dépôt Windows.')
    print('Pour publier l’installateur Windows validé : scripts/publish_windows_release.py --cloud dans TunPlayer Win.')


if __name__=='__main__':
    try:main()
    except (RuntimeError,OSError) as error:raise SystemExit(str(error))
