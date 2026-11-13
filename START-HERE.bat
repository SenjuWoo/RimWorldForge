@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" echo RimWorldForge setup failed with exit code %EXITCODE%.
pause
exit /b %EXITCODE%
