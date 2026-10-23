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
echo Accepta Python 3.11 sau mai nou (64-bit) si instaleaza bibliotecile LuxAI.
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
