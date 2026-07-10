@echo off
REM Rewrite and reload the synthetic sample data (safe to run any time).
cd /d "%~dp0"
"C:\Users\LaurenKorn\jvenv\Scripts\python.exe" seed_sample_data.py
echo.
pause
