@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('Ruleaza mai intai install_windows.bat pentru a instala aplicatia.', 'Nexora AI')" >nul 2>&1
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
exit /b 0
