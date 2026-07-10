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
db.execute("DELETE FROM password_resets")

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

# Đặt GOOGLE_CLIENT_ID → id_token của app KHÁC (aud lạ) bị từ chối, aud đúng thì qua
def _tokeninfo_aud(aud):
    def f(url, params=None, timeout=None):
        m = MagicMock(); m.status_code = 200
        m.json.return_value = {"email": "google@user.vn", "email_verified": "true",
                               "name": "Google User", "picture": "", "aud": aud}
        return m
    return f

with patch.object(auth_mod.Config, 'GOOGLE_CLIENT_ID', 'myapp.apps.googleusercontent.com'):
    with patch.object(auth_mod, 'requests') as mreq:
        mreq.get.side_effect = _tokeninfo_aud("appkhac.apps.googleusercontent.com")
        r = api.post("/auth/google", json={"credential": "JWT_APP_KHAC"})
    check(r.status_code == 401, "D5 google_wrong_aud_rejected")
    with patch.object(auth_mod, 'requests') as mreq:
        mreq.get.side_effect = _tokeninfo_aud("myapp.apps.googleusercontent.com")
        r = api.post("/auth/google", json={"credential": "JWT_DUNG"})
    check(r.status_code == 200, "D6 google_right_aud_ok")

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

print("\n── F. Quên mật khẩu (OTP qua email) ──")
import re
import app.core.mailer as mailer_mod

sent = {}
def _fake_send(to, subject, body):
    sent["to"] = to; sent["body"] = body
    return True

# SMTP chưa cấu hình → báo rõ 503, không nổ
with patch.object(mailer_mod, 'configured', return_value=False):
    r = api.post("/auth/forgot", json={"username": "chu@homestay.vn"})
check(r.status_code == 503, "F1 forgot_no_smtp_503")

with patch.object(mailer_mod, 'configured', return_value=True), \
     patch.object(mailer_mod, 'send_mail', side_effect=_fake_send):
    r = api.post("/auth/forgot", json={"username": "chu@homestay.vn"})
    check(r.status_code == 200 and r.get_json()["ok"], "F2 forgot_ok")
    # Email lạ → vẫn câu chung chung (chống dò tài khoản), KHÔNG gửi mail
    before = dict(sent)
    r = api.post("/auth/forgot", json={"username": "khongton@x.vn"})
    check(r.status_code == 200 and r.get_json()["ok"] and sent == before,
          "F3 forgot_unknown_generic_no_mail")

check(sent.get("to") == "chu@homestay.vn", "F4 mail_to_user", f"{sent.get('to')}")
code = re.search(r"\b(\d{6})\b", sent["body"]).group(1)

# Mã không lưu thô trong DB (chỉ sha256)
row = db.query("SELECT code_hash FROM password_resets WHERE username='chu@homestay.vn'")[0]
check(code not in row["code_hash"] and len(row["code_hash"]) == 64, "F5 code_hashed")

wrong = "000000" if code != "000000" else "111111"
r = api.post("/auth/reset", json={"username": "chu@homestay.vn", "code": wrong, "new_password": "moimoi"})
check(r.status_code == 401, "F6 reset_wrong_code")

r = api.post("/auth/reset", json={"username": "chu@homestay.vn", "code": code, "new_password": "ab"})
check(r.status_code == 400, "F7 reset_pw_too_short")

r = api.post("/auth/reset", json={"username": "chu@homestay.vn", "code": code, "new_password": "moimoi"})
check(r.status_code == 200, "F8 reset_ok")
r = api.post("/auth/login", json={"username": "chu@homestay.vn", "password": "moimoi"})
check(r.status_code == 200, "F9 login_new_pw")

# Mã dùng 1 lần — dùng lại phải chết
r = api.post("/auth/reset", json={"username": "chu@homestay.vn", "code": code, "new_password": "khac1"})
check(r.status_code == 401, "F10 code_single_use")

# Mọi phiên cũ bị huỷ sau reset (token cấp trước đó hết hiệu lực)
r = api.get("/auth/me", headers=bearer(tok))
check(r.status_code == 401, "F11 old_sessions_revoked")

# Nhập sai quá RESET_MAX_ATTEMPTS lần → mã bị huỷ (429)
with patch.object(mailer_mod, 'configured', return_value=True), \
     patch.object(mailer_mod, 'send_mail', side_effect=_fake_send):
    api.post("/auth/forgot", json={"username": "chu@homestay.vn"})
code2 = re.search(r"\b(\d{6})\b", sent["body"]).group(1)
wrong2 = "999999" if code2 != "999999" else "888888"
for _ in range(auth_mod.RESET_MAX_ATTEMPTS):
    api.post("/auth/reset", json={"username": "chu@homestay.vn", "code": wrong2, "new_password": "moimoi"})
r = api.post("/auth/reset", json={"username": "chu@homestay.vn", "code": code2, "new_password": "moimoi"})
check(r.status_code == 429, "F12 too_many_attempts_kills_code")
r = api.post("/auth/reset", json={"username": "chu@homestay.vn", "code": code2, "new_password": "moimoi"})
check(r.status_code == 401, "F13 code_deleted_after_429")

# Mã hết hạn → từ chối
with patch.object(mailer_mod, 'configured', return_value=True), \
     patch.object(mailer_mod, 'send_mail', side_effect=_fake_send):
    api.post("/auth/forgot", json={"username": "chu@homestay.vn"})
code3 = re.search(r"\b(\d{6})\b", sent["body"]).group(1)
db.execute("UPDATE password_resets SET expires_at='2000-01-01T00:00:00' WHERE username='chu@homestay.vn'")
r = api.post("/auth/reset", json={"username": "chu@homestay.vn", "code": code3, "new_password": "moimoi"})
check(r.status_code == 401, "F14 expired_code_rejected")

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
