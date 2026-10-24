#define UNICODE
#define _UNICODE
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

/* Forward Unicode arguments using the Windows quoting rules, never a shell. */
static wchar_t command[32768];
static size_t used=0;
static int append(wchar_t ch) {
    if (used>=32766) return 0;
    command[used++]=ch;command[used]=0;return 1;
}
static int quote(const wchar_t *arg) {
    if (!append(L'"')) return 0;
    while (*arg) {
        size_t slashes=0;
        while (*arg==L'\\') { slashes++;arg++; }
        if (*arg==L'"' || !*arg) slashes*=2;
        while (slashes--) if (!append(L'\\')) return 0;
        if (!*arg) break;
        if (*arg==L'"' && !append(L'\\')) return 0;
        if (!append(*arg++)) return 0;
    }
    return append(L'"');
}
int WINAPI wWinMain(HINSTANCE instance,HINSTANCE previous,PWSTR tail,int show) {
    (void)instance;(void)previous;(void)tail;(void)show;
    wchar_t root[32768],python[32768],bootstrap[32768];
    DWORD size=GetModuleFileNameW(NULL,root,32768);
    if (!size || size>=32768) return 2;
    wchar_t *end=wcsrchr(root,L'\\');if (!end) return 2;*end=0;
    if (wcslen(root)+40>=32768) return 2;
    wcscpy(python,root);wcscat(python,L"\\runtime\\bin\\pythonw.exe");
    wcscpy(bootstrap,root);wcscat(bootstrap,L"\\bootstrap.py");
    int argc=0;LPWSTR *argv=CommandLineToArgvW(GetCommandLineW(),&argc);
    if (!argv) return 2;
    int ok=quote(python)&&append(L' ')&&quote(L"-I")&&append(L' ')&&quote(L"-B")&&append(L' ')&&quote(bootstrap);
    for (int i=1;ok && i<argc;i++) ok=append(L' ')&&quote(argv[i]);
    LocalFree(argv);
    if (!ok) { MessageBoxW(NULL,L"La ligne de commande est trop longue.",L"TunPlayer",MB_OK|MB_ICONERROR);return 2; }
    STARTUPINFOW startup={0};PROCESS_INFORMATION process={0};startup.cb=sizeof(startup);
    if (!CreateProcessW(python,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,root,&startup,&process)) {
        MessageBoxW(NULL,L"Impossible de demarrer Python. Reinstallez TunPlayer.",L"TunPlayer",MB_OK|MB_ICONERROR);return 2;
    }
    CloseHandle(process.hThread);WaitForSingleObject(process.hProcess,INFINITE);
    DWORD code=1;GetExitCodeProcess(process.hProcess,&code);CloseHandle(process.hProcess);
    return (int)code;
}
