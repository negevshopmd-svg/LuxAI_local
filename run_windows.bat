@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Ruleaza mai intai install_windows.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate
python main.py
pause
