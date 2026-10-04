@echo off
cd /d "%~dp0"
rem Buduje lokalna baze przedmiotow z plikow Diablo II: Resurrected (katalog game_data).
rem Potrzebne tylko wtedy, gdy nie masz tokenu Traderie - patrz README.
rem Sciezke do gry mozna podac jako argument, inaczej program szuka jej sam.
rem najpierw srodowisko projektu (.venv), a jak go nie ma - Python z systemu
set PY=py -3.11
if exist ".venv\Scripts\python.exe" set PY=".venv\Scripts\python.exe"
%PY% game_extract.py %*
pause
