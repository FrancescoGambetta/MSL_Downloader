@echo off
setlocal

REM Windows runner (double-click).
REM Runs the app via conda-run (no need to "activate" from a terminal).

pushd "%~dp0" >NUL

where conda >NUL 2>NUL
if errorlevel 1 (
  echo [FAIL] 'conda' not found in PATH.
  echo        Open an "Anaconda Prompt" or ensure Conda is added to PATH, then re-run.
  popd >NUL
  exit /b 1
)

conda run -n dwnapp streamlit run app/app.py
set "RC=%errorlevel%"
popd >NUL
exit /b %RC%
