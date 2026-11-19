@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
echo === Lux AI Updater ===
echo Inchide Jarvis inainte de actualizare.
rem The setup window (scripts\setup_ui.ps1) shows the progress; this console hides itself.
set "LUXAI_BAT_UI=1"
del /q ".luxai_update_ui" >nul 2>nul

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
set "BOOT="
if not exist "scripts\fetch_updater.py" goto legacy_download

rem 0.4.2r: one exact commit through the GitHub API, git hash checked, compiled,
rem unique file name, and a lock so a second Update.bat cannot touch this one.
rem CALL keeps cmd.exe from stripping the quotes of a quoted interpreter path.
for /f "usebackq delims=" %%L in (`call %LUXAI_PYTHON% -I "scripts\fetch_updater.py"`) do set "BOOT=%%L"
if "%BOOT%"=="BUSY" (
    echo O alta actualizare LuxAI ruleaza deja. Asteapta sa termine.
    pause
    exit /b 1
)
if not defined BOOT goto boot_failed
if "%BOOT:~0,5%"=="ERROR" goto boot_failed
if not exist "%BOOT%" goto boot_failed
goto run_update

:boot_failed
echo EROARE: Nu am putut descarca si verifica updaterul din GitHub.
if defined BOOT echo %BOOT%
echo Verifica conexiunea la internet si incearca din nou.
del /q ".luxai_bootstrap.lock" >nul 2>nul
pause
exit /b 1

:legacy_download
rem An installation older than 0.4.2r has no fetch_updater.py yet.
set "BOOT=Update.py.new"
curl.exe -fL --retry 2 --connect-timeout 15 --max-time 180 -o "%BOOT%" "https://raw.githubusercontent.com/negevshopmd-svg/LuxAI_local/main/Update.py"
if errorlevel 1 (
    del /q "%BOOT%" >nul 2>nul
    echo EROARE: Nu am putut descarca updaterul din GitHub.
    echo Verifica conexiunea la internet si incearca din nou.
    pause
    exit /b 1
)
%LUXAI_PYTHON% -I -c "from pathlib import Path; compile(Path('Update.py.new').read_bytes(), 'Update.py', 'exec')"
if errorlevel 1 (
    del /q "%BOOT%" >nul 2>nul
    echo EROARE: Updaterul descarcat nu este valid. Am pastrat versiunea existenta.
    pause
    exit /b 1
)

:run_update
rem Parse this entire block before Update.py can replace the running batch file.
rem Run the validated download in place. Its normal transaction installs Update.py,
rem so bootstrap failures never replace the installed updater or leave a backup.
(
    %LUXAI_PYTHON% "%BOOT%"
    if errorlevel 1 (
        del /q "%BOOT%" >nul 2>nul
        del /q ".luxai_bootstrap.lock" >nul 2>nul
        rem The window already shows the error and its details: no hidden pause.
        if exist ".luxai_update_ui" (
            del /q ".luxai_update_ui" >nul 2>nul
            exit /b 1
        )
        echo.
        echo Actualizarea NU s-a incheiat cu succes. Citeste eroarea de mai sus.
        pause
        exit /b 1
    ) else (
        del /q "%BOOT%" >nul 2>nul
        del /q ".luxai_bootstrap.lock" >nul 2>nul
        rem Also retry removing the discontinued local Fish S2 installation
        rem after a successful update. Update.py handles link/junction safety.
        if exist "models\fishaudio\" (
            echo Elimin fisierele Fish S2 local din models\fishaudio...
            %LUXAI_PYTHON% Update.py --remove-fish-local
            if errorlevel 1 (
                echo AVERTISMENT: Fish S2 local nu a putut fi eliminat complet.
                echo Inchide Jarvis si ruleaza din nou Update.bat.
                if exist ".luxai_update_ui" (
                    del /q ".luxai_update_ui" >nul 2>nul
                    exit /b 1
                )
                pause
                exit /b 1
            )
        )
        del /q ".luxai_update_ui" >nul 2>nul
        exit /b 0
    )
)
