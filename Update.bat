@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
echo === Lux AI Updater ===
echo Inchide Jarvis inainte de actualizare.

rem Use LuxAI's own working interpreter first, not an unrelated Python on PATH.
set "LUXAI_PYTHON="
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -I -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 set LUXAI_PYTHON=".venv\Scripts\python.exe"
)
if not defined LUXAI_PYTHON (
    py -3 -I -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 set "LUXAI_PYTHON=py -3"
)
if not defined LUXAI_PYTHON (
    python -I -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 set "LUXAI_PYTHON=python"
)
if not defined LUXAI_PYTHON (
    echo EROARE: Nu am gasit Python 3.11 sau mai nou. Ruleaza install_windows.bat.
    pause
    exit /b 1
)

echo Descarc versiunea actuala a programului de actualizare din GitHub...

where curl.exe >nul 2>nul
if errorlevel 1 (
    echo EROARE: curl.exe nu este disponibil. Pe Windows 10/11 ar trebui sa fie inclus.
    echo Nu pornesc updaterul vechi.
    pause
    exit /b 1
)

curl.exe -fL --retry 2 --connect-timeout 15 --max-time 180 -o "Update.py.new" "https://raw.githubusercontent.com/negevshopmd-svg/LuxAI_local/main/Update.py"
if errorlevel 1 (
    del /q "Update.py.new" >nul 2>nul
    echo EROARE: Nu am putut descarca updaterul din GitHub.
    echo Verifica conexiunea la internet si incearca din nou.
    pause
    exit /b 1
)

rem Never replace the installed updater with a truncated/invalid Python file.
%LUXAI_PYTHON% -I -c "from pathlib import Path; compile(Path('Update.py.new').read_bytes(), 'Update.py', 'exec')"
if errorlevel 1 (
    del /q "Update.py.new" >nul 2>nul
    echo EROARE: Updaterul descarcat nu este valid. Am pastrat versiunea existenta.
    pause
    exit /b 1
)

rem Parse this entire block before Update.py can replace the running batch file.
rem Run the validated download in place. Its normal transaction installs Update.py,
rem so bootstrap failures never replace the installed updater or leave a backup.
rem The current updater filters development sources and safely trims old bundled copies.
(
    %LUXAI_PYTHON% Update.py.new
    if errorlevel 1 (
        del /q "Update.py.new" >nul 2>nul
        echo.
        echo Actualizarea NU s-a incheiat cu succes. Citeste eroarea de mai sus.
        pause
        exit /b 1
    ) else (
        del /q "Update.py.new" >nul 2>nul
        exit /b 0
    )
)
