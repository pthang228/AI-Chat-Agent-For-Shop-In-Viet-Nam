#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_style_rag.py — Style RAG (kho mẫu hội thoại) + tóm tắt cuộn hội thoại:
  A. knowledge: tách kho fact/style, ingest không quét chéo, retrieve_style + intent bonus
  B. claude_ai._compose_system: block style/trạng thái/tóm tắt + thứ tự cache (today CUỐI)
  C. tóm tắt cuộn: trigger, history_for_ai, persist summary
  D. knowledge_learn: phân loại fact/style, extract_style (⭐), generate_style_set (NDJSON cắt cụt)

Chạy (TỪ GỐC):  python tests/test_style_rag.py
"""

import os, sys, time
from unittest.mock import MagicMock, patch

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
# DB test riêng — XOÁ trước khi dùng (DB tồn đọng từ lần chạy trước gây fail giả)
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
_DB = str(_TMPDIR / 'test_db_style_tmp.sqlite')
for _f in (_DB, _DB + '-shm', _DB + '-wal'):
    try: os.remove(_f)
    except OSError: pass
os.environ['HOMESTAY_DB_PATH'] = _DB
sys.path.insert(0, '.')

from app.core import knowledge
from app.core import knowledge_learn
from app.core import claude_ai
from app.core.conversation import ConversationState

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

SHOP = "styletest"

# ═══ A. Kho fact/style tách bạch ═══════════════════════════════════
print("\n── A. knowledge: kho fact/style ──")

knowledge.ingest([
    {"title": "Giá phòng 301", "content": "Phòng 301 giá 550k/đêm",
     "keywords": ["gia phong 301", "bao nhieu tien"]},
], shop=SHOP)
knowledge.add_chunks([
    {"title": "Khách chê đắt", "content": "Khách: sao mắc vậy\nShop: dạ [giá phòng] là giá chuẩn rồi ạ 😊",
     "keywords": ["mac vay", "dat qua", "che dat"], "intent": "bargain"},
    {"title": "Khách phân vân", "content": "Khách: để em suy nghĩ\nShop: dạ mình cứ thong thả ạ",
     "keywords": ["suy nghi", "phan van"], "intent": ""},
], shop=SHOP, kind=knowledge.KIND_STYLE)

check(knowledge.count(SHOP, kind="fact") == 1, "A1 count_fact")
check(knowledge.count(SHOP, kind="style") == 2, "A2 count_style")
check(len(knowledge.list_chunks(SHOP)) == 3, "A3 list_all_gồm_cả_2_loại")

# ingest fact lần 2 KHÔNG được quét kho style
knowledge.ingest([{"title": "Giá mới", "content": "Phòng 301 giá 600k", "keywords": ["gia"]}], shop=SHOP)
check(knowledge.count(SHOP, kind="style") == 2, "A4 ingest_fact_không_xoá_style")
check(knowledge.count(SHOP, kind="fact") == 1, "A5 ingest_fact_thay_fact")

# retrieve (fact) không dính mẩu style
hits = knowledge.retrieve("phòng 301 giá bao nhiêu", shop=SHOP)
check(all(h["kind"] == "fact" for h in hits), "A6 retrieve_chỉ_fact",
      f"kinds={[h['kind'] for h in hits]}")

# retrieve_style: keyword match
sh = knowledge.retrieve_style("sao mắc vậy shop", shop=SHOP)
check(sh and sh[0]["title"] == "Khách chê đắt", "A7 style_keyword_match",
      f"got={[c['title'] for c in sh]}")
# intent bonus: câu mơ hồ + intent bargain → mẩu bargain thắng
sh2 = knowledge.retrieve_style("ừm", shop=SHOP, intent="bargain")
check((not sh2) or sh2[0].get("intent") == "bargain", "A8 style_intent_bonus",
      f"got={[(c['title'], c.get('intent')) for c in sh2]}")
# không khớp gì → [] (không nhét bừa)
check(knowledge.retrieve_style("xyzabc123", shop=SHOP) == [], "A9 style_no_match_rỗng")

blk = knowledge.format_style_block(sh)
check("VÍ DỤ CÁCH TƯ VẤN" in blk and "KHÔNG lấy giá" in blk and "[giá phòng]" in blk,
      "A10 style_block_có_rào_chắn")

sid = knowledge.list_chunks(SHOP, kind="style")[0]["id"]
check(knowledge.delete_chunk(sid, shop=SHOP), "A11 delete_chunk")
check(knowledge.count(SHOP, kind="style") == 1, "A12 delete_đúng_1_mẩu")
knowledge.add_chunks([{"title": "Khách chê đắt", "content": "Khách: sao mắc vậy\nShop: dạ [giá phòng] chuẩn ạ",
                       "keywords": ["mac vay", "dat qua"], "intent": "bargain"}],
                     shop=SHOP, kind=knowledge.KIND_STYLE)

# ═══ B. _compose_system: block + thứ tự cache ══════════════════════
print("\n── B. _compose_system ──")

PERSONA = claude_ai.HYBRID_MARKER + "\nBạn là trợ lý shop Styletest."

with patch.object(claude_ai, "_load_system_prompt", return_value=PERSONA), \
     patch.object(claude_ai, "_resolve_shop", return_value=SHOP), \
     patch.object(claude_ai, "_memory_block", return_value="TRÍ NHỚ: khách quen"):
    system, dbg = claude_ai._compose_system(
        "sao mắc vậy", [], user_id="u1", account="meta",
        conv_state={"stage": "offering", "checkin": "20/07/2026",
                    "summary": "- Khách hỏi phòng 301, đã báo giá",
                    "intent": "bargain"})

check(dbg["mode"] == "hybrid", "B1 hybrid_mode")
check(dbg.get("style_chunks"), "B2 style_chunks_trong_debug", f"dbg={dbg.get('style_chunks')}")
check("VÍ DỤ CÁCH TƯ VẤN" in system, "B3 style_block_trong_system")
check("TRẠNG THÁI TƯ VẤN" in system and "20/07/2026" in system, "B4 state_block")
check("TÓM TẮT HỘI THOẠI TRƯỚC" in system and "phòng 301" in system, "B5 summary_block")
# Thứ tự cache: persona ĐẦU, _today_context CUỐI (đổi từng phút không phá prefix)
check(system.startswith("Bạn là trợ lý shop Styletest"), "B6 persona_đứng_đầu",
      f"head={system[:60]!r}")
check(system.rstrip().endswith("=" * 50) or "THỜI GIAN THỰC TẾ" in system[-1500:],
      "B7 today_context_cuối", f"tail={system[-80:]!r}")
i_today = system.find("THỜI GIAN THỰC TẾ")
check(i_today > system.find("VÍ DỤ CÁCH TƯ VẤN") > -1
      and i_today > system.find("TÓM TẮT HỘI THOẠI TRƯỚC") > -1,
      "B8 today_sau_mọi_block")

# legacy: không marker → base đầu, today cuối
with patch.object(claude_ai, "_load_system_prompt", return_value="Prompt cũ thường."), \
     patch.object(claude_ai, "_resolve_shop", return_value=SHOP), \
     patch.object(claude_ai, "_memory_block", return_value=""):
    system2, dbg2 = claude_ai._compose_system("hi", [], conv_state={"summary": "- tóm tắt cũ"})
check(dbg2["mode"] == "legacy" and system2.startswith("Prompt cũ thường."), "B9 legacy_base_đầu")
check(system2.find("THỜI GIAN THỰC TẾ") > system2.find("TÓM TẮT HỘI THOẠI TRƯỚC") > -1,
      "B10 legacy_summary+today_cuối")

# ═══ C. Tóm tắt cuộn ═══════════════════════════════════════════════
print("\n── C. Tóm tắt cuộn ──")

# C1: history_for_ai bỏ tin đã tóm
cs = ConversationState(user_id="u1")
for i in range(30):
    cs.add_user_message(f"tin {i}")
cs.summary = "- đã tóm 18 tin đầu"
cs.summary_upto = 18
h = cs.history_for_ai(20)
check(len(h) == 12 and h[0]["content"] == "tin 18", "C1 history_bỏ_tin_đã_tóm",
      f"len={len(h)} first={h[0]['content'] if h else None}")
cs2 = ConversationState(user_id="u2")
for i in range(5):
    cs2.add_user_message(f"m{i}")
check(len(cs2.history_for_ai(20)) == 5, "C2 chưa_tóm_giữ_nguyên")

# C3: Brain._maybe_summarize trigger + persist
from app.core.brain import Brain

class _FakeConvMgr:
    _account = "meta"
    def __init__(self, conv): self._conv = conv; self.saved = 0
    def get(self, uid): return self._conv
    def save(self): self.saved += 1

conv = ConversationState(user_id="fb:P:U")
for i in range(30):
    (conv.add_user_message if i % 2 == 0 else conv.add_assistant_message)(f"tin số {i}")

mgr = _FakeConvMgr(conv)
brain = Brain(channel=MagicMock(), conv_manager=mgr)

with patch.object(claude_ai, "summarize_history",
                  return_value="- khách hỏi phòng, đã báo giá") as msum:
    brain._maybe_summarize("fb:P:U")
    for _ in range(50):          # thread nền → chờ tối đa 5s
        if conv.summary: break
        time.sleep(0.1)

check(conv.summary == "- khách hỏi phòng, đã báo giá", "C3 summary_được_ghi",
      f"summary={conv.summary!r}")
check(conv.summary_upto == 30 - Brain.SUMMARY_KEEP, "C4 summary_upto_đúng_cửa_sổ",
      f"upto={conv.summary_upto}")
check(mgr.saved >= 1, "C5 đã_persist")
check(msum.call_count == 1, "C6 gọi_AI_đúng_1_lần")

# C7: chưa đủ ngưỡng → không tóm
conv2 = ConversationState(user_id="u3")
for i in range(10):
    conv2.add_user_message(f"t{i}")
mgr2 = _FakeConvMgr(conv2)
b2 = Brain(channel=MagicMock(), conv_manager=mgr2)
with patch.object(claude_ai, "summarize_history") as msum2:
    b2._maybe_summarize("u3")
    time.sleep(0.3)
check(msum2.call_count == 0 and conv2.summary == "", "C7 dưới_ngưỡng_không_tóm")

# C8: summarize_history lỗi AI → trả tóm tắt cũ, không ném
with patch.object(claude_ai, "_call_ai", side_effect=RuntimeError("boom")):
    out = claude_ai.summarize_history("- cũ", [{"role": "user", "content": "hi"}])
check(out == "- cũ", "C8 lỗi_AI_giữ_tóm_tắt_cũ")

# ═══ D. knowledge_learn: phân loại + ⭐ + NDJSON ═══════════════════
print("\n── D. knowledge_learn ──")

_MSGS = [{"role": "user", "content": "sao bên mình mắc hơn chỗ khác vậy shop"},
         {"role": "assistant", "content": "dạ bên em phòng mới, có hồ bơi riêng á chị"}]

# D1: AI trả kind=style → suggestion style + approve vào đúng kho
with patch.object(claude_ai, "_call_ai", return_value=(
        '{"kind": "style", "title": "Khách so giá nơi khác",'
        '"content": "Khách: sao mắc hơn chỗ khác\\nShop: dạ bên em [điểm mạnh] á chị",'
        '"keywords": ["mac hon cho khac", "so gia"], "intent": "bargain"}')):
    sug = knowledge_learn.suggest_from_reply(
        "u9", "meta", _MSGS, "dạ bên em phòng mới, có hồ bơi riêng á chị", shop=SHOP)
check(sug and sug["kind"] == "style" and sug["intent"] == "bargain",
      "D1 suggest_phân_loại_style", f"sug={sug and {k: sug[k] for k in ('kind','intent')}}")

n_style_before = knowledge.count(SHOP, kind="style")
approved = knowledge_learn.approve(sug["id"])
check(knowledge.count(SHOP, kind="style") == n_style_before + 1
      and knowledge.count(SHOP, kind="fact") == 1,
      "D2 approve_vào_kho_style")
newest = knowledge.list_chunks(SHOP, kind="style")[-1]
check(newest["intent"] == "bargain", "D3 approve_giữ_intent")

# D4: kind=fact (mặc định) vẫn như cũ
with patch.object(claude_ai, "_call_ai", return_value=(
        '{"kind": "fact", "title": "Giờ nhận phòng", "content": "Nhận phòng từ 14h",'
        '"keywords": ["may gio nhan phong"]}')):
    sug2 = knowledge_learn.suggest_from_reply(
        "u10", "meta", [{"role": "user", "content": "mấy giờ nhận phòng vậy shop"}],
        "dạ 14h chiều mình nhận phòng được nha", shop=SHOP)
check(sug2 and sug2["kind"] == "fact", "D4 suggest_fact_như_cũ")

# D5: ⭐ extract_style_from_messages lưu thẳng kho style
with patch.object(claude_ai, "_call_ai", return_value=(
        '{"title": "Khách giục trả lời", "content": "Khách: shop ơi\\nShop: dạ em đây ạ",'
        '"keywords": ["shop oi", "co ai khong"], "intent": ""}')):
    ck = knowledge_learn.extract_style_from_messages(
        [{"role": "user", "content": "shop ơi có ai không, rep em với"},
         {"role": "assistant", "content": "dạ em đây ạ, chị cần gì em tư vấn liền nè"}],
        shop=SHOP)
check(ck and ck["kind"] == "style"
      and any(c["title"] == "Khách giục trả lời" for c in knowledge.list_chunks(SHOP, kind="style")),
      "D5 extract_style_lưu_thẳng")

# D6: AI bảo skip → None, không lưu
with patch.object(claude_ai, "_call_ai", return_value='{"skip": true}'):
    ck2 = knowledge_learn.extract_style_from_messages(
        [{"role": "user", "content": "ok cảm ơn shop nhiều nha hẹn gặp lại"}], shop=SHOP)
check(ck2 is None, "D6 extract_skip")

# D7: generate_style_set — NDJSON có dòng cuối BỊ CẮT CỤT → chỉ mất dòng đó
_NDJSON = (
    '{"title": "Khách chê đắt", "content": "Khách: mắc quá\\nShop: dạ [giá] chuẩn ạ", "keywords": ["mac qua"], "intent": "bargain"}\n'
    '{"title": "Khách hỏi đường", "content": "Khách: chỗ mình ở đâu\\nShop: dạ [địa chỉ] ạ", "keywords": ["o dau"], "intent": ""}\n'
    '{"title": "Dòng bị cắt cụt", "content": "Khách: aaa'   # ← thiếu ngoặc đóng
)
with patch("app.core.prompt_builder._call_ai_long", return_value=_NDJSON):
    out = knowledge_learn.generate_style_set("transcript dài dài đây nè hehe", shop=SHOP)
check(len(out) == 2 and out[0]["title"] == "Khách chê đắt", "D7 ndjson_vớt_dòng_lành",
      f"n={len(out)}")
check(all(c["kind"] == "style" for c in out), "D8 ndjson_gắn_kind_style")

# D9: nguồn quá ngắn → ValueError
try:
    knowledge_learn.generate_style_set("ngắn", shop=SHOP)
    check(False, "D9 nguồn_ngắn_phải_raise")
except ValueError:
    check(True, "D9 nguồn_ngắn_phải_raise")

# ═══ Kết quả ═══════════════════════════════════════════════════════
print("\n" + "=" * 40)
print(f"  KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
