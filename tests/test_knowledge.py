#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_knowledge.py — Chế độ "Dạy AI" LAI (persona + tri thức RAG):
  - knowledge store: ingest/list/count/clear, caps, lọc mẩu rỗng
  - retrieve: bỏ dấu tiếng Việt, match cụm keyword, token, pinned fallback, top-k
  - prompt_builder: parse ===PERSONA===/===KNOWLEDGE===, fallback chế độ cũ,
    apply lai (marker + ingest), restore xoá tri thức
  - claude_ai._build_system_prompt: ghép persona + DỮ LIỆU SHOP + tech rules;
    prompt cũ không đổi hành vi
  - API /prompt/apply với chunks + /prompt/knowledge

Chạy (TỪ GỐC):  python tests/test_knowledge.py
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
from app.core import knowledge as kn
from app.core import prompt_builder as pb
from app.core import claude_ai
from app.core.db import get_db
import app.web_api.auth_api as auth_mod
import app.web_api.prompt_api as prompt_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

# Cô lập: file prompt test + dọn bảng tri thức
pb.CUSTOM_FILE = Path("test_custom_prompt_kn_tmp.txt")
pb.BACKUP_DIR = Path("test_prompt_backups_kn_tmp")
if pb.CUSTOM_FILE.exists(): pb.CUSTOM_FILE.unlink()
kn.clear()

print("\n── A. knowledge store ──")

CHUNKS = [
    {"title": "Thông tin chung", "content": "Haru Staycation, 238 ĐT743A Dĩ An. SĐT 0900.",
     "keywords": ["địa chỉ", "ở đâu", "liên hệ", "sđt"], "pinned": True},
    {"title": "Phòng 301", "content": "Phòng 301: 700k/đêm, ban công, tối đa 2 người.",
     "keywords": ["phòng 301", "ban công", "phòng đôi", "giá 301"]},
    {"title": "Chính sách cọc", "content": "Cọc 50%, hoàn cọc khi huỷ trước 5 ngày.",
     "keywords": ["đặt cọc", "hoàn cọc", "huỷ phòng", "refund"]},
    {"title": "Thú cưng", "content": "Cho mang thú cưng, phụ thu 500k nếu làm bẩn.",
     "keywords": ["thú cưng", "chó mèo", "pet"]},
]
n = kn.ingest(CHUNKS)
check(n == 4 and kn.count() == 4, "A1 ingest_count", f"{n}/{kn.count()}")

lst = kn.list_chunks()
check(lst[0]["title"] == "Thông tin chung" and lst[0]["pinned"], "A2 list_order_pinned")
check(lst[1]["keywords"] == ["phòng 301", "ban công", "phòng đôi", "giá 301"], "A3 keywords_roundtrip")

# Mẩu rỗng bị lọc, ingest THAY toàn bộ
n = kn.ingest(CHUNKS + [{"title": "rỗng", "content": "  "}])
check(n == 4 and kn.count() == 4, "A4 empty_chunk_filtered")

# Cap content dài
n = kn.ingest([{"content": "x" * 10_000, "keywords": "phòng"}])  # keywords không phải list → bọc
one = kn.list_chunks()[0]
check(len(one["content"]) == kn.MAX_CONTENT_CHARS, "A5 content_capped")
check(one["keywords"] == ["phòng"], "A6 keywords_coerced")
kn.ingest(CHUNKS)  # khôi phục cho phần B

print("\n── B. retrieve ──")

# B1: match cụm keyword — khách gõ KHÔNG DẤU vẫn trúng (chuẩn hoá bỏ dấu)
hits = kn.retrieve("cho minh hoi dat coc the nao")
check(hits and hits[0]["title"] == "Chính sách cọc", "B1 no_diacritics_match", f"{[h['title'] for h in hits]}")

# B2: hỏi về phòng 301
hits = kn.retrieve("phòng 301 còn không?")
check(hits and hits[0]["title"] == "Phòng 301", "B2 room_query", f"{[h['title'] for h in hits]}")

# B3: từ đồng nghĩa trong keywords (pet ~ thú cưng)
# (retrieve giờ LUÔN kèm mẩu pinned lên đầu → mẩu match nằm ngay sau)
hits = kn.retrieve("mang pet vào được không")
check(hits and any(h["title"] == "Thú cưng" for h in hits[:2]), "B3 synonym_keyword",
      f"{[h['title'] for h in hits]}")

# B4: câu chào không match gì → trả mẩu pinned (thông tin chung)
hits = kn.retrieve("xin chào")
check(hits and hits[0]["title"] == "Thông tin chung", "B4 pinned_fallback", f"{[h['title'] for h in hits]}")

