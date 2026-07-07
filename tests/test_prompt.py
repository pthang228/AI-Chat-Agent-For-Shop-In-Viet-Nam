#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_prompt.py — Prompt Builder (link dữ liệu + hướng dẫn → AI viết prompt):
  - fetch_link: HTML→text, lỗi HTTP, link trống, tự thêm https, cắt bớt dài
  - generate: gộp link + hướng dẫn vào messages, bóc ```fence```, thiếu input
  - apply/current/restore: lưu custom_prompt.txt + backup, khôi phục mặc định
  - claude_ai ưu tiên custom_prompt.txt
  - API /prompt/* (Bearer)

Chạy (TỪ GỐC):  python tests/test_prompt.py
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

from pathlib import Path
from flask import Flask
from app.core import prompt_builder as pb
from app.core.db import get_db
import app.web_api.auth_api as auth_mod
import app.web_api.prompt_api as prompt_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

# Cô lập file prompt custom vào file test
pb.CUSTOM_FILE = Path("test_custom_prompt_tmp.txt")
pb.BACKUP_DIR = Path("test_prompt_backups_tmp")
if pb.CUSTOM_FILE.exists(): pb.CUSTOM_FILE.unlink()

print("\n── A. fetch_link ──")

def _resp(status=200, text="", ctype="text/html"):
    m = MagicMock(); m.status_code = status; m.text = text
    m.headers = {"Content-Type": ctype}
    return m

with patch.object(pb, 'requests') as mreq:
    mreq.get.return_value = _resp(text="<html><head><style>x{}</style></head><body><h1>Bảng giá</h1><p>Phòng 201: 500k/đêm</p><script>bad()</script></body></html>")
    r = pb.fetch_link("https://haru.vn/gia")
    check(r["ok"] and "Bảng giá" in r["text"] and "Phòng 201: 500k/đêm" in r["text"], "A1 html_to_text", f"{r}")
    check("bad()" not in r["text"] and "x{}" not in r["text"], "A2 strips_script_style")

with patch.object(pb, 'requests') as mreq:
    mreq.get.return_value = _resp(status=404)
    r = pb.fetch_link("https://haru.vn/404")
    check(not r["ok"] and "404" in r["error"], "A3 http_error")

check(not pb.fetch_link("")["ok"], "A4 empty_link")

with patch.object(pb, 'requests') as mreq:
    mreq.get.return_value = _resp(text="giá phòng abc", ctype="text/plain")
    r = pb.fetch_link("haru.vn/gia.txt")   # không có scheme → tự thêm https
    check(r["ok"] and r["url"].startswith("https://"), "A5 auto_https", f"{r}")
    check(mreq.get.call_args[0][0] == "https://haru.vn/gia.txt", "A5 fetched_url")

with patch.object(pb, 'requests') as mreq:
    mreq.get.return_value = _resp(text="x" * 50_000, ctype="text/plain")
    r = pb.fetch_link("https://haru.vn/big")
    check(len(r["text"]) <= pb.MAX_LINK_CHARS + 50, "A6 caps_length", len(r["text"]))

print("\n── B. generate ──")

FAKE_PROMPT = "BẠN LÀ TRỢ LÝ HOMESTAY HARU\n" + "chi tiết " * 100

with patch.object(pb, 'requests') as mreq, \
     patch.object(pb, '_call_ai_long', return_value=f"```\n{FAKE_PROMPT}\n```") as mai:
    mreq.get.return_value = _resp(text="<p>Phòng 201 giá 500k</p>")
    r = pb.generate(["https://haru.vn/gia", ""], "Xưng em với khách")
    check(r["draft"] == FAKE_PROMPT.strip(), "B1 strips_fence", r["draft"][:60])
    sent = mai.call_args[0][0]
    user_msg = sent[1]["content"]
    check("Phòng 201 giá 500k" in user_msg, "B2 link_data_included")
    check("Xưng em với khách" in user_msg, "B3 instructions_included")
    check("CHUYÊN GIA" in sent[0]["content"], "B4 meta_prompt")
    check(r["sources"][0]["ok"], "B5 sources_reported", f"{r['sources']}")

# Không có gì → ValueError
try:
    with patch.object(pb, 'requests'):
        pb.generate([], "")
    check(False, "B6 empty_input_rejected")
except ValueError:
    check(True, "B6 empty_input_rejected")

# Link lỗi nhưng CÓ hướng dẫn → vẫn chạy
with patch.object(pb, 'requests') as mreq, \
     patch.object(pb, '_call_ai_long', return_value=FAKE_PROMPT):
    mreq.get.return_value = _resp(status=500)
    r = pb.generate(["https://die.vn"], "chỉ dẫn thôi")
    check(r["draft"] and not r["sources"][0]["ok"], "B7 bad_link_ok_with_instructions")

# Link dạng dict {url, note} → ghi chú của shop đặt ngay trước nội dung đã fetch
with patch.object(pb, 'requests') as mreq, \
     patch.object(pb, '_call_ai_long', return_value=FAKE_PROMPT) as mai:
    mreq.get.return_value = _resp(text="<p>Phòng 201 giá 500k</p>")
    r = pb.generate([{"url": "https://haru.vn/gia", "note": "bảng giá phòng"}], "")
    user_msg = mai.call_args[0][0][1]["content"]
    check("Shop mô tả link này: bảng giá phòng" in user_msg
          and "Phòng 201 giá 500k" in user_msg and r["sources"][0]["ok"],
          "B8 dict_link_note_included", user_msg[:200])

# Link Google Sheets DỮ LIỆU tới generate → ĐỌC THẬT qua _gsheet_text (service
# account) và nội dung vào prompt (sheet LỊCH đã bị prompt_api tách trước đó)
with patch.object(pb, 'requests') as mreq, \
     patch.object(pb, '_gsheet_text', return_value="Massage 60p, 400000") as mgs, \
     patch.object(pb, '_call_ai_long', return_value=FAKE_PROMPT) as mai:
    r = pb.generate([{"url": "https://docs.google.com/spreadsheets/d/abc123/edit", "note": "bảng giá"}], "")
    user_msg = mai.call_args[0][0][1]["content"]
    check(mgs.called and "Massage 60p, 400000" in user_msg
          and "bảng giá" in user_msg and r["sources"][0]["ok"],
          "B9 gsheet_data_duoc_doc_that", user_msg[:200])

# Model shop chọn để DẠY + extra_context (cấu hình shop tự đính kèm) → truyền xuống AI
with patch.object(pb, 'requests') as mreq, \
     patch.object(pb, '_call_ai_long', return_value=FAKE_PROMPT) as mai:
    mreq.get.return_value = _resp(text="<p>data</p>")
    r = pb.generate(["https://x.vn"], "hi", model="gpt-4o-mini", owner="shop@x.vn",
                    extra_context="LIÊN HỆ KHẨN CẤP CỦA SHOP: 0901")
    check(mai.call_args[1].get("model_key") == "gpt-4o-mini"
          and mai.call_args[1].get("owner") == "shop@x.vn",
          "B10 model_owner_passed", f"{mai.call_args[1]}")
    user_msg = mai.call_args[0][0][1]["content"]
    check("===== CẤU HÌNH SHOP (tự động) =====" in user_msg and "0901" in user_msg,
          "B11 extra_context_included", user_msg[:200])

# _call_ai_long với model_key → đi qua ai_models.chat (max_tokens/temperature dạy AI)
from app.core.config import Config as _Cfg
_Cfg.OPENAI_API_KEY = "sk-test-b12"

def _mkresp(text, finish):
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=text), finish_reason=finish)]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    return resp

# (client giờ dựng qua ai_models.client_for — mock ở đó)
import app.core.ai_models as am_mod
_mclient = MagicMock()
with patch.object(am_mod, "client_for", return_value=(_mclient, "gpt-4o-mini")) as mcf:
    # Vòng 1 chạm trần (finish_reason='length') → tự viết tiếp vòng 2
    _mclient.chat.completions.create.side_effect = [
        _mkresp("PHẦN-1|", "length"), _mkresp("PHẦN-2", "stop")]
    out = pb._call_ai_long([{"role": "user", "content": "x"}],
                           model_key="gpt-4o-mini", owner="o@x.vn")
    call1 = _mclient.chat.completions.create.call_args_list[0][1]
    check(out == "PHẦN-1|PHẦN-2" and mcf.call_args[0][0] == "gpt-4o-mini"
          and call1["model"] == "gpt-4o-mini"
          and call1["max_tokens"] == pb.GEN_MAX_TOKENS
          and _mclient.chat.completions.create.call_count == 2,
          "B12 gen_full_viet_tiep_khi_cham_tran",
          f"out={out!r} calls={_mclient.chat.completions.create.call_count}")

print("\n── C. apply / current / restore ──")
cur = pb.current()
check(cur["source"] == "default" and len(cur["prompt"]) > 0, "C1 default_initial", cur["source"])

try:
    pb.apply("ngắn"); check(False, "C2 too_short_rejected")
except ValueError:
    check(True, "C2 too_short_rejected")

pb.apply(FAKE_PROMPT)
cur = pb.current()
check(cur["source"] == "custom" and cur["prompt"] == FAKE_PROMPT.strip(), "C3 apply_saves")

# claude_ai ưu tiên custom (trỏ Config.DATA_DIR? — _load_system_prompt đọc DATA_DIR/custom_prompt.txt,
# test này ghi file test riêng nên chỉ kiểm tra qua pb.current; hành vi ưu tiên custom
# được kiểm chứng bằng logic file tồn tại ở C3/C5)

# Apply lần 2 → bản cũ vào backup
pb.apply(FAKE_PROMPT + "\nphiên bản 2")
check(any(pb.BACKUP_DIR.glob("custom_prompt-*.txt")), "C4 backup_created")

st = pb.restore_default()
check(st["source"] == "default" and not pb.CUSTOM_FILE.exists(), "C5 restore_default")

print("\n── D. API /prompt/* ──")
db = get_db()
for t in ("users", "auth_tokens"):
    db.execute(f"DELETE FROM {t}")

flask_app = Flask(__name__)
auth_mod.register_auth_routes(flask_app)
prompt_mod.register_prompt_routes(flask_app)
api = flask_app.test_client()

tok = api.post("/auth/register", json={"username": "p@x.vn", "password": "test1234"}).get_json()["token"]
H = {"Authorization": f"Bearer {tok}"}

r = api.get("/prompt/current", headers=H)
check(r.status_code == 200 and r.get_json()["source"] == "default", "D1 current_ok")
check(api.get("/prompt/current").status_code == 401, "D2 needs_auth")

with patch.object(pb, 'requests') as mreq, \
     patch.object(pb, '_call_ai_long', return_value=FAKE_PROMPT):
    mreq.get.return_value = _resp(text="<p>data</p>")
    r = api.post("/prompt/generate", json={"links": ["https://x.vn"], "instructions": "hi"}, headers=H)
check(r.status_code == 200 and r.get_json()["draft"] == FAKE_PROMPT.strip(), "D3 api_generate")

r = api.post("/prompt/generate", json={"links": [], "instructions": ""}, headers=H)
check(r.status_code == 400, "D4 api_generate_empty_400")

# Model không hợp lệ / thiếu key → 400 (không gọi AI)
r = api.post("/prompt/generate", json={"links": ["https://x.vn"], "instructions": "hi",
                                       "model": "model-lạ"}, headers=H)
check(r.status_code == 400, "D4b api_generate_bad_model_400")

# Model hợp lệ (server có key) → truyền model_key + owner vào generate;
# cấu hình shop (canned reply của workspace) tự đính kèm vào dữ liệu dạy
from app.core.config import Config as _Cfg
_old_ds = _Cfg.DEEPSEEK_API_KEY
_Cfg.DEEPSEEK_API_KEY = "sk-test"
db.execute("INSERT INTO canned_replies (title, content, created_at, tenant) VALUES (?,?,?,?)",
           ("Chào khách", "Xin chào bạn iu", "2026-01-01", "p@x.vn"))
db.execute("UPDATE users SET bank_code='MB', bank_account='9998887776', "
           "bank_holder='NGUYEN BI MAT' WHERE username='p@x.vn'")
with patch.object(pb, 'requests') as mreq, \
     patch.object(pb, '_call_ai_long', return_value=FAKE_PROMPT) as mai:
    mreq.get.return_value = _resp(text="<p>data</p>")
    r = api.post("/prompt/generate", json={"links": ["https://x.vn"], "instructions": "hi",
                                           "model": "deepseek-chat"}, headers=H)
check(r.status_code == 200 and mai.call_args[1].get("model_key") == "deepseek-chat"
      and mai.call_args[1].get("owner") == "p@x.vn",
      "D4c api_generate_model_passed", f"{r.status_code} {mai.call_args[1] if mai.call_args else None}")
_api_user_msg = mai.call_args[0][0][1]["content"] if mai.call_args else ""
# Câu mẫu KHÔNG bơm vào input AI nữa (tránh sinh mẩu kép) — nó được ghép cứng
# thành 1 mẩu tri thức trong response (kiểm ở D4d2)
check("===== CẤU HÌNH SHOP (tự động) =====" in _api_user_msg
      and "Xin chào bạn iu" not in _api_user_msg,
      "D4d api_generate_shop_config_attached", _api_user_msg[:200])
_chunks = (r.get_json() or {}).get("chunks") or []
check(any(c.get("title") == "Câu trả lời mẫu của shop"
          and "Xin chào bạn iu" in (c.get("content") or "") for c in _chunks),
      "D4d2 canned_thanh_mau_co_dinh", f"{[c.get('title') for c in _chunks]}")
# TUYỆT ĐỐI KHÔNG gom tài khoản ngân hàng vào dữ liệu dạy
check("9998887776" not in _api_user_msg and "NGUYEN BI MAT" not in _api_user_msg,
      "D4e bank_never_attached")
_Cfg.DEEPSEEK_API_KEY = _old_ds
db.execute("DELETE FROM canned_replies WHERE tenant='p@x.vn'")

r = api.post("/prompt/apply", json={"prompt": FAKE_PROMPT}, headers=H)
check(r.status_code == 200 and r.get_json()["source"] == "custom", "D5 api_apply")

r = api.post("/prompt/restore-default", headers=H)
check(r.status_code == 200 and r.get_json()["source"] == "default", "D6 api_restore")

# Dọn file tạm
import shutil
if pb.CUSTOM_FILE.exists(): pb.CUSTOM_FILE.unlink()
shutil.rmtree(pb.BACKUP_DIR, ignore_errors=True)

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
