@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title LuxAI - Local GGUF AI setup

echo.
echo ===== LuxAI GGUF engine setup =====
echo Installs official precompiled llama-cpp-python CPU packages.
echo No compiler is needed. Uses this LuxAI .venv, not system Python.
echo.
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Missing .venv. Run install_windows.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m luxai.local_ai_setup
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo ERROR: No working llama-cpp-python backend.
    echo Details: logs\local_ai_install.log
    echo Try install_windows.bat if the Python environment is damaged.
) else (
    echo.
    echo SUCCESS: Local GGUF backend verified.
    echo Restart LuxAI and choose a model in Settings.
)
echo.
pause
exit /b %CODE%
