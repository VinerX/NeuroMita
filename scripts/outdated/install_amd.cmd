@echo off
chcp 65001 > nul
cd /d "%~dp0"

set PY=libs\python\python.exe

echo Проверяем наличие uv...
%PY% -m pip show uv >nul 2>&1

rem  ERRORLEVEL = 0  ->  пакет найден
rem  ERRORLEVEL = 1  ->  пакет не найден
if errorlevel 1 (
    echo uv не найден, устанавливаем...
    %PY% -m pip install --upgrade uv || (
        echo Ошибка установки uv && exit /b 1
    )
) else (
    echo uv уже установлен
)

echo ----------------------------------------------
%PY% -m uv pip install -r requirements.txt --no-cache-dir
%PY% -m uv pip install onnxruntime-directml --no-cache-dir
%PY% -m uv run libs\python\Scripts\pywin32_postinstall.py -install
echo ----------------------------------------------
pause