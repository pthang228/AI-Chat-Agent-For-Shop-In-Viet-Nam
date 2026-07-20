#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ai_models.py — MULTI-MODEL AI + tính theo usage khi vượt quota:
  A. Catalog + giá: price_vnd_1m, cost_vnd, catalog_for_ui (available theo key)
  B. model_for_owner: chọn hợp lệ / không hợp lệ / thiếu key → mặc định
  C. record_token_usage: trong quota KHÔNG trừ ví; hết quota + bật usage → trừ ví
     + cộng usage_spent; reset theo tháng
  D. can_reply: hết quota → False; bật usage còn hạn mức + ví → True; chạm limit → False
  E. API /billing/ai-model + /billing/usage: validate + lưu
  F. model_for(owner, account): override PER-APP (user_apps.ai_model) theo kênh
  G. API /auth/apps/<id>/ai-model: đặt/xoá model riêng từng chatbot

Chạy TỪ GỐC: python -m tests.test_ai_models
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
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_ai_models_tmp.sqlite')
os.environ['API_AUTH_GUARD'] = '1'
os.environ['WORKER_SYNC'] = '1'
os.environ['AI_USD_VND'] = '25000'      # tỷ giá cố định cho test
os.environ['AI_PRICE_MARKUP'] = '1.0'
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_ai_models_tmp.sqlite{suf}")).unlink(missing_ok=True)

from flask import Flask
from app.web_api.auth_api import register_auth_routes
from app.web_api.billing_api import register_billing_routes
from app.core import ai_models as am
from app.core import billing
from app.core.db import get_db

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")


print("A. Catalog + giá")
pin, pout = am.price_vnd_1m("deepseek-chat")   # 0.26 / 0.38 USD × 25000
check(pin == 6500 and pout == 9500, "A1 giá VNĐ/1M đúng tỷ giá", (pin, pout))
c = am.cost_vnd("gpt-4o", 1000, 500)           # (1000*2.5 + 500*10)/1e6 × 25000
check(abs(c - 187.5) < 0.01, "A2 cost_vnd đúng công thức", c)
ui = am.catalog_for_ui()
check(len(ui) == len(am.public_catalog()) and all("in_vnd" in m for m in ui), "A3 catalog_for_ui đủ model public")
check(any(m["default"] for m in ui), "A4 có model mặc định")
# Model nội bộ (Groq fallback) KHÔNG lộ ra UI / KHÔNG cho shop chọn, nhưng có giá để tính
check(not any(m["key"].startswith("groq-") for m in ui), "A5 model nội bộ ẩn khỏi UI")
check("groq-llama-70b" in am.CATALOG and am.cost_vnd("groq-llama-70b", 1000, 1000) > 0,
      "A6 model nội bộ vẫn tính được chi phí")
# KB budget co theo giá: DeepSeek nhồi hết, GPT-4o co lại
check(am.kb_char_budget("deepseek-chat") == 24000 and am.kb_char_budget("gpt-4o") < 24000,
      "A7 kb_char_budget co theo giá model")

print("B. model_for_owner")
from app.core.config import Config
Config.DEEPSEEK_API_KEY = "sk-test"; Config.OPENAI_API_KEY = ""
check(am.model_for_owner(None) == am.DEFAULT_MODEL, "B1 không owner → mặc định")

app = Flask(__name__)
register_auth_routes(app)
register_billing_routes(app)
cli = app.test_client()
r = cli.post("/auth/register", json={"username": "shop@x.vn", "password": "1234", "homestay": "Shop"})
H = {"Authorization": f"Bearer {r.json['token']}"}
U = "shop@x.vn"

db = get_db()
db.execute("UPDATE billing SET ai_model='gpt-5-mini' WHERE username=?", (U,))
check(am.model_for_owner(U) == am.DEFAULT_MODEL, "B2 chọn model thiếu key → về mặc định")
Config.OPENAI_API_KEY = "sk-openai-test"
check(am.model_for_owner(U) == "gpt-5-mini", "B3 có key → dùng model đã chọn")
db.execute("UPDATE billing SET ai_model='model-lạ' WHERE username=?", (U,))
check(am.model_for_owner(U) == am.DEFAULT_MODEL, "B4 model lạ → mặc định")
db.execute("UPDATE billing SET ai_model='' WHERE username=?", (U,))

print("C. record_token_usage")
def brow():
    return db.query("SELECT * FROM billing WHERE username=?", (U,))[0]
db.execute("UPDATE billing SET balance=100000 WHERE username=?", (U,))
# Trong quota (trial mới → chưa vượt) → không trừ ví
billing.record_token_usage(U, "deepseek-chat", 100_000, 50_000)
b = brow()
check(b["balance"] == 100000 and (b["usage_spent"] or 0) == 0,
      "C1 trong quota: KHÔNG trừ ví, usage_spent=0", dict(b))
