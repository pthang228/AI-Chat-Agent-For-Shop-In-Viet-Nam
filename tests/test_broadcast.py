#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_broadcast.py — TIN NHẮN HÀNG LOẠT (broadcast/remarketing):
  A. audience: lọc kênh + segment all/active/inactive
  B. CRUD chiến dịch (create/get/list, JSON roundtrip)
  C. _send_one: 200 / lỗi body / server kênh chết
  D. Worker _run end-to-end (mock HTTP) — counters, log, status done
  E. cancel dừng worker
  F. API /broadcasts (bare Flask): preview/create validate/send/cancel/404
  G. chat_tools /broadcast-send: gửi + lưu lịch sử + KHÔNG bật owner_active

Chạy TỪ GỐC: python tests/test_broadcast.py
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
os.environ.setdefault('REPLY_DELAY', '0')
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_broadcast_tmp.sqlite')   # DB test riêng
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
os.environ['BROADCAST_THROTTLE'] = '0'   # test không chờ giãn cách
sys.path.insert(0, '.')

from pathlib import Path
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_broadcast_tmp.sqlite{suf}")).unlink(missing_ok=True)

from datetime import datetime, timedelta
from app.core.db import get_db
from app.core import broadcast

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")


# ── Seed sessions: 2 zalo (1 mới, 1 cũ 60 ngày), 1 meta mới, 1 telegram cũ ──
db = get_db()
NOW = datetime.now()
def seed(account, uid, days_ago):
    db.execute(
        "INSERT OR REPLACE INTO sessions (account, user_id, name, stage, owner_active,"
        " last_updated, messages) VALUES (?,?,?,'greeting',0,?,'[]')",
        (account, uid, "Khách " + uid, (NOW - timedelta(days=days_ago)).isoformat()))

seed("1", "Z_MOI", 1)
seed("1", "Z_CU", 60)
seed("meta", "fb:P1:U9", 2)
seed("telegram", "tg:B1:C7", 45)

# ── A. audience ──────────────────────────────────────────────────────
print("A. audience")
a = broadcast.audience(["zalo", "meta", "telegram"], {"type": "all"})
check(len(a) == 4, "A1 all = 4 khách", a)
a = broadcast.audience(["zalo"], {"type": "all"})
check(len(a) == 2 and all(x["channel"] == "zalo" for x in a), "A2 lọc kênh zalo", a)
a = broadcast.audience(["zalo", "meta", "telegram"], {"type": "active", "days": 7})
check(sorted(x["user_id"] for x in a) == ["Z_MOI", "fb:P1:U9"], "A3 active 7 ngày", a)
a = broadcast.audience(["zalo", "meta", "telegram"], {"type": "inactive", "days": 30})
check(sorted(x["user_id"] for x in a) == ["Z_CU", "tg:B1:C7"], "A4 inactive 30 ngày", a)
a = broadcast.audience(["khong_ton_tai"], {"type": "all"})
check(a == [], "A5 kênh lạ → rỗng")
a = broadcast.audience(["zalo"], {"type": "active", "days": "rác"})
check(len(a) >= 1, "A6 days rác → fallback 30, không nổ")

# ── B. CRUD ──────────────────────────────────────────────────────────
print("B. CRUD chiến dịch")
b = broadcast.create("KM tháng 7", "Giảm 10% cho khách quen!", ["zalo", "meta"],
                     {"type": "inactive", "days": 30}, created_by="chu@shop.vn")
check(b["id"] > 0 and b["status"] == "draft", "B1 create → draft", b)
check(b["channels"] == ["zalo", "meta"] and b["segment"]["days"] == 30, "B2 JSON roundtrip")
check(broadcast.get(b["id"])["name"] == "KM tháng 7", "B3 get")
check(broadcast.get(99999) is None, "B4 get id lạ → None")
check(len(broadcast.list_all()) == 1, "B5 list")

# ── C. _send_one ─────────────────────────────────────────────────────
print("C. _send_one")
item = {"account": "meta", "user_id": "fb:P1:U9", "channel": "meta"}

