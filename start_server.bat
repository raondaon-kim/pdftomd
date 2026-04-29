@echo off
REM ============================================================================
REM  pdftomd local launcher (Windows, pure cmd)
REM
REM  - Resolves its own location, so it works from any drive / path.
REM  - Tolerates spaces and Korean characters in parent folder names.
REM  - Pure cmd, ASCII messages only, no chcp switch (chcp 65001 breaks the
REM    cmd interpreter on some Windows 10 builds). Korean folder names work
REM    end-to-end; they may just look garbled in error messages.
REM  - Detects ports 9007 (backend) / 9017 (frontend) already in use and
REM    asks the user to kill them, then exits so they can re-run.
REM  - Auto-installs backend and frontend dependencies on first run.
REM  - Launches backend and frontend in their own console windows so closing
REM    one does not affect the other.
REM  - Opens http://localhost:9017 in the default browser when ready.
REM
REM  Pure cmd on purpose (no PowerShell). Works even when ExecutionPolicy
REM  blocks scripts. ASCII-only messages avoid CP949 / UTF-8 mojibake.
REM ============================================================================

setlocal EnableDelayedExpansion

REM Note on encodings: this script is ASCII-only and does NOT switch the
REM console code page. Switching to UTF-8 (chcp 65001) is known to break
REM the cmd interpreter on some Windows 10 builds (bat file lines get
REM misparsed). We tolerate the default CP949 console: if the project path
REM contains Korean characters they may LOOK garbled when printed in error
REM messages, but cmd handles the path bytes correctly internally, so the
REM script still works end-to-end.

REM Use the project root regardless of where the user double-clicked from.
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "BACKEND_DIR=%PROJECT_ROOT%\backend"
set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"
set "BACKEND_PORT=9007"
set "FRONTEND_PORT=9017"
set "BACKEND_URL=http://127.0.0.1:%BACKEND_PORT%/health"
set "FRONTEND_URL=http://localhost:%FRONTEND_PORT%"

echo.
echo ============================================================
echo  pdftomd local launcher
echo  project: "%PROJECT_ROOT%"
echo  backend port : %BACKEND_PORT%
echo  frontend port: %FRONTEND_PORT%
echo ============================================================
echo.

REM ---------------------------------------------------------------------------
REM  1. Sanity checks
REM ---------------------------------------------------------------------------
if not exist "%BACKEND_DIR%\app\main.py" (
    echo [ERROR] backend\app\main.py not found at "%BACKEND_DIR%".
    echo         Make sure this .bat is placed at the project root.
    goto :fail
)
if not exist "%FRONTEND_DIR%\package.json" (
    echo [ERROR] frontend\package.json not found at "%FRONTEND_DIR%".
    echo         Make sure this .bat is placed at the project root.
    goto :fail
)

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not on PATH. Install Python 3.11+ and try again.
    goto :fail
)
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js is not on PATH. Install Node 20+ and try again.
    goto :fail
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm is not on PATH. Install Node 20+ ^(npm comes with it^) and try again.
    goto :fail
)

REM curl is bundled with Windows 10 1803+ and Windows 11. We use it for HTTP
REM health probes. If it is missing we just skip the readiness wait.
set "HAVE_CURL=0"
where curl >nul 2>&1
if not errorlevel 1 set "HAVE_CURL=1"

if not exist "%PROJECT_ROOT%\.env" (
    echo [WARN] .env not found at "%PROJECT_ROOT%\.env".
    if exist "%PROJECT_ROOT%\.env.example" (
        echo        A template exists at .env.example.
        echo        Copy it to .env and fill in ANTHROPIC_API_KEY or GEMINI_API_KEY.
    ) else (
        echo        Create a .env file with at least one of:
        echo          ANTHROPIC_API_KEY=...
        echo          GEMINI_API_KEY=...
    )
    echo.
    echo The backend will refuse to start without a key. Aborting.
    goto :fail
)

REM ---------------------------------------------------------------------------
REM  2. Port checks. If either port is busy, list the offending PIDs and
REM     ask the user to close them, then exit.
REM ---------------------------------------------------------------------------
call :check_port %BACKEND_PORT% backend
if errorlevel 1 goto :fail
call :check_port %FRONTEND_PORT% frontend
if errorlevel 1 goto :fail

REM ---------------------------------------------------------------------------
REM  3. Install/refresh backend deps. We always run `pip install -e .` so
REM     pyproject.toml changes (new packages, version bumps) are picked up
REM     automatically after a `git pull`. Already-satisfied requirements take
REM     only a few seconds, so this is cheap on subsequent runs.
REM ---------------------------------------------------------------------------
echo [STEP] Syncing backend dependencies ^(pip install -e .^)...
pushd "%BACKEND_DIR%"
python -m pip install --disable-pip-version-check -e .
set "PIP_RC=!ERRORLEVEL!"
popd
if not "!PIP_RC!"=="0" (
    echo [ERROR] pip install failed ^(exit !PIP_RC!^). See output above.
    goto :fail
)

