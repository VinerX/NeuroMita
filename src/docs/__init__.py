
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
    
    <div class="warning">
        <p><strong>Внимание:</strong> Компоненты, описанные ниже (особенно CUDA и Visual Studio), требуются <strong>в первую очередь</strong> для моделей <strong>Fish Speech+ (medium+)</strong> и <strong>Fish Speech+ + RVC (medium+low)</strong>.</p>
        <p>Модели <strong>Edge-TTS + RVC (low)</strong>, <strong>Silero + RVC (low+)</strong> и <strong>Fish Speech (medium)</strong> должны функционировать без установки данных дополнительных компонентов.</p>
    </div>
    
    <div class="model-info">
        <h3>Информация о моделях и требованиях</h3>
        <ul>
            <li><strong>Edge-TTS + RVC (low):</strong> Базовая модель, <em>не требует</em> установки дополнительных компонентов.</li>
            <li><strong>Silero + RVC (low+):</strong> Базовая модель, <em>не требует</em> установки дополнительных компонентов.</li>
            <li><strong>Fish Speech (medium):</strong> Базовая модель, <em>не требует</em> установки дополнительных компонентов. <strong>Требуется NVIDIA GPU.</strong></li>
            <li><strong>Fish Speech+ (medium+):</strong> Для компиляции Triton нужны только Microsoft VC++ Build Tools. TinyCC уже входит в triton-windows; Windows SDK и CUDA Toolkit отдельно не требуются. Рекомендуется NVIDIA с compute capability <strong>SM 8.0+</strong> (RTX 30xx, 40xx, 50xx и сопоставимые профессиональные модели).</li>
            <li><strong>Fish Speech+RVC (medium+low):</strong> Для компиляции Triton нужны только Microsoft VC++ Build Tools. TinyCC уже входит в triton-windows; Windows SDK и CUDA Toolkit отдельно не требуются. Рекомендуется NVIDIA с compute capability <strong>SM 8.0+</strong> (RTX 30xx, 40xx, 50xx и сопоставимые профессиональные модели).</li>
        </ul>
    </div>
    
    <h2>Необходимые компоненты</h2>
    
    <div class="requirement">
        <h3>1. LLVM (Компилятор)</h3>
        <p>Необходим для компиляции кода Triton.</p>
        <ol>
            <li>Загрузите и установите компилятор LLVM (рекомендуется версия 17.x):
                <ul>
                    <li><a href="https://huggingface.co/fishaudio/fish-speech-1/resolve/main/LLVM-17.0.6-win64.exe?download=true" target="_blank" rel="noopener noreferrer">LLVM-17.0.6 (HF)</a></li>
                    <li><a href="https://github.com/llvm/llvm-project/releases" target="_blank" rel="noopener noreferrer">LLVM Releases (Официальный сайт)</a> - выберите "Windows (64-bit)" для требуемой версии.</li>
                </ul>
            </li>
            <li><strong>Важно:</strong> В процессе установки необходимо выбрать опцию <code>Add LLVM to the system PATH for current user</code> или <code>...for all users</code> для добавления LLVM в системную переменную окружения PATH.</li>
            <li>Завершите установку.</li>
        </ol>
    </div>
    
    <div class="requirement">
        <h3>2. Microsoft Visual C++ Redistributable</h3>
        <p>Предоставляет библиотеки времени выполнения C++, необходимые для запуска приложений, скомпилированных с помощью Visual Studio. Устраняет ошибки, связанные с отсутствием DLL-файлов (например, <code>VCRUNTIME140_1.dll</code>).</p>
        <ul>
            <li><a href="https://aka.ms/vs/17/release/vc_redist.x64.exe" target="_blank" rel="noopener noreferrer">Загрузить Microsoft Visual C++ Redistributable (x64)</a> (Обычно последняя версия является подходящей).</li>
        </ul>
        <p>Установите загруженный пакет.</p>
    </div>

    <div class="optional-component"> <!-- Изменен стиль на optional-component -->
        <h3>3. Microsoft VC++ Build Tools</h3>
        <p>Для Fish Speech+ / Fish Speech+RVC Triton использует MSVC. TinyCC уже входит в пакет triton-windows; Windows SDK и CUDA Toolkit для этой операции отдельно не нужны.</p>
        <p><strong>Установите Build Tools</strong>, если окно проверки Triton сообщает, что MSVC не найден. Если после этого компиляция всё ещё не проходит, попробуйте ручную инициализацию и приложите лог ошибки.</p>
        <p>При необходимости установки:</p>
        <ul>
            <li><a href="https://visualstudio.microsoft.com/ru/downloads/" target="_blank" rel="noopener noreferrer">Загрузить Visual Studio</a> (Редакция Community бесплатна).</li>
            <li>При установке выберите рабочую нагрузку: <strong>"Разработка классических приложений на C++"</strong> (Desktop development with C++).</li>
            <li>Выберите компонент MSVC из набора C++ Build Tools. Windows SDK выбирать специально не требуется.</li>
        </ul>
    </div>
    
    <div class="optional-component"> <!-- Изменен стиль на optional-component -->
        <h3>4. CUDA Toolkit - <i>Установка может не потребоваться</i></h3>
        <p>Требуется для вычислений на GPU NVIDIA. Используется Triton для ускорения.</p>
        <p><strong>Рекомендация:</strong> Проверьте работоспособность моделей medium+/medium+low после установки LLVM, VC++ Redistributable и перезагрузки. Установка полного CUDA Toolkit требуется только в случае, если инициализация Triton явно указывает на его отсутствие или возникают ошибки, связанные с CUDA, и у вас установлен совместимый GPU NVIDIA.</p>
         <p>При необходимости установки:</p>
         <ul>
            <li>Убедитесь, что версия драйвера NVIDIA совместима с выбранной версией CUDA Toolkit.</li>
            <li><a href="https://developer.nvidia.com/cuda-toolkit-archive" target="_blank" rel="noopener noreferrer">Архив загрузок CUDA Toolkit</a> (Рекомендуются версии 12.4, но скоро будет 12.6).</li>
            <li>Загрузите и установите выбранную версию.</li>
        </ul>
    </div>
                
    <div class="note">
        <p><strong>Контрольные шаги после установки:</strong></p>
        <ol>
            <li><strong>Перезагрузите компьютер</strong> после установки всех необходимых компонентов (особенно LLVM, Visual Studio, CUDA).</li>
            <li>Запустите приложение повторно.</li>
            <li>В случае возникновения ошибок при инициализации, изучите вывод в консоли для получения детальной информации об ошибках.</li>
            <li>В случае, если при инициализации модели выдаёт ошибку, попробуйте запустить файл <strong>init_triton.bat</strong> в корневой папке с приложением мода.</li>
            <li>Если ошибка продолжает попадаться, сообщите об этой ошибке в <a href="https://github.com/VinerX/NeuroMita/issues"  target="_blank" rel="noopener noreferrer">Issues</a> или в <a href="https://discord.gg/Tu5MPFxM4P">официальном Discord сообществе.</a></li>
        </ol>
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
        
        if os.path.exists(doc_path):
            return True # Файл уже существует
            
        # Файла нет, пытаемся создать
        if doc_name in self.doc_contents:
            html_content = self.doc_contents[doc_name]
            try:
                # Убедимся, что директория существует 
                os.makedirs(self.docs_dir, exist_ok=True) 
                
                # Записываем HTML контент в файл
                with open(doc_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"Файл документации '{doc_path}' успешно создан.")
                return True
            except Exception as e:
                print(f"Ошибка при создании файла документации '{doc_path}': {e}")
                return False
        else:
            print(f"Ошибка: Контент для документа '{doc_name}' не найден в DocsManager.")
            return False

    def open_doc(self, doc_name: str):
        """
        Открывает указанный файл документации в веб-браузере по умолчанию.
        Если файл не существует, пытается его создать.
        """
        print(f"Запрос на открытие документации: {doc_name}")
        if self._ensure_doc_exists(doc_name):
            doc_path = self._get_doc_path(doc_name)
            try:
                file_uri = 'file:///' + os.path.realpath(doc_path).replace('\\', '/') 
                print(f"Открытие файла: {file_uri}")
                webbrowser.open(file_uri)
            except Exception as e:
                print(f"Не удалось открыть файл документации '{doc_path}' в браузере: {e}")
        else:
            print(f"Не удалось открыть документацию '{doc_name}', так как файл не существует и не может быть создан.")
