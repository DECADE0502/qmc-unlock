@echo off
rem Build the portable (onedir) and single-file (onefile) executables.
setlocal
cd /d "%~dp0.."

echo ==== build qmc-unlock ====
echo repo: %CD%
echo.

if not exist "assets\app.ico" (
    echo [*] generating icon ...
    python make_icon.py
)

if not exist "qmc2_fast.dll" (
    echo [*] compiling C accelerator ^(needs gcc, optional^) ...
    python -c "import shutil; import qmc_unlock as q; q.load_caccel(); p=q.CACCEL_DIR/'qmc2_fast.dll'; shutil.copy(str(p),'qmc2_fast.dll') if p.exists() else print('    skipped')"
)

echo [1/2] onedir (portable, recommended) ...
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name qmc-unlock-portable --icon assets\app.ico ^
  --add-binary "qmc2_fast.dll;." ^
  --collect-all tkinterdnd2 --collect-all frida qmc-unlock-gui.py
if errorlevel 1 goto fail

echo [2/2] onefile ...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name qmc-unlock --icon assets\app.ico ^
  --add-binary "qmc2_fast.dll;." ^
  --collect-all tkinterdnd2 --collect-all frida qmc-unlock-gui.py
if errorlevel 1 goto fail

echo.
echo done:
echo   dist\qmc-unlock-portable\    add portable.txt + data\ before shipping
echo   dist\qmc-unlock.exe
goto end

:fail
echo.
echo [!] build failed - pip install pyinstaller tkinterdnd2 frida

:end
pause
