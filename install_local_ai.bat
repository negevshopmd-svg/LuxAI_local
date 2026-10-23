@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title LuxAI - Optional GGUF model support

echo.
echo === Optional local AI model installation ===
echo This step is only needed to chat with a local GGUF model.
echo Keyboard, mouse, web and voice commands work without it.
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Python environment missing. Run install_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "from llama_cpp import Llama; print('llama-cpp-python is ready')"
if not errorlevel 1 (
    echo Local GGUF support is already installed.
    pause
    exit /b 0
)

echo Downloading an official prebuilt CPU wheel when available...
echo No compiler or source-code build will be attempted.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --prefer-binary --only-binary=:all: --extra-index-url "https://abetlen.github.io/llama-cpp-python/whl/cpu" llama-cpp-python
if errorlevel 1 (
    echo.
    echo No compatible prebuilt llama-cpp-python wheel for this Python.
    echo LuxAI still runs its regular commands.
    echo Local GGUF requires a compatible wheel and Python version.
    echo Details: https://github.com/abetlen/llama-cpp-python
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -c "from llama_cpp import Llama; print('Local GGUF backend installed')"
if errorlevel 1 (
    echo Installation could not be verified. Check the Python package.
    pause
    exit /b 1
)
echo.
echo Installed successfully. Restart LuxAI.
pause
exit /b 0
