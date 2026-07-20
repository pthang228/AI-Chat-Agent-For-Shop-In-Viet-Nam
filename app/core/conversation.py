"""
Theo dõi trạng thái hội thoại với từng khách hàng.

LƯU TRỮ: SQLite (data/homestay.db, bảng sessions + stats_archive — xem app/core/db.py).
Đáp ứng 10.000+ khách: chỉ ghi DÒNG của khách có thay đổi (dirty tracking qua get()),
không ghi đè cả file như JSON cũ. Toàn bộ session vẫn cache trong RAM để dashboard/
thống kê đọc nhanh (10k khách ≈ vài chục MB — nhẹ).

Tự MIGRATE 1 lần từ JSON cũ (data/sessions*.json, stats_archive*.json) khi khởi động —
file cũ được đổi tên thành *.migrated để giữ backup.
"""

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import Config
from app.core.db import get_db

OWNER_ACTIVE_HOURS = 48   # Tự reset owner_active sau N giờ
AUTOSAVE_INTERVAL  = 60   # Tự lưu DB mỗi N giây


@dataclass
class ConversationState:
    user_id: str
    messages: list[dict] = field(default_factory=list)   # lịch sử chat gửi cho AI
    name: str = ""                                        # tên hiển thị của khách
    avatar: str = ""                                      # URL ảnh đại diện (kênh cung cấp)
    checkin:  Optional[str] = None                        # dd/mm/yyyy
    checkout: Optional[str] = None
    selected_room: Optional[str] = None
    stage: str = "greeting"  # greeting | checking | offering | confirmed | owner_notified
    assigned_to: str = ""               # nhân viên được phân công (username, rỗng = chưa gán)
    tenant: str = ""                    # SHOP sở hữu hội thoại (username chủ) — multi-tenant
    owner_active: bool = False          # True khi chủ nhà đang tự xử lý
    owner_active_since: Optional[datetime] = None   # Thời điểm bật owner_active
    last_updated: datetime = field(default_factory=datetime.now)
    # TÓM TẮT CUỘN: hội thoại dài vượt cửa sổ raw → AI tóm phần cũ thành vài dòng
    # trạng thái; summary_upto = messages[:upto] đã nằm trong summary (không gửi lại thô)
    summary: str = ""
    summary_upto: int = 0
    last_intent: str = ""               # intent lượt trước (RAM-only) — style RAG dùng chọn mẫu

    # ── Message helpers ───────────────────────────────────────────

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self.last_updated = datetime.now()

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})
        self.last_updated = datetime.now()

    def get_recent_messages(self, n: int = 20) -> list[dict]:
        return self.messages[-n:]

    def history_for_ai(self, n: int = 20) -> list[dict]:
        """Cửa sổ lịch sử gửi AI, BIẾT tóm tắt cuộn: tin đã nằm trong summary
        (messages[:summary_upto]) không gửi thô lại — summary thay mặt chúng.
        Chưa có summary → y hệt get_recent_messages(n)."""
        start = max(len(self.messages) - n, min(self.summary_upto, len(self.messages)))
        return self.messages[start:]

    # ── Owner-active helpers ──────────────────────────────────────

    def set_owner_active(self, active: bool):
        """Bật/tắt owner_active, ghi timestamp khi bật."""
        self.owner_active = active
        self.owner_active_since = datetime.now() if active else None
        self.last_updated = datetime.now()

    def is_owner_active(self, hours: int = OWNER_ACTIVE_HOURS) -> bool:
        """
        Trả về True nếu owner_active đang có hiệu lực.
        Tự động reset về False sau `hours` giờ.
        """
        if not self.owner_active:
            return False
        if self.owner_active_since is None:
            # Dữ liệu cũ không có timestamp → reset luôn
            self.owner_active = False
            return False
        elapsed = (datetime.now() - self.owner_active_since).total_seconds()
        if elapsed > hours * 3600:
            self.owner_active = False
            self.owner_active_since = None
            return False
        return True