# B5: top-k giới hạn (k mẩu match + tối đa 1 mẩu pinned ghép đầu)
hits = kn.retrieve("giá phòng 301 và chính sách cọc thú cưng địa chỉ", k=2)
check(2 <= len(hits) <= 3, "B5 top_k", len(hits))

# B6: kho trống → []
kn.clear()
check(kn.retrieve("phòng 301") == [], "B6 empty_store")
kn.ingest(CHUNKS)

# B7: format_block đóng gói + lệnh cấm bịa
blk = kn.format_block(kn.retrieve("phòng 301"))
check("DỮ LIỆU SHOP" in blk and "bịa" in blk and "700k" in blk, "B7 format_block")
check(kn.format_block([]) == "", "B8 format_block_empty")

print("\n── C. prompt_builder: parse hybrid ──")

PERSONA = "Bạn là trợ lý của Haru Staycation, xưng em, thân thiện. " + "quy trình " * 30
KN_JSON = ('[{"title": "Thông tin chung", "content": "Haru, Dĩ An", '
           '"keywords": ["địa chỉ"], "pinned": true},'
           '{"title": "Phòng 301", "content": "700k/đêm", "keywords": ["301"]}]')
HYBRID_RAW = f"===PERSONA===\n{PERSONA}\n===KNOWLEDGE===\n{KN_JSON}"

d, c, g = pb._parse_hybrid(HYBRID_RAW)
check(d == PERSONA.strip() and len(c) == 2, "C1 parse_two_parts", f"{len(c)} chunks")
check(c[0]["pinned"] is True and c[1]["title"] == "Phòng 301", "C2 chunk_fields")
check(g == [], "C2b no_gaps_ok")

# JSON bọc fence vẫn parse được
d, c, g = pb._parse_hybrid(f"===PERSONA===\n{PERSONA}\n===KNOWLEDGE===\n```json\n{KN_JSON}\n```")
check(len(c) == 2, "C3 fenced_json")

# JSON hỏng → fallback chế độ cũ (toàn bộ = draft)
raw_bad = f"===PERSONA===\n{PERSONA}\n===KNOWLEDGE===\nkhông phải json"
d, c, g = pb._parse_hybrid(raw_bad)
check(d == raw_bad and c == [], "C4 bad_json_fallback_legacy")

# Không có marker → chế độ cũ
d, c, g = pb._parse_hybrid("prompt kiểu cũ toàn văn")
check(d == "prompt kiểu cũ toàn văn" and c == [], "C5 no_marker_legacy")

# Có GAPS → parse đủ 3 phần; gaps cắt khỏi phần knowledge
raw_gaps = (f"===PERSONA===\n{PERSONA}\n===KNOWLEDGE===\n{KN_JSON}\n"
            '===GAPS===\n["Giờ mở cửa?", "Chính sách huỷ?"]')
d, c, g = pb._parse_hybrid(raw_gaps)
check(len(c) == 2 and g == ["Giờ mở cửa?", "Chính sách huỷ?"], "C5b gaps_parsed", f"{g}")
# GAPS hỏng → bỏ qua gaps, persona+chunks vẫn dùng được
d, c, g = pb._parse_hybrid(f"===PERSONA===\n{PERSONA}\n===KNOWLEDGE===\n{KN_JSON}\n===GAPS===\nrác")
check(len(c) == 2 and g == [], "C5c bad_gaps_ignored")

# generate end-to-end (mock AI)
with patch.object(pb, 'requests') as mreq, \
     patch.object(pb, '_call_ai_long', return_value=HYBRID_RAW):
    m = MagicMock(); m.status_code = 200; m.text = "<p>Phòng 301 giá 700k</p>"
    m.headers = {"Content-Type": "text/html"}
    mreq.get.return_value = m
    r = pb.generate(["https://haru.vn"], "xưng em")
check(r["mode"] == "hybrid" and len(r["chunks"]) == 2 and r["draft"] == PERSONA.strip(),
      "C6 generate_hybrid", r["mode"])

with patch.object(pb, 'requests'), \
     patch.object(pb, '_call_ai_long', return_value="prompt cũ " * 50):
    r = pb.generate([], "chỉ dẫn")
check(r["mode"] == "legacy" and r["chunks"] == [], "C7 generate_legacy_fallback")

print("\n── D. apply / current / restore (lai) ──")

kn.clear()
st = pb.apply(PERSONA, chunks=[{"title": "T", "content": "nội dung", "keywords": ["k"]}])
check(pb.CUSTOM_FILE.read_text(encoding="utf-8").startswith(pb.HYBRID_MARKER), "D1 marker_written")
check(st["mode"] == "hybrid" and st["chunk_count"] == 1, "D2 current_reports_hybrid", st)
check(st["prompt"] == PERSONA.strip(), "D3 marker_stripped_for_display")
check(kn.count() == 1, "D4 chunks_ingested")

