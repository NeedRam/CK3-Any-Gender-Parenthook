@echo off
setlocal
if "%~1"=="" (
    echo Usage: run_inspect_function_analysis.cmd address [instruction_limit]
    exit /b 2
)
call "%~dp0run_ghidra_analysis.cmd" InspectFunction.java %~1 %~2
exit /b %ERRORLEVEL%
