@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title LuxAI Local - Windows setup

echo.
echo ================================================
echo     LuxAI Local - Instalare / Reparare Windows
echo ================================================
echo.
echo Verifica Python 3.11, 3.12, 3.13 si 3.14 (64-bit).\necho Selecteaza o versiune compatibila sau instaleaza Python daca lipseste.\necho Actualizeaza pachetele existente la ultimele versiuni compatibile.
echo Repara automat un .venv copiat de pe alt calculator.
echo Nu sterge modelele sau configuratia personala.
echo.

if not exist "scripts\install_windows.ps1" (
    echo EROARE: Lipseste scripts\install_windows.ps1.
    echo Descarca arhiva COMPLETA LuxAI_Local de pe GitHub.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_windows.ps1"
set "RESULT=%ERRORLEVEL%"
echo.

if not "%RESULT%"=="0" (
    echo Instalarea nu s-a terminat. Vezi logs\install_windows.log.
    echo Poti rula install_windows.bat din nou dupa rezolvarea erorii.
    pause
    exit /b %RESULT%
)

echo Instalare finalizata. Poti porni run_windows.bat.
pause
exit /b 0
