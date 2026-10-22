@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === LuxAI Local | Instalare Windows ===
py -3.11 -m venv .venv
if errorlevel 1 (
    echo EROARE: Python 3.11 nu este disponibil. Instaleaza Python 3.11 64-bit.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :pip_error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :pip_error

echo.
echo === Instalez OCR integrat Tesseract, limba rusa si engleza ===
.venv\Scripts\python.exe -m luxai.ocr_setup
if errorlevel 1 (
    echo ATENTIE: OCR nu a putut fi instalat.
    echo Verifica conexiunea sau permisiunile Windows.
    echo Jarvis va reincerca automat la pornire.
) else (
    echo Tesseract OCR este gata in aplicatie.
)

echo.
echo Instalarea programului s-a terminat.
echo Pentru GPU AMD/Vulkan poate fi necesar un build llama-cpp-python compatibil.
pause
exit /b 0

:pip_error
echo EROARE: Instalarea bibliotecilor Python a esuat.
pause
exit /b 1
