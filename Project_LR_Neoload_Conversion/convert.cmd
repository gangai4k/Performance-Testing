@echo off
rem Usage: convert.cmd <LoadRunner source folder> <output folder> [extra lr2nl options]
if "%~2"=="" (
  echo Usage: convert.cmd ^<LoadRunner source folder^> ^<output folder^> [--users N] [--duration 5m] [--fail-under 85]
  exit /b 1
)
set "SRC=%~f1"
set "OUT=%~f2"
cd /d "%~dp0"
python -m lr2nl convert --source "%SRC%" --output "%OUT%" %3 %4 %5 %6 %7 %8
