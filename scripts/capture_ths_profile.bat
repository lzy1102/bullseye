@echo off
rem ============================================================================
rem  One-click capture of THS (tonghuashun) counter login parameters.
rem  ASCII-only launcher on purpose: cmd.exe mis-parses non-ASCII batch files
rem  depending on the console codepage. All output/logic lives in the Python
rem  script (UTF-8 safe).
rem
rem  Usage:
rem     scripts\capture_ths_profile.bat
rem     scripts\capture_ths_profile.bat --timeout 600
rem     scripts\capture_ths_profile.bat --pid 12345
rem ============================================================================
setlocal
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "SCRIPT_DIR=%~dp0"

where py >nul 2>&1 && (
    py -3 "%SCRIPT_DIR%capture_ths_profile.py" %*
    goto :done
)
where python >nul 2>&1 && (
    python "%SCRIPT_DIR%capture_ths_profile.py" %*
    goto :done
)

echo [x] Python not found. Install Python 3.9+ and add it to PATH.
echo     https://www.python.org/downloads/
pause
exit /b 1

:done
if errorlevel 1 (
    echo.
    pause
)
endlocal