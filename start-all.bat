@echo off
chcp 65001 >nul
title Homestay Bot - Launcher
set "PATH=%PATH%;C:\Program Files\nodejs"

echo ================================================
echo   HOMESTAY BOT - Dang khoi dong cac dich vu...
echo ================================================
echo.

echo [1/3] Zalo Node (QR + nhan/gui Zalo) ...
start "Zalo Node" /D "%~dp0zalo-node" cmd /k npm start

echo [2/3] Python (nao bo tra loi khach) ...
start "Python Brain" /D "%~dp0" cmd /k python -m app.main_node

echo [3/3] Web UI (giao dien quan ly) ...
start "Web UI" /D "%~dp0web-ui" cmd /k npm run dev

echo.
echo Cho 7 giay cho cac dich vu san sang roi mo trinh duyet...
timeout /t 7 >nul
start http://localhost:5173

echo.
echo Xong! 3 cua so dich vu da mo. Dong cua so nao = tat dich vu do.
echo De DUNG het: dong ca 3 cua so vua mo.
pause