class ConversationManager:
    def __init__(self, account: int = 1, db_path=None):
        self._account = str(account)
        # Đường dẫn JSON CŨ (chỉ để migrate 1 lần + tương thích code/test cũ)
        fname = "sessions.json" if account == 1 else f"sessions_{account}.json"
        aname = "stats_archive.json" if account == 1 else f"stats_archive_{account}.json"
        self._file = Config.DATA_DIR / fname
        self._archive_file = Config.DATA_DIR / aname

        self._db = get_db(db_path)
        self._sessions: dict[str, ConversationState] = {}
        self._dirty: set[str] = set()   # user_id có thay đổi từ lần save trước
        self._lock = threading.Lock()

        self._migrate_legacy_json()
        self._load()
        self._start_autosave()

    # ── Migrate JSON cũ → SQLite (chạy 1 lần) ─────────────────────

    def _migrate_legacy_json(self):
        # Chỉ migrate khi chạy trên DB chính (homestay.db) — tests dùng DB riêng
        # qua HOMESTAY_DB_PATH, không được đụng/đổi tên file JSON thật.
        if Path(self._db.path).name != "homestay.db":
            return
        try:
            has_rows = self._db.query(
                "SELECT 1 FROM sessions WHERE account=? LIMIT 1", (self._account,))
            if not has_rows and self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8")) or {}
                rows = []
                for uid, s in raw.items():
                    rows.append((
                        self._account, uid, s.get("name", ""),
                        s.get("checkin"), s.get("checkout"), s.get("selected_room"),
                        s.get("stage", "greeting"),
                        1 if s.get("owner_active") else 0,
                        s.get("owner_active_since"),
                        s.get("last_updated") or datetime.now().isoformat(),
                        json.dumps(s.get("messages", []), ensure_ascii=False),
                        "",   # avatar — JSON cũ không có
                        "",   # assigned_to — JSON cũ không có
                        "",   # tenant — JSON cũ không có (migrate_tenant sẽ gán chủ đầu tiên)
                        "",   # summary — JSON cũ không có
                        0,    # summary_upto
                    ))
                if rows:
                    self._db.executemany(self._INSERT_SQL, rows)
                # replace (không phải rename): Windows không cho rename đè file có sẵn
                self._file.replace(self._file.with_suffix(".json.migrated"))
                print(f"[Sessions] Migrate {len(rows)} session(s) JSON → SQLite ({self._db.path})")

            has_arch = self._db.query(
                "SELECT 1 FROM stats_archive WHERE account=? LIMIT 1", (self._account,))
            if not has_arch and self._archive_file.exists():
                arch = json.loads(self._archive_file.read_text(encoding="utf-8")) or []
                rows = [
                    (self._account, r.get("user_id", ""), r.get("stage"),
                     r.get("total_msg", 0), r.get("user_msg", 0), r.get("bot_msg", 0),
                     r.get("date", ""))
                    for r in arch if r.get("date")
                ]
                if rows:
                    self._db.executemany(
                        "INSERT INTO stats_archive(account,user_id,stage,total_msg,user_msg,bot_msg,date) "
                        "VALUES (?,?,?,?,?,?,?)", rows)
                self._archive_file.replace(self._archive_file.with_suffix(".json.migrated"))
                print(f"[Sessions] Migrate {len(rows)} dòng archive JSON → SQLite")
        except Exception as e:
            print(f"[Sessions] Lỗi migrate JSON→SQLite: {e}")

    # ── Persistence ───────────────────────────────────────────────

    def _load(self):
        """Load toàn bộ session của account này vào RAM khi khởi động."""
        try:
            for r in self._db.query("SELECT * FROM sessions WHERE account=?", (self._account,)):
                oas, lu = r["owner_active_since"], r["last_updated"]
                self._sessions[r["user_id"]] = ConversationState(
                    user_id       = r["user_id"],
                    messages      = json.loads(r["messages"] or "[]"),
                    name          = r["name"] or "",
                    avatar        = (r["avatar"] if "avatar" in r.keys() else "") or "",
                    checkin       = r["checkin"],
                    checkout      = r["checkout"],
                    selected_room = r["selected_room"],
                    stage         = r["stage"] or "greeting",
                    assigned_to   = (r["assigned_to"] if "assigned_to" in r.keys() else "") or "",
                    tenant        = (r["tenant"] if "tenant" in r.keys() else "") or "",
                    owner_active  = bool(r["owner_active"]),
                    owner_active_since = datetime.fromisoformat(oas) if oas else None,
                    last_updated  = datetime.fromisoformat(lu) if lu else datetime.now(),
                    summary       = (r["summary"] if "summary" in r.keys() else "") or "",
                    summary_upto  = int(r["summary_upto"] or 0) if "summary_upto" in r.keys() else 0,
                )
            print(f"[Sessions] Load {len(self._sessions)} session(s) account={self._account} từ {self._db.path}")
        except Exception as e:
            print(f"[Sessions] Lỗi load: {e}")

    # Ghi TÊN CỘT tường minh: cột avatar thêm sau (ALTER) nên thứ tự cột có thể
    # khác nhau giữa DB cũ và DB tạo mới — insert positional sẽ lệch cột.
    _INSERT_SQL = (
        "INSERT OR REPLACE INTO sessions (account, user_id, name, checkin, checkout,"
        " selected_room, stage, owner_active, owner_active_since, last_updated,"
        " messages, avatar, assigned_to, tenant, summary, summary_upto)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")

    def _row(self, s: ConversationState):
        return (
            self._account, s.user_id, s.name,
            s.checkin, s.checkout, s.selected_room, s.stage,
            1 if s.owner_active else 0,
            s.owner_active_since.isoformat() if s.owner_active_since else None,
            s.last_updated.isoformat(),
            json.dumps(s.messages, ensure_ascii=False),
            s.avatar or "",
            s.assigned_to or "",
            s.tenant or "",
            s.summary or "",
            int(s.summary_upto or 0),
        )

    def save(self):
        """Ghi các session CÓ THAY ĐỔI xuống SQLite (thread-safe).
        Khác JSON cũ: chỉ ghi dòng dirty → 10k khách vẫn nhanh."""
        with self._lock:
            dirty, self._dirty = self._dirty, set()
            rows = [self._row(self._sessions[uid]) for uid in dirty if uid in self._sessions]
        if not rows:
            return
        try:
            self._db.executemany(self._INSERT_SQL, rows)
        except Exception as e:
            print(f"[Sessions] Lỗi save: {e}")
            with self._lock:
                self._dirty |= dirty   # giữ lại để thử ghi lần sau

    # ── Lưu trữ thống kê (session bị dọn vẫn còn số liệu cho /stats) ──

    def _archive_session(self, s: ConversationState):
        """Gấp 1 session sắp bị dọn thành 1 dòng thống kê (không giữ nội dung chat)."""
        msgs = s.messages
        try:
            # Ghi kèm TENANT của session: shop thuê vẫn thấy số liệu lịch sử
            # sau khi session bị dọn (compute_stats lọc archive theo tenant)
            self._db.execute(
                "INSERT INTO stats_archive(account,user_id,stage,total_msg,user_msg,bot_msg,date,tenant) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (self._account, s.user_id, s.stage, len(msgs),
                 sum(1 for m in msgs if m.get("role") == "user"),
                 sum(1 for m in msgs if m.get("role") == "assistant"),
                 s.last_updated.strftime("%Y-%m-%d"), s.tenant or ""))
        except Exception as e:
            print(f"[Sessions] Lỗi archive: {e}")

    def archived_stats(self) -> list[dict]:
        try:
            return [
                {"user_id": r["user_id"], "stage": r["stage"], "total_msg": r["total_msg"],
                 "user_msg": r["user_msg"], "bot_msg": r["bot_msg"], "date": r["date"],
                 # tenant để compute_stats lọc theo shop (dòng cũ trước migrate = '')
                 "tenant": (r["tenant"] if "tenant" in r.keys() else "") or ""}
                for r in self._db.query(
                    "SELECT * FROM stats_archive WHERE account=?", (self._account,))
            ]
        except Exception as e:
            print(f"[Sessions] Lỗi đọc archive: {e}")
            return []

    def _start_autosave(self):
        """Tự lưu + dọn session hết hạn định kỳ mỗi AUTOSAVE_INTERVAL giây."""
        def _loop():
            import time
            while True:
                time.sleep(AUTOSAVE_INTERVAL)
                # Dọn hội thoại quá hạn (mặc định 30 ngày, chỉnh qua .env
                # SESSION_RETENTION_HOURS) — thống kê đã gấp vào archive trước khi xoá
                self.cleanup_old(hours=Config.SESSION_RETENTION_HOURS)
                self.save()
        t = threading.Thread(target=_loop, daemon=True, name="sessions-autosave")
        t.start()

    # ── CRUD ──────────────────────────────────────────────────────

    def get(self, user_id: str) -> ConversationState:
        """Lấy (hoặc tạo) session. Caller thường mutate sau khi get →
        đánh dấu dirty để save() ghi xuống DB. Tạo session + mark dirty trong
        CÙNG lock để không đua với cleanup_old (thread autosave) pop cùng lúc."""
        with self._lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = ConversationState(user_id=user_id)
            self._dirty.add(user_id)
            return self._sessions[user_id]

    def reset(self, user_id: str):
        self._sessions.pop(user_id, None)
        with self._lock:
            self._dirty.discard(user_id)
        try:
            self._db.execute("DELETE FROM sessions WHERE account=? AND user_id=?",
                             (self._account, user_id))
        except Exception as e:
            print(f"[Sessions] Lỗi reset: {e}")

    def cleanup_old(self, hours: int = None):
        """Xóa session không hoạt động quá N giờ (mặc định SESSION_RETENTION_HOURS —
        30 ngày). Lưu trữ số liệu thống kê vào stats_archive trước khi xoá."""
        if hours is None:
            hours = Config.SESSION_RETENTION_HOURS
        now = datetime.now()
        expired = [
            uid for uid, s in list(self._sessions.items())
            if (now - s.last_updated).total_seconds() > hours * 3600
        ]
        for uid in expired:
            with self._lock:
                s = self._sessions.get(uid)
                # Tin mới vừa đến (get() cập nhật last_updated) trong lúc dọn →
                # không còn "hết hạn" nữa → BỎ QUA, không xoá nhầm session sống.
                if s is None or (now - s.last_updated).total_seconds() <= hours * 3600:
                    continue
                self._archive_session(s)              # giữ số liệu cho /stats
                self._sessions.pop(uid, None)
                self._dirty.discard(uid)
        if expired:
            try:
                self._db.executemany(
                    "DELETE FROM sessions WHERE account=? AND user_id=?",
                    [(self._account, uid) for uid in expired])
            except Exception as e:
                print(f"[Sessions] Lỗi xoá session hết hạn: {e}")
            print(f"[Sessions] Đã xóa {len(expired)} session(s) hết hạn (đã lưu trữ thống kê)")
