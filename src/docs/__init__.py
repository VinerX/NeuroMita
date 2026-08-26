from core.error_utils import format_exception

import os
import webbrowser
import sys

# --- HTML Контент Документации ---
_INSTALLATION_GUIDE_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <title>Установка компонентов для локальной озвучки</title>
    <meta charset="UTF-8">
    <style>
        body { 
            font-family: 'Segoe UI', Arial, sans-serif; 
            line-height: 1.6;
            margin: 0;
            padding: 25px;
            color: #e0e0e0; /* Светлый текст */
            background-color: #1e1e1e; /* Темный фон */
            max-width: 1000px;
            margin: 20px auto; /* Центрирование и отступы */
            border: 1px solid #444;
            border-radius: 5px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.5);
        }
        h1, h2, h3 { color: #64b5f6; /* Голубоватый для заголовков */ }
        h1 { text-align: center; border-bottom: 1px solid #444; padding-bottom: 10px; margin-bottom: 25px;}
        .requirement, .note, .warning, .model-info, .optional-component { 
            padding: 15px;
            margin-bottom: 20px;
            border-left: 5px solid;
            background-color: #2a2a2a; /* Чуть светлее фона */
            border-radius: 3px;
        }
        .requirement { border-color: #8e44ad; /* Фиолетовый */ }
        .warning { background-color: #4d3a00; border-color: #ffab00; /* Оранжевый/желтый */ color: #ffd54f; }
        .note { background-color: #1e3a5f; border-color: #2196F3; /* Синий */ color: #bbdefb;}
        .model-info { background-color: #1b4d2d; border-color: #4CAF50; /* Зеленый */ color: #c8e6c9;}
        /* Используем новый стиль для опциональных компонентов */
        .optional-component { background-color: #3a2f4a; border-color: #ab47bc; /* Пурпурный */ color: #e1bee7; } 
        a { color: #81d4fa; text-decoration: none; } /* Светло-голубые ссылки */
        a:hover { text-decoration: underline; }
        ul, ol { padding-left: 25px; }
        li { margin-bottom: 8px; }
        code { 
            background-color: #333;
            padding: 3px 6px;
            border-radius: 3px;
            font-family: 'Consolas', 'Courier New', monospace;
            color: #f0f0f0;
            border: 1px solid #444;
        }
        strong { color: #fdd835; /* Желтый для акцентов */ }
    </style>
</head>
<body>
    <h1>Установка компонентов для локальной озвучки</h1>
    
    <div class="note">
        <p><strong>Коротко:</strong> для Fish Speech+ приложение устанавливает <code>triton-windows</code> и настраивает его само. LLVM, полный CUDA Toolkit и Visual Studio Build Tools вручную обычно не нужны.</p>
    </div>
    
    <div class="model-info">
        <h3>Информация о моделях и требованиях</h3>
        <ul>
            <li><strong>Edge-TTS + RVC (low):</strong> Базовая модель, <em>не требует</em> установки дополнительных компонентов.</li>
            <li><strong>Silero + RVC (low+):</strong> Базовая модель, <em>не требует</em> установки дополнительных компонентов.</li>
            <li><strong>Fish Speech (medium):</strong> Базовая модель, <em>не требует</em> установки дополнительных компонентов. <strong>Требуется NVIDIA GPU.</strong></li>
            <li><strong>Fish Speech+ (medium+):</strong> использует torch.compile/Triton. Рекомендуется NVIDIA с compute capability <strong>SM 8.0+</strong>.</li>
            <li><strong>Fish Speech+RVC (medium+low):</strong> те же требования к компиляции, плюс зависимости RVC.</li>
            <li><strong>F5-TTS (high):</strong> живой и выразительный голос по референсному аудио; поддерживает NVIDIA, AMD, Intel и CPU, но может быть менее стабильным, чем Fish Speech.</li>
            <li><strong>F5-TTS + RVC (high+low):</strong> F5-TTS с дополнительным приближением тембра через RVC; требует больше ресурсов.</li>
        </ul>
    </div>
    
    <h2 id="fish_compile">Компиляция Fish Speech+</h2>
    <div class="requirement">
        <p>При первой озвучке модель может компилироваться несколько минут. Чтобы сделать это заранее, откройте <strong>AI Hub → локальные модели → Fish Speech+ → настройки</strong> и нажмите <strong>«Компилировать»</strong>.</p>
        <p>После создания кеша там же доступны <strong>«Перекомпилировать»</strong> и <strong>«Удалить компиляцию»</strong>. Приложение хранит один общий кеш в управляемой папке <code>Lib/environment/cache</code>; новые папки-поколения не создаются.</p>
        <p>Без переменной <code>CC</code> и заранее активированного окружения Visual Studio Triton Windows использует встроенный TinyCC. Опытный пользователь может переопределить компилятор через <code>CC</code>; для MSVC также требуется окружение Visual Studio с путями SDK.</p>
        <p><a href="https://github.com/triton-lang/triton-windows" target="_blank" rel="noopener noreferrer">Документация Triton Windows</a></p>

        <h3 id="triton_msvc_fallback">Если встроенный TinyCC не работает</h3>
        <p>Переход на MSVC имеет смысл, если в полном логе компиляции упоминается <code>tcc.exe</code>, не удаётся собрать <code>__triton_launcher.pyd</code> либо TinyCC сообщает об ошибке компиляции или линковки. VC++ Redistributable для этого недостаточно: нужен именно компилятор и Windows SDK.</p>
        <ol>
            <li>Установите <a href="https://visualstudio.microsoft.com/visual-cpp-build-tools/" target="_blank" rel="noopener noreferrer">Visual Studio Build Tools</a>. В установщике выберите MSVC v143 для x64/x86 и актуальный Windows 10/11 SDK.</li>
            <li>Откройте <strong>x64 Native Tools Command Prompt for VS 2022</strong> и из него запустите <code>Launcher.exe</code>. Это добавит в процесс не только <code>cl.exe</code>, но и обязательные пути <code>INCLUDE</code>/<code>LIB</code> для SDK.</li>
            <li>В AI Hub откройте настройки Fish Speech+, удалите неудачную компиляцию и нажмите <strong>«Компилировать»</strong> повторно.</li>
        </ol>
        <p>Эквивалент для обычного <code>cmd.exe</code> (путь зависит от редакции Visual Studio):</p>
        <pre><code>call "C:\\Program Files (x86)\\Microsoft Visual Studio\\2022\\BuildTools\\Common7\\Tools\\VsDevCmd.bat" -arch=amd64
Launcher.exe</code></pre>
        <p>Если переменная <code>CC</code> уже задана вручную и указывает на TinyCC, после активации Visual Studio environment выполните <code>set CC=cl</code>. Не задавайте только путь к <code>cl.exe</code> без окружения SDK — такая проверка выглядит успешной, но сборка обычно падает на заголовках или библиотеках.</p>
        <p><a href="https://github.com/triton-lang/triton-windows?tab=readme-ov-file#5-c-compiler" target="_blank" rel="noopener noreferrer">Подробнее о выборе C-компилятора в Triton Windows</a></p>
    </div>

    <div class="optional-component" id="vc_redist">
        <h3>VC++ Redistributable — только при DLL-ошибке</h3>
        <p>Предоставляет библиотеки времени выполнения C++, необходимые для запуска приложений, скомпилированных с помощью Visual Studio. Устраняет ошибки, связанные с отсутствием DLL-файлов (например, <code>VCRUNTIME140_1.dll</code>).</p>
        <ul>
            <li><a href="https://aka.ms/vs/17/release/vc_redist.x64.exe" target="_blank" rel="noopener noreferrer">Загрузить Microsoft Visual C++ Redistributable (x64)</a> (Обычно последняя версия является подходящей).</li>
        </ul>
        <p>Установите загруженный пакет.</p>
    </div>

    <div class="note">
        <p><strong>Длинные пути Windows:</strong> если Triton сообщает о превышении длины пути, включите поддержку длинных путей кнопкой в окне компиляции и перезапустите Windows. <a href="https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation" target="_blank" rel="noopener noreferrer">Документация Microsoft</a>.</p>
        <p>При повторной ошибке сохраните лог окна компиляции и приложите его к обращению в <a href="https://github.com/VinerX/NeuroMita/issues" target="_blank" rel="noopener noreferrer">Issues</a>.</p>
    </div>
</body>
</html>
"""

# _OTHER_DOC_HTML = """..."""

class DocsManager:
    """
    Управляет созданием, хранением и открытием HTML файлов документации.
    """
    def __init__(self):
        # Определяем путь к папке 'docs', где находится этот файл
        self.docs_dir = os.path.dirname(os.path.abspath(sys.executable))
        
        # Словарь для хранения контента документации {имя_файла: html_строка}
        self.doc_contents = {
            "installation_guide.html": _INSTALLATION_GUIDE_HTML,
            # "another_guide.html": _OTHER_DOC_HTML, # Пример для будущих доков
        }

    def _get_doc_path(self, doc_name: str) -> str:
        """Возвращает полный путь к файлу документации."""
        return os.path.join(self.docs_dir, doc_name)

    def _ensure_doc_exists(self, doc_name: str) -> bool:
        """
        Проверяет, существует ли файл документации. Если нет, создает его
        из хранящегося контента.
        Возвращает True, если файл существует или был успешно создан, иначе False.
        """
        doc_path = self._get_doc_path(doc_name)
        
        if doc_name in self.doc_contents:
            html_content = self.doc_contents[doc_name]
            try:
                # Убедимся, что директория существует 
                os.makedirs(self.docs_dir, exist_ok=True) 
                
                # Записываем HTML контент в файл
                with open(doc_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"Документация '{doc_path}' обновлена.")
                return True
            except Exception as e:
                print(f"Ошибка при создании файла документации '{doc_path}': {format_exception(e)}")
                return False
        if os.path.exists(doc_path):
            return True
        print(f"Ошибка: Контент для документа '{doc_name}' не найден в DocsManager.")
        return False

    def open_doc(self, doc_name: str):
        """
        Открывает указанный файл документации в веб-браузере по умолчанию.
        Если файл не существует, пытается его создать.
        """
        print(f"Запрос на открытие документации: {doc_name}")
        file_name, separator, anchor = str(doc_name).partition("#")
        if self._ensure_doc_exists(file_name):
            doc_path = self._get_doc_path(file_name)
            try:
                file_uri = 'file:///' + os.path.realpath(doc_path).replace('\\', '/')
                if separator and anchor:
                    file_uri += "#" + anchor
                print(f"Открытие файла: {file_uri}")
                webbrowser.open(file_uri)
            except Exception as e:
                print(f"Не удалось открыть файл документации '{doc_path}' в браузере: {format_exception(e)}")
        else:
            print(f"Не удалось открыть документацию '{doc_name}', так как файл не существует и не может быть создан.")
