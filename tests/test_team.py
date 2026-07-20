#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_team.py — TEAM INBOX + PHÂN QUYỀN NHÂN VIÊN:
  A. Đăng ký chủ → role=owner, workspace=chính mình
  B. /team CRUD (tạo/list/validate/đổi pw/xoá) — chỉ chủ
  C. Nhân viên đăng nhập → role=staff; guard CHẶN route quản trị (403),
     CHO route hộp thư; /teammates cả 2 vai đọc được; /auth/apps đọc app CHỦ
  D. Đổi mật khẩu nhân viên → phiên cũ bị huỷ
  E. Phân công hội thoại (assign) + assigned_to trong summary + persist DB
  F. Xoá nhân viên → token chết

Chạy TỪ GỐC: python tests/test_team.py  (cần PYTHONIOENCODING=utf-8 trên Windows)
"""

import os, sys
from unittest.mock import MagicMock

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
# DB test RIÊNG (không dùng chung test_db_tmp — tránh phá test khác chạy song song)
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_team_tmp.sqlite')
os.environ['API_AUTH_GUARD'] = '1'   # BẬT guard — chính là thứ đang test
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

from pathlib import Path
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_team_tmp.sqlite{suf}")).unlink(missing_ok=True)

from flask import Flask
from app.core.channel import Channel
from app.core.conversation import ConversationManager
from app.web_api.api_guard import install_cors, install_auth_guard
from app.web_api.auth_api import register_auth_routes, role_of, workspace_of
from app.web_api.chat_tools import register_chat_tools

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")


class FakeChannel(Channel):
    def __init__(self): self.texts = []
    def send_text(self, uid, text): self.texts.append((uid, text))
    def send_room_photos(self, uid, names): pass
    def send_price_photos(self, uid): pass
    def notify_owner(self, text): pass
    def call_owner(self): pass


cm = ConversationManager(account=1)
cm._sessions.clear()

app = Flask(__name__)
install_cors(app)
# staff_deny giống bridge thật
install_auth_guard(
    app,
    public_exact={"/auth/login", "/auth/register", "/auth/google"},
    staff_deny=(
        "/billing", "/prompt", "/team", "/broadcasts", "/copilot",
        "/orders/bank", "/bot-toggle",
        "POST /photos/sets", "DELETE /photos/sets",
        "DELETE /conversations",
    ),
)
register_auth_routes(app)
register_chat_tools(app, "", cm, FakeChannel(), account="1")
client = app.test_client()


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── A. Đăng ký chủ ───────────────────────────────────────────────────
print("A. Đăng ký chủ (owner)")
r = client.post("/auth/register", json={"username": "chu@shop.vn", "password": "1234",
                                        "homestay": "Shop Test"})
check(r.status_code == 200 and r.json["ok"], "A1 đăng ký chủ", r.text)
OWNER_TOK = r.json["token"]
check(r.json["user"]["role"] == "owner", "A2 role=owner", r.json["user"])
check(r.json["user"]["workspace"] == "chu@shop.vn", "A3 workspace=chính mình")

# ── B. Quản lý team ──────────────────────────────────────────────────
print("B. /team CRUD")
r = client.post("/team", json={"email": "nv@shop.vn", "name": "Lan", "password": "5678"},
                headers=bearer(OWNER_TOK))
check(r.status_code == 200 and r.json["ok"], "B1 tạo nhân viên", r.text)
check(r.json["member"]["role"] == "staff", "B2 member role=staff")

r = client.post("/team", json={"email": "nv@shop.vn", "name": "X", "password": "9999"},
                headers=bearer(OWNER_TOK))
check(r.status_code == 409, "B3 email trùng → 409", r.status_code)
r = client.post("/team", json={"email": "khong-phai-email", "password": "5678"},
                headers=bearer(OWNER_TOK))
check(r.status_code == 400, "B4 email sai → 400")
r = client.post("/team", json={"email": "nv2@shop.vn", "password": "12"},
                headers=bearer(OWNER_TOK))
check(r.status_code == 400, "B5 mật khẩu ngắn → 400")
r = client.get("/team", headers=bearer(OWNER_TOK))
check(r.status_code == 200 and len(r.json) == 1 and r.json[0]["username"] == "nv@shop.vn",
      "B6 list team = 1 nhân viên", r.text)
r = client.get("/team")
check(r.status_code == 401, "B7 không token → 401")

# ── C. Nhân viên đăng nhập + phân quyền ──────────────────────────────
print("C. Phân quyền staff")
r = client.post("/auth/login", json={"username": "nv@shop.vn", "password": "5678"})
check(r.status_code == 200, "C1 staff đăng nhập được", r.text)
STAFF_TOK = r.json["token"]
check(r.json["user"]["role"] == "staff", "C2 role=staff")
check(r.json["user"]["workspace"] == "chu@shop.vn", "C3 workspace = chủ")

for path, method in [("/billing/me", "GET"), ("/prompt/current", "GET"),
                     ("/team", "GET"), ("/broadcasts", "GET"),
                     ("/bot-toggle", "POST"), ("/orders/bank", "GET")]:
    r = client.open(path, method=method, headers=bearer(STAFF_TOK))
    check(r.status_code == 403, f"C4 staff {method} {path} → 403", r.status_code)

r = client.delete("/conversations/U1", headers=bearer(STAFF_TOK))
check(r.status_code == 403, "C5 staff DELETE /conversations → 403", r.status_code)

# Chủ KHÔNG bị chặn các route đó (không route thật → 404, khác 403)
r = client.get("/broadcasts", headers=bearer(OWNER_TOK))
check(r.status_code == 404, "C6 owner không bị staff_deny (404 vì app test không đăng ký route)",
      r.status_code)

r = client.get("/teammates", headers=bearer(STAFF_TOK))
check(r.status_code == 200 and len(r.json) == 2, "C7 staff đọc /teammates (chủ + nv)", r.text)
check(r.json[0]["role"] == "owner" and r.json[1]["username"] == "nv@shop.vn",
      "C8 teammates: chủ đứng đầu")

# /auth/apps: staff thấy app CỦA CHỦ, không được thêm/xoá
r = client.post("/auth/apps", json={"name": "Kênh Zalo", "channel": "zalo"},
                headers=bearer(OWNER_TOK))
check(r.status_code == 200, "C9 chủ thêm app")
app_id = r.json["app"]["id"]
r = client.get("/auth/apps", headers=bearer(STAFF_TOK))
check(r.status_code == 200 and len(r.json) == 1 and r.json[0]["name"] == "Kênh Zalo",
      "C10 staff đọc app của chủ", r.text)
r = client.post("/auth/apps", json={"name": "X", "channel": "meta"}, headers=bearer(STAFF_TOK))
check(r.status_code == 403, "C11 staff thêm app → 403")
r = client.delete(f"/auth/apps/{app_id}", headers=bearer(STAFF_TOK))
check(r.status_code == 403, "C12 staff xoá app → 403")

# ── D. Đổi mật khẩu nhân viên → huỷ phiên cũ ─────────────────────────
print("D. Đổi mật khẩu nhân viên")
r = client.patch("/team/nv@shop.vn", json={"password": "moi9999", "name": "Lan ca sáng"},
                 headers=bearer(OWNER_TOK))
check(r.status_code == 200 and r.json["member"]["name"] == "Lan ca sáng", "D1 đổi pw + tên", r.text)
r = client.get("/auth/me", headers=bearer(STAFF_TOK))
check(r.status_code == 401, "D2 token cũ của nhân viên bị huỷ", r.status_code)
r = client.post("/auth/login", json={"username": "nv@shop.vn", "password": "moi9999"})
check(r.status_code == 200, "D3 đăng nhập bằng pw mới")
STAFF_TOK = r.json["token"]
r = client.patch("/team/lackhac@x.vn", json={"password": "1234"}, headers=bearer(OWNER_TOK))
check(r.status_code == 404, "D4 sửa người không thuộc team → 404")

# ── E. Phân công hội thoại ───────────────────────────────────────────
print("E. Phân công hội thoại (assign)")
conv = cm.get("U1"); conv.add_user_message("xin chào"); cm.save()
r = client.post("/conversations/U1/assign", json={"username": "nv@shop.vn"},
                headers=bearer(OWNER_TOK))
check(r.status_code == 200 and r.json["assigned_to"] == "nv@shop.vn", "E1 gán hội thoại", r.text)
check(cm._sessions["U1"].assigned_to == "nv@shop.vn", "E2 state RAM cập nhật")
from app.core.db import get_db
row = get_db().query("SELECT assigned_to FROM sessions WHERE account='1' AND user_id='U1'")[0]
check(row["assigned_to"] == "nv@shop.vn", "E3 persist xuống SQLite")
from app.web_api.bridge import _conv_summary
check(_conv_summary("U1", cm._sessions["U1"])["assigned_to"] == "nv@shop.vn",
      "E4 summary trả assigned_to")
r = client.post("/conversations/U1/assign", json={"username": ""}, headers=bearer(STAFF_TOK))
check(r.status_code == 200 and cm._sessions["U1"].assigned_to == "", "E5 staff bỏ gán được")
r = client.post("/conversations/KHONG_TON_TAI/assign", json={"username": "a@b.c"},
                headers=bearer(OWNER_TOK))
check(r.status_code == 404, "E6 hội thoại không tồn tại → 404")

# Helper thuần
check(role_of({"role": "", "username": "x"}) == "owner", "E7 role_of rỗng → owner (DB cũ)")
check(workspace_of({"role": "staff", "owner_username": "boss@x.vn", "username": "nv@x.vn"})
      == "boss@x.vn", "E8 workspace_of staff → chủ")

# ── F. Xoá nhân viên ─────────────────────────────────────────────────
print("F. Xoá nhân viên")
r = client.delete("/team/nv@shop.vn", headers=bearer(OWNER_TOK))
check(r.status_code == 200, "F1 xoá nhân viên")
r = client.get("/auth/me", headers=bearer(STAFF_TOK))
check(r.status_code == 401, "F2 token nhân viên đã xoá → 401")
r = client.get("/team", headers=bearer(OWNER_TOK))
check(len(r.json) == 0, "F3 team trống")

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
