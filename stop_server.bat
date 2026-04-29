@echo off
REM ============================================================================
REM  pdftomd local stopper (Windows, pure cmd)
REM
REM  Kills whatever is listening on ports 9007 (backend) and 9017 (frontend).
REM  Safe to run if nothing is running.
REM ============================================================================

setlocal EnableDelayedExpansion

set "BACKEND_PORT=9007"
set "FRONTEND_PORT=9017"

echo.
echo ============================================================
echo  pdftomd stop
echo ============================================================
echo.

call :kill_port %BACKEND_PORT% backend
call :kill_port %FRONTEND_PORT% frontend

echo.
echo Done.
echo This window will close in 3 seconds.
timeout /t 3 /nobreak >nul
endlocal
exit /b 0


REM ===========================================================================
REM  :kill_port <port> <label>
REM ===========================================================================
:kill_port
set "PORT=%~1"
set "LABEL=%~2"
set "FOUND=0"

for /f "tokens=5" %%P in ('netstat -ano -p TCP ^| findstr /R /C:":%PORT% .*LISTENING"') do (
    set "FOUND=1"
    echo [STOP] Killing PID %%P on port %PORT% ^(%LABEL%^)...
    taskkill /F /PID %%P >nul 2>&1
    if errorlevel 1 (
        echo        taskkill failed for PID %%P. You may need to run as admin.
    ) else (
        echo        OK
    )
)
if "!FOUND!"=="0" echo [OK] Port %PORT% ^(%LABEL%^) is already free.
exit /b 0