# Ép hết quota (trial: 500 lượt/ngày) + bật usage
db.execute("UPDATE billing SET ai_used=?, ai_period=?, usage_enabled=1, usage_limit=50000 "
           "WHERE username=?", (10_000, billing._period("trial"), U))
billing.record_token_usage(U, "deepseek-chat", 1_000_000, 1_000_000)  # 6500+9500=16000đ
b = brow()
check(b["balance"] == 100000 - 16000, "C2 vượt quota + bật usage → trừ ví đúng giá", b["balance"])
check(b["usage_spent"] == 16000, "C3 usage_spent cộng dồn", b["usage_spent"])
# Tắt usage → vượt quota cũng không trừ
db.execute("UPDATE billing SET usage_enabled=0 WHERE username=?", (U,))
billing.record_token_usage(U, "deepseek-chat", 1_000_000, 0)
b = brow()
check(b["balance"] == 84000 and b["usage_spent"] == 16000,
      "C4 tắt usage: không trừ thêm", dict(balance=b["balance"], spent=b["usage_spent"]))

print("D. can_reply với usage")
db.execute("UPDATE billing SET usage_enabled=0 WHERE username=?", (U,))
check(not billing.can_reply(U), "D1 hết quota + tắt usage → bot dừng")
db.execute("UPDATE billing SET usage_enabled=1, usage_limit=50000 WHERE username=?", (U,))
check(billing.can_reply(U), "D2 bật usage còn hạn mức + ví → bot chạy")
db.execute("UPDATE billing SET usage_spent=50000 WHERE username=?", (U,))
check(not billing.can_reply(U), "D3 chạm giới hạn tháng → bot dừng")
db.execute("UPDATE billing SET usage_spent=0, balance=0 WHERE username=?", (U,))
check(not billing.can_reply(U), "D4 ví 0đ → bot dừng")
db.execute("UPDATE billing SET balance=50000, ai_used=0 WHERE username=?", (U,))
check(billing.can_reply(U), "D5 còn quota → chạy bình thường")

print("E. API chọn model + usage")
r = cli.get("/billing/me", headers=H)
check(r.status_code == 200 and len(r.json["ai_models"]) == len(am.public_catalog()),
      "E1 /billing/me kèm bảng giá model")
r = cli.post("/billing/ai-model", headers=H, json={"model": "gpt-4o-mini"})
check(r.status_code == 200 and r.json["ai_model"] == "gpt-4o-mini", "E2 chọn model OK", r.text[:80])
r = cli.post("/billing/ai-model", headers=H, json={"model": "model-lạ"})
check(r.status_code == 400, "E3 model lạ → 400")
Config.OPENAI_API_KEY = ""
r = cli.post("/billing/ai-model", headers=H, json={"model": "gpt-4o"})
check(r.status_code == 400, "E4 thiếu key server → 400")
Config.OPENAI_API_KEY = "sk-openai-test"
r = cli.post("/billing/usage", headers=H, json={"enabled": True, "limit": 300000})
check(r.status_code == 200 and r.json["usage_enabled"] and r.json["usage_limit"] == 300000,
      "E5 bật usage + limit OK", r.text[:80])
r = cli.post("/billing/usage", headers=H, json={"enabled": True, "limit": 0})
check(r.status_code == 400, "E6 bật mà limit 0 → 400")
r = cli.post("/billing/usage", headers=H, json={"enabled": False, "limit": 0})
check(r.status_code == 200 and not r.json["usage_enabled"], "E7 tắt usage OK")

print("F. model_for per-app (user_apps.ai_model)")
db.execute("UPDATE billing SET ai_model='' WHERE username=?", (U,))
check(am.model_for(U, "1") == am.DEFAULT_MODEL, "F1 không override → model shop (mặc định)")
db.execute("INSERT INTO user_apps(id, username, name, channel, created_at, ai_model) "
           "VALUES (?,?,?,?,?,?)",
           ("app-zalo-1", U, "Bot Zalo", "zalo", "2026-01-01", "gpt-4o-mini"))
check(am.model_for(U, "1") == "gpt-4o-mini", "F2 account '1' → kênh zalo → model per-app")
check(am.model_for(U, "zalo") == "gpt-4o-mini", "F3 account 'zalo' cũng map kênh zalo")
db.execute("UPDATE billing SET ai_model='gpt-5-mini' WHERE username=?", (U,))
check(am.model_for(U, "telegram") == "gpt-5-mini", "F4 kênh không override → model shop")
Config.OPENAI_API_KEY = ""
check(am.model_for(U, "1") == am.DEFAULT_MODEL, "F5 override thiếu key → mặc định")
Config.OPENAI_API_KEY = "sk-openai-test"
db.execute("UPDATE billing SET ai_model='' WHERE username=?", (U,))

