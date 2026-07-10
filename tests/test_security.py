#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_security.py — lớp bảo mật cơ sở (security.py + login lockout):
  A. RateLimiter cửa sổ trượt: cho tới hạn mức, chặn khi vượt, hồi sau window
  B. LoginGuard: đếm sai → khoá tạm tăng dần; thành công xoá bộ đếm; khoá theo
     cả username-trên-IP lẫn IP tổng
  C. install_security: security headers có mặt; HSTS chỉ khi FORCE_HTTPS; 429
     khi vượt rate-limit endpoint nhạy cảm; guard tắt khi API_AUTH_GUARD=0
  D. /auth/login thật: nhập sai 5 lần → lần 6 bị 429 "locked"; nhập ĐÚNG reset
  E. client_ip: tôn trọng X-Forwarded-For chỉ khi TRUST_PROXY

Chạy (TỪ GỐC):  python tests/test_security.py
"""

import os, sys
from unittest.mock import MagicMock

sys.modules.update({
    'gspread': MagicMock(), 'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(), 'openai': MagicMock(),
    'groq': MagicMock(), 'winsound': MagicMock(), 'requests': MagicMock(), 'dotenv': MagicMock(),
})
os.environ['HOMESTAY_DB_PATH'] = 'test_db_security_tmp.sqlite'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

import time
from flask import Flask

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

from app.web_api import security as sec

# ══ A. RateLimiter ═══════════════════════════════════════════════════
print("\nA. RATE LIMITER")
rl = sec.RateLimiter(limit=3, window=0.5)
check(all(rl.hit("ip1") for _ in range(3)), "A1 cho đủ 3 lần trong hạn mức")
check(not rl.hit("ip1"), "A2 lần 4 bị chặn")
check(rl.hit("ip2"), "A3 khoá khác (ip2) không ảnh hưởng")
time.sleep(0.55)
check(rl.hit("ip1"), "A4 sau khi hết window → cho lại")

# ══ B. LoginGuard ════════════════════════════════════════════════════
print("\nB. LOGIN GUARD")
lg = sec.LoginGuard()
check(lg.locked_for("bob", "1.1.1.1") == 0, "B1 ban đầu không khoá")
for _ in range(sec.LoginGuard.THRESHOLD):
    lg.record_fail("bob", "1.1.1.1")
check(lg.locked_for("bob", "1.1.1.1") > 0, "B2 sai 5 lần → bị khoá tạm")
check(lg.locked_for("bob", "9.9.9.9") == 0, "B3 IP khác vẫn vào được (khoá theo user+IP)")
# IP tổng: 1 IP rải nhiều account cũng bị chặn
lg2 = sec.LoginGuard()
for i in range(sec.LoginGuard.THRESHOLD):
    lg2.record_fail(f"user{i}", "2.2.2.2")
check(lg2.locked_for("nguoimoi", "2.2.2.2") > 0, "B4 1 IP dò nhiều account → khoá theo IP")
# thành công xoá bộ đếm
lg3 = sec.LoginGuard()
lg3.record_fail("kate", "3.3.3.3"); lg3.record_fail("kate", "3.3.3.3")
lg3.record_success("kate", "3.3.3.3")
for _ in range(sec.LoginGuard.THRESHOLD - 1):
    lg3.record_fail("kate", "3.3.3.3")
check(lg3.locked_for("kate", "3.3.3.3") == 0, "B5 đăng nhập ĐÚNG reset bộ đếm sai")
# khoá tăng dần
lg4 = sec.LoginGuard()
for _ in range(sec.LoginGuard.THRESHOLD):
    lg4.record_fail("x", "4.4.4.4")
w1 = lg4.locked_for("x", "4.4.4.4")
for _ in range(sec.LoginGuard.THRESHOLD):
    lg4.record_fail("x", "4.4.4.4")
w2 = lg4.locked_for("x", "4.4.4.4")
check(w2 > w1, "B6 khoá tăng dần khi tiếp tục sai", f"{w1:.0f}→{w2:.0f}s")

# ══ C. install_security ══════════════════════════════════════════════
print("\nC. INSTALL_SECURITY")
os.environ['API_AUTH_GUARD'] = '1'
sec._login_limiter.clear(); sec._signup_limiter.clear(); sec._global_limiter.clear()

app = Flask(__name__)
sec.install_security(app)
@app.route("/auth/login", methods=["POST"])
def _fake_login():
    return {"ok": True}
@app.route("/x")
def _x():
    return {"ok": True}
cl = app.test_client()

r = cl.get("/x")
check(r.headers.get("X-Frame-Options") == "DENY", "C1 X-Frame-Options: DENY")
check(r.headers.get("X-Content-Type-Options") == "nosniff", "C2 nosniff")
check("Content-Security-Policy" in r.headers, "C3 có CSP")
check("Strict-Transport-Security" not in r.headers, "C4 KHÔNG HSTS khi chưa FORCE_HTTPS")

# rate-limit endpoint nhạy cảm: limit login = 10/phút
codes = [cl.post("/auth/login").status_code for _ in range(12)]
check(codes.count(429) >= 1 and codes[0] == 200, "C5 login vượt 10 lần → 429", codes)
r = cl.post("/auth/login")
check(r.status_code == 429 and r.headers.get("Retry-After") == "60", "C6 429 kèm Retry-After")

# guard tắt khi API_AUTH_GUARD=0
os.environ['API_AUTH_GUARD'] = '0'
sec._login_limiter.clear()
codes = [cl.post("/auth/login").status_code for _ in range(20)]
check(429 not in codes, "C7 tắt (test mode) → không rate-limit")
os.environ['API_AUTH_GUARD'] = '1'

# HSTS khi FORCE_HTTPS
os.environ['FORCE_HTTPS'] = '1'
app2 = Flask(__name__)
sec.install_security(app2)
app2.route("/y")(lambda: {"ok": True})
r = app2.test_client().get("/y")
check(r.headers.get("Strict-Transport-Security", "").startswith("max-age="), "C8 HSTS khi FORCE_HTTPS=1")
os.environ['FORCE_HTTPS'] = ''

# ══ D. /auth/login thật (login lockout tích hợp) ═════════════════════
print("\nD. LOGIN LOCKOUT E2E")
sec.login_guard.clear()
sec._login_limiter.clear()
from app.core.db import get_db
from app.web_api.auth_api import register_auth_routes, hash_password
db = get_db()
db.execute("DELETE FROM users WHERE username=?", ("victim@test.vn",))
db.execute("INSERT INTO users(username, password_hash, homestay, provider, created_at) VALUES (?,?,?,?,?)",
           ("victim@test.vn", hash_password("correct-horse"), "Shop", "password", "2026-01-01"))

app3 = Flask(__name__)
sec.install_security(app3)
register_auth_routes(app3)
c3 = app3.test_client()

# sai 5 lần (dưới ngưỡng rate-limit 10/phút nên tới được lockout của login_guard)
for _ in range(5):
    r = c3.post("/auth/login", json={"username": "victim@test.vn", "password": "sai"})
check(r.status_code == 401, "D1 nhập sai trả 401")
r = c3.post("/auth/login", json={"username": "victim@test.vn", "password": "sai"})
check(r.status_code == 429 and r.get_json().get("code") == "locked", "D2 lần thứ 6 → 429 locked", r.get_json())
# ngay cả mật khẩu ĐÚNG cũng bị chặn khi đang khoá
r = c3.post("/auth/login", json={"username": "victim@test.vn", "password": "correct-horse"})
check(r.status_code == 429, "D3 đang khoá → mật khẩu đúng vẫn bị chặn (chống dò)")
# xoá khoá (mô phỏng hết thời gian) → đăng nhập đúng thành công + reset
sec.login_guard.clear()
r = c3.post("/auth/login", json={"username": "victim@test.vn", "password": "correct-horse"})
check(r.status_code == 200 and r.get_json().get("ok"), "D4 hết khoá + đúng mật khẩu → đăng nhập OK", r.get_json())
db.execute("DELETE FROM users WHERE username=?", ("victim@test.vn",))

# ══ E. client_ip + TRUST_PROXY ═══════════════════════════════════════
print("\nE. CLIENT IP")
appE = Flask(__name__)
@appE.route("/ip")
def _ip():
    return {"ip": sec.client_ip()}
cE = appE.test_client()
os.environ['TRUST_PROXY'] = ''
r = cE.get("/ip", headers={"X-Forwarded-For": "5.5.5.5, 6.6.6.6"})
check(r.get_json()["ip"] != "5.5.5.5", "E1 mặc định KHÔNG tin X-Forwarded-For")
os.environ['TRUST_PROXY'] = '1'
r = cE.get("/ip", headers={"X-Forwarded-For": "5.5.5.5, 6.6.6.6"})
check(r.get_json()["ip"] == "5.5.5.5", "E2 TRUST_PROXY=1 → lấy IP đầu XFF")
os.environ['TRUST_PROXY'] = ''

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
