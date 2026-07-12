#include <windows.h>
#include <conio.h>
#include <stdio.h>
#include <wchar.h>

static void wait_for_key(void) {
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
    wchar_t python[MAX_PATH];
    wchar_t script[MAX_PATH];
    wchar_t command_line[MAX_PATH * 2 + 8];
    wchar_t *last_separator;
    DWORD launcher_path_length;
    STARTUPINFOW startup_info;
    PROCESS_INFORMATION process_info;
    DWORD exit_code = 1;

    ZeroMemory(&startup_info, sizeof(startup_info));
    ZeroMemory(&process_info, sizeof(process_info));
    startup_info.cb = sizeof(startup_info);

    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);

    launcher_path_length = GetModuleFileNameW(NULL, launcher_dir, ARRAYSIZE(launcher_dir));
    if (launcher_path_length == 0 || launcher_path_length >= ARRAYSIZE(launcher_dir)) {
        return fail(L"ERROR: Не удалось определить папку Launcher.exe.");
    }

    last_separator = wcsrchr(launcher_dir, L'\\');
    if (last_separator == NULL) {
        return fail(L"ERROR: Некорректный путь к Launcher.exe.");
    }
    *last_separator = L'\0';

    if (_snwprintf_s(python, ARRAYSIZE(python), _TRUNCATE,
                     L"%ls\\libs\\python\\python.exe", launcher_dir) < 0 ||
        _snwprintf_s(script, ARRAYSIZE(script), _TRUNCATE,
                     L"%ls\\run.py", launcher_dir) < 0) {
        return fail(L"ERROR: Путь к файлам запуска слишком длинный.");
    }

    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        return fail(L"ERROR: Не найден libs\\python\\python.exe.\n"
                    L"Извлеките ZIP-архив полностью и повторите запуск.");
    }
    if (GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        return fail(L"ERROR: Не найден run.py рядом с Launcher.exe.");
    }

    if (_snwprintf_s(command_line, ARRAYSIZE(command_line), _TRUNCATE,
                     L"\"%ls\" \"%ls\"", python, script) < 0) {
        return fail(L"ERROR: Команда запуска слишком длинная.");
    }

    if (!CreateProcessW(python, command_line, NULL, NULL, TRUE, 0, NULL,
                        launcher_dir, &startup_info, &process_info)) {
        fwprintf(stderr, L"ERROR: Не удалось запустить Python (код Win32: %lu).\n",
                 GetLastError());
        wait_for_key();
        return 1;
    }

    WaitForSingleObject(process_info.hProcess, INFINITE);
    if (!GetExitCodeProcess(process_info.hProcess, &exit_code)) {
        exit_code = 1;
    }
    CloseHandle(process_info.hThread);
    CloseHandle(process_info.hProcess);

    if (exit_code != 0) {
        fwprintf(stderr, L"\nNeuroMita завершилась с кодом %lu.\n", exit_code);
        wait_for_key();
    }
    return (int)exit_code;
}
