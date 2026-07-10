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
    avatar             TEXT NOT NULL DEFAULT '',   -- URL ảnh đại diện khách (kênh cung cấp)
    assigned_to        TEXT NOT NULL DEFAULT '',   -- nhân viên được phân công (username)
    tenant             TEXT NOT NULL DEFAULT '',   -- SHOP sở hữu hội thoại (username chủ) — multi-tenant
    PRIMARY KEY (account, user_id)
);
-- (index idx_sessions_tenant tạo trong _migrate_tenant — SAU khi ALTER thêm cột
--  cho DB cũ; đặt ở đây sẽ nổ "no such column" với DB tạo trước multi-tenant)
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
    role          TEXT NOT NULL DEFAULT 'owner',     -- owner | staff (nhân viên)
    owner_username TEXT NOT NULL DEFAULT '',         -- staff thuộc workspace chủ nào
    created_at    TEXT NOT NULL
);

-- Phiên đăng nhập (nhiều thiết bị cùng lúc, mỗi thiết bị 1 token)
CREATE TABLE IF NOT EXISTS auth_tokens (
    token      TEXT PRIMARY KEY,
    username   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tokens_user ON auth_tokens(username);

-- Mã quên mật khẩu (OTP 6 số gửi email) — mỗi user 1 mã đang hiệu lực
CREATE TABLE IF NOT EXISTS password_resets (
    username   TEXT PRIMARY KEY,
    code_hash  TEXT NOT NULL,               -- sha256(mã) — không lưu mã thô
    attempts   INTEGER NOT NULL DEFAULT 0,  -- đếm nhập sai, quá 5 lần huỷ mã
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL                -- hết hạn sau 15 phút
);

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

-- SỔ ĐƠN HÀNG — bot tự tạo đơn nháp khi khách chốt (booking_confirmed),
-- chủ shop duyệt/đổi trạng thái trong web; scheduler nhắc khi tới hạn (due_at)
CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT UNIQUE NOT NULL,            -- DH0001, DH0002…
    channel       TEXT NOT NULL DEFAULT '',        -- zalo|meta|telegram|tiktok|shopee
    user_id       TEXT NOT NULL DEFAULT '',        -- khách trong hội thoại (mở lại chat được)
    customer_name TEXT NOT NULL DEFAULT '',
    phone         TEXT NOT NULL DEFAULT '',
    order_type    TEXT NOT NULL DEFAULT 'booking', -- booking (phòng/lịch hẹn) | goods (bán hàng)
    items         TEXT NOT NULL DEFAULT '[]',      -- JSON [{name, qty, price}]
    total         INTEGER NOT NULL DEFAULT 0,      -- VND
    status        TEXT NOT NULL DEFAULT 'draft',   -- draft|awaiting_payment|paid|fulfilled|done|cancelled
    due_at        TEXT,                            -- ISO — ngày checkin / hạn gửi hàng
    note          TEXT NOT NULL DEFAULT '',
    timeline      TEXT NOT NULL DEFAULT '[]',      -- JSON [{at, event}] nhật ký đơn
    reminded      INTEGER NOT NULL DEFAULT 0,      -- đã nhắc tới hạn chưa
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_due ON orders(due_at);

-- Bộ ảnh đặt tên (Thư viện ảnh) — shop upload, bot gửi khi khách hỏi trúng tên/keywords
CREATE TABLE IF NOT EXISTS photo_sets (
    slug       TEXT PRIMARY KEY,             -- tên thư mục an toàn (bỏ dấu, dash)
    name       TEXT NOT NULL,                -- tên hiển thị shop đặt
    keywords   TEXT NOT NULL DEFAULT '[]',   -- JSON array các cách khách hay hỏi
    created_at TEXT NOT NULL
);

-- LỊCH ĐẶT CHỖ per-shop: mỗi shop tự dán link Google Sheet (hệ thống bóc ID),
-- bot tra lịch trống theo sheet CỦA SHOP đó (shop gốc dùng .env legacy + bảng này)
CREATE TABLE IF NOT EXISTS shop_sheets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant     TEXT NOT NULL,                -- username chủ shop
    name       TEXT NOT NULL DEFAULT '',     -- tên chi nhánh hiển thị với khách
    sheet_id   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shop_sheets_tenant ON shop_sheets(tenant);

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

-- CRM KHÁCH HÀNG: hồ sơ bổ sung cho từng hội thoại (account+user_id = 1 khách).
-- Tên hiển thị lấy từ sessions.name (kênh tự cập nhật); cột name ở đây là
-- BẢN GHI ĐÈ do chủ tự đặt (ưu tiên hơn khi khác rỗng).
CREATE TABLE IF NOT EXISTS customers (
    account    TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',   -- chủ tự đặt (đè tên kênh)
    salutation TEXT NOT NULL DEFAULT '',   -- cách xưng hô: anh|chị|em|bạn...
    phone      TEXT NOT NULL DEFAULT '',
    email      TEXT NOT NULL DEFAULT '',
    address    TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    updated_at TEXT,
    PRIMARY KEY (account, user_id)
);

-- TRÍ NHỚ AI VỀ KHÁCH — facts để bot cá nhân hoá phản hồi (AI bóc hoặc chủ ghi tay)
CREATE TABLE IF NOT EXISTS customer_memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account    TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    content    TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'manual',  -- manual | ai
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cmem_cust ON customer_memory(account, user_id);

-- LỊCH SỬ THAY ĐỔI hồ sơ khách (audit — ai đổi gì, cũ → mới)
CREATE TABLE IF NOT EXISTS customer_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account    TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    field      TEXT NOT NULL,
    old_value  TEXT NOT NULL DEFAULT '',
    new_value  TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chist_cust ON customer_history(account, user_id);

-- NHẮC VIỆC FOLLOW-UP: "hẹn chăm lại khách này ngày X" — CRM hiện panel việc
-- đến hạn (khách hỏi giá chưa chốt, hẹn gọi lại...). status pending|done.
CREATE TABLE IF NOT EXISTS followups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account    TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    due_at     TEXT NOT NULL,                    -- ISO ngày (giờ) cần chăm
    status     TEXT NOT NULL DEFAULT 'pending',  -- pending | done
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    done_at    TEXT,
    tenant     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_fu_due ON followups(status, due_at);
CREATE INDEX IF NOT EXISTS idx_fu_cust ON followups(account, user_id);

-- MÃ GIẢM GIÁ (voucher) — chủ tạo, áp vào đơn khi chốt (loyalty.py)
CREATE TABLE IF NOT EXISTS vouchers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT UNIQUE NOT NULL,             -- KHACHVIP10...
    kind       TEXT NOT NULL DEFAULT 'amount',   -- amount (đ) | percent (%)
    value      INTEGER NOT NULL DEFAULT 0,
    min_total  INTEGER NOT NULL DEFAULT 0,       -- đơn tối thiểu mới được áp
    max_uses   INTEGER NOT NULL DEFAULT 0,       -- 0 = không giới hạn
    used       INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,                             -- ISO, NULL = không hết hạn
    active     INTEGER NOT NULL DEFAULT 1,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    tenant     TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS voucher_redemptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id INTEGER NOT NULL,
    order_id   INTEGER NOT NULL DEFAULT 0,
    user_id    TEXT NOT NULL DEFAULT '',
    amount     INTEGER NOT NULL DEFAULT 0,       -- số tiền đã giảm
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vred_v ON voucher_redemptions(voucher_id);

-- CÂU TRẢ LỜI MẪU (canned replies) — chủ soạn sẵn, bấm 1 chạm chèn vào ô chat
CREATE TABLE IF NOT EXISTS canned_replies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL DEFAULT '',   -- nhãn ngắn hiện trên nút
    content    TEXT NOT NULL,              -- nội dung chèn vào ô nhập
    created_at TEXT NOT NULL
);