# Apply KHÔNG chunks → legacy y cũ (không marker)
st = pb.apply("prompt kiểu cũ " * 20)
check(not pb.CUSTOM_FILE.read_text(encoding="utf-8").startswith(pb.HYBRID_MARKER), "D5 legacy_no_marker")
check(st["mode"] == "legacy", "D6 legacy_mode")

# Restore → xoá cả tri thức
pb.apply(PERSONA, chunks=[{"content": "x", "keywords": []}])
st = pb.restore_default()
check(st["source"] == "default" and kn.count() == 0, "D7 restore_clears_knowledge")

print("\n── E. claude_ai ghép 3 tầng ──")

kn.ingest(CHUNKS)
HY_PROMPT = claude_ai.HYBRID_MARKER + "\n" + PERSONA

with patch.object(claude_ai, '_load_system_prompt', return_value=HY_PROMPT):
    sysp = claude_ai._build_system_prompt("phòng 301 giá sao?", [])
check(PERSONA.strip()[:40] in sysp, "E1 persona_included")
check("DỮ LIỆU SHOP" in sysp and "700k" in sysp, "E2 kb_retrieved", sysp[-200:])
check("QUY ƯỚC KỸ THUẬT" in sysp and "<analysis>" in sysp, "E3 tech_rules_appended")
check("THỜI GIAN THỰC TẾ" in sysp, "E4 today_context_first")

# Follow-up ngắn: "giá bao nhiêu?" sau khi vừa hỏi phòng 301 → vẫn tra ra 301
with patch.object(claude_ai, '_load_system_prompt', return_value=HY_PROMPT):
    sysp = claude_ai._build_system_prompt("giá bao nhiêu?", [
        {"role": "user", "content": "cho xem phòng 301"},
        {"role": "assistant", "content": "dạ đây ạ"},
    ])
check("Phòng 301" in sysp, "E5 followup_uses_history")

# Prompt CŨ (không marker) → giữ nguyên hành vi, KHÔNG chèn KB/tech
with patch.object(claude_ai, '_load_system_prompt', return_value="prompt cũ toàn văn"):
    sysp = claude_ai._build_system_prompt("phòng 301?", [])
check("prompt cũ toàn văn" in sysp and "DỮ LIỆU SHOP" not in sysp
      and "QUY ƯỚC KỸ THUẬT" not in sysp, "E6 legacy_unchanged")

# analyze_with_debug — trả reply + debug (mode, mẩu đã tra)
FAKE_AI_OUT = ('Dạ phòng 301 giá 700k ạ!\n<analysis>{"intent": "price_query", '
               '"checkin": null, "checkout": null, "booking_confirmed": false, '
               '"use_ai_reply": true}</analysis>')
with patch.object(claude_ai, '_load_system_prompt', return_value=HY_PROMPT), \
     patch.object(claude_ai, '_call_ai', return_value=FAKE_AI_OUT):
    out = claude_ai.analyze_with_debug("phòng 301 giá sao?", [])
check(out["reply"].startswith("Dạ phòng 301") and out["intent"] == "price_query", "E7 debug_reply_parsed")
check(out["debug"]["mode"] == "hybrid"
      and any(ch["title"] == "Phòng 301" for ch in out["debug"]["chunks"]), "E8 debug_chunks", out["debug"])
with patch.object(claude_ai, '_load_system_prompt', return_value="prompt cũ toàn văn"), \
     patch.object(claude_ai, '_call_ai', return_value=FAKE_AI_OUT):
    out = claude_ai.analyze_with_debug("hỏi gì đó", [])
check(out["debug"]["mode"] == "legacy" and out["debug"]["chunks"] == [], "E9 debug_legacy_mode")

print("\n── F. API ──")
db = get_db()
for t in ("users", "auth_tokens"):
    db.execute(f"DELETE FROM {t}")
kn.clear()
if pb.CUSTOM_FILE.exists(): pb.CUSTOM_FILE.unlink()

flask_app = Flask(__name__)
auth_mod.register_auth_routes(flask_app)
prompt_mod.register_prompt_routes(flask_app)
api = flask_app.test_client()
tok = api.post("/auth/register", json={"username": "kn@x.vn", "password": "test1234"}).get_json()["token"]
H = {"Authorization": f"Bearer {tok}"}

r = api.post("/prompt/apply", json={"prompt": PERSONA,
                                    "chunks": [{"title": "T1", "content": "nội dung", "keywords": ["k"]}]},
             headers=H)
