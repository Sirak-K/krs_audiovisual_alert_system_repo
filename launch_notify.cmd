@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE="

if defined CODEX_NOTIFY_PYTHON if exist "%CODEX_NOTIFY_PYTHON%" set "PYTHON_EXE=%CODEX_NOTIFY_PYTHON%"

if not defined PYTHON_EXE if exist "%LocalAppData%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\python.exe" set "PYTHON_EXE=%LocalAppData%\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\python.exe"

if not defined PYTHON_EXE for %%P in (
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
    "%ProgramFiles(x86)%\Python313\python.exe"
    "%ProgramFiles(x86)%\Python312\python.exe"
    "%ProgramFiles(x86)%\Python311\python.exe"
    "%ProgramFiles(x86)%\Python310\python.exe"
) do (
    if not defined PYTHON_EXE if exist "%%~fP" set "PYTHON_EXE=%%~fP"
)

if not defined PYTHON_EXE set "PYTHON_EXE=%LocalAppData%\Microsoft\WindowsApps\python.exe"

set "CODEX_NOTIFY_RESOLVED_PYTHON=%PYTHON_EXE%"
"%PYTHON_EXE%" "%SCRIPT_DIR%notify.py" %*
exit /b %errorlevel%
