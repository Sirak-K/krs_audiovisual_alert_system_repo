@echo off
setlocal

set "PYTHON_EXE=C:\Users\SSIRA\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\python.exe"
set "APP_DIR=%~dp0"

"%PYTHON_EXE%" "%APP_DIR%notify.py" --self-test
exit /b %errorlevel%
