@echo off
setlocal

REM Windows runner (double-click).
REM Activates the Conda env and starts Streamlit.

pushd "%~dp0" >NUL

where conda >NUL 2>NUL
if errorlevel 1 (
  echo [FAIL] 'conda' not found in PATH.
  echo        Open an "Anaconda Prompt" or ensure Conda is added to PATH, then re-run.
  popd >NUL
  exit /b 1
)

for /f "usebackq delims=" %%B in (`conda info --base 2^>NUL`) do set "CONDA_BASE=%%B"
if not defined CONDA_BASE (
  echo [FAIL] Unable to locate Conda base directory via "conda info --base".
  popd >NUL
  exit /b 1
)

if exist "%CONDA_BASE%\condabin\conda.bat" (
  call "%CONDA_BASE%\condabin\conda.bat" activate dwnapp
) else (
  echo [FAIL] "%CONDA_BASE%\condabin\conda.bat" not found.
  echo        Open an "Anaconda Prompt" and re-run, or ensure Conda is installed correctly.
  popd >NUL
  exit /b 1
)

if errorlevel 1 (
  echo [FAIL] conda activate dwnapp failed
  popd >NUL
  exit /b 1
)

pushd "app" >NUL
streamlit run ".\\app.py"
set "RC=%errorlevel%"
popd >NUL
popd >NUL
exit /b %RC%
