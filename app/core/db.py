"""
SQLite dùng chung cho toàn app — thay các file JSON sessions*.json.

Vì sao SQLite (không phải Postgres/MySQL):
  - Có sẵn trong Python, KHÔNG cần cài server DB — khách hàng double-click là chạy.
  - 1 file data/homestay.db, WAL mode → nhiều tiến trình (bridge/meta/telegram/tiktok)
    đọc-ghi đồng thời an toàn.
  - Ghi TỪNG DÒNG (khách nào đổi ghi khách đó) thay vì ghi đè cả file JSON →
    10.000+ khách vẫn nhẹ (JSON cũ: mỗi tin nhắn ghi lại toàn bộ file).

Bảng:
  sessions      — hội thoại khách (mỗi khách 1 dòng, messages là JSON text)
  stats_archive — số liệu thống kê của hội thoại đã dọn (giữ vĩnh viễn, rất nhỏ)
"""

import sqlite3
import threading

from app.core.config import Config

_conns: dict = {}
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    account            TEXT NOT NULL,
    user_id            TEXT NOT NULL,
    name               TEXT NOT NULL DEFAULT '',
    checkin            TEXT,
    checkout           TEXT,
    selected_room      TEXT,
    stage              TEXT NOT NULL DEFAULT 'greeting',
    owner_active       INTEGER NOT NULL DEFAULT 0,
    owner_active_since TEXT,
    last_updated       TEXT NOT NULL,
    messages           TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (account, user_id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_acc_lu ON sessions(account, last_updated);

CREATE TABLE IF NOT EXISTS stats_archive (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    account   TEXT NOT NULL,
    user_id   TEXT NOT NULL,
    stage     TEXT,
    total_msg INTEGER NOT NULL DEFAULT 0,
    user_msg  INTEGER NOT NULL DEFAULT 0,
    bot_msg   INTEGER NOT NULL DEFAULT 0,
    date      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_archive_acc_date ON stats_archive(account, date);

-- Tài khoản web (chủ homestay) — thay localStorage hb_users
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,          -- email (lowercase)
    password_hash TEXT,                      -- NULL với tài khoản Google
    homestay      TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',  -- email liên hệ (có thể khác username)
    provider      TEXT NOT NULL DEFAULT 'password',  -- password | google
    picture       TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

-- Phiên đăng nhập (nhiều thiết bị cùng lúc, mỗi thiết bị 1 token)
CREATE TABLE IF NOT EXISTS auth_tokens (
    token      TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tokens_user ON auth_tokens(username);

-- App (kênh chat) của từng user — thay localStorage hb_apps
CREATE TABLE IF NOT EXISTS user_apps (
    id         TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    name       TEXT NOT NULL,
    channel    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_apps_user ON user_apps(username);

-- Gói dịch vụ + ví tiền của từng user (billing)
CREATE TABLE IF NOT EXISTS billing (
    username   TEXT PRIMARY KEY,
    balance    INTEGER NOT NULL DEFAULT 0,        -- ví (VND)
    plan       TEXT NOT NULL DEFAULT 'trial',     -- trial | month | quarter | year | lifetime (thời hạn)
    tier       TEXT NOT NULL DEFAULT 'trial',     -- trial | starter | pro | business (hạng)
    lifetime   INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,                              -- ISO; NULL với lifetime
    promo_used INTEGER NOT NULL DEFAULT 0,        -- đã dùng mã giới thiệu chưa
    ai_used    INTEGER NOT NULL DEFAULT 0,        -- số lượt AI trả lời trong kỳ hiện tại
    ai_period  TEXT NOT NULL DEFAULT '',          -- kỳ tính quota YYYY-MM (reset mỗi tháng)
    created_at TEXT NOT NULL
);

-- Lệnh nạp tiền (chuyển khoản thủ công, admin xác nhận)
CREATE TABLE IF NOT EXISTS deposits (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT NOT NULL,
    amount       INTEGER NOT NULL,
    code         TEXT UNIQUE NOT NULL,            -- nội dung chuyển khoản, vd NAP483920
    status       TEXT NOT NULL DEFAULT 'pending', -- pending | confirmed | canceled
    created_at   TEXT NOT NULL,
    confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits(username);

-- Kho tri thức RAG — "Dạy AI" chế độ lai băm dữ liệu shop thành mẩu (chunk),
-- mỗi tin nhắn chỉ tra mẩu liên quan thay vì nhồi cả prompt 13k ký tự
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    shop       TEXT NOT NULL DEFAULT 'default',
    title      TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL,
    keywords   TEXT NOT NULL DEFAULT '[]',  -- JSON array các cách khách hay hỏi
    pinned     INTEGER NOT NULL DEFAULT 0,  -- 1 = luôn kèm khi không match gì (thông tin chung)
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_shop ON knowledge_chunks(shop);

-- Bộ ảnh đặt tên (Thư viện ảnh) — shop upload, bot gửi khi khách hỏi trúng tên/keywords
CREATE TABLE IF NOT EXISTS photo_sets (
    slug       TEXT PRIMARY KEY,             -- tên thư mục an toàn (bỏ dấu, dash)
    name       TEXT NOT NULL,                -- tên hiển thị shop đặt
    keywords   TEXT NOT NULL DEFAULT '[]',   -- JSON array các cách khách hay hỏi
    created_at TEXT NOT NULL
);

-- Lịch sử giao dịch (nạp/mua gói/khuyến mãi)
CREATE TABLE IF NOT EXISTS transactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    type       TEXT NOT NULL,        -- deposit | purchase | promo
    amount     INTEGER NOT NULL,     -- + nạp, - mua gói
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(username);
"""


class Db:
    """Kết nối SQLite + lock ghi (1 conn/1 file/1 tiến trình, dùng chung mọi thread)."""

    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        with self.lock:
            self.conn.executescript(_SCHEMA)
            self._migrate_columns()
            self.conn.commit()

    def _migrate_columns(self):
        """Thêm cột mới vào bảng đã tồn tại (CREATE TABLE IF NOT EXISTS không tự thêm).
        Mỗi (bảng, cột, kiểu+default) — bỏ qua nếu đã có."""
        adds = [
            ("billing", "tier",      "TEXT NOT NULL DEFAULT 'trial'"),
            ("billing", "ai_used",   "INTEGER NOT NULL DEFAULT 0"),
            ("billing", "ai_period", "TEXT NOT NULL DEFAULT ''"),
        ]
        for table, col, decl in adds:
            try:
                cols = [r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")]
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except Exception:
                pass

    def execute(self, sql, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def executemany(self, sql, rows):
        with self.lock:
            cur = self.conn.executemany(sql, rows)
            self.conn.commit()
            return cur

    def query(self, sql, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchall()


def get_db(path=None) -> Db:
    """Db singleton theo đường dẫn file (mặc định Config.DB_PATH = data/homestay.db)."""
    path = str(path or Config.DB_PATH)
    with _lock:
        db = _conns.get(path)
        if db is None:
            db = Db(path)
            _conns[path] = db
        return db
