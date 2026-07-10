@echo off
REM Start the JBBBS Prospecting Tool locally as a MANAGER (all four pages).
cd /d "%~dp0"
set DEV_ROLE=manager
"C:\Users\LaurenKorn\jvenv\Scripts\python.exe" -m streamlit run app.py --server.port 8501
