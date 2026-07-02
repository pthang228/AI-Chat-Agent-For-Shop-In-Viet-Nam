@echo off
chcp 65001 >nul
title Homestay Bot - Stop All
echo Dang dung cac dich vu (Zalo Node 4000, Brain 5005, Meta 5006, Telegram 5007, TikTok 5008, Web UI 5173, ngrok)...
powershell -NoProfile -Command "$ports=4000,5005,5006,5007,5008,5173; foreach($p in $ports){ Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }; Get-Process ngrok,cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; 'Da dung xong.'"
timeout /t 2 >nul
