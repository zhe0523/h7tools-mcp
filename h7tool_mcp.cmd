@echo off
rem Launch the H7-TOOL MCP server.
rem
rem The project virtual environment is preferred: it is the only interpreter that
rem has hidapi installed, and without hidapi every hardware tool silently returns
rem empty results (device search and other filesystem tools keep working).
rem
rem `py -3.12` is kept only as a last resort. An Anaconda install does not register
rem itself with the Windows `py` launcher, so on such machines `py -3.12` fails even
rem when a 3.12 interpreter is present.
setlocal
set "HERE=%~dp0"
set "VENV_PY=%HERE%.venv\Scripts\python.exe"

if not exist "%VENV_PY%" goto try_path_python
"%VENV_PY%" "%HERE%h7tool_mcp.py" %*
exit /b %ERRORLEVEL%

:try_path_python
where python >nul 2>nul
if errorlevel 1 goto try_py_launcher
python "%HERE%h7tool_mcp.py" %*
exit /b %ERRORLEVEL%

:try_py_launcher
py -3.12 "%HERE%h7tool_mcp.py" %*
exit /b %ERRORLEVEL%
