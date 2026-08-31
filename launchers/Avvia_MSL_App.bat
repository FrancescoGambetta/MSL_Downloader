@echo off
setlocal
rem This script now lives in launchers\, one level below the project root --
rem everything it runs (webapi, frontend) is relative to the root, not here.
cd /d "%~dp0.."

echo ============================================
echo   MSL Downloader + Catalog Manager (React)
echo ============================================
echo.

call conda activate dwnapp
if errorlevel 1 (
    echo [ERRORE] Impossibile attivare l'ambiente Conda dwnapp.
    echo Esegui prima Create_env.bat ^(nella cartella principale del progetto^) oppure verifica che Conda sia disponibile.
    pause
    exit /b 1
)

rem Start the backend API (webapi, port 8000) in its own window, unless it's
rem already running -- avoids a second process fighting over the same port.
powershell.exe -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo Avvio backend ^(webapi, porta 8000^)...
    start "MSL WebAPI" cmd /k "cd /d ""%~dp0.."" && call conda activate dwnapp && uvicorn webapi.main:app --port 8000"
) else (
    echo Backend gia' in esecuzione su http://localhost:8000
)

rem Start the frontend dev server (React/Vite, port 5173) in its own window,
rem same already-running check.
powershell.exe -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo Avvio frontend ^(React, porta 5173^)...
    start "MSL Frontend" cmd /k "cd /d ""%~dp0..\frontend"" && npm run dev"
) else (
    echo Frontend gia' in esecuzione su http://localhost:5173
)

echo.
echo Attendo che il frontend sia pronto...
set _wait_count=0
:waitloop
powershell.exe -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 goto ready
set /a _wait_count+=1
if %_wait_count% GEQ 30 (
    echo.
    echo [ATTENZIONE] Il frontend non risulta ancora pronto dopo 30s.
    echo Controlla la finestra "MSL Frontend" per eventuali errori.
    goto openbrowser
)
timeout /t 1 /nobreak >nul
goto waitloop

:ready
echo Frontend pronto.

:openbrowser
echo Apro il browser su http://localhost:5173
start "" "http://localhost:5173"

echo.
echo Entrambi i servizi girano nelle loro finestre separate.
echo Chiudi questa finestra quando vuoi: i server restano attivi
echo nelle rispettive finestre "MSL WebAPI" e "MSL Frontend".
pause
endlocal
exit /b