def fake_resp(code, body=None):
    m = MagicMock(); m.status_code = code
    m.json.return_value = body or {}
    return m

with patch.object(broadcast.requests, "post", return_value=fake_resp(200, {"ok": True})) as p:
    ok, err = broadcast._send_one(item, "hello", "TOK123")
    check(ok and err == "", "C1 gửi 200 → ok")
    called_url = p.call_args[0][0]
    check("/meta/conversations/fb:P1:U9/broadcast-send" in called_url, "C2 đúng URL prefix kênh", called_url)
    check(p.call_args[1]["headers"]["Authorization"] == "Bearer TOK123", "C3 đính Bearer")

with patch.object(broadcast.requests, "post",
                  return_value=fake_resp(502, {"error": "ngoài cửa sổ 24h"})):
    ok, err = broadcast._send_one(item, "hello", "")
    check(not ok and "24h" in err, "C4 lỗi body → err rõ", err)

with patch.object(broadcast.requests, "post", side_effect=ConnectionError("refused")):
    ok, err = broadcast._send_one(item, "hello", "")
    check(not ok and "không chạy" in err, "C5 server kênh chết → err 'không chạy'", err)

# ── D. Worker _run end-to-end ────────────────────────────────────────
print("D. Worker _run")
b2 = broadcast.create("Test run", "Tin thử nghiệm gửi hàng loạt", ["zalo", "meta", "telegram"],
                      {"type": "all"})
db.execute("UPDATE broadcasts SET status='sending' WHERE id=?", (b2["id"],))

def selective_post(url, **kw):
    # telegram giả chết, còn lại 200
    if ":5007" in url:
        raise ConnectionError("refused")
    return fake_resp(200, {"ok": True})

with patch.object(broadcast.requests, "post", side_effect=selective_post):
    broadcast._run(b2["id"], "TOK")
r = broadcast.get(b2["id"])
check(r["status"] == "done", "D1 status done", r["status"])
check(r["total"] == 4 and r["sent"] == 3 and r["failed"] == 1,
      "D2 counters 3 gửi / 1 lỗi / 4 tổng", (r["total"], r["sent"], r["failed"]))
logs = broadcast.logs(b2["id"])
check(len(logs) == 4, "D3 log đủ 4 dòng")
fails = broadcast.logs(b2["id"], only_failed=True)
check(len(fails) == 1 and fails[0]["user_id"] == "tg:B1:C7", "D4 log lỗi đúng khách telegram", fails)

# start() không chạy lại chiến dịch đã xong
check(not broadcast.start(b2["id"]), "D5 start lại chiến dịch done → False")

# ── E. cancel ────────────────────────────────────────────────────────
print("E. cancel")
b3 = broadcast.create("Sẽ dừng", "Tin sẽ bị dừng ngay", ["zalo"], {"type": "all"})
db.execute("UPDATE broadcasts SET status='sending' WHERE id=?", (b3["id"],))
check(broadcast.cancel(b3["id"]), "E1 cancel sending → True")
with patch.object(broadcast.requests, "post", return_value=fake_resp(200)) as p:
    broadcast._run(b3["id"], "")
    check(p.call_count == 0, "E2 worker thấy cancelled → không gửi tin nào")
check(broadcast.get(b3["id"])["status"] == "cancelled", "E3 status giữ cancelled")
check(not broadcast.cancel(b2["id"]), "E4 cancel chiến dịch done → False")

# ── F. API /broadcasts ───────────────────────────────────────────────
print("F. API /broadcasts")
from flask import Flask
from app.web_api.broadcast_api import register_broadcast_routes
api = Flask(__name__)
register_broadcast_routes(api)
c = api.test_client()

r = c.post("/broadcasts/preview", json={"channels": ["zalo"], "segment": {"type": "all"}})
check(r.status_code == 200 and r.json["count"] == 2 and r.json["by_channel"]["zalo"] == 2,
      "F1 preview đếm đúng", r.text)
