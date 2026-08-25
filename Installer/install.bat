@echo off
setlocal
set "AGP_STEAM_ROOT=%ProgramFiles(x86)%\Steam\steamapps\common\Crusader Kings III\binaries"
if not exist "%AGP_STEAM_ROOT%" set "AGP_STEAM_ROOT=%ProgramFiles%\Steam\steamapps\common\Crusader Kings III\binaries"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -TargetRoot "%AGP_STEAM_ROOT%" -PackageRoot "%~dp0.." -Interactive %*
set "AGP_EXIT=%ERRORLEVEL%"
endlocal & exit /b %AGP_EXIT%
