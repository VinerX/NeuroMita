import os
from pathlib import Path

# Ищем файл установщика
file_path = Path("src/utils/pip_installer.py")
if not file_path.exists():
    file_path = Path("utils/pip_installer.py")

if not file_path.exists():
    print("Ошибка: файл pip_installer.py не найден!")
    exit(1)

code = file_path.read_text(encoding="utf-8")

# 1. Исправляем race condition в цикле чтения пайпов (чтобы не терять хвост лога)
old_loop = "while proc.poll() is None:"
new_loop = "while proc.poll() is None or t_out.is_alive() or t_err.is_alive():"
code_mod = code.replace(old_loop, new_loop)

# 2. Исправляем ложные срабатывания слова "error" в путях компиляции (build\lib\antlr4\error)
old_error_check = 'if any(k in low for k in ("error", "ошибка", "failed", "traceback", "exception", "critical")):'
new_error_check = 'if any(k in low for k in ("error:", "ошибка:", "failed:", "traceback", "exception", "critical")) or (("error" in low or "failed" in low) and "build\\\\" not in low and "bdist." not in low):'
code_mod = code_mod.replace(old_error_check, new_error_check)

if code_mod != code:
    file_path.write_text(code_mod, encoding="utf-8")
    print("✓ pip_installer.py успешно обновлен! Баг гонки потоков устранен.")
else:
    print("Ошибка: Шаблоны для замены не найдены. Убедитесь, что используете оригинальный файл.")