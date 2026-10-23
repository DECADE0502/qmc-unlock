@echo off
rem Drag one or more files / a folder onto this script to decrypt them
rem with the CLI (auto-grab key from the QQ Music client + trim tail).
setlocal
set HERE=%~dp0..
if "%~1"=="" (
    echo Usage: drag mflac/mgg files or a folder onto this .bat
    pause
    exit /b 1
)
set TARGET=%~1
if exist "%TARGET%\" (set OUT=%TARGET%\decoded) else (for %%I in ("%TARGET%") do set OUT=%%~dpIdecoded)
python "%HERE%\qmc_unlock.py" decrypt "%TARGET%" -o "%OUT%" --auto-client --trim
pause
