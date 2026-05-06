@echo off
setlocal

REM Windows runner (double-click).
REM Creates the Conda environment from environment.yml.

pushd "%~dp0" >NUL

where conda >NUL 2>NUL
if errorlevel 1 (
  echo [FAIL] 'conda' not found in PATH.
  echo        Open an "Anaconda Prompt" or ensure Conda is added to PATH, then re-run.
  popd >NUL
  exit /b 1
)

conda env create -f environment.yml
if errorlevel 1 (
  echo [FAIL] conda env create failed
  popd >NUL
  exit /b 1
)

echo [OK] Environment created. Next: Run_App.bat
popd >NUL
exit /b 0
