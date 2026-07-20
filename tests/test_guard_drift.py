#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_guard_drift.py — CHẶN DRIFT BẢO MẬT khi thêm/sửa kênh (kiểm tra TĨNH source):

Bài học: guard sở hữu từng CHỈ có ở telegram_api, 5 kênh copy còn lại bị bỏ quên
→ IDOR xoá/tắt kênh chéo shop. Test này quét MỌI file app/web_api/*.py:
  A. Route quản trị account NGUY HIỂM (DELETE trên .../<id>, .../toggle,
     /set-owner) phải gọi own_account_or_404 (hoặc _own_bot_or_404 của telegram)
     trong thân handler.
  B. Route LIỆT KÊ account (/accounts, /shops, /sites, /pages, /bots) phải lọc
     theo chủ (filter_owned hoặc list_bots(owner=...)).
  C. channel_registry phủ đủ mọi kênh + store nào cũng có get_owner_username.

Kênh thứ 9 copy scaffold thiếu guard → test này ĐỎ ngay trong CI.
Chạy TỪ GỐC: python tests/test_guard_drift.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, '.')

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

WEB_API = Path("app/web_api")

# route path chứa các đoạn này = route quản trị ACCOUNT KÊNH (không phải hội thoại)
ACCOUNT_SEGMENTS = ("/accounts", "/shops", "/sites", "/pages", "/bots")
# _platform_admin_or_403: route quản trị NỀN TẢNG (admin thấy hết là chủ đích)
GUARD_TOKENS = ("own_account_or_404", "_own_bot_or_404", "_platform_admin_or_403")
LIST_TOKENS = ("filter_owned", "owner=None if _is_admin else", "owner=",
               "_platform_admin_or_403")

# Route được MIỄN có chủ đích (public/nghiệp vụ khác) — thêm vào đây phải có lý do.
EXEMPT = {
    # (file, route_path, methods) — hiện không có miễn trừ nào
}


def route_blocks(src: str):
    """Cắt source thành các block (route_path, methods, body) theo @app.route."""
    out = []
    pat = re.compile(r'@app\.route\(\s*"([^"]+)"(?:\s*,\s*methods=\[([^\]]*)\])?\s*\)')
    matches = list(pat.finditer(src))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(src), m.end() + 4000)
        body = src[m.end():end]
        methods = (m.group(2) or '"GET"').replace('"', "").replace("'", "")
        out.append((m.group(1), [x.strip().upper() for x in methods.split(",")], body))
    return out


print("\n── A+B. Quét guard mọi file web_api ──")
n_dangerous = n_lists = 0
for f in sorted(WEB_API.glob("*.py")):
    src = f.read_text(encoding="utf-8")
    for path, methods, body in route_blocks(src):
        is_account = any(seg in path for seg in ACCOUNT_SEGMENTS)
        if not is_account:
            continue
        if (f.name, path, tuple(methods)) in EXEMPT:
            continue
        # A. Nguy hiểm: DELETE .../<id>, POST .../toggle, POST /set-owner
        dangerous = ("DELETE" in methods and "<" in path) or path.endswith("/toggle")
        if dangerous:
            n_dangerous += 1
            check(any(t in body for t in GUARD_TOKENS),
                  f"A {f.name} {methods} {path} có guard sở hữu",
                  "thiếu own_account_or_404")
        # B. Liệt kê: GET đúng path account (không tham số con)
        if "GET" in methods and path.rstrip("/").endswith(ACCOUNT_SEGMENTS):
            n_lists += 1
            check(any(t in body for t in LIST_TOKENS),
                  f"B {f.name} GET {path} lọc theo chủ", "thiếu filter_owned/owner=")

# set-owner nằm ngoài ACCOUNT_SEGMENTS (path /xx/set-owner) — quét riêng
for f in sorted(WEB_API.glob("*.py")):
    src = f.read_text(encoding="utf-8")
    for path, methods, body in route_blocks(src):
        if path.endswith("/set-owner"):
            n_dangerous += 1
            check(any(t in body for t in GUARD_TOKENS) or "telegram_owner.set_owner" in body,
                  f"A {f.name} {path} có guard sở hữu", "thiếu own_account_or_404")

check(n_dangerous >= 12, f"A* quét được đủ route nguy hiểm ({n_dangerous})", n_dangerous)
check(n_lists >= 5, f"B* quét được đủ route liệt kê ({n_lists})", n_lists)

print("\n── C. Registry phủ đủ kênh + hợp đồng store ──")
from unittest.mock import MagicMock
sys.modules.update({
    'gspread': MagicMock(), 'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(), 'dotenv': MagicMock(),
})
import os
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_drift_tmp.sqlite')

from app.core import channel_registry as reg
from app.web_api.bridge import ALL_CHANNELS

check(set(reg.ALL_KEYS) == set(ALL_CHANNELS),
      "C1 registry khớp ALL_CHANNELS của bridge", (reg.ALL_KEYS, ALL_CHANNELS))
for key in reg.ALL_KEYS:
    st = reg.store_for(key)
    check(st is not None and hasattr(st, "get_owner_username"),
          f"C2 store '{key}' có get_owner_username")
check(reg.owner_of("telegram:bot-la") is None, "C3 owner_of account lạ → None")
check(reg.store_for("kenh-la") is None, "C4 kênh lạ → None (không nổ)")

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
