@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Fondo IA - mineria
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
if not exist informes mkdir informes
echo Descargando datos y minando. Puede tardar una hora; el fondo sigue funcionando en su ventana.
echo Lo que va haciendo queda en informes\mineria_manual.log
echo [%date% %time%] inicio > informes\mineria_manual.log
".venv\Scripts\python.exe" -m fondo descargar >> informes\mineria_manual.log 2>&1
".venv\Scripts\python.exe" -m fondo minar >> informes\mineria_manual.log 2>&1
echo FIN >> informes\mineria_manual.log
