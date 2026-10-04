@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
".venv\Scripts\python.exe" -m fondo incubar-ultima > registro_incubar.txt 2>&1
type registro_incubar.txt
timeout /t 6 >nul
