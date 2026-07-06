#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_retrieval.py — nâng cấp RAG retrieval (IDF weighting + teencode expansion):
  A. Teencode/viết tắt: "co ship k", "bn tien", "ib e" khớp đúng mẩu
  B. IDF: token ĐẶC TRƯNG (số phòng '301', tên riêng) thắng token phổ biến
     ('phong','gia' có ở mọi mẩu) → không còn nhiễu "mẩu nào cũng khớp"
  C. Không dấu vẫn khớp; follow-up ghép ngữ cảnh; pinned fallback giữ nguyên

Chạy (TỪ GỐC):  python tests/test_retrieval.py
"""

import os, sys
from unittest.mock import MagicMock

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(), 'requests': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ['HOMESTAY_DB_PATH'] = 'test_db_retrieval_tmp.sqlite'
sys.path.insert(0, '.')

from app.core import knowledge as kb

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

SHOP = "retr-test"
kb.clear(SHOP)
kb.ingest([
    {"title": "Thông tin chung", "content": "Homestay Nắng, 12 Lê Lợi, mở 24/7.",
     "keywords": ["dia chi", "o dau", "gio mo cua"], "pinned": True},
    {"title": "Phòng 301", "content": "Phòng 301 giá 500k mỗi đêm, 2 người, view biển.",
     "keywords": ["phong 301", "gia phong 301", "301 bao nhieu"]},
    {"title": "Phòng 201", "content": "Phòng 201 giá 350k mỗi đêm, 2 người, view vườn.",
     "keywords": ["phong 201", "gia phong 201", "201 bao nhieu"]},
    {"title": "Giao hàng", "content": "Có ship toàn quốc, phí 30k, freeship đơn trên 500k.",
     "keywords": ["ship", "giao hang", "phi ship", "co ship khong"]},
    {"title": "Thanh toán", "content": "Nhận chuyển khoản, số tài khoản MB 0123 chủ Nguyen Van A.",
     "keywords": ["chuyen khoan", "so tai khoan", "thanh toan"]},
], SHOP)

def titles(hits): return [h["title"] for h in hits]

print("\n── A. Teencode / viết tắt ──")
# "co ship k" — 'k' phải nở thành 'khong' → khớp keyword "co ship khong"
h = kb.retrieve("co ship k shop", SHOP)
check(h and h[0]["title"] == "Giao hàng", "A1 ship_teencode", titles(h))
# "bn tien" — 'bn' → 'bao nhieu'
h = kb.retrieve("phong 301 bn tien", SHOP)
check(h and h[0]["title"] == "Phòng 301", "A2 bn_expansion", titles(h))
# "stk" → "so tai khoan"
h = kb.retrieve("cho xin stk vs", SHOP)
check(h and h[0]["title"] == "Thanh toán", "A3 stk_expansion", titles(h))

print("\n── B. IDF: token đặc trưng thắng token phổ biến ──")
# 'gia' và 'phong' có ở NHIỀU mẩu (phổ biến, IDF thấp); '301' hiếm (IDF cao)
# → hỏi "gia phong 301" phải ra 301 chứ không phải 201
h = kb.retrieve("gia phong 301 the nao", SHOP)
check(h and h[0]["title"] == "Phòng 301", "B1 distinctive_301_wins", titles(h))
h = kb.retrieve("phong 201 gia bao nhieu", SHOP)
check(h and h[0]["title"] == "Phòng 201", "B2 distinctive_201_wins", titles(h))
# chỉ số phòng trần
h = kb.retrieve("301", SHOP)
check(h and h[0]["title"] == "Phòng 301", "B3 bare_number", titles(h))
# câu chỉ toàn từ phổ biến "gia phong" (không số) → không crash, trả có thứ tự ổn định
h = kb.retrieve("gia phong", SHOP)
check(isinstance(h, list) and len(h) > 0, "B4 common_only_no_crash", titles(h))

print("\n── C. Không dấu + follow-up + pinned ──")
# không dấu
h = kb.retrieve("dia chi o dau", SHOP)
check(h and h[0]["title"] == "Thông tin chung", "C1 no_accent", titles(h))
# follow-up: câu hiện tại mơ hồ "bao nhieu 1 dem" + tin trước "phong 301"
h = kb.retrieve("phong 301\nbao nhieu 1 dem", SHOP)
check(h and h[0]["title"] == "Phòng 301", "C2 followup_context", titles(h))
# câu vu vơ không khớp gì → mẩu pinned
h = kb.retrieve("hello xin chao", SHOP)
check(h and h[0]["pinned"], "C3 no_match_pinned", titles(h))
# kho trống → []
kb.clear("shop-trong-rong")
check(kb.retrieve("gi do", "shop-trong-rong") == [], "C4 empty_corpus")

print("\n── D. context_chunks: kho nhỏ nhồi hết / kho lớn retrieve ──")
# Kho nhỏ (5 mẩu, tổng content ~vài trăm ký tự) → mode 'full', trả HẾT
ch, mode = kb.context_chunks("gia phong 301", SHOP)
check(mode == "full" and len(ch) == 5, "D1 small_kb_full", f"mode={mode} n={len(ch)}")
check(ch[0]["pinned"], "D2 pinned_first")   # pinned lên đầu
# Kho lớn (vượt ngưỡng) → mode 'retrieval', chỉ top-k
big = [{"title": f"Mẩu {i}", "content": "x" * 500 + f" so {i}",
        "keywords": [f"so {i}"]} for i in range(40)]
kb.ingest(big, "big-shop")
ch, mode = kb.context_chunks("so 7", "big-shop")
check(mode == "retrieval" and len(ch) <= 4, "D3 big_kb_retrieval", f"mode={mode} n={len(ch)}")
check(any("so 7" in c["content"] for c in ch), "D4 big_kb_finds_right", [c["title"] for c in ch])
kb.clear("big-shop")

kb.clear(SHOP)
print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
