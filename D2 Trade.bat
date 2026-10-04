@echo off
cd /d "%~dp0"
rem najpierw srodowisko projektu (.venv), a jak go nie ma - Python z systemu
set PYW=pyw -3.11
if exist ".venv\Scripts\pythonw.exe" set PYW=".venv\Scripts\pythonw.exe"
start "" %PYW% d2_web.py