-- BOT HỌC TỪ HỘI THOẠI: chủ trả lời tay câu bot không biết → AI bóc thành mẩu
-- tri thức ĐỀ XUẤT, chủ duyệt trong web mới vào knowledge_chunks (không tự học sai)
CREATE TABLE IF NOT EXISTS knowledge_suggestions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    shop       TEXT NOT NULL DEFAULT 'default',
    channel    TEXT NOT NULL DEFAULT '',        -- kênh phát sinh (zalo|meta|...)
    user_id    TEXT NOT NULL DEFAULT '',        -- hội thoại phát sinh
    question   TEXT NOT NULL DEFAULT '',        -- câu khách hỏi
    answer     TEXT NOT NULL DEFAULT '',        -- câu chủ trả lời tay
    title      TEXT NOT NULL DEFAULT '',        -- mẩu tri thức AI đề xuất
    content    TEXT NOT NULL,
    keywords   TEXT NOT NULL DEFAULT '[]',      -- JSON array
    status     TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ksug_shop_status ON knowledge_suggestions(shop, status);

-- TIN NHẮN HÀNG LOẠT (broadcast/remarketing) — chủ soạn 1 tin gửi cho nhóm khách
-- cũ theo kênh + mức độ hoạt động. Tin KHÔNG chèn vào luồng hội thoại (tránh đè
-- cache RAM của tiến trình kênh) — lịch sử nằm ở broadcast_log.
CREATE TABLE IF NOT EXISTS broadcasts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL,
    channels    TEXT NOT NULL DEFAULT '[]',      -- JSON array key kênh (zalo|meta|...)
    segment     TEXT NOT NULL DEFAULT '{}',      -- JSON {type: all|active|inactive, days}
    status      TEXT NOT NULL DEFAULT 'draft',   -- draft|sending|done|cancelled
    total       INTEGER NOT NULL DEFAULT 0,      -- số khách trong tập gửi
    sent        INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS broadcast_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    broadcast_id INTEGER NOT NULL,
    account      TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'sent',   -- sent | failed
    error        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bclog_bid ON broadcast_log(broadcast_id);

