@echo off
setlocal
cd /d "%~dp0"
echo ===========================================
echo Fish S2 Pro Local - one-time setup
echo Model: models\fishaudio\s2-pro-q4_k_m.gguf
echo Downloads about 3.6 GB of model data.
echo ===========================================
if exist ".venv\Scripts\python.exe" (
    set "FISH_PY=.venv\Scripts\python.exe"
) else (
    set "FISH_PY=python"
)
"%FISH_PY%" -m luxai.fish_local_setup
if errorlevel 1 (
    echo.
    echo Fish S2 setup did not complete. See the error above.
) else (
    echo.
    echo Fish S2 setup completed. Restart Jarvis to refresh settings.
)
pause
endlocal