REM ---------------------------------------------------------------------------
REM  4. Install/refresh frontend deps. `npm install` against an existing
REM     node_modules + lockfile is a fast no-op when nothing changed, so we
REM     run it every time to pick up package.json / package-lock.json updates.
REM ---------------------------------------------------------------------------
echo [STEP] Syncing frontend dependencies ^(npm install^)...
if not exist "%FRONTEND_DIR%\node_modules\next\package.json" (
    echo        First-time install, may take a minute...
)
pushd "%FRONTEND_DIR%"
call npm install --no-audit --no-fund
set "NPM_RC=!ERRORLEVEL!"
popd
if not "!NPM_RC!"=="0" (
    echo [ERROR] npm install failed ^(exit !NPM_RC!^). See output above.
    goto :fail
)

REM ---------------------------------------------------------------------------
REM  5. Launch backend in its own window.
REM ---------------------------------------------------------------------------
echo [STEP] Starting backend on port %BACKEND_PORT%...
start "pdftomd-backend" /D "%BACKEND_DIR%" cmd /k "python -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"

REM ---------------------------------------------------------------------------
REM  6. Wait for the backend health endpoint to respond. Use curl if available,
REM     otherwise fall back to a fixed delay.
REM ---------------------------------------------------------------------------
if "%HAVE_CURL%"=="1" (
    echo        Waiting for backend to become ready...
    call :wait_for_url "%BACKEND_URL%" 30
    if errorlevel 1 (
        echo [WARN] Backend did not become ready within 30 seconds.
        echo        Continuing anyway. Check the backend window for errors.
    )
) else (
    echo        curl not found, sleeping 8 seconds for backend to come up...
    timeout /t 8 /nobreak >nul
)

REM ---------------------------------------------------------------------------
REM  7. Launch frontend in its own window.
REM ---------------------------------------------------------------------------
echo [STEP] Starting frontend on port %FRONTEND_PORT%...
start "pdftomd-frontend" /D "%FRONTEND_DIR%" cmd /k "npm run dev"

REM ---------------------------------------------------------------------------
REM  8. Wait for the frontend, then open the browser.
REM ---------------------------------------------------------------------------
if "%HAVE_CURL%"=="1" (
    echo        Waiting for frontend to become ready...
    call :wait_for_url "%FRONTEND_URL%" 30
) else (
    echo        curl not found, sleeping 6 seconds for frontend to come up...
    timeout /t 6 /nobreak >nul
)

echo [STEP] Opening %FRONTEND_URL% ...
start "" "%FRONTEND_URL%"

echo.
echo ============================================================
echo  Servers are running in their own windows.
echo  - Backend  : http://127.0.0.1:%BACKEND_PORT%
echo  - Frontend : %FRONTEND_URL%
echo  Close those two windows to stop, or run stop_server.bat.
echo ============================================================
echo.
echo This launcher window will close in 5 seconds.
timeout /t 5 /nobreak >nul
endlocal
exit /b 0


REM ===========================================================================
REM  :check_port <port> <label>
REM    Returns 0 if the port is free; otherwise prints the offending PID and
REM    returns 1. Uses netstat so PowerShell is not required.
REM ===========================================================================
:check_port
set "PORT=%~1"
set "LABEL=%~2"
set "BUSY_PIDS="

REM netstat -ano lists every connection in LISTENING state with its PID.
REM We grep for ":<port> " followed by anything ending in LISTENING.
for /f "tokens=5" %%P in ('netstat -ano -p TCP ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    if not defined BUSY_PIDS (
        set "BUSY_PIDS=%%P"
    ) else (
        echo !BUSY_PIDS! | findstr /B /E "%%P" >nul || set "BUSY_PIDS=!BUSY_PIDS! %%P"
    )
)

if not defined BUSY_PIDS exit /b 0

echo [ERROR] Port %PORT% ^(%LABEL%^) is already in use.
echo         Offending PID^(s^): !BUSY_PIDS!
echo.
echo         Close the existing server, or kill it with:
for %%P in (!BUSY_PIDS!) do (
    echo             taskkill /F /PID %%P
)
echo.
echo         After closing, run start_server.bat again.
exit /b 1


REM ===========================================================================
REM  :wait_for_url <url> <max_seconds>
REM    Polls the URL with curl every second up to max_seconds.
REM    Returns 0 once the URL responds 2xx/3xx, 1 on timeout.
REM ===========================================================================
:wait_for_url
set "WAIT_URL=%~1"
set "WAIT_MAX=%~2"
set /a WAIT_I=0
:wait_loop
curl -s -o NUL -f --max-time 2 "%WAIT_URL%" >nul 2>&1
if not errorlevel 1 exit /b 0
set /a WAIT_I+=1
if %WAIT_I% GEQ %WAIT_MAX% exit /b 1
timeout /t 1 /nobreak >nul
goto :wait_loop


:fail
echo.
echo Launch aborted. Press any key to close.
pause >nul
endlocal
exit /b 1
