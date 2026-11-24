@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Installer\uninstall.ps1" -PackageRoot "%~dp0" -Interactive %*
set "AGP_EXIT=%ERRORLEVEL%"
endlocal & exit /b %AGP_EXIT%
