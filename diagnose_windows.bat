@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title LuxAI Local - Diagnostic Windows 10 / 11

echo.
echo === LuxAI Local - Diagnostic ===
echo Verific Windows, Python si pornirea aplicatiei.
echo.

ver
if not exist ".venv\Scripts\python.exe" (
    echo EROARE: Python din .venv lipseste.
    echo Ruleaza install_windows.bat pentru a-l instala sau repara.
    pause
    exit /b 1
)
if not exist "launch_windows.py" (
    echo EROARE: Lipseste launch_windows.py.
    echo Actualizeaza proiectul folosind Update.bat.
    pause
    exit /b 1
)

echo.
echo === Python ===
".venv\Scripts\python.exe" -V
if errorlevel 1 (
    echo EROARE: Mediul Python copiat de pe alt calculator este defect.
    echo Ruleaza install_windows.bat.
    pause
    exit /b 1
)

echo.
echo === Pornesc LuxAI cu erorile vizibile ===
".venv\Scripts\python.exe" "%~dp0launch_windows.py"
set "APP_EXIT=%ERRORLEVEL%"

echo.
echo === LuxAI a iesit cu codul %APP_EXIT% ===
if not "%APP_EXIT%"=="0" (
    echo Verifica logs\startup_error.log si logs\install_windows.log.
    if exist "logs\startup_error.log" (
        echo.
        echo === Ultimele erori de pornire ===
        powershell.exe -NoProfile -Command "Get-Content -LiteralPath 'logs\startup_error.log' -Tail 35"
    )
)
echo.
pause
exit /b %APP_EXIT%
