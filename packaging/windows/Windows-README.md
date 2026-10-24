# TunPlayer 1.0.0 pour Windows x64

Windows 10 ou Windows 11 64 bits. Python, GTK, mpv et FFmpeg sont inclus :
vous n'avez pas besoin d'installer Python ni MSYS2 pour utiliser TunPlayer.

L'installateur place le programme dans `%LOCALAPPDATA%\Programs\TunPlayer`
et ajoute un raccourci au menu Demarrer. Les donnees restent separees dans
`%LOCALAPPDATA%\TunPlayer` ; elles sont conservees lors de la desinstallation.

La video utilise une fenetre enfant Win32 dans TunPlayer, sans lecteur externe.
Une erreur de demarrage est enregistree dans le profil (`startup-error.log`).

L'installateur n'est pas signe par un certificat de signature de code.
Le manifeste `build-manifest.json` contient le commit source et les versions
des bibliotheques MSYS2. Les licences tierces sont dans `runtime/share/licenses`.
Le code et les recettes de construction sont publics :
https://github.com/fourat50/TunPlayer

Les correctifs d'integration Windows et sa recette se trouvent sur `main`.
Le tag Linux `v1.0.0` et le paquet `.deb` existant ne sont pas modifies.

Pour verifier le telechargement dans PowerShell :

```powershell
Get-FileHash .\TunPlayer-1.0.0-windows-x64-setup.exe -Algorithm SHA256
```

Comparez le resultat a `Windows-SHA256SUMS`, joint a la release GitHub.
