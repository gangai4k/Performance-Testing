@echo off
rem Starts the LoadRunner to NeoLoad converter UI.
cd /d "%~dp0"
python -m lr2nl ui
if errorlevel 1 pause
