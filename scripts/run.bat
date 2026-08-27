@echo off
chcp 65001 >nul
cd /d "%~dp0"
title NeuroMita - Launching
mode con: cols=80 lines=8
echo NeuroMita is starting. Please wait...
echo.

if not exist "libs\python\python.exe" (
    echo ERROR: libs\python\python.exe not found.
    echo Please extract the whole ZIP archive and run again.
    pause
    exit /b 1
)

libs\python\python.exe run.py
if errorlevel 1 pause
