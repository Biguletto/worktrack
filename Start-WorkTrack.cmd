@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv || goto failed
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto failed
)
".venv\Scripts\python.exe" deploy\start_local.py || goto failed
exit /b 0
:failed
echo WorkTrack could not start. See the message above.
pause
exit /b 1
