"""
SQLiteChannelStore — backend CHUNG cho 7 "danh bạ kênh" (telegram/meta/zalo_oa/
webchat/tiktok/shopee/zalo_node), thay các file data/*.json per-process.

Vì sao bỏ JSON file:
  - Mỗi tiến trình giữ 1 bản dict trong RAM rồi ghi đè CẢ FILE → bridge và
    tiến trình kênh cùng ghi là last-writer-wins, bản ghi của bên kia bị NUỐT
    (đã dính thật với zalo_accounts.json).
  - SQLite (data/homestay.db, WAL) ghi TỪNG DÒNG, nhiều tiến trình đọc-ghi
    đồng thời an toàn — đúng hạ tầng sessions/orders đang dùng.

Thiết kế:
  - Đọc-ghi TƯƠI từ SQLite mỗi thao tác (không cache RAM) → tiến trình nào
    upsert xong là tiến trình khác thấy ngay, hết race liên tiến trình.
  - data = JSON toàn bộ hồ sơ account trong 1 cột (schema linh hoạt theo kênh,
    không phải ALTER khi kênh thêm field); owner_username mirror ra cột riêng
    để query theo chủ shop nhanh.
  - secret_fields ('token', 'access_token', 'refresh_token', 'caller_session'…):
    tự secretbox.encrypt khi ghi, secretbox.decrypt khi đọc → bí mật nằm MÃ HOÁ
    at-rest trong DB, code store các kênh không phải tự gọi secretbox nữa
    (1 tầng mã hoá duy nhất — secretbox có prefix idempotent nhưng code phải rõ).
  - MIGRATE 1 LẦN từ file JSON cũ (pattern y hệt ConversationManager
    ._migrate_legacy_json): bảng chưa có dòng kênh này + file cũ tồn tại →
    import rồi đổi tên file thành *.migrated giữ backup. CHỈ migrate khi chạy
    trên DB chính homestay.db — tests dùng HOMESTAY_DB_PATH riêng, không được
    đụng/đổi tên file JSON thật.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from app.core import secretbox
from app.core.db import get_db

log = logging.getLogger(__name__)


class SQLiteChannelStore:
    def __init__(self, channel: str, legacy_file=None, secret_fields=()):
        self.channel = str(channel)
        self._legacy_file = Path(legacy_file) if legacy_file else None
        self._secret_fields = tuple(secret_fields)
        self._tag = f"ChannelStore:{self.channel}"
        self._db = get_db()
        self._migrate_legacy_json()

    # ── Mã hoá at-rest (chỉ các field bí mật, phần còn lại giữ JSON đọc được) ──

    def _enc(self, data: dict) -> dict:
        if not self._secret_fields:
            return data
        out = dict(data)
        for f in self._secret_fields:
            v = out.get(f)
            if isinstance(v, str) and v:
                out[f] = secretbox.encrypt(v)   # idempotent — đã 'enc:v1:' thì giữ nguyên
        return out

    def _dec(self, data: dict) -> dict:
        if not self._secret_fields:
            return data
        for f in self._secret_fields:
            v = data.get(f)
            if isinstance(v, str) and v:
                data[f] = secretbox.decrypt(v)  # dữ liệu thô cũ (không prefix) trả nguyên
        return data

    # ── Migrate JSON cũ → SQLite (chạy 1 lần) ─────────────────────────────

    def _migrate_legacy_json(self):
        # Chỉ migrate khi chạy trên DB chính (homestay.db) — tests dùng DB riêng
        # qua HOMESTAY_DB_PATH, không được đụng/đổi tên file JSON thật.
        if Path(self._db.path).name != "homestay.db":
            return
        f = self._legacy_file
        if f is None or not f.exists():
            return
        try:
            has_rows = self._db.query(
                "SELECT 1 FROM channel_accounts WHERE channel=? LIMIT 1",
                (self.channel,))
            if has_rows:
                return
            raw = json.loads(f.read_text(encoding="utf-8")) or {}
            n = 0
            for aid, data in raw.items():
                if isinstance(data, dict):
                    self.upsert(str(aid), data)   # đi qua upsert → secret được mã hoá luôn
                    n += 1
            # replace (không phải rename): Windows không cho rename đè file có sẵn
            f.replace(f.with_suffix(f.suffix + ".migrated"))
            log.info(f"[{self._tag}] Migrate {n} account(s) JSON → SQLite ({self._db.path})")
        except Exception as e:
            log.error(f"[{self._tag}] migrate JSON→SQLite lỗi: {e}")

    # ── CRUD (đọc-ghi tươi, không cache) ──────────────────────────────────

    def get(self, account_id) -> dict:
        """Hồ sơ account (secret đã GIẢI mã) — {} nếu không có."""
        try:
            rows = self._db.query(
                "SELECT data FROM channel_accounts WHERE channel=? AND account_id=?",
                (self.channel, str(account_id)))
            if not rows:
                return {}
            return self._dec(json.loads(rows[0]["data"] or "{}"))
        except Exception as e:
            log.error(f"[{self._tag}] get lỗi: {e}")
            return {}

    def upsert(self, account_id, data: dict):
        """Ghi ĐÈ toàn bộ hồ sơ account (caller đọc-sửa-ghi dưới lock riêng)."""
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO channel_accounts"
                "(channel, account_id, owner_username, data, updated_at)"
                " VALUES (?,?,?,?,?)",
                (self.channel, str(account_id),
                 (data.get("owner_username") or ""),
                 json.dumps(self._enc(data), ensure_ascii=False),
                 datetime.now().isoformat()))
        except Exception as e:
            log.error(f"[{self._tag}] upsert lỗi: {e}")

    def remove(self, account_id):
        try:
            self._db.execute(
                "DELETE FROM channel_accounts WHERE channel=? AND account_id=?",
                (self.channel, str(account_id)))
        except Exception as e:
            log.error(f"[{self._tag}] remove lỗi: {e}")

    def exists(self, account_id) -> bool:
        try:
            return bool(self._db.query(
                "SELECT 1 FROM channel_accounts WHERE channel=? AND account_id=? LIMIT 1",
                (self.channel, str(account_id))))
        except Exception as e:
            log.error(f"[{self._tag}] exists lỗi: {e}")
            return False

    def all(self) -> dict:
        """{account_id: data} toàn kênh (secret đã giải mã) — cho list/scan."""
        out = {}
        try:
            for r in self._db.query(
                    "SELECT account_id, data FROM channel_accounts WHERE channel=?",
                    (self.channel,)):
                try:
                    out[r["account_id"]] = self._dec(json.loads(r["data"] or "{}"))
                except Exception as e:
                    log.error(f"[{self._tag}] dòng {r['account_id']} JSON hỏng: {e}")
        except Exception as e:
            log.error(f"[{self._tag}] all lỗi: {e}")
        return out

    def list(self) -> list:
        """[(account_id, data)] — tiện iterate giữ thứ tự ổn định."""
        return sorted(self.all().items())

    def clear(self):
        """Xoá SẠCH account của kênh này (chủ yếu cho tests dọn dữ liệu)."""
        try:
            self._db.execute(
                "DELETE FROM channel_accounts WHERE channel=?", (self.channel,))
        except Exception as e:
            log.error(f"[{self._tag}] clear lỗi: {e}")
