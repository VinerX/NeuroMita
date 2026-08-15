#include <windows.h>
#include <conio.h>
#include <fcntl.h>
#include <io.h>
#include <stdio.h>
#include <wchar.h>

static void configure_console(void) {
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    _setmode(_fileno(stdout), _O_U8TEXT);
    _setmode(_fileno(stderr), _O_U8TEXT);
}

static void wait_for_key(void) {
    if (!_isatty(_fileno(stdin))) {
        return;
    }
    fputws(L"\nНажмите любую клавишу для выхода . . .", stderr);
    _getwch();
}

static int fail(const wchar_t *message) {
    fputws(message, stderr);
    fputwc(L'\n', stderr);
    wait_for_key();
    return 1;
}

int wmain(void) {
    wchar_t launcher_dir[MAX_PATH];
    wchar_t batch_file[MAX_PATH];
    wchar_t cmd_exe[MAX_PATH];
    wchar_t command_line[MAX_PATH * 3 + 32];
    wchar_t *last_separator;
    DWORD launcher_path_length;
    UINT system_dir_length;
    STARTUPINFOW startup_info;
    PROCESS_INFORMATION process_info;

    ZeroMemory(&startup_info, sizeof(startup_info));
    ZeroMemory(&process_info, sizeof(process_info));
    startup_info.cb = sizeof(startup_info);

    configure_console();

    launcher_path_length = GetModuleFileNameW(NULL, launcher_dir, ARRAYSIZE(launcher_dir));
    if (launcher_path_length == 0 || launcher_path_length >= ARRAYSIZE(launcher_dir)) {
        return fail(L"ERROR: Не удалось определить папку Launcher.exe.");
    }

    last_separator = wcsrchr(launcher_dir, L'\\');
    if (last_separator == NULL) {
        return fail(L"ERROR: Некорректный путь к Launcher.exe.");
    }
    *last_separator = L'\0';

    if (_snwprintf_s(batch_file, ARRAYSIZE(batch_file), _TRUNCATE,
                     L"%ls\\run.bat", launcher_dir) < 0) {
        return fail(L"ERROR: Путь к run.bat слишком длинный.");
    }
    if (GetFileAttributesW(batch_file) == INVALID_FILE_ATTRIBUTES) {
        return fail(L"ERROR: Не найден run.bat рядом с Launcher.exe.");
    }

    system_dir_length = GetSystemDirectoryW(cmd_exe, ARRAYSIZE(cmd_exe));
    if (system_dir_length == 0 || system_dir_length >= ARRAYSIZE(cmd_exe)) {
        return fail(L"ERROR: Не удалось определить системную папку Windows.");
    }
    if (_snwprintf_s(cmd_exe + system_dir_length,
                     ARRAYSIZE(cmd_exe) - system_dir_length,
                     _TRUNCATE, L"\\cmd.exe") < 0) {
        return fail(L"ERROR: Путь к cmd.exe слишком длинный.");
    }

    /*
     * Delegate to the exact same batch entry point used by the fallback
     * shortcut. Launcher.exe exits as soon as cmd.exe has inherited the
     * console, so Windows does not keep the installed launcher image locked
     * while NeuroMita is running or applying an update.
     */
    if (_snwprintf_s(command_line, ARRAYSIZE(command_line), _TRUNCATE,
                     L"\"%ls\" /D /S /C call \"%ls\"", cmd_exe, batch_file) < 0) {
        return fail(L"ERROR: Команда запуска слишком длинная.");
    }

    if (!CreateProcessW(cmd_exe, command_line, NULL, NULL, TRUE, 0, NULL,
                        launcher_dir, &startup_info, &process_info)) {
        fwprintf(stderr, L"ERROR: Не удалось запустить run.bat (код Win32: %lu).\n",
                 GetLastError());
        wait_for_key();
        return 1;
    }

    CloseHandle(process_info.hThread);
    CloseHandle(process_info.hProcess);
    return 0;
}
