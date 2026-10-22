@echo off
cd /d "%~dp0"
py -3.11 -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Instalarea de baza s-a terminat.
echo Pentru GPU AMD/Vulkan poate fi necesar un build llama-cpp-python compatibil.
pause
