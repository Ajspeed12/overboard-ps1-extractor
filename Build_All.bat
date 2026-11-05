@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (set "PYTHON=python") else (set "PYTHON=py -3")
%PYTHON% -c "import PIL" >nul 2>nul
if errorlevel 1 (
  echo Install Pillow first: %PYTHON% -m pip install -r requirements.txt
  pause
  exit /b 1
)
%PYTHON% unpack_resources.py "game" "unpacked"
if errorlevel 1 goto failed
%PYTHON% build_collection.py "unpacked" "Rebuilt_Collection"
if errorlevel 1 goto failed
echo Finished. The OBJ files are in Rebuilt_Collection.
pause
exit /b 0
:failed
echo Build stopped. See the error above.
pause
exit /b 1
