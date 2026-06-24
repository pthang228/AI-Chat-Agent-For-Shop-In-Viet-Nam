@echo off
REM Chạy kênh Zalo CŨ (zlapi/cookie) — fallback. Tự khởi động lại nếu crash.
REM Cần cookie ở data\zalo_cookies.json (tạo bằng: python scripts\get_zalo_id.py)
cd /d "%~dp0.."
:loop
python -m app.channels.zalo_cookie.main
echo Bot crashed, restart in 5s...
timeout /t 5
goto loop
