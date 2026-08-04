@echo off
setlocal

if "%~1"=="" (
    echo Usage: run_ghidra_analysis.cmd PostScript.java [script arguments...]
    exit /b 2
)

if not defined AGP_GHIDRA_HOME set "AGP_GHIDRA_HOME=%LOCALAPPDATA%\Temp\ghidra_12.1.2_PUBLIC\ghidra_12.1.2_PUBLIC"
if not defined AGP_CK3_EXE set "AGP_CK3_EXE=C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\binaries\ck3.exe"
set "ANALYZE_HEADLESS=%AGP_GHIDRA_HOME%\support\analyzeHeadless.bat"
set "SCRIPT_PATH=%~dp0"
set "SCRIPT_PATH=%SCRIPT_PATH:~0,-1%"
set "PROJECT_PATH=%TEMP%\agp_ghidra_project_targeted"
set "POST_SCRIPT=%~1"
shift

if not exist "%ANALYZE_HEADLESS%" (
    echo Ghidra headless launcher not found: %ANALYZE_HEADLESS%
    exit /b 1
)
if not exist "%AGP_CK3_EXE%" (
    echo CK3 executable not found: %AGP_CK3_EXE%
    exit /b 1
)
if not exist "%PROJECT_PATH%" md "%PROJECT_PATH%"

set "SCRIPT_ARGS="
:collect_args
if "%~1"=="" goto run_analysis
set "SCRIPT_ARGS=%SCRIPT_ARGS% "%~1""
shift
goto collect_args

:run_analysis
call "%ANALYZE_HEADLESS%" "%PROJECT_PATH%" ck3_analysis -import "%AGP_CK3_EXE%" -scriptPath "%SCRIPT_PATH%" -preScript ConfigureAnalysis.java -postScript "%POST_SCRIPT%" %SCRIPT_ARGS% -deleteProject
exit /b %ERRORLEVEL%
