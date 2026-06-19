@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%;%PYTHONPATH%"
python -m app.collector_client.cli %*
exit /b %ERRORLEVEL%
