@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Fondo IA
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
echo [%date% %time%] Arranque >> registro.txt

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (python --version >nul 2>nul && set "PY=python")
if not defined PY goto sinpython
%PY% --version >> registro.txt 2>&1

if not exist ".venv\Scripts\python.exe" (
  echo Preparando el entorno. La primera vez tarda un par de minutos...
  %PY% -m venv .venv >> registro.txt 2>&1
)
if not exist ".venv\Scripts\python.exe" goto errorvenv

echo Comprobando dependencias...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt >> registro.txt 2>&1
if errorlevel 1 goto errorpip
echo INSTALADO >> registro.txt

echo.
echo Fondo en marcha en modo papel. No mueve dinero real.
echo No cierres esta ventana: si la cierras, el fondo se para.
echo Panel: http://localhost:8765
echo Lo que va haciendo queda apuntado en registro.txt
start "" /min cmd /c "timeout /t 15 >nul & start http://localhost:8765"
:bucle
".venv\Scripts\python.exe" -m fondo auto >> registro.txt 2>&1
if %errorlevel%==3 goto bucle
echo PARADO >> registro.txt
echo.
echo El fondo se ha parado. El motivo esta al final de registro.txt
pause
exit /b 0

:sinpython
echo SIN_PYTHON >> registro.txt
echo No hay Python instalado en este ordenador.
echo Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH" y vuelve a abrir este archivo.
pause
exit /b 1

:errorvenv
echo ERROR_VENV >> registro.txt
echo No se ha podido crear el entorno de Python. Mira registro.txt
pause
exit /b 1

:errorpip
echo ERROR_PIP >> registro.txt
echo No se han podido instalar las dependencias. Mira registro.txt
pause
exit /b 1
