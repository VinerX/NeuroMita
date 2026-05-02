
@echo off
cd /d "%~dp0.."

:loop
libs\python\python.exe -m uv run NeuroMita.pyz
if %errorlevel%==42 (
    echo Обновление применено, перезапускаю...
    goto loop
)
pause
