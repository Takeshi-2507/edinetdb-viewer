@echo off
set PATH=C:\Program Files\nodejs;%PATH%
cd /d E:\edinetdb-viewer\frontend
if exist node_modules rmdir /s /q node_modules
echo Installing npm packages...
call npm install
echo.
echo Done! Exit code: %ERRORLEVEL%
pause
