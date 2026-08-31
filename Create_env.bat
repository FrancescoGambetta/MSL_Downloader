@echo off
setlocal

cd /d "%~dp0"

conda env create -f environment.yml

pause
exit /b