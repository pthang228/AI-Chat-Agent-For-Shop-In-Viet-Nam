#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_secretbox.py — tầng mã hoá at-rest (secretbox) + fail-closed production:
  A. Có khoá: roundtrip encrypt/decrypt, tiền tố enc:v1:, encrypt idempotent
  B. Không khoá: degrade (encrypt trả nguyên văn), decrypt dữ liệu mã hoá → ''
  C. Sai khoá: decrypt → '' (không nổ, không lộ)
  D. serve._check_production_secrets: public + thiếu khoá → TỪ CHỐI khởi động;
     có khoá / không public / ALLOW_PLAINTEXT_SECRETS=1 → cho chạy
  E. SQLiteChannelStore secret_fields: token nằm MÃ HOÁ thật trong DB (query thô
     ra 'enc:v1:'), đọc qua store trả bản giải mã

Chạy TỪ GỐC: python tests/test_secretbox.py
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
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_secretbox_tmp.sqlite')
os.environ.pop('NOVACHAT_SECRET_KEY', None)
os.environ.pop('ALLOW_PLAINTEXT_SECRETS', None)
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_secretbox_tmp.sqlite{suf}")).unlink(missing_ok=True)

from app.core import secretbox

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

SECRET = "tg-caller-session-string-RẤT-BÍ-MẬT-123"

print("\n── A. Có khoá: roundtrip ──")
os.environ['NOVACHAT_SECRET_KEY'] = 'test-key-abc'
check(secretbox.enabled(), "A1 enabled khi có khoá + lib")
enc = secretbox.encrypt(SECRET)
check(enc.startswith("enc:v1:") and SECRET not in enc, "A2 mã hoá có tiền tố, không lộ bản thô", enc[:30])
check(secretbox.decrypt(enc) == SECRET, "A3 giải mã đúng roundtrip")
check(secretbox.encrypt(enc) == enc, "A4 encrypt idempotent (không mã hoá kép)")
check(secretbox.decrypt("chuỗi thô cũ") == "chuỗi thô cũ", "A5 dữ liệu thô cũ trả nguyên (migrate dần)")

print("\n── B. Không khoá: degrade ──")
os.environ.pop('NOVACHAT_SECRET_KEY', None)
check(not secretbox.enabled(), "B1 not enabled khi thiếu khoá")
check(secretbox.encrypt(SECRET) == SECRET, "B2 encrypt degrade trả nguyên văn")
check(secretbox.decrypt(enc) == "", "B3 decrypt dữ liệu mã hoá thiếu khoá → '' (không lộ)")

print("\n── C. Sai khoá ──")
os.environ['NOVACHAT_SECRET_KEY'] = 'khoá-KHÁC'
check(secretbox.decrypt(enc) == "", "C1 decrypt sai khoá → '' (không nổ)")
os.environ['NOVACHAT_SECRET_KEY'] = 'test-key-abc'
check(secretbox.decrypt(enc) == SECRET, "C2 đặt lại đúng khoá → giải được")

print("\n── D. serve fail-closed khi public thiếu khoá ──")
from app.core.config import Config
from app.web_api import serve

_old_pub = Config.PUBLIC_BASE_URL

# D1: không public → không chặn (dù thiếu khoá)
os.environ.pop('NOVACHAT_SECRET_KEY', None)
Config.PUBLIC_BASE_URL = ""
try:
    serve._check_production_secrets(); ok = True
except SystemExit:
    ok = False
check(ok, "D1 local không public → cho chạy")

# D2: public + thiếu khoá → SystemExit
Config.PUBLIC_BASE_URL = "https://novachat.example.com"
try:
    serve._check_production_secrets(); ok = False
except SystemExit:
    ok = True
check(ok, "D2 public + thiếu khoá → TỪ CHỐI khởi động")

# D3: public + có khoá → cho chạy
os.environ['NOVACHAT_SECRET_KEY'] = 'test-key-abc'
try:
    serve._check_production_secrets(); ok = True
except SystemExit:
    ok = False
check(ok, "D3 public + có khoá → cho chạy")

# D4: public + thiếu khoá + ALLOW_PLAINTEXT_SECRETS=1 → cho chạy (cố tình)
os.environ.pop('NOVACHAT_SECRET_KEY', None)
os.environ['ALLOW_PLAINTEXT_SECRETS'] = '1'
try:
    serve._check_production_secrets(); ok = True
except SystemExit:
    ok = False
check(ok, "D4 override ALLOW_PLAINTEXT_SECRETS=1 → cho chạy")
os.environ.pop('ALLOW_PLAINTEXT_SECRETS', None)
Config.PUBLIC_BASE_URL = _old_pub

print("\n── E. ChannelStore: secret nằm MÃ HOÁ thật trong DB ──")
os.environ['NOVACHAT_SECRET_KEY'] = 'test-key-abc'
from app.core.channel_store import SQLiteChannelStore
from app.core.db import get_db
st = SQLiteChannelStore("test_sb", secret_fields=("token",))
st.upsert("acc1", {"name": "Bot", "token": SECRET, "owner_username": "shop@x.vn"})
raw = get_db().query(
    "SELECT data FROM channel_accounts WHERE channel='test_sb' AND account_id='acc1'")[0]["data"]
check("enc:v1:" in raw and SECRET not in raw, "E1 DB thô chứa 'enc:v1:', không chứa secret", raw[:60])
check(st.get("acc1").get("token") == SECRET, "E2 đọc qua store trả bản giải mã")
check(st.get("acc1").get("name") == "Bot", "E3 field thường giữ JSON đọc được")

try:
    get_db().conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_secretbox_tmp.sqlite{suf}")).unlink(missing_ok=True)

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
