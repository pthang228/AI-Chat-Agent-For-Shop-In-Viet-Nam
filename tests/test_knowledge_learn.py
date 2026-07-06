#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_knowledge_learn.py — BOT HỌC TỪ HỘI THOẠI (bán tự động, có duyệt):
  - knowledge.add_chunks: CỘNG THÊM (không xoá kho như ingest), trần MAX_CHUNKS
  - knowledge_learn.suggest_from_reply: lọc rẻ (câu ngắn), AI skip, bóc mẩu,
    dedup câu hỏi trùng, tìm đúng câu khách hỏi gần nhất
  - approve (kèm sửa nội dung) → mẩu vào kho; reject; API /prompt/suggestions
  - hook: endpoint send của bridge tạo đề xuất (WORKER_SYNC=1)

Chạy (TỪ GỐC):  python tests/test_knowledge_learn.py
"""

import os, sys
from unittest.mock import MagicMock, patch

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(), 'requests': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
os.environ.setdefault('OWNER_ZALO_ID', 'OWNER123')
os.environ['HOMESTAY_DB_PATH'] = 'test_db_klearn_tmp.sqlite'   # DB test RIÊNG file này
os.environ['API_AUTH_GUARD'] = '0'   # tắt auth-guard trong test (test_client không có token)
os.environ['WORKER_SYNC'] = '1'      # submit chạy đồng bộ → kiểm tra kết quả ngay
sys.path.insert(0, '.')

import json
from pathlib import Path
from app.core import knowledge, knowledge_learn as kl
from app.core.db import get_db

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
db.execute("DELETE FROM knowledge_chunks")
db.execute("DELETE FROM knowledge_suggestions")

print("\n── A. knowledge.add_chunks (cộng dồn) ──")

# A1: ingest 2 mẩu rồi add_chunks 1 mẩu → 3 mẩu, mẩu cũ còn nguyên
knowledge.ingest([
    {"title": "Giá phòng", "content": "Phòng 201 giá 500k/đêm", "keywords": ["gia phong"]},
    {"title": "Giờ nhận", "content": "Nhận phòng 14h", "keywords": ["check in"]},
])
n = knowledge.add_chunks([{"title": "Gửi xe", "content": "Gửi xe miễn phí trong hầm",
                           "keywords": ["gui xe", "de xe"]}])
check(n == 1, "A1 add_returns_1", f"n={n}")
titles = [c["title"] for c in knowledge.list_chunks()]
check(titles == ["Giá phòng", "Giờ nhận", "Gửi xe"], "A1 old_kept_new_appended", f"{titles}")

# A2: mẩu rỗng content → bỏ; trần MAX_CHUNKS được tôn trọng
check(knowledge.add_chunks([{"title": "x", "content": ""}]) == 0, "A2 empty_skipped")
with patch.object(knowledge, "MAX_CHUNKS", 3):
    check(knowledge.add_chunks([{"title": "y", "content": "z"}]) == 0, "A2 cap_respected")

# A3: retrieve thấy mẩu mới thêm
hits = knowledge.retrieve("cho em gui xe o dau")
check(any(c["title"] == "Gửi xe" for c in hits), "A3 retrieve_new_chunk", f"{hits}")

print("\n── B. suggest_from_reply ──")

MSGS = [
    {"role": "user", "content": "chào shop"},
    {"role": "assistant", "content": "Chào bạn ạ!"},
    {"role": "user", "content": "bên mình có nhận thú cưng không ạ?"},
]
AI_CHUNK = json.dumps({
    "title": "Chính sách thú cưng",
    "content": "Homestay nhận thú cưng dưới 5kg, phụ thu 50k/đêm.",
    "keywords": ["thu cung", "pet", "mang cho meo"],
}, ensure_ascii=False)

# B1: luồng chuẩn — chủ trả lời tay → AI bóc mẩu → đề xuất pending
with patch("app.core.claude_ai._call_ai", return_value=AI_CHUNK):
    s = kl.suggest_from_reply("zalo:U1", "zalo", MSGS, "Bên mình nhận pet dưới 5kg nha, phụ thu 50k/đêm")
check(bool(s) and s["status"] == "pending" and s.get("id"), "B1 suggestion_created", f"{s}")
check(s["question"] == "bên mình có nhận thú cưng không ạ?", "B1 question_extracted", f"{s['question']}")
check(s["title"] == "Chính sách thú cưng" and "5kg" in s["content"], "B1 chunk_from_ai")
check(kl.count_pending() == 1, "B1 pending_1")

# B2: câu hỏi TRÙNG (đã có đề xuất) → bỏ qua, không gọi AI lần 2
with patch("app.core.claude_ai._call_ai", return_value=AI_CHUNK) as mai:
    s2 = kl.suggest_from_reply("zalo:U2", "zalo", MSGS, "Nhận pet dưới 5kg nha bạn, phụ thu 50k")
check(s2 is None and not mai.called, "B2 dup_question_skip_no_ai", f"{s2}")

# B3: AI trả skip → không lưu
msgs3 = MSGS[:-1] + [{"role": "user", "content": "dạ vâng em cảm ơn shop nhiều ạ"}]
with patch("app.core.claude_ai._call_ai", return_value='{"skip": true}'):
    s3 = kl.suggest_from_reply("zalo:U3", "zalo", msgs3, "Dạ không có gì đâu ạ, hẹn gặp bạn!")
check(s3 is None and kl.count_pending() == 1, "B3 ai_skip")

# B4: lọc rẻ — trả lời quá ngắn / không có câu hỏi → không gọi AI
with patch("app.core.claude_ai._call_ai") as mai:
    check(kl.suggest_from_reply("z:U", "zalo", MSGS, "ok nha") is None, "B4 short_answer_skip")
    check(kl.suggest_from_reply("z:U", "zalo", [{"role": "assistant", "content": "chào"}],
                                "Bên mình mở cửa từ 8h sáng tới 22h đêm") is None,
          "B4 no_question_skip")
    check(not mai.called, "B4 no_ai_call")

# B5: AI trả rác (không phải JSON) → None, không crash
msgs5 = MSGS[:-1] + [{"role": "user", "content": "khách sạn có hồ bơi không?"}]
with patch("app.core.claude_ai._call_ai", return_value="xin lỗi tôi không hiểu"):
    check(kl.suggest_from_reply("z:U5", "zalo", msgs5, "Có hồ bơi tầng thượng mở 6h-20h nhé") is None,
          "B5 bad_json_none")

# B6: messages ĐÃ chứa câu trả lời của chủ (dashboard add trước) → vẫn tìm đúng câu hỏi
msgs6 = MSGS + [{"role": "assistant", "content": "Bên mình nhận pet nha"}]
with patch("app.core.claude_ai._call_ai", return_value=AI_CHUNK):
    db.execute("DELETE FROM knowledge_suggestions")   # xoá để khỏi dính dedup B2
    s6 = kl.suggest_from_reply("meta:U6", "meta", msgs6, "Bên mình nhận pet dưới 5kg, phụ thu 50k/đêm")
check(s6 and s6["question"] == "bên mình có nhận thú cưng không ạ?", "B6 skip_own_answer_in_messages")

print("\n── C. approve / reject ──")

before = knowledge.count()
# C1: duyệt NGUYÊN BẢN → mẩu vào kho + status approved
appr = kl.approve(s6["id"])
check(appr["status"] == "approved", "C1 status_approved")
check(knowledge.count() == before + 1, "C1 chunk_added")
check(any(c["title"] == "Chính sách thú cưng" for c in knowledge.list_chunks()), "C1 chunk_in_kb")

# C2: duyệt lại lần 2 → lỗi (đã xử lý)
try:
    kl.approve(s6["id"]); check(False, "C2 double_approve_rejected")
except ValueError:
    check(True, "C2 double_approve_rejected")

# C3: duyệt KÈM SỬA nội dung → bản sửa vào kho
with patch("app.core.claude_ai._call_ai", return_value=AI_CHUNK):
    msgs7 = MSGS[:-1] + [{"role": "user", "content": "có chỗ đậu ô tô không shop?"}]
    s7 = kl.suggest_from_reply("tg:U7", "telegram", msgs7, "Có bãi ô tô sau nhà, miễn phí cho khách")
appr7 = kl.approve(s7["id"], title="Bãi đậu ô tô", content="Bãi ô tô sau nhà, MIỄN PHÍ cho khách lưu trú.")
check(any(c["title"] == "Bãi đậu ô tô" and "MIỄN PHÍ" in c["content"]
          for c in knowledge.list_chunks()), "C3 edited_before_approve")

# C4: reject → không vào kho
with patch("app.core.claude_ai._call_ai", return_value=AI_CHUNK):
    msgs8 = MSGS[:-1] + [{"role": "user", "content": "shop có ship hàng ra đảo không?"}]
    s8 = kl.suggest_from_reply("sp:U8", "shopee", msgs8, "Bên mình có ship đảo, phí 100k bạn nhé")
n_before = knowledge.count()
kl.reject(s8["id"])
check(knowledge.count() == n_before, "C4 reject_no_chunk")
check(kl.count_pending() == 0, "C4 pending_cleared")
check(len(kl.list_suggestions("rejected")) == 1, "C4 in_rejected_list")

# C5: approve id không tồn tại → ValueError
try:
    kl.approve(99999); check(False, "C5 missing_id_error")
except ValueError:
    check(True, "C5 missing_id_error")

print("\n── D. API /prompt/suggestions (bare Flask + register_prompt_routes) ──")
from flask import Flask
from app.web_api.prompt_api import register_prompt_routes
from app.web_api.auth_api import _issue_token, hash_password
from datetime import datetime as _dt

db.execute("INSERT OR IGNORE INTO users(username,password_hash,homestay,email,provider,picture,created_at)"
           " VALUES(?,?,?,?,?,?,?)",
           ("kl@test", hash_password("x"), "", "", "password", "", _dt.now().isoformat()))
tok = _issue_token(db, "kl@test")
H = {"Authorization": f"Bearer {tok}"}
api = register_prompt_routes(Flask(__name__)).test_client()

# D1: không token → 401
check(api.get("/prompt/suggestions").status_code == 401, "D1 no_token_401")

# D2: list pending
with patch("app.core.claude_ai._call_ai", return_value=AI_CHUNK):
    msgs9 = MSGS[:-1] + [{"role": "user", "content": "quán có wifi không chị?"}]
    s9 = kl.suggest_from_reply("oa:U9", "zalooa", msgs9, "Wifi miễn phí, pass là 88888888 bạn nha")
r = api.get("/prompt/suggestions", headers=H)
body = r.get_json()
check(r.status_code == 200 and body["pending"] == 1
      and body["suggestions"][0]["id"] == s9["id"], "D2 list_pending", f"{body}")

# D3: approve qua API kèm sửa
r = api.post(f"/prompt/suggestions/{s9['id']}/approve", headers=H,
             json={"content": "Wifi miễn phí toàn quán, mật khẩu 88888888."})
check(r.status_code == 200 and r.get_json()["pending"] == 0, "D3 approve_api", f"{r.get_json()}")
check(any("88888888" in c["content"] for c in knowledge.list_chunks()), "D3 chunk_saved")

# D4: reject qua API + id sai → 400
with patch("app.core.claude_ai._call_ai", return_value=AI_CHUNK):
    msgs10 = MSGS[:-1] + [{"role": "user", "content": "nhà mình có cho nấu ăn không?"}]
    s10 = kl.suggest_from_reply("tt:U10", "tiktok", msgs10, "Có bếp chung tầng 1, nấu thoải mái nhé bạn")
check(api.post(f"/prompt/suggestions/{s10['id']}/reject", headers=H, json={}).status_code == 200,
      "D4 reject_api")
check(api.post("/prompt/suggestions/99999/approve", headers=H, json={}).status_code == 400,
      "D4 bad_id_400")

print("\n── E. Hook: chủ gửi tay từ dashboard bridge → tự tạo đề xuất ──")
from app.core.conversation import ConversationManager
from app.core.brain import Brain
from app.core.channel import Channel
import app.web_api.bridge as bridge_mod

class FakeChannel(Channel):
    def send_text(self, uid, text): pass
    def send_room_photos(self, uid, names): pass
    def send_price_photos(self, uid): pass
    def notify_owner(self, text): pass
    def call_owner(self): pass

cm = ConversationManager(account="kl-test")
cm._sessions.clear()
conv = cm.get("KH1")
conv.add_user_message("cho hỏi homestay có cho mượn xe máy không ạ?")

bridge_mod.BOT_STATE_FILE = Path("test_bot_state_kl_tmp.json")
brain = Brain(channel=FakeChannel(), conv_manager=cm)
client = bridge_mod.create_bridge(brain, cm).test_client()

db.execute("DELETE FROM knowledge_suggestions")
with patch("app.core.claude_ai._call_ai", return_value=json.dumps({
        "title": "Thuê xe máy", "content": "Cho thuê xe máy 100k/ngày, cần CCCD.",
        "keywords": ["thue xe may", "muon xe"]}, ensure_ascii=False)):
    r = client.post("/conversations/KH1/send",
                    json={"text": "Bên mình có cho thuê xe máy 100k/ngày nha, bạn để lại CCCD là được"})
check(r.status_code == 200, "E1 send_ok")
check(kl.count_pending() == 1, "E1 suggestion_from_dashboard_send", f"pending={kl.count_pending()}")
sug = kl.list_suggestions()[0]
check(sug["channel"] == "zalo" and "xe máy" in sug["question"], "E1 channel_and_question", f"{sug}")

# Dọn
db.execute("DELETE FROM knowledge_suggestions")
db.execute("DELETE FROM knowledge_chunks")
Path("test_bot_state_kl_tmp.json").unlink(missing_ok=True)

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
