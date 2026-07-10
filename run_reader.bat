@echo off
REM Start the JBBBS Prospecting Tool locally as a READER (Ranked List + Lookup only).
REM Uses the local DEV_ROLE override, which does not exist in the deployed app.
cd /d "%~dp0"
set DEV_ROLE=reader
"C:\Users\LaurenKorn\jvenv\Scripts\python.exe" -m streamlit run app.py --server.port 8501