-- LIÊN HỆ KHẨN CẤP & THÔNG BÁO CHỦ SHOP (thay cơ chế tự-gọi-điện không scale).
-- 1 dòng / chủ shop. emergency_* = liên hệ bot ĐƯA CHO KHÁCH khi cần gấp;
-- share_mode = khi nào bot đưa (off|strict|ask|greeting); events = JSON
-- {sự_kiện: off|notify|call} quyết định báo chủ thế nào cho từng loại.
CREATE TABLE IF NOT EXISTS notify_config (
    username        TEXT PRIMARY KEY,
    emergency_phone TEXT NOT NULL DEFAULT '',
    emergency_zalo  TEXT NOT NULL DEFAULT '',
    emergency_tele  TEXT NOT NULL DEFAULT '',
    share_mode      TEXT NOT NULL DEFAULT 'ask',   -- off|strict|ask|greeting
    events          TEXT NOT NULL DEFAULT '{}',    -- JSON {event: off|notify|call}
    updated_at      TEXT
);
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
            self._migrate_tenant()
            self.conn.commit()

    def _migrate_columns(self):
        """Thêm cột mới vào bảng đã tồn tại (CREATE TABLE IF NOT EXISTS không tự thêm).
        Mỗi (bảng, cột, kiểu+default) — bỏ qua nếu đã có."""
        adds = [
            ("billing", "tier",      "TEXT NOT NULL DEFAULT 'trial'"),
            ("billing", "ai_used",   "INTEGER NOT NULL DEFAULT 0"),
            ("billing", "ai_period", "TEXT NOT NULL DEFAULT ''"),
            # Tài khoản nhận tiền của SHOP (QR động VietQR gửi khách khi chốt đơn)
            ("users", "bank_code",    "TEXT NOT NULL DEFAULT ''"),
            ("users", "bank_account", "TEXT NOT NULL DEFAULT ''"),
            ("users", "bank_holder",  "TEXT NOT NULL DEFAULT ''"),
            # Avatar khách (DB cũ chưa có cột — LƯU Ý: mọi INSERT vào sessions phải
            # ghi TÊN CỘT tường minh vì cột này nằm cuối ở DB cũ nhưng giữa schema mới)
            ("sessions", "avatar",    "TEXT NOT NULL DEFAULT ''"),
            # TEAM: phân quyền nhân viên — role owner|staff; staff thuộc workspace
            # của owner_username (rỗng = chính mình là chủ)
            ("users", "role",           "TEXT NOT NULL DEFAULT 'owner'"),
            ("users", "owner_username", "TEXT NOT NULL DEFAULT ''"),
            # Hội thoại được PHÂN CÔNG cho nhân viên nào (username, rỗng = chưa gán)
            ("sessions", "assigned_to", "TEXT NOT NULL DEFAULT ''"),
            # MULTI-TENANT: shop nào sở hữu dòng dữ liệu này (username chủ shop).
            # Dữ liệu cũ (rỗng) được gán về CHỦ ĐẦU TIÊN ở _migrate_tenant().
            ("sessions", "tenant",         "TEXT NOT NULL DEFAULT ''"),
            ("orders", "tenant",           "TEXT NOT NULL DEFAULT ''"),
            ("canned_replies", "tenant",   "TEXT NOT NULL DEFAULT ''"),
            ("photo_sets", "tenant",       "TEXT NOT NULL DEFAULT ''"),
            # Quản trị nền tảng CHẶN shop (khoá đăng nhập + tắt bot cả workspace)
            ("users", "blocked",           "INTEGER NOT NULL DEFAULT 0"),
            # MULTI-MODEL AI + tính theo usage khi vượt quota (kiểu Claude):
            # ai_model = model shop chọn; usage_* = bật/tắt, giới hạn đ/tháng,
            # đã tiêu bao nhiêu trong kỳ (usage_period = YYYY-MM)
            ("billing", "ai_model",      "TEXT NOT NULL DEFAULT ''"),
            # Model AI riêng CHO TỪNG CHATBOT (user_apps) — rỗng = dùng model
            # mức shop (billing.ai_model). Xem ai_models.model_for().
            ("user_apps", "ai_model",    "TEXT NOT NULL DEFAULT ''"),
            ("billing", "usage_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("billing", "usage_limit",   "INTEGER NOT NULL DEFAULT 0"),
            ("billing", "usage_spent",   "INTEGER NOT NULL DEFAULT 0"),
            ("billing", "usage_period",  "TEXT NOT NULL DEFAULT ''"),
            # CRM nâng cấp: tag (JSON array), vòng đời (rỗng = tự suy từ đơn hàng),
            # gộp hồ sơ trùng SĐT ("account|user_id" hồ sơ chính), điểm thưởng.
            # LƯU Ý: mọi INSERT OR REPLACE vào customers phải ghi ĐỦ các cột này
            # (OR REPLACE = xoá dòng cũ chèn dòng mới — thiếu cột là mất dữ liệu).
            ("customers", "tags",        "TEXT NOT NULL DEFAULT '[]'"),
            ("customers", "stage",       "TEXT NOT NULL DEFAULT ''"),
            ("customers", "merged_into", "TEXT NOT NULL DEFAULT ''"),
            ("customers", "points",      "INTEGER NOT NULL DEFAULT 0"),
            # Voucher áp vào đơn + chống cộng điểm 2 lần khi đơn done
            ("orders", "voucher_code",   "TEXT NOT NULL DEFAULT ''"),
            ("orders", "discount",       "INTEGER NOT NULL DEFAULT 0"),
            ("orders", "points_awarded", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for table, col, decl in adds:
            try:
                cols = [r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")]
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except Exception:
                pass

    def _migrate_tenant(self):
        """MULTI-TENANT migrate 1 lần: dữ liệu cũ (tenant='') gán về CHỦ ĐẦU TIÊN
        (user không phải nhân viên, tạo sớm nhất) — trước đây app single-tenant nên
        toàn bộ dữ liệu thuộc về chủ đó. DB mới/trống → không làm gì."""
        try:
            # Index tạo ở đây (sau ALTER của _migrate_columns) — không đặt trong
            # _SCHEMA vì DB cũ chưa có cột lúc executescript chạy.
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON sessions(tenant)")
        except Exception:
            pass
        try:
            rows = self.conn.execute(
                "SELECT username FROM users WHERE COALESCE(role,'owner') != 'staff' "
                "ORDER BY created_at LIMIT 1").fetchall()
            if not rows:
                return
            first = rows[0][0]
            for table in ("sessions", "orders", "canned_replies", "photo_sets"):
                try:
                    self.conn.execute(
                        f"UPDATE {table} SET tenant=? WHERE tenant=''", (first,))
                except Exception:
                    pass
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
