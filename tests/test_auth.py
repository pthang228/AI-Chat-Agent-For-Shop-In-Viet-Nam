#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_auth.py — auth thật (users/token/apps trong SQLite):
  - đăng ký / đăng nhập / sai mật khẩu / trùng tài khoản
  - token: /auth/me, logout, token rác
  - đổi hồ sơ, đổi mật khẩu (kể cả acc Google đặt pw lần đầu)
  - Google login (mock tokeninfo)
  - apps CRUD + chống trùng khi migrate

Chạy (TỪ GỐC):  python tests/test_auth.py
"""

import os, sys
from unittest.mock import MagicMock, patch

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ['HOMESTAY_DB_PATH'] = 'test_db_tmp.sqlite'
sys.path.insert(0, '.')

from flask import Flask
import app.web_api.auth_api as auth_mod
from app.core.db import get_db

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
db.execute("DELETE FROM users"); db.execute("DELETE FROM auth_tokens"); db.execute("DELETE FROM user_apps")

flask_app = Flask(__name__)
auth_mod.register_auth_routes(flask_app)
api = flask_app.test_client()

def bearer(t): return {"Authorization": f"Bearer {t}"}

print("\n── A. Đăng ký / đăng nhập ──")
r = api.post("/auth/register", json={"username": "Chu@Homestay.VN", "password": "matkhau1", "homestay": "Haru"})
b = r.get_json()
check(r.status_code == 200 and b["ok"] and b["token"], "A1 register_ok", f"{b}")
check(b["user"]["username"] == "chu@homestay.vn" and b["user"]["homestay"] == "Haru", "A1 user_normalized", f"{b}")
tok = b["token"]

r = api.post("/auth/register", json={"username": "chu@homestay.vn", "password": "khac"})
check(r.status_code == 409, "A2 register_duplicate")

r = api.post("/auth/register", json={"username": "x@y.z", "password": "ab"})
check(r.status_code == 400, "A3 password_too_short")

r = api.post("/auth/login", json={"username": "chu@homestay.vn", "password": "matkhau1"})
check(r.status_code == 200 and r.get_json()["token"], "A4 login_ok")

r = api.post("/auth/login", json={"username": "chu@homestay.vn", "password": "sai"})
check(r.status_code == 401, "A5 login_wrong_pw")

r = api.post("/auth/login", json={"username": "khongton@tai.vn", "password": "x"})
check(r.status_code == 401 and r.get_json().get("code") == "not_found", "A6 login_not_found")

# Mật khẩu không lưu thô trong DB
row = db.query("SELECT password_hash FROM users WHERE username='chu@homestay.vn'")[0]
check(row["password_hash"].startswith("pbkdf2$") and "matkhau1" not in row["password_hash"],
      "A7 pw_hashed", row["password_hash"][:30])

print("\n── B. Token / me / logout ──")
r = api.get("/auth/me", headers=bearer(tok))
check(r.status_code == 200 and r.get_json()["user"]["username"] == "chu@homestay.vn", "B1 me_ok")

r = api.get("/auth/me", headers=bearer("tokenrac"))
check(r.status_code == 401, "B2 me_bad_token")

r = api.get("/auth/me")
check(r.status_code == 401, "B3 me_no_token")

r = api.post("/auth/logout", headers=bearer(tok))
check(r.status_code == 200, "B4 logout_ok")
r = api.get("/auth/me", headers=bearer(tok))
check(r.status_code == 401, "B5 token_revoked")

# Đăng nhập lại lấy token mới cho phần sau
tok = api.post("/auth/login", json={"username": "chu@homestay.vn", "password": "matkhau1"}).get_json()["token"]

print("\n── C. Hồ sơ / mật khẩu ──")
r = api.post("/auth/update", json={"homestay": "Haru Staycation", "email": "lienhe@haru.vn"}, headers=bearer(tok))
b = r.get_json()
check(r.status_code == 200 and b["user"]["homestay"] == "Haru Staycation" and b["user"]["email"] == "lienhe@haru.vn",
      "C1 update_profile", f"{b}")

r = api.post("/auth/update", json={"email": "khong-hop-le"}, headers=bearer(tok))
check(r.status_code == 400, "C2 update_bad_email")

r = api.post("/auth/password", json={"old_password": "sai", "new_password": "matkhau2"}, headers=bearer(tok))
check(r.status_code == 401, "C3 change_pw_wrong_old")

r = api.post("/auth/password", json={"old_password": "matkhau1", "new_password": "matkhau2"}, headers=bearer(tok))
check(r.status_code == 200, "C4 change_pw_ok")
r = api.post("/auth/login", json={"username": "chu@homestay.vn", "password": "matkhau2"})
check(r.status_code == 200, "C5 login_new_pw")

print("\n── D. Google login (mock tokeninfo) ──")
def _fake_tokeninfo(url, params=None, timeout=None):
    m = MagicMock(); m.status_code = 200
    m.json.return_value = {"email": "google@user.vn", "email_verified": "true",
                           "name": "Google User", "picture": "http://pic"}
    return m

with patch.object(auth_mod, 'requests') as mreq:
    mreq.get.side_effect = _fake_tokeninfo
    r = api.post("/auth/google", json={"credential": "JWT_GIA"})
b = r.get_json()
check(r.status_code == 200 and b["user"]["provider"] == "google" and not b["user"]["has_password"],
      "D1 google_ok", f"{b}")
gtok = b["token"]

with patch.object(auth_mod, 'requests') as mreq:
    bad = MagicMock(); bad.status_code = 400
    mreq.get.return_value = bad
    r = api.post("/auth/google", json={"credential": "JWT_SAI"})
check(r.status_code == 401, "D2 google_rejected")

# Acc Google đặt mật khẩu lần đầu (không cần pw cũ)
r = api.post("/auth/password", json={"old_password": "", "new_password": "pwmoi"}, headers=bearer(gtok))
check(r.status_code == 200, "D3 google_set_first_pw")
r = api.post("/auth/login", json={"username": "google@user.vn", "password": "pwmoi"})
check(r.status_code == 200, "D4 google_then_pw_login")

print("\n── E. Apps của user ──")
r = api.post("/auth/apps", json={"name": "Haru Zalo", "channel": "zalo"}, headers=bearer(tok))
b = r.get_json()
check(r.status_code == 200 and b["app"]["id"], "E1 add_app", f"{b}")
app_id = b["app"]["id"]

# Chống trùng (migrate chạy lại)
r = api.post("/auth/apps", json={"name": "Haru Zalo", "channel": "zalo"}, headers=bearer(tok))
check(r.get_json().get("duplicated") and r.get_json()["app"]["id"] == app_id, "E2 dedupe")

api.post("/auth/apps", json={"name": "Haru TikTok", "channel": "tiktok"}, headers=bearer(tok))
r = api.get("/auth/apps", headers=bearer(tok))
apps = r.get_json()
check(len(apps) == 2 and apps[0]["name"] == "Haru Zalo", "E3 list_apps", f"{apps}")

# User khác không thấy app của người này
r = api.get("/auth/apps", headers=bearer(gtok))
check(r.get_json() == [], "E4 apps_isolated")

r = api.delete(f"/auth/apps/{app_id}", headers=bearer(tok))
check(r.status_code == 200, "E5 delete_app")
r = api.get("/auth/apps", headers=bearer(tok))
check(len(r.get_json()) == 1, "E5 deleted", f"{r.get_json()}")

r = api.get("/auth/apps")
check(r.status_code == 401, "E6 apps_need_auth")

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
