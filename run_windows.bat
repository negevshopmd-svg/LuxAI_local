@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title LuxAI Local - Jarvis

if not exist "scripts\install_windows.ps1" goto needs_setup

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_windows.ps1" -CheckVenv >nul 2>&1
if errorlevel 1 goto needs_setup
goto launch

:needs_setup
echo.
echo Instalarea LuxAI lipseste sau .venv a fost copiat de pe alt calculator.
echo Installerul poate crea automat un mediu Python nou, fara sa stearga configuratia.
choice /C DN /N /M "D = Instaleaza/repara acum, N = Inchide: "
if errorlevel 2 exit /b 1

call "%~dp0install_windows.bat"
if errorlevel 1 (
    echo Jarvis nu a pornit: instalarea nu a fost finalizata.
    pause
    exit /b 1
)

:launch
if not exist ".venv\Scripts\pythonw.exe" (
    echo EROARE: .venv\Scripts\pythonw.exe lipseste.
    echo Ruleaza install_windows.bat.
    pause
    exit /b 1
)
if not exist "launch_windows.py" (
    echo EROARE: Lipseste launch_windows.py.
    echo Ruleaza Update.bat sau descarca arhiva completa.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0launch_windows.py"
exit /b 0
