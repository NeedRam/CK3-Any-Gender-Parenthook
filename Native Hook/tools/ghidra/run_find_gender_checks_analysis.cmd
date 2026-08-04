@echo off
setlocal
call "%~dp0run_ghidra_analysis.cmd" FindGenderChecks.java 199
exit /b %ERRORLEVEL%
