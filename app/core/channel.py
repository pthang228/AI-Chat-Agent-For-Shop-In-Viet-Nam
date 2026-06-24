"""
Giao diện kênh (Channel) — lớp trừu tượng để "não bộ" (brain.py) gửi tin
mà không cần biết đang chạy trên Zalo, Instagram, Messenger hay web widget.

Mỗi kênh cụ thể (vd: ZaloChannel trong bot.py) kế thừa lớp này và cài đặt
các primitive bên dưới bằng SDK/API tương ứng của nền tảng đó.

Quy ước: brain chỉ làm việc với `user_id` (định danh khách trong 1 cuộc hội thoại).
Việc map user_id → thread/conversation thực tế là của từng kênh tự lo.
"""

from abc import ABC, abstractmethod


class Channel(ABC):

    # ── Gửi cho khách ──────────────────────────────────────────────

    @abstractmethod
    def send_text(self, user_id: str, text: str) -> None:
        """Gửi tin nhắn text cho khách."""
        raise NotImplementedError

    @abstractmethod
    def send_room_photos(self, user_id: str, room_names: list[str]) -> None:
        """Gửi ảnh các phòng (vd: ['Phòng 201', 'Phòng 301'])."""
        raise NotImplementedError

    @abstractmethod
    def send_price_photos(self, user_id: str) -> None:
        """Gửi ảnh bảng giá của các homestay."""
        raise NotImplementedError

    # ── Thông báo chủ nhà ──────────────────────────────────────────

    @abstractmethod
    def notify_owner(self, text: str) -> None:
        """Gửi thông báo cho chủ nhà (nhóm Zalo / DM / kênh khác)."""
        raise NotImplementedError

    @abstractmethod
    def call_owner(self) -> None:
        """Gọi/đổ chuông báo chủ nhà (beep + Telegram, hoặc cơ chế khác)."""
        raise NotImplementedError
