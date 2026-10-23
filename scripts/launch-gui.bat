@echo off
rem Launch the GUI without a console window.
rem Usage: launch-gui.bat [optional paths...]
setlocal
start "" pythonw "%~dp0..\qmc-unlock-gui.py" %*
