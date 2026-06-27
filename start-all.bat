@echo off
chcp 65001 >nul
title Homestay Bot - Launcher
set "PATH=%PATH%;C:\Program Files\nodejs"

echo ================================================
echo   HOMESTAY BOT - Dang khoi dong cac dich vu...
echo ================================================
echo.

echo [1/4] Zalo Node (QR + nhan/gui Zalo) ...
start "Zalo Node" /D "%~dp0zalo-node" cmd /k npm start

echo [2/4] Python Brain Zalo (nao bo tra loi Zalo) ...
start "Python Brain" /D "%~dp0" cmd /k python -m app.main_node

echo [3/5] Meta (Messenger + Instagram + ngrok) ...
start "Meta Bot" /D "%~dp0" cmd /k python scripts\run_meta.py

echo [4/5] Telegram bot ...
start "Telegram Bot" /D "%~dp0" cmd /k python -m app.main_telegram

echo [5/5] Web UI (giao dien quan ly) ...
start "Web UI" /D "%~dp0web-ui" cmd /k npm run dev

echo.
echo Cho 8 giay cho cac dich vu san sang roi mo trinh duyet...
timeout /t 8 >nul
start http://localhost:5173

echo.
echo Xong! 5 cua so dich vu da mo. Dong cua so nao = tat dich vu do.
echo De DUNG het: dong ca 5 cua so (hoac chay stop-all.bat).
pause
