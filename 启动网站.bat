@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 pause & exit /b 1
py -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
