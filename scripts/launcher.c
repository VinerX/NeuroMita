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

static int open_wait_handle(DWORD pid, HANDLE *process_out) {
    HANDLE process;
    DWORD error;

    *process_out = NULL;
    if (pid == 0 || pid == GetCurrentProcessId()) {
        return 1;
    }

    process = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (process == NULL) {
        error = GetLastError();
        if (error == ERROR_INVALID_PARAMETER) {
            return 1;
        }
        fwprintf(stderr, L"ERROR: Не удалось открыть процесс %lu для ожидания (Win32: %lu).\n",
                 pid, error);
        return 0;
    }

    *process_out = process;
    return 1;
}

static int wait_for_process_handle(DWORD pid, HANDLE process) {
    DWORD wait_result;

    if (process == NULL) {
        return 1;
    }

    wait_result = WaitForSingleObject(process, INFINITE);
    if (wait_result != WAIT_OBJECT_0) {
        fwprintf(stderr, L"ERROR: Ошибка ожидания процесса %lu (код: %lu).\n",
                 pid, wait_result);
        return 0;
    }
    return 1;
}

static int apply_pending_zipapp(const wchar_t *launcher_dir) {
    wchar_t pending[MAX_PATH];
    wchar_t active[MAX_PATH];
    wchar_t marker[MAX_PATH];
    wchar_t pending_dir[MAX_PATH];
    wchar_t python_update_dir[MAX_PATH];
    wchar_t update_dir[MAX_PATH];
    DWORD attributes;

    if (_snwprintf_s(pending, ARRAYSIZE(pending), _TRUNCATE,
                     L"%ls\\.update\\python\\pending\\NeuroMita.pyz", launcher_dir) < 0 ||
        _snwprintf_s(active, ARRAYSIZE(active), _TRUNCATE,
                     L"%ls\\NeuroMita.pyz", launcher_dir) < 0 ||
        _snwprintf_s(marker, ARRAYSIZE(marker), _TRUNCATE,
                     L"%ls\\.update\\python\\activation.json", launcher_dir) < 0 ||
        _snwprintf_s(pending_dir, ARRAYSIZE(pending_dir), _TRUNCATE,
                     L"%ls\\.update\\python\\pending", launcher_dir) < 0 ||
        _snwprintf_s(python_update_dir, ARRAYSIZE(python_update_dir), _TRUNCATE,
                     L"%ls\\.update\\python", launcher_dir) < 0 ||
        _snwprintf_s(update_dir, ARRAYSIZE(update_dir), _TRUNCATE,
                     L"%ls\\.update", launcher_dir) < 0) {
        fputws(L"ERROR: Путь pending Python update слишком длинный.\n", stderr);
        return 0;
    }

    attributes = GetFileAttributesW(pending);
    if (attributes == INVALID_FILE_ATTRIBUTES) {
        return 1;
    }
    if (attributes & FILE_ATTRIBUTE_DIRECTORY) {
        fputws(L"ERROR: Pending NeuroMita.pyz оказался директорией.\n", stderr);
        return 0;
    }

    fputws(L"Применяю подготовленное обновление NeuroMita.pyz...\n", stdout);
    if (!MoveFileExW(
            pending,
            active,
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        fwprintf(
            stderr,
            L"ERROR: Не удалось атомарно активировать NeuroMita.pyz (Win32: %lu). "
            L"Старый файл оставлен активным, pending update сохранён.\n",
            GetLastError());
        return 0;
    }

    DeleteFileW(marker);
    RemoveDirectoryW(pending_dir);
    RemoveDirectoryW(python_update_dir);
    RemoveDirectoryW(update_dir);
    fputws(L"NeuroMita.pyz успешно активирован.\n", stdout);
    return 1;
}

static int collect_wait_pids(int argc, wchar_t **argv, DWORD *pids, size_t capacity, size_t *count) {
    int index;
    *count = 0;

    for (index = 1; index < argc; ++index) {
        wchar_t *end = NULL;
        unsigned long value;

        if (wcscmp(argv[index], L"--wait-pid") != 0) {
            fwprintf(stderr, L"ERROR: Неизвестный аргумент Launcher.exe: %ls\n", argv[index]);
            return 0;
        }
        if (++index >= argc) {
            fputws(L"ERROR: После --wait-pid требуется PID процесса.\n", stderr);
            return 0;
        }
        value = wcstoul(argv[index], &end, 10);
        if (end == argv[index] || *end != L'\0' || value == 0 || value > MAXDWORD) {
            fwprintf(stderr, L"ERROR: Некорректный PID: %ls\n", argv[index]);
            return 0;
        }
        if (*count >= capacity) {
            fputws(L"ERROR: Слишком много процессов передано для ожидания.\n", stderr);
            return 0;
        }
        pids[(*count)++] = (DWORD)value;
    }
    return 1;
}

int wmain(int argc, wchar_t **argv) {
    wchar_t launcher_dir[MAX_PATH];
    wchar_t batch_file[MAX_PATH];
    wchar_t cmd_exe[MAX_PATH];
    wchar_t command_line[MAX_PATH * 3 + 32];
    wchar_t *last_separator;
    DWORD launcher_path_length;
    UINT system_dir_length;
    STARTUPINFOW startup_info;
    PROCESS_INFORMATION process_info;
    DWORD wait_pids[8];
    HANDLE wait_handles[8];
    size_t wait_pid_count = 0;
    size_t index;

    ZeroMemory(&startup_info, sizeof(startup_info));
    ZeroMemory(&process_info, sizeof(process_info));
    startup_info.cb = sizeof(startup_info);

    configure_console();

    if (!collect_wait_pids(argc, argv, wait_pids, ARRAYSIZE(wait_pids), &wait_pid_count)) {
        wait_for_key();
        return 1;
    }

    ZeroMemory(wait_handles, sizeof(wait_handles));

    launcher_path_length = GetModuleFileNameW(NULL, launcher_dir, ARRAYSIZE(launcher_dir));
    if (launcher_path_length == 0 || launcher_path_length >= ARRAYSIZE(launcher_dir)) {
        return fail(L"ERROR: Не удалось определить папку Launcher.exe.");
    }

    last_separator = wcsrchr(launcher_dir, L'\\');
    if (last_separator == NULL) {
        return fail(L"ERROR: Некорректный путь к Launcher.exe.");
    }
    *last_separator = L'\0';

    /*
     * Open every process handle before waiting. This pins the exact process
     * objects and avoids a PID-reuse race if the supervisor exits immediately
     * after the application process.
     */
    for (index = 0; index < wait_pid_count; ++index) {
        if (!open_wait_handle(wait_pids[index], &wait_handles[index])) {
            size_t close_index;
            for (close_index = 0; close_index < index; ++close_index) {
                if (wait_handles[close_index] != NULL) {
                    CloseHandle(wait_handles[close_index]);
                }
            }
            wait_for_key();
            return 1;
        }
    }

    for (index = 0; index < wait_pid_count; ++index) {
        int waited = wait_for_process_handle(wait_pids[index], wait_handles[index]);
        if (wait_handles[index] != NULL) {
            CloseHandle(wait_handles[index]);
        }
        if (!waited) {
            size_t close_index;
            for (close_index = index + 1; close_index < wait_pid_count; ++close_index) {
                if (wait_handles[close_index] != NULL) {
                    CloseHandle(wait_handles[close_index]);
                }
            }
            wait_for_key();
            return 1;
        }
    }

    if (!apply_pending_zipapp(launcher_dir)) {
        wait_for_key();
        return 1;
    }

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
     * Launcher owns only the post-exit activation boundary. Once any pending
     * zipapp has been promoted, it delegates to the same run.bat entry point
     * and exits immediately, so Launcher.exe itself is not kept locked while
     * NeuroMita is running.
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