print("G. API /auth/apps/<id>/ai-model (model riêng từng chatbot)")
r = cli.post("/auth/apps", headers=H, json={"name": "Bot Tele", "channel": "telegram"})
app_id = r.json["app"]["id"]
r = cli.post(f"/auth/apps/{app_id}/ai-model", headers=H, json={"model": "gpt-4o-mini"})
check(r.status_code == 200 and r.json["ai_model"] == "gpt-4o-mini", "G1 đặt model per-app OK",
      r.text[:80])
r = cli.get("/auth/apps", headers=H)
_found = [a for a in r.json if a["id"] == app_id]
check(_found and _found[0]["ai_model"] == "gpt-4o-mini", "G2 GET /auth/apps trả ai_model")
check(am.model_for(U, "telegram") == "gpt-4o-mini", "G3 model_for thấy override telegram")
r = cli.post(f"/auth/apps/{app_id}/ai-model", headers=H, json={"model": "model-lạ"})
check(r.status_code == 400, "G4 model lạ → 400")
Config.OPENAI_API_KEY = ""
r = cli.post(f"/auth/apps/{app_id}/ai-model", headers=H, json={"model": "gpt-4o"})
check(r.status_code == 400, "G5 thiếu key server → 400")
Config.OPENAI_API_KEY = "sk-openai-test"
r = cli.post(f"/auth/apps/{app_id}/ai-model", headers=H, json={"model": ""})
check(r.status_code == 200 and r.json["ai_model"] == "", "G6 model rỗng = xoá override")
check(am.model_for(U, "telegram") == am.DEFAULT_MODEL, "G7 sau xoá → về model shop")
r = cli.post("/auth/apps/khong-ton-tai/ai-model", headers=H, json={"model": "gpt-4o-mini"})
check(r.status_code == 404, "G8 app không tồn tại → 404")

# ── H. Trần model theo HẠNG gói (chống shop gói rẻ chọn model đắt) ──
print("\n── H. Trần model theo hạng gói ──")
check(am.allowed_for_tier("deepseek-chat", "trial"), "H1 trial dùng được DeepSeek")
check(not am.allowed_for_tier("gpt-4o", "starter"), "H2 starter KHÔNG được GPT-4o")
check(not am.allowed_for_tier("gpt-5", "pro"), "H3 pro KHÔNG được GPT-5")
check(am.allowed_for_tier("gpt-5", "business"), "H4 business được mọi model")
check(am.min_tier_for("gpt-4o") == "business" and am.min_tier_for("gpt-5-mini") == "pro",
      "H5 min_tier_for đúng", (am.min_tier_for("gpt-4o"), am.min_tier_for("gpt-5-mini")))
check(all("min_tier" in m for m in am.catalog_for_ui()), "H6 catalog_for_ui kèm min_tier")

# API: user trial chọn model đắt → 400; model rẻ → 200
r = cli.post("/billing/ai-model", headers=H, json={"model": "gpt-4o"})
check(r.status_code == 400 and "hạng gói" in (r.json.get("error") or ""),
      "H7 trial chọn GPT-4o → 400 kèm lý do", r.text[:100])
r = cli.post("/billing/ai-model", headers=H, json={"model": "gpt-4o-mini"})
check(r.status_code == 200, "H8 trial chọn GPT-4o mini → OK", r.text[:80])
r = cli.post(f"/auth/apps/{app_id}/ai-model", headers=H, json={"model": "gpt-4o"})
check(r.status_code == 400, "H9 per-app cũng bị trần theo hạng", r.text[:80])

# Runtime downgrade: DB còn ghi model đắt (hạ gói sau khi chọn) → chat() hạ về mặc định
get_db().execute("UPDATE billing SET ai_model='gpt-4o', tier='starter' WHERE username=?", (U,))
_calls = {}
class _FakeResp:
    class _C:
        class _M: content = "ok"
        message = _M()
    choices = [_C()]
    usage = None
class _FakeClient:
    class chat:
        class completions:
            @staticmethod
            def create(**kw):
                _calls["model"] = kw.get("model")
                return _FakeResp()
from unittest.mock import patch
with patch.object(am, "client_for", lambda k, t=None: (_FakeClient(), am.CATALOG[k]["model"])):
    am.chat([{"role": "user", "content": "hi"}], owner=U)
check(_calls.get("model") == am.CATALOG[am.DEFAULT_MODEL]["model"],
      "H10 runtime hạ model vượt hạng về mặc định", _calls)
get_db().execute("UPDATE billing SET ai_model='', tier='trial' WHERE username=?", (U,))

# dọn
try:
    get_db().conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_ai_models_tmp.sqlite{suf}")).unlink(missing_ok=True)

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
