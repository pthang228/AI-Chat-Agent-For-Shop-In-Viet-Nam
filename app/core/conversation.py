"""
Theo dõi trạng thái hội thoại với từng khách hàng.
Hỗ trợ lưu/load JSON để persist qua các lần restart.
"""

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import Config

OWNER_ACTIVE_HOURS = 48   # Tự reset owner_active sau N giờ
AUTOSAVE_INTERVAL  = 60   # Tự lưu file mỗi N giây


@dataclass
class ConversationState:
    user_id: str
    messages: list[dict] = field(default_factory=list)   # lịch sử chat gửi cho AI
    checkin:  Optional[str] = None                        # dd/mm/yyyy
    checkout: Optional[str] = None
    selected_room: Optional[str] = None
    stage: str = "greeting"  # greeting | checking | offering | confirmed | owner_notified
    owner_active: bool = False          # True khi chủ nhà đang tự xử lý
    owner_active_since: Optional[datetime] = None   # Thời điểm bật owner_active
    last_updated: datetime = field(default_factory=datetime.now)

    # ── Message helpers ───────────────────────────────────────────

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self.last_updated = datetime.now()

    def add_assistant_message(self, content: str):
        self.messages.append({"role": "assistant", "content": content})
        self.last_updated = datetime.now()

    def get_recent_messages(self, n: int = 20) -> list[dict]:
        return self.messages[-n:]

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
    def __init__(self, account: int = 1):
        fname = "sessions.json" if account == 1 else f"sessions_{account}.json"
        self._file = Config.DATA_DIR / fname
        self._sessions: dict[str, ConversationState] = {}
        self._lock = threading.Lock()
        self._load()
        self._start_autosave()

    # ── Persistence ───────────────────────────────────────────────

    def _load(self):
        """Load sessions từ JSON khi khởi động."""
        if not self._file.exists():
            return
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
            for uid, s in raw.items():
                oas = s.get("owner_active_since")
                lu  = s.get("last_updated")
                self._sessions[uid] = ConversationState(
                    user_id       = uid,
                    messages      = s.get("messages", []),
                    checkin       = s.get("checkin"),
                    checkout      = s.get("checkout"),
                    selected_room = s.get("selected_room"),
                    stage         = s.get("stage", "greeting"),
                    owner_active  = s.get("owner_active", False),
                    owner_active_since = datetime.fromisoformat(oas) if oas else None,
                    last_updated  = datetime.fromisoformat(lu) if lu else datetime.now(),
                )
            print(f"[Sessions] Load {len(self._sessions)} session(s) từ {self._file}")
        except Exception as e:
            print(f"[Sessions] Lỗi load: {e}")

    def save(self):
        """Lưu tất cả sessions xuống JSON (thread-safe)."""
        with self._lock:
            try:
                data = {}
                for uid, s in self._sessions.items():
                    data[uid] = {
                        "messages"          : s.messages,
                        "checkin"           : s.checkin,
                        "checkout"          : s.checkout,
                        "selected_room"     : s.selected_room,
                        "stage"             : s.stage,
                        "owner_active"      : s.owner_active,
                        "owner_active_since": s.owner_active_since.isoformat() if s.owner_active_since else None,
                        "last_updated"      : s.last_updated.isoformat(),
                    }
                self._file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                print(f"[Sessions] Lỗi save: {e}")

    def _start_autosave(self):
        """Tự lưu + dọn session hết hạn định kỳ mỗi AUTOSAVE_INTERVAL giây."""
        def _loop():
            import time
            while True:
                time.sleep(AUTOSAVE_INTERVAL)
                self.cleanup_old(hours=48)  # xóa session không hoạt động 48h
                self.save()
        t = threading.Thread(target=_loop, daemon=True, name="sessions-autosave")
        t.start()

    # ── CRUD ──────────────────────────────────────────────────────

    def get(self, user_id: str) -> ConversationState:
        if user_id not in self._sessions:
            self._sessions[user_id] = ConversationState(user_id=user_id)
        return self._sessions[user_id]

    def reset(self, user_id: str):
        self._sessions.pop(user_id, None)
        self.save()

    def cleanup_old(self, hours: int = 48):
        """Xóa session không hoạt động quá N giờ rồi lưu lại."""
        now = datetime.now()
        expired = [
            uid for uid, s in self._sessions.items()
            if (now - s.last_updated).total_seconds() > hours * 3600
        ]
        for uid in expired:
            del self._sessions[uid]
        if expired:
            print(f"[Sessions] Đã xóa {len(expired)} session(s) hết hạn")
            self.save()