r = c.post("/broadcasts", json={"message": "ngắn", "channels": ["zalo"]})
check(r.status_code == 400, "F2 tin quá ngắn → 400")
r = c.post("/broadcasts", json={"message": "Tin đủ dài rồi nhé", "channels": []})
check(r.status_code == 400, "F3 không kênh → 400")
r = c.post("/broadcasts", json={"message": "Tin đủ dài rồi nhé", "channels": ["zalo", "kênh_lạ"]})
check(r.status_code == 200 and r.json["broadcast"]["channels"] == ["zalo"],
      "F4 create lọc kênh lạ", r.text)
bid = r.json["broadcast"]["id"]
r = c.get(f"/broadcasts/{bid}")
check(r.status_code == 200 and r.json["broadcast"]["status"] == "draft", "F5 get chi tiết")
r = c.get("/broadcasts/99999")
check(r.status_code == 404, "F6 get id lạ → 404")
with patch.object(broadcast, "start", return_value=True) as st:
    r = c.post(f"/broadcasts/{bid}/send")
    check(r.status_code == 200 and st.called, "F7 send gọi start")
r = c.post(f"/broadcasts/{bid}/cancel")
check(r.status_code == 200 and broadcast.get(bid)["status"] == "cancelled", "F8 cancel draft")
r = c.get("/broadcasts")
check(r.status_code == 200 and isinstance(r.json, list) and len(r.json) >= 3, "F9 list")

# send_now trong create → start được gọi
with patch.object(broadcast, "start", return_value=True) as st:
    r = c.post("/broadcasts", json={"message": "Gửi ngay luôn nhé", "channels": ["zalo"],
                                    "send_now": True})
    check(r.status_code == 200 and st.called, "F10 create send_now → start")

# ── G. chat_tools /broadcast-send ────────────────────────────────────
print("G. chat_tools broadcast-send")
from app.core.channel import Channel
from app.core.conversation import ConversationManager
from app.web_api.chat_tools import register_chat_tools

class FakeChannel(Channel):
    def __init__(self): self.texts = []; self.ctx = "UNSET"
    def send_text(self, uid, text): self.texts.append((uid, text))
    def send_room_photos(self, uid, names): pass
    def send_price_photos(self, uid): pass
    def notify_owner(self, text): pass
    def call_owner(self): pass
    def set_ctx(self, v): self.ctx = v

cm = ConversationManager(account="telegram")
cm._sessions.clear()
conv = cm.get("tg:B1:C7"); conv.add_user_message("hi"); cm.save()
fch = FakeChannel()
tools = Flask(__name__)
register_chat_tools(tools, "/tg", cm, fch, account="telegram")
tc = tools.test_client()

r = tc.post("/tg/conversations/tg:B1:C7/broadcast-send", json={"text": "Khuyến mãi nè!"})
check(r.status_code == 200, "G1 gửi 200", r.text)
check(fch.texts == [("tg:B1:C7", "Khuyến mãi nè!")], "G2 channel.send_text đúng", fch.texts)
check(fch.ctx == "B1", "G3 set_ctx đa khách từ user_id", fch.ctx)
c7 = cm._sessions["tg:B1:C7"]
check(c7.messages[-1] == {"role": "assistant", "content": "Khuyến mãi nè!"},
      "G4 lưu vào lịch sử hội thoại")
check(not c7.owner_active, "G5 KHÔNG bật owner_active (bot vẫn auto-reply)")
r = tc.post("/tg/conversations/tg:B1:C7/broadcast-send", json={"text": ""})
check(r.status_code == 400, "G6 text rỗng → 400")
r = tc.post("/tg/conversations/LA_LAM/broadcast-send", json={"text": "x"})
check(r.status_code == 404, "G7 hội thoại lạ → 404")

class BoomChannel(FakeChannel):
    def send_text(self, uid, text): raise RuntimeError("token hỏng")
boom = Flask(__name__)
register_chat_tools(boom, "/tg2", cm, BoomChannel(), account="telegram2")
r = boom.test_client().post("/tg2/conversations/tg:B1:C7/broadcast-send", json={"text": "x"})
check(r.status_code == 502 and "token hỏng" in r.json["error"], "G8 kênh nổ → 502 + lỗi rõ")

