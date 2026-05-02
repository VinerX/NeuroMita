@echo off
chcp 65001 > nul
cd /d "%~dp0"

set PY=libs\python\python.exe
set UV_EXE=libs\python\Scripts\uv.exe

if exist "%UV_EXE%" (
    echo Найден %UV_EXE%, использую его.
    set UV_CMD=%UV_EXE%
    goto uv_ready
)

echo Проверяем наличие pip...
%PY% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo pip не найден, включаем ensurepip...
    %PY% -m ensurepip --upgrade || (
        echo Ошибка включения pip && exit /b 1
    )
)

echo uv как модуль не найден, устанавливаем...
%PY% -m pip install --upgrade uv --no-cache-dir || (
    echo Ошибка установки uv && exit /b 1
)

set UV_CMD=%PY% -m uv

:uv_ready
echo ----------------------------------------------
%UV_CMD% pip install -r requirements.txt --no-cache-dir
%UV_CMD% pip install onnxruntime-directml --no-cache-dir
%UV_CMD% run libs\python\Scripts\pywin32_postinstall.py -install
echo ----------------------------------------------
pause
