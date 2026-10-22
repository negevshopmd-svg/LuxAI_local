@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Lux AI Updater ===
echo Descarc versiunea actuala a programului de actualizare din GitHub...

where curl.exe >nul 2>nul
if errorlevel 1 (
    echo EROARE: curl.exe nu este disponibil. Pe Windows 10/11 ar trebui sa fie inclus.
    echo Nu pornesc updaterul vechi.
    pause
    exit /b 1
)

curl.exe -fL --retry 2 --connect-timeout 15 -o "Update.py.new" "https://raw.githubusercontent.com/negevshopmd-svg/LuxAI_local/main/Update.py"
if errorlevel 1 (
    del /q "Update.py.new" >nul 2>nul
    echo EROARE: Nu am putut descarca updaterul din GitHub.
    echo Verifica conexiunea la internet si incearca din nou.
    pause
    exit /b 1
)

move /Y "Update.py.new" "Update.py" >nul
if errorlevel 1 (
    echo EROARE: Nu am putut inlocui Update.py.
    pause
    exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 Update.py
) else (
    python Update.py
)
echo.
pause
