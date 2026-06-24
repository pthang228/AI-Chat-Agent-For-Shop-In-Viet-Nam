#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_meta.py — chạy bot Meta (Messenger + Instagram) kèm tunnel cloudflared
trong 1 lệnh duy nhất, tự lấy URL công khai và nhét vào PUBLIC_BASE_URL.

Vì sao cần: cloudflared "quick tunnel" cấp URL https MIỄN PHÍ (không cần tài khoản)
nhưng URL ĐỔI mỗi lần chạy. Script này tự lấy URL mới và đưa cho bot + in ra để
bạn dán vào Meta (Callback URL). Mỗi lần khởi động lại phải khai lại webhook ở Meta
(chỉ trong giai đoạn test; lên production thì dùng domain/cố định).

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

PORT = os.getenv("META_WEBHOOK_PORT", "5006")
URL_PAT = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def find_cloudflared():
    p = shutil.which("cloudflared")
    if p:
        return p
    for c in (
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        r"C:\Program Files\cloudflared\cloudflared.exe",
    ):
        if os.path.exists(c):
            return c
    return None


def start_tunnel(cf, port):
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
        m = URL_PAT.search(line)
        if m:
            url = m.group(0)
            break
    return proc, url


def main():
    cf = find_cloudflared()
    if not cf:
        print("❌ Chưa có cloudflared. Cài: winget install --id Cloudflare.cloudflared")
        sys.exit(1)

    print("⏳ Đang mở tunnel cloudflared tới cổng", PORT, "...")
    proc, url = start_tunnel(cf, PORT)
    if not url:
        print("❌ Không lấy được URL tunnel (thử chạy lại).")
        proc.terminate()
        sys.exit(1)

    # Cho Config thấy URL công khai (set TRƯỚC khi import app.main_node/Config).
    # load_dotenv(override=False) nên giá trị này thắng dòng rỗng trong .env.
    os.environ["PUBLIC_BASE_URL"] = url

    from app.core.config import Config  # import sau khi set env
    print("=" * 64)
    print(f"  ✅ URL công khai : {url}")
    print(f"  📋 Dán vào Meta  → Callback URL : {url}/fb/webhook")
    print(f"                    Verify Token  : {Config.FB_VERIFY_TOKEN}")
    print(f"                    Subscribe     : messages, messaging_postbacks")
    print("=" * 64)
    if not Config.FB_PAGE_ACCESS_TOKEN:
        print("  ⚠️  Chưa có FB_PAGE_ACCESS_TOKEN → bot chạy MOCK (chỉ log, chưa gửi thật).")
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
