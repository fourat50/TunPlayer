Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!ifndef VERSION
!error "VERSION is required"
!endif
!ifndef BUNDLE_ROOT
!error "BUNDLE_ROOT is required"
!endif
!ifndef OUTPUT
!error "OUTPUT is required"
!endif
Name "TunPlayer ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\TunPlayer"
InstallDirRegKey HKCU "Software\TunPlayer" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
!define MUI_ICON "${BUNDLE_ROOT}\tunplayer.ico"
!define MUI_UNICON "${BUNDLE_ROOT}\tunplayer.ico"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "English"
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "TunPlayer necessite Windows 64 bits."
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "TunPlayer necessite Windows 10 ou Windows 11."
    Abort
  ${EndIf}
  SetShellVarContext current
FunctionEnd
Section "TunPlayer" Main
  SetOutPath "$INSTDIR"
  File /r "${BUNDLE_ROOT}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\TunPlayer"
  CreateShortcut "$SMPROGRAMS\TunPlayer\TunPlayer.lnk" "$INSTDIR\TunPlayer.exe"
  CreateShortcut "$SMPROGRAMS\TunPlayer\Desinstaller.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\TunPlayer" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TunPlayer" "DisplayName" "TunPlayer"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TunPlayer" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TunPlayer" "Publisher" "fourat50"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TunPlayer" "DisplayIcon" "$INSTDIR\TunPlayer.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TunPlayer" "UninstallString" '$"$INSTDIR\Uninstall.exe$"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TunPlayer" "QuietUninstallString" '$"$INSTDIR\Uninstall.exe$" /S'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TunPlayer" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TunPlayer" "NoRepair" 1
SectionEnd
Section "Uninstall"
  SetShellVarContext current
  IfFileExists "$INSTDIR\build-manifest.json" +3
    MessageBox MB_ICONSTOP "Installation TunPlayer introuvable."
    Abort
  Delete "$SMPROGRAMS\TunPlayer\TunPlayer.lnk"
  Delete "$SMPROGRAMS\TunPlayer\Desinstaller.lnk"
  RMDir "$SMPROGRAMS\TunPlayer"
  DeleteRegKey HKCU "Software\TunPlayer"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\TunPlayer"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\support"
  Delete "$INSTDIR\TunPlayer.exe"
  Delete "$INSTDIR\bootstrap.py"
  Delete "$INSTDIR\build-manifest.json"
  Delete "$INSTDIR\tunplayer.ico"
  Delete "$INSTDIR\Windows-README.md"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd
