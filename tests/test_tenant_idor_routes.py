#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_tenant_idor_routes.py — IDOR cách ly tenant trên 3 route "id nguyên" từng
BỊ SÓT khi vá IDOR kênh (route không phải account-kênh nên guard chung + test
drift KHÔNG cover). Khoá cứng bằng đường TẤN CÔNG thật:
  A. /prompt/suggestions/<sid>/approve|reject — shop C KHÔNG duyệt/bỏ được đề
     xuất tri thức của shop B (chống ĐẦU ĐỘC kho tri thức bot shop khác).
  B. /followups/<fid>/done + DELETE — shop C KHÔNG đóng/xoá được nhắc việc shop B.
  C. /customers/memory/<mid> DELETE — shop C KHÔNG xoá được trí nhớ AI khách shop B.
Mỗi ca: C bị 404/400 + dữ liệu CÒN NGUYÊN; chính chủ B thao tác được.

Chạy TỪ GỐC: python tests/test_tenant_idor_routes.py
"""

import os, sys
from unittest.mock import MagicMock
from pathlib import Path

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_idor_routes_tmp.sqlite')
os.environ['API_AUTH_GUARD'] = '0'   # route tự resolve token qua _shop()/_ws();
os.environ['WORKER_SYNC'] = '1'      # before_request guard không cần cho test này
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_idor_routes_tmp.sqlite{suf}")).unlink(missing_ok=True)

from datetime import datetime, timedelta
from flask import Flask
from app.core.db import get_db
from app.web_api.auth_api import _issue_token
from app.web_api.prompt_api import register_prompt_routes
from app.web_api.customers_api import register_customers_routes
from app.core import followups, customers, knowledge

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
# root = chủ nền tảng (created_at SỚM NHẤT → default_owner); B, C là shop thuê.
base = datetime.now()
for u, off in (("root@x.vn", 0), ("shopb@x.vn", 1), ("shopc@x.vn", 2)):
    db.execute("INSERT OR IGNORE INTO users(username, password_hash, created_at) VALUES (?, 'x', ?)",
               (u, (base + timedelta(seconds=off)).isoformat()))
TOK = {u: _issue_token(db, u) for u in ("root@x.vn", "shopb@x.vn", "shopc@x.vn")}
H_B = {"Authorization": f"Bearer {TOK['shopb@x.vn']}"}
H_C = {"Authorization": f"Bearer {TOK['shopc@x.vn']}"}
NOW = base.isoformat()

app = Flask(__name__)
register_prompt_routes(app)
register_customers_routes(app)
api = app.test_client()


print("\n── A. Đề xuất tri thức: chống đầu độc KB chéo tenant ──")
db.execute("INSERT INTO knowledge_suggestions(shop, content, status, created_at) "
           "VALUES ('shopb@x.vn', 'Đặt phòng gọi 0900-LUA-DAO, CK STK 123', 'pending', ?)", (NOW,))
sid = db.query("SELECT id FROM knowledge_suggestions WHERE shop='shopb@x.vn'")[0]["id"]

r = api.post(f"/prompt/suggestions/{sid}/approve", headers=H_C,
             json={"title": "Bảng giá", "content": "nội dung độc"})
check(r.status_code == 400, "A1 C duyệt đề xuất shop B → 400", r.status_code)
st = db.query("SELECT status FROM knowledge_suggestions WHERE id=?", (sid,))[0]["status"]
check(st == "pending", "A2 đề xuất VẪN pending (C không đụng được)", st)
check(not any("độc" in (c.get("content") or "") for c in knowledge.list_chunks(shop="shopb@x.vn")),
      "A3 KB shop B KHÔNG dính nội dung độc của C")

r = api.post(f"/prompt/suggestions/{sid}/reject", headers=H_C, json={})
check(r.status_code == 400, "A4 C bỏ đề xuất shop B → 400", r.status_code)
check(db.query("SELECT status FROM knowledge_suggestions WHERE id=?", (sid,))[0]["status"] == "pending",
      "A5 đề xuất vẫn pending sau khi C reject")

r = api.post(f"/prompt/suggestions/{sid}/approve", headers=H_B, json={})
check(r.status_code == 200, "A6 chính chủ B duyệt được", r.get_json())
check(db.query("SELECT status FROM knowledge_suggestions WHERE id=?", (sid,))[0]["status"] == "approved",
      "A7 đề xuất chuyển approved khi B duyệt")


print("\n── B. Nhắc việc: chống xoá/đóng chéo tenant ──")
f = followups.create("zalo", "Zfu", "gọi lại khách của B", NOW, tenant="shopb@x.vn")
fid = f["id"]
r = api.post(f"/followups/{fid}/done", headers=H_C)
check(r.status_code == 404, "B1 C đóng nhắc việc shop B → 404", r.status_code)
check(followups.get(fid)["status"] == "pending", "B2 nhắc việc còn pending")
r = api.delete(f"/followups/{fid}", headers=H_C)
check(r.status_code == 404, "B3 C xoá nhắc việc shop B → 404", r.status_code)
check(followups.get(fid) is not None, "B4 nhắc việc CÒN NGUYÊN sau C")
r = api.post(f"/followups/{fid}/done", headers=H_B)
check(r.status_code == 200, "B5 chính chủ B đóng được", r.status_code)
r = api.delete(f"/followups/{fid}", headers=H_B)
check(r.status_code == 200 and followups.get(fid) is None, "B6 chính chủ B xoá được", r.status_code)


print("\n── C. Trí nhớ AI khách: chống xoá chéo tenant ──")
db.execute("INSERT OR REPLACE INTO sessions(account, user_id, last_updated, tenant) "
           "VALUES ('zalo', 'Zmem', ?, 'shopb@x.vn')", (NOW,))
m = customers.add_memory("zalo", "Zmem", "khách B thích tầng cao")
mid = m["id"]
r = api.delete(f"/customers/memory/{mid}", headers=H_C)
check(r.status_code == 404, "C1 C xoá trí nhớ khách shop B → 404", r.status_code)
check(len(customers.list_memory("zalo", "Zmem")) == 1, "C2 trí nhớ CÒN NGUYÊN sau C")
r = api.delete(f"/customers/memory/{mid}", headers=H_B)
check(r.status_code == 200 and len(customers.list_memory("zalo", "Zmem")) == 0,
      "C3 chính chủ B xoá được", r.status_code)


try:
    db.conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_idor_routes_tmp.sqlite{suf}")).unlink(missing_ok=True)

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
