@echo off
setlocal
title MCP Shared Workspace - ngrok status
color 0B
cls

set "PUBLIC_HOSTNAME=%~1"
if "%PUBLIC_HOSTNAME%"=="" (
    echo ERROR: No public hostname was supplied.
    echo Start the tunnel with start-workspace-hidden.vbs.
    pause
    exit /b 1
)

echo ============================================================
echo  MCP SHARED WORKSPACE - PUBLIC CONNECTION
echo ============================================================
echo.
echo  MCP endpoint:  https://%PUBLIC_HOSTNAME%/mcp
echo  Local server:  http://127.0.0.1:8000
echo  ngrok status:  http://127.0.0.1:4040
echo.
echo  PM2 keeps the MCP server running in the background.
echo  This minimized window owns the ngrok tunnel.
echo  Minimize this window to keep your MCP client connected.
echo  Closing it stops the tunnel and disconnects the client.
echo.
echo  ngrok output follows. Restore this window to inspect status.
echo ============================================================
echo.

ngrok.exe http 8000 --url https://%PUBLIC_HOSTNAME%

set "NGROK_EXIT=%ERRORLEVEL%"
echo.
echo ngrok stopped with exit code %NGROK_EXIT%.
echo Press a key to close this status window.
pause >nul
exit /b %NGROK_EXIT%
