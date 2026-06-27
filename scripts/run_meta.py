#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_meta.py — chạy bot Meta (Messenger + Instagram) kèm tunnel HTTPS trong 1 lệnh,
tự lấy URL công khai và nhét vào PUBLIC_BASE_URL.

2 chế độ tunnel:
  • NGROK (khuyên dùng) — nếu .env có NGROK_DOMAIN: dùng ngrok với domain TĨNH
    → URL KHÔNG đổi khi restart → chỉ dán vào Meta 1 lần duy nhất.
    Cần: đăng ký ngrok.com, `ngrok config add-authtoken <token>` (1 lần),
    lấy 1 domain tĩnh free ở dashboard → đặt NGROK_DOMAIN=<domain> trong .env.
  • CLOUDFLARED (fallback) — nếu KHÔNG có NGROK_DOMAIN: quick tunnel free, URL ĐỔI
    mỗi lần chạy → phải khai lại webhook ở Meta mỗi lần.

Chạy (TỪ GỐC dự án):  python scripts/run_meta.py
Dừng: Ctrl+C.
"""

import os
import re
import sys
import time
import shutil
import threading
import subprocess

sys.path.insert(0, ".")

# Nạp .env sớm để đọc NGROK_DOMAIN trước khi quyết định loại tunnel
try:
    from dotenv import load_dotenv
    load_dotenv(".env")
except Exception:
    pass

PORT = os.getenv("META_WEBHOOK_PORT", "5006")
NGROK_DOMAIN = (os.getenv("NGROK_DOMAIN") or "").strip().replace("https://", "").rstrip("/")
CF_URL_PAT = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def _which(name, candidates):
    p = shutil.which(name)
    if p:
        return p
    for c in candidates:
        for hit in __import__("glob").glob(c):
            if os.path.exists(hit):
                return hit
    return None


def find_cloudflared():
    return _which("cloudflared", [
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        r"C:\Program Files\cloudflared\cloudflared.exe",
    ])


def find_ngrok():
    return _which("ngrok", [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Ngrok.Ngrok_*\ngrok.exe"),
    ])


def start_ngrok(ng, domain, port):
    """Tunnel ngrok với domain TĨNH → URL cố định = https://<domain>.
    Dùng --url (ngrok 3.x; --domain đã deprecated)."""
    url = f"https://{domain}"
    cmd = [ng, "http", f"--url={url}", port, "--log=stdout"]
    authtoken = (os.getenv("NGROK_AUTHTOKEN") or "").strip()
    if authtoken:
        cmd.append(f"--authtoken={authtoken}")   # truyền thẳng, khỏi phụ thuộc file config
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    # Chờ ngrok dựng xong (đọc log tới khi thấy tunnel started hoặc gặp lỗi)
    t0 = time.time()
    while time.time() - t0 < 15:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                print("❌ ngrok thoát sớm — xem lỗi phía trên (thường: còn 1 phiên ngrok khác đang chạy,"
                      " hoặc authtoken/agent version). ngrok free CHỈ 1 phiên cùng lúc.")
                break
            continue
        low = line.lower()
        if "started tunnel" in low or "msg=\"join connections\"" in low:
            break
        if "err_ngrok" in low or "authentication failed" in low or "lvl=crit" in low:
            print(f"❌ ngrok lỗi: {line.strip()[:200]}")
            break
    return proc, url


def start_cloudflared(cf, port):
    proc = subprocess.Popen(
        [cf, "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    url, t0 = None, time.time()
    while time.time() - t0 < 30:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = CF_URL_PAT.search(line)
        if m:
            url = m.group(0)
            break
    return proc, url


def main():
    if NGROK_DOMAIN:
        ng = find_ngrok()
        if not ng:
            print("❌ Chưa có ngrok. Cài: winget install --id Ngrok.Ngrok")
            sys.exit(1)
        print(f"⏳ Mở ngrok (domain tĩnh {NGROK_DOMAIN}) tới cổng {PORT} ...")
        proc, url = start_ngrok(ng, NGROK_DOMAIN, PORT)
    else:
        cf = find_cloudflared()
        if not cf:
            print("❌ Chưa có cloudflared. Cài: winget install --id Cloudflare.cloudflared")
            print("   (hoặc dùng ngrok domain tĩnh: đặt NGROK_DOMAIN trong .env)")
            sys.exit(1)
        print(f"⏳ Mở cloudflared quick tunnel tới cổng {PORT} (URL sẽ ĐỔI mỗi lần) ...")
        proc, url = start_cloudflared(cf, PORT)

    if not url:
        print("❌ Không lấy được URL tunnel (thử chạy lại).")
        proc.terminate()
        sys.exit(1)

    # Cho Config thấy URL công khai (set TRƯỚC khi import Config).
    os.environ["PUBLIC_BASE_URL"] = url

    # Ghi URL ra file cho dễ copy (khỏi lục console)
    try:
        from app.core.config import Config as _C
        (_C.DATA_DIR / "public_url.txt").write_text(url, encoding="utf-8")
    except Exception:
        pass

    from app.core.config import Config  # import sau khi set env
    fixed = " (CỐ ĐỊNH — chỉ dán Meta 1 lần)" if NGROK_DOMAIN else " (ĐỔI mỗi lần — phải khai lại Meta)"
    print("=" * 64)
    print(f"  ✅ URL công khai : {url}{fixed}")
    print(f"  📋 Dán vào Meta  → Callback URL : {url}/fb/webhook")
    print(f"                    Verify Token  : {Config.FB_VERIFY_TOKEN}")
    print(f"                    Subscribe     : messages, messaging_postbacks")
    print("=" * 64)
    if not Config.FB_PAGE_ACCESS_TOKEN:
        print("  ⚠️  Chưa có FB_PAGE_ACCESS_TOKEN → Messenger dùng token theo Page từ UI.")
    if not Config.IG_ACCESS_TOKEN:
        print("  ⚠️  Chưa có IG_ACCESS_TOKEN → gửi DM Instagram sẽ MOCK (điền vào .env).")
    print()

    # Hút output tunnel cho khỏi đầy buffer
    threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()

    from app.main_meta import main as meta_main
    try:
        meta_main()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
