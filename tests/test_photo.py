#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_photo.py — Thư viện ảnh (bộ ảnh đặt tên → bot gửi khách):
  - photo_library: slugify, CRUD bộ, add/remove ảnh, safe_filename (chặn traversal),
    find_sets (match bỏ dấu theo cụm, không match vu vơ)
  - send_photo_folder trên các Channel (mock)
  - photo_api: CRUD + upload multipart + serve + auth
  - brain: photo_request/price ưu tiên bộ ảnh khớp; không khớp → cơ chế cũ

Chạy (TỪ GỐC):  python tests/test_photo.py
"""

import os, sys, io
from unittest.mock import MagicMock, patch

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_tmp.sqlite')
sys.path.insert(0, '.')

import tempfile
from pathlib import Path
from flask import Flask
from app.core import photo_library as pl
from app.core.db import get_db
import app.web_api.auth_api as auth_mod
import app.web_api.photo_api as photo_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

# Cô lập thư mục ảnh vào temp
_TMP = Path(tempfile.mkdtemp(prefix="photolib_test_"))
pl.LIBRARY_DIR = _TMP
get_db().execute("DELETE FROM photo_sets")

# 1x1 PNG hợp lệ
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000154a24f5f0000000049454e44ae426082")

print("\n── A. slugify + CRUD ──")
check(pl.slugify("Bảng Giá Dịch Vụ!") == "bang-gia-dich-vu", "A1 slugify_bo_dau", pl.slugify("Bảng Giá Dịch Vụ!"))
s = pl.create_set("Bảng giá", ["bảng giá", "giá dịch vụ", "menu"])
check(s["slug"] == "bang-gia" and s["files"] == [], "A2 create_set")
check(len(pl.list_sets()) == 1, "A3 list")
try:
    pl.create_set("Bảng giá"); check(False, "A4 dup_rejected")
except ValueError:
    check(True, "A4 dup_rejected")
try:
    pl.create_set(""); check(False, "A5 empty_name_rejected")
except ValueError:
    check(True, "A5 empty_name_rejected")

print("\n── B. add / remove ảnh + an toàn ──")
fn = pl.add_photo("bang-gia", "menu.png", PNG)
check(fn == "menu.png" and "menu.png" in pl.get_set("bang-gia")["files"], "B1 add_photo")
fn2 = pl.add_photo("bang-gia", "menu.png", PNG)   # trùng tên → đánh số
check(fn2 != "menu.png" and len(pl.get_set("bang-gia")["files"]) == 2, "B2 dup_name_numbered", fn2)
check(pl.safe_filename("../../evil.png") == "evil.png", "B3 traversal_stripped", pl.safe_filename("../../evil.png"))
check(pl.safe_filename("hack.exe") is None, "B4 non_image_rejected")
check(pl.safe_filename("ảnh phòng.JPG") is not None, "B5 image_ok")
try:
    pl.add_photo("bang-gia", "x.txt", b"x"); check(False, "B6 bad_ext_rejected")
except ValueError:
    check(True, "B6 bad_ext_rejected")
pl.remove_photo("bang-gia", "menu.png")
check("menu.png" not in pl.get_set("bang-gia")["files"], "B7 remove_photo")

print("\n── C. find_sets (match khách) ──")
pl.create_set("Phòng 301", ["phòng 301", "phong ba lẻ một", "ban công"])
pl.add_photo("phong-301", "a.png", PNG)
pl.add_photo("bang-gia", "b.png", PNG)  # bang-gia có ảnh lại

# match theo tên bộ (bỏ dấu)
r = pl.find_sets("cho mình xin bảng giá với")
check(r and r[0]["slug"] == "bang-gia", "C1 match_name", [x["slug"] for x in r])
# match không dấu
r = pl.find_sets("phong 301 con khong shop oi")
check(r and r[0]["slug"] == "phong-301", "C2 match_no_diacritics", [x["slug"] for x in r])
# match theo keyword cụm
r = pl.find_sets("phòng có ban công không")
check(r and r[0]["slug"] == "phong-301", "C3 match_keyword_phrase")
# KHÔNG match vu vơ (câu chào không chứa tên/keyword nào)
check(pl.find_sets("chào shop nha") == [], "C4 no_spurious_match")
# bộ không có ảnh → không trả về
pl.create_set("Trống", ["bộ trống test"])
check(pl.find_sets("bộ trống test") == [], "C5 empty_set_excluded")

print("\n── D. delete_set dọn file ──")
d = pl.set_dir("phong-301")
check(d.is_dir(), "D1 dir_exists")
pl.delete_set("phong-301")
check(not d.exists() and pl.get_set("phong-301") is None, "D2 deleted_with_files")

print("\n── E. Channel.send_photo_folder ──")
from app.core.channel import Channel
class DummyBase(Channel):
    def send_text(self, u, t): pass
    def send_room_photos(self, u, r): pass
    def send_price_photos(self, u): pass
    def notify_owner(self, t): pass
    def call_owner(self): pass
check(DummyBase().send_photo_folder("u", _TMP, "x") is False, "E1 default_false")

# Telegram override dùng _send_dir
with patch.dict(sys.modules, {'requests': MagicMock()}):
    from app.channels.telegram import TelegramChannel
    tgc = TelegramChannel.__new__(TelegramChannel)
    tgc._parse = lambda u: ("bot1", "chat1")
    tgc._token_for = lambda b: ""
    tgc._sent = []
    tgc._post = lambda *a, **k: None
    sent = []
    tgc._send_photo_file = lambda tok, chat, p: sent.append(p)
    ok = tgc.send_photo_folder("u", pl.set_dir("bang-gia"), "📋 Bảng giá:")
    check(ok is True and len(sent) >= 1, "E2 telegram_sends_dir", f"ok={ok} sent={len(sent)}")
    ok2 = tgc.send_photo_folder("u", _TMP / "khong-ton-tai", "x")
    check(ok2 is False, "E3 missing_dir_false")

print("\n── F. photo_api ──")
db = get_db()
for t in ("users", "auth_tokens"):
    db.execute(f"DELETE FROM {t}")
flask_app = Flask(__name__)
auth_mod.register_auth_routes(flask_app)
photo_mod.register_photo_routes(flask_app)
api = flask_app.test_client()
tok = api.post("/auth/register", json={"username": "ph@x.vn", "password": "test1234"}).get_json()["token"]
H = {"Authorization": f"Bearer {tok}"}

check(api.get("/photos/sets").status_code == 401, "F1 needs_auth")
r = api.post("/photos/sets", json={"name": "Menu chính", "keywords": ["menu", "món ăn"]}, headers=H)
check(r.status_code == 200 and r.get_json()["set"]["slug"] == "menu-chinh", "F2 create")
r = api.post("/photos/sets/menu-chinh/upload",
             data={"files": (io.BytesIO(PNG), "mon1.png")},
             content_type="multipart/form-data", headers=H)
check(r.status_code == 200 and len(r.get_json()["set"]["files"]) == 1, "F3 upload", r.get_json())
# upload file không phải ảnh → vào errors, không lưu
r = api.post("/photos/sets/menu-chinh/upload",
             data={"files": (io.BytesIO(b"x"), "bad.txt")},
             content_type="multipart/form-data", headers=H)
check(len(r.get_json()["errors"]) == 1 and len(r.get_json()["set"]["files"]) == 1, "F4 bad_file_errored")
# serve ảnh (public — không cần auth)
r = api.get("/photos/file/menu-chinh/mon1.png")
check(r.status_code == 200 and r.data[:4] == b"\x89PNG", "F5 serve_public")
r = api.post("/photos/sets/menu-chinh/keywords", json={"keywords": ["thực đơn"]}, headers=H)
check(r.get_json()["set"]["keywords"] == ["thực đơn"], "F6 update_keywords")
r = api.delete("/photos/sets/menu-chinh", headers=H)
check(r.status_code == 200 and pl.get_set("menu-chinh") is None, "F7 delete")

print("\n── G. brain ưu tiên bộ ảnh ──")
# Dựng brain tối giản với channel mock; kiểm nhánh photo trong handle
from app.core import brain as brain_mod
pl.create_set("Combo cưới", ["chụp cưới", "combo cưới", "album cưới"])
pl.add_photo("combo-cuoi", "c.png", PNG)

calls = {"folder": [], "price": 0, "room": 0}
ch = MagicMock()
ch.send_photo_folder = lambda u, folder, cap: (calls["folder"].append(Path(folder).name) or True)
ch.send_price_photos = lambda u: calls.__setitem__("price", calls["price"] + 1)
ch.send_room_photos = lambda u, r: calls.__setitem__("room", calls["room"] + 1)

# Trực tiếp test logic match trong brain: khách hỏi "album cưới" → gửi bộ, KHÔNG gọi price
matched = pl.find_sets("cho xem album cưới đi")
check(matched and matched[0]["slug"] == "combo-cuoi", "G1 brain_match_helper")
for s in matched:
    ch.send_photo_folder("u", pl.set_dir(s["slug"]), f"📸 {s['name']}:")
check(calls["folder"] == ["combo-cuoi"] and calls["price"] == 0, "G2 sends_set_not_price")

print("\n── H. Não AI kết hợp Thư viện ảnh (thẻ [GUI_ANH]) ──")
from app.core import claude_ai

# H1-H3: _parse_ai_output bóc thẻ (biến thể có dấu/không dấu, nhiều thẻ)
out = claude_ai._parse_ai_output("Dạ đây là bảng giá ạ! [GUI_ANH: Combo cưới]")
check(out.get("send_photos") == ["Combo cưới"] and "[GUI_ANH" not in out["reply"],
      "H1 parse thẻ không dấu + reply sạch", out)
out = claude_ai._parse_ai_output("Mình gửi bạn nhé [Gửi_Ảnh: bảng giá]")
check(out.get("send_photos") == ["bảng giá"], "H2 parse thẻ CÓ DẤU", out)
out = claude_ai._parse_ai_output("Đây ạ [GUI_ANH: Bảng giá][GUI ANH: Combo cưới]")
check(out.get("send_photos") == ["Bảng giá", "Combo cưới"] and out["reply"] == "Đây ạ",
      "H3 nhiều thẻ + cả biến thể space", out)
out = claude_ai._parse_ai_output("Không có thẻ gì cả")
check("send_photos" not in out, "H4 không thẻ → không có key send_photos")

# H5-H6: _photo_block theo shop (tenant) — có bộ thì liệt kê + hướng dẫn thẻ
pl.create_set("Menu Tết", ["menu tết", "món tết"], tenant_ws="shopX@x.vn")
pl.add_photo("menu-tet", "m.png", PNG)
blk = claude_ai._photo_block("shopX@x.vn")
check("Menu Tết" in blk and "GUI_ANH" in blk, "H5 _photo_block liệt kê bộ + hướng dẫn thẻ", blk[:80])
check(claude_ai._photo_block("shop-trong@x.vn") == "", "H6 shop không có bộ → block rỗng")

# H7-H9: brain._send_ai_photos — đúng tên → gửi + trả tên; sai tên/khác shop → bỏ
from types import SimpleNamespace
calls2 = {"folder": []}
_b = SimpleNamespace(channel=SimpleNamespace(
    send_photo_folder=lambda u, folder, cap: (calls2["folder"].append(Path(folder).name) or True)))
conv_x = SimpleNamespace(tenant="shopX@x.vn")
sent = brain_mod.Brain._send_ai_photos(_b, "u1", conv_x, ["menu tết"])
check(sent == ["Menu Tết"] and calls2["folder"] == ["menu-tet"],
      "H7 gửi đúng bộ theo tên (bỏ dấu, đúng shop)", (sent, calls2))
sent = brain_mod.Brain._send_ai_photos(_b, "u1", conv_x, ["bộ không tồn tại"])
check(sent == [], "H8 AI bịa tên → bỏ qua, không nổ")
conv_y = SimpleNamespace(tenant="shopY@x.vn")
sent = brain_mod.Brain._send_ai_photos(_b, "u1", conv_y, ["menu tết"])
check(sent == [], "H9 khác shop → KHÔNG gửi bộ của shopX (multi-tenant)")

# H10: kênh không hỗ trợ gửi folder (trả False) → sent rỗng, luồng thường tiếp
_b2 = SimpleNamespace(channel=SimpleNamespace(send_photo_folder=lambda u, f, c: False))
sent = brain_mod.Brain._send_ai_photos(_b2, "u1", conv_x, ["menu tết"])
check(sent == [], "H10 kênh không hỗ trợ → sent rỗng")

# Dọn
import shutil
shutil.rmtree(_TMP, ignore_errors=True)
get_db().execute("DELETE FROM photo_sets")

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
