@echo off
REM VenCap MCP Server launcher (run by Task Scheduler at startup).
REM Loops forever: if the server exits for any reason it is restarted after
REM 15 seconds. Python writes server_console.log itself (with monthly
REM rotation); only crashes that happen before logging is set up land in
REM server_startup_errors.log.
cd /d "C:\Vencap Bot Dev\Claude MCP Bot\mcp_server"
:loop
"..\.venv\Scripts\python.exe" mcp_server.py 2>> server_startup_errors.log
echo %date% %time%  server exited with code %errorlevel% - restarting in 15s >> server_startup_errors.log
REM ping is used as the delay because "timeout" fails under Task Scheduler
ping -n 16 127.0.0.1 > nul
goto loop