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
rem Jarvis.exe = the same Python with the name "Jarvis" and its icon, so Task
rem Manager shows "Jarvis" instead of "Python". Built/refreshed when needed;
rem if it cannot be built, pythonw.exe is used as before.
if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" -m luxai.jarvis_exe >nul 2>&1
rem Run-as-administrator mode: start through the scheduled task (no prompt),
rem but only when the task belongs to THIS folder (another copy is never started).
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
rem Each folder has its own task name (audit 2 #5), written by the settings switch.
set "ADMIN_TASK=LuxAI Jarvis (admin)"
if exist ".luxai_data\admin_task.txt" set /p ADMIN_TASK=<".luxai_data\admin_task.txt"
schtasks /Query /TN "%ADMIN_TASK%" /XML 2>nul | findstr /I /L /C:"<WorkingDirectory>%HERE%</WorkingDirectory>" >nul
if not errorlevel 1 (
    schtasks /Run /TN "%ADMIN_TASK%" >nul 2>&1
    if not errorlevel 1 exit /b 0
)
set "JARVIS_EXE=.venv\Scripts\pythonw.exe"
if exist ".venv\Scripts\Jarvis.exe" if exist ".venv\Scripts\Jarvis.exe.stamp" set "JARVIS_EXE=.venv\Scripts\Jarvis.exe"
start "" "%JARVIS_EXE%" "%~dp0launch_windows.py"
if errorlevel 1 (
    echo EROARE: Windows nu a putut porni %JARVIS_EXE%.
    echo Ruleaza install_windows.bat pentru reparare.
    pause
    exit /b 1
)
rem The process started; its own window or logs\startup_error.log reports a later failure.
exit /b 0
