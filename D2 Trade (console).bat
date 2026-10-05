@echo off
cd /d "%~dp0"
rem najpierw srodowisko projektu (.venv), a jak go nie ma - Python z systemu
set PY=py -3.11
if exist ".venv\Scripts\python.exe" set PY=".venv\Scripts\python.exe"
%PY% src\d2_web.py
pause