# ── H. recover_stuck + resume (crash giữa chừng) ─────────────────────
print("H. recover_stuck + resume")
b4 = broadcast.create("Kẹt sending", "Tin bị crash giữa chừng nè", ["zalo", "meta", "telegram"],
                      {"type": "all"})
old_ts = (NOW - timedelta(hours=2)).isoformat()
db.execute("UPDATE broadcasts SET status='sending', started_at=? WHERE id=?",
           (old_ts, b4["id"]))
# giả lập crash SAU khi gửi được 1 khách (log ghi từng người nhận) + 1 khách fail
db.execute("INSERT INTO broadcast_log (broadcast_id, account, user_id, status, error, created_at)"
           " VALUES (?,?,?,?,?,?)", (b4["id"], "1", "Z_MOI", "sent", "", old_ts))
db.execute("INSERT INTO broadcast_log (broadcast_id, account, user_id, status, error, created_at)"
           " VALUES (?,?,?,?,?,?)", (b4["id"], "telegram", "tg:B1:C7", "failed", "chết", old_ts))

n = broadcast.recover_stuck(max_age_minutes=30)
r = broadcast.get(b4["id"])
check(n == 1 and r["status"] == "failed", "H1 kẹt sending quá hạn → failed", (n, r["status"]))
check("gián đoạn" in (r.get("note") or ""), "H2 note ghi rõ gián đoạn", r.get("note"))

# chiến dịch 'sending' CÒN SỐNG (log mới trong hạn) → recover không đụng
b5 = broadcast.create("Đang chạy", "Tin đang gửi bình thường", ["zalo"], {"type": "all"})
db.execute("UPDATE broadcasts SET status='sending', started_at=? WHERE id=?",
           (old_ts, b5["id"]))
db.execute("INSERT INTO broadcast_log (broadcast_id, account, user_id, status, error, created_at)"
           " VALUES (?,?,?,'sent','',?)", (b5["id"], "1", "Z_MOI", NOW.isoformat()))
check(broadcast.recover_stuck(30) == 0 and broadcast.get(b5["id"])["status"] == "sending",
      "H3 còn nhịp tim (log mới) → không đánh failed")
db.execute("UPDATE broadcasts SET status='done' WHERE id=?", (b5["id"],))   # dọn

# start() nhận lại chiến dịch failed (mock Thread → không chạy nền, kiểm deterministic)
with patch.object(broadcast.threading, "Thread") as mt:
    check(broadcast.start(b4["id"], "TOK"), "H4 start() nhận chiến dịch failed (gửi lại)")
r = broadcast.get(b4["id"])
check(r["status"] == "sending" and not r.get("note"), "H5 gửi lại → sending, xoá note")

# _run resume: bỏ qua khách đã sent, retry khách failed, counters gộp lần trước
sent_urls = []
def resume_post(url, **kw):
    sent_urls.append(url)
    return fake_resp(200, {"ok": True})
with patch.object(broadcast.requests, "post", side_effect=resume_post):
    broadcast._run(b4["id"], "TOK")
r = broadcast.get(b4["id"])
check(r["status"] == "done", "H6 gửi lại xong → done", r["status"])
check(len(sent_urls) == 3 and not any("Z_MOI" in u for u in sent_urls),
      "H7 resume bỏ qua khách đã sent, gửi 3 khách còn lại (kể cả retry failed)", sent_urls)
check(r["total"] == 4 and r["sent"] == 4 and r["failed"] == 0,
      "H8 counters gộp: 1 lần trước + 3 lần này", (r["total"], r["sent"], r["failed"]))
logs4 = broadcast.logs(b4["id"])
check(len(logs4) == 4 and sum(1 for l in logs4 if l["status"] == "sent") == 4,
      "H9 log không đếm kép (failed cũ đã dọn khi retry)", [(l["user_id"], l["status"]) for l in logs4])

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
