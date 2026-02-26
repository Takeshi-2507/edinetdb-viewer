@echo off
set PATH=C:\Program Files\nodejs;C:\Users\tai_p\AppData\Local\Python\pythoncore-3.14-64\Scripts;%PATH%
echo ===== EDINET DB Viewer =====

REM バックエンド起動
start "Backend" cmd /k "set PATH=C:\Users\tai_p\AppData\Local\Python\pythoncore-3.14-64\Scripts;%PATH% && cd /d %~dp0 && python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"

REM フロントエンド起動
start "Frontend" cmd /k "set PATH=C:\Program Files\nodejs;%PATH% && cd /d %~dp0\frontend && npm run dev"

echo.
echo バックエンド: http://localhost:8000
echo フロントエンド: http://localhost:5173
echo.
echo 少し待ってからブラウザで http://localhost:5173 を開いてください
timeout /t 5 >nul
start http://localhost:5173
