@echo off
setlocal
call "%~dp0run_ghidra_analysis.cmd" FindParentValidation.java
exit /b %ERRORLEVEL%
