@echo off
rem Runs the lr2nl unit tests (standard library unittest, no packages needed).
cd /d "%~dp0"
python -m unittest discover -s tests -t . -v