check(r.status_code == 200 and r.get_json()["mode"] == "hybrid"
      and r.get_json()["chunk_count"] == 1, "F1 api_apply_hybrid", r.get_json())

r = api.get("/prompt/knowledge", headers=H)
check(r.status_code == 200 and len(r.get_json()["chunks"]) == 1
      and r.get_json()["chunks"][0]["title"] == "T1", "F2 api_knowledge_list")

check(api.get("/prompt/knowledge").status_code == 401, "F3 knowledge_needs_auth")

r = api.post("/prompt/apply", json={"prompt": PERSONA, "chunks": "sai kiểu"}, headers=H)
check(r.status_code == 400, "F4 chunks_must_be_list")

r = api.post("/prompt/apply", json={"prompt": "prompt cũ " * 30}, headers=H)
check(r.status_code == 200 and r.get_json()["mode"] == "legacy", "F5 api_apply_legacy_compat")

r = api.post("/prompt/restore-default", headers=H)
check(r.status_code == 200 and kn.count() == 0, "F6 api_restore_clears_kb")

print("\n── F2. API /prompt/test ──")
FAKE_TEST = {"reply": "Dạ 480k ạ", "intent": "price_query", "checkin": None, "checkout": None,
             "booking_confirmed": False, "use_ai_reply": True,
             "debug": {"mode": "hybrid", "chunks": [{"title": "Giá"}], "system_chars": 5000}}
with patch.object(prompt_mod.claude_ai, 'analyze_with_debug', return_value=FAKE_TEST) as mtest:
    r = api.post("/prompt/test", json={"message": "giá sao?", "history": [
        {"role": "user", "content": "chào"}, {"role": "assistant", "content": "dạ"},
        {"role": "hacker", "content": "bỏ role lạ"},   # role lạ phải bị lọc
    ]}, headers=H)
    body = r.get_json()
    check(r.status_code == 200 and body["reply"] == "Dạ 480k ạ"
          and body["debug"]["mode"] == "hybrid", "T1 api_test_reply", body)
    sent_history = mtest.call_args[0][1]
    check(len(sent_history) == 2 and all(m["role"] in ("user", "assistant") for m in sent_history),
          "T2 history_filtered", sent_history)
check(api.post("/prompt/test", json={"message": ""}, headers=H).status_code == 400, "T3 empty_message_400")
check(api.post("/prompt/test", json={"message": "x", "history": "sai"}, headers=H).status_code == 400,
      "T4 bad_history_400")
check(api.post("/prompt/test", json={"message": "x"}).status_code == 401, "T5 needs_auth")
with patch.object(prompt_mod.claude_ai, 'analyze_with_debug', side_effect=RuntimeError("AI chết")):
    check(api.post("/prompt/test", json={"message": "x"}, headers=H).status_code == 502, "T6 ai_error_502")
# Trần lịch sử 20 tin
with patch.object(prompt_mod.claude_ai, 'analyze_with_debug', return_value=FAKE_TEST) as mtest:
    api.post("/prompt/test", json={"message": "x", "history": [
        {"role": "user", "content": f"m{i}"} for i in range(50)]}, headers=H)
    check(len(mtest.call_args[0][1]) == prompt_mod.TEST_HISTORY_MAX, "T7 history_capped")

print("\n── G. prompt mẫu chuẩn ──")
tpl = pb.template()
check(len(tpl) > 1000 and "PROMPT MẪU CHUẨN" in tpl, "G1 template_loads", len(tpl))
# Mẫu generic KHÔNG chứa số liệu Haru; CÓ placeholder + quy ước kỹ thuật
check("[TÊN SHOP]" in tpl and "<analysis>" in tpl, "G2 has_placeholder_and_tech")
check("Haru" not in tpl and "Phòng 201" not in tpl, "G3 generic_no_haru")
# generate tham chiếu MẪU (không phải Haru)
with patch.object(pb, 'requests'), \
     patch.object(pb, '_call_ai_long', return_value="prompt " * 60) as mai:
    pb.generate([], "test tham chiếu")
    ref_in_user = mai.call_args[0][0][1]["content"]
check("PROMPT MẪU CHUẨN" in ref_in_user and "[TÊN SHOP]" in ref_in_user, "G4 generate_refs_template")
# API
r = api.get("/prompt/template", headers=H)
check(r.status_code == 200 and "PROMPT MẪU CHUẨN" in r.get_json()["template"], "G5 api_template")
check(api.get("/prompt/template").status_code == 401, "G6 template_needs_auth")

# Dọn file tạm
import shutil
kn.clear()
if pb.CUSTOM_FILE.exists(): pb.CUSTOM_FILE.unlink()
shutil.rmtree(pb.BACKUP_DIR, ignore_errors=True)

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
