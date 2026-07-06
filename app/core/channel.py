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

    # ── Ngữ cảnh account đa khách (đa số kênh 1-account = no-op) ────
    # Các kênh đa khách (tiktok/shopee/zalo_oa/telegram) lưu account đang xử lý
    # trong threading.local để notify_owner/call_owner báo ĐÚNG chủ. Vì ctx là
    # thread-local, khi brain SPAWN thread con (vd _make_order tạo đơn nền) thì
    # ctx KHÔNG tự truyền sang → phải snapshot get_ctx() rồi set_ctx() lại trong
    # thread con. Base class no-op cho kênh 1-account (zalo/meta).

    def set_ctx(self, value) -> None:
        pass

    def get_ctx(self):
        return None

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

    def send_photo_folder(self, user_id: str, folder, caption: str) -> bool:
        """Gửi cả 1 thư mục ảnh (bộ ảnh Thư viện ảnh do shop đặt tên).
        Mặc định: kênh chưa hỗ trợ → False (brain sẽ fallback cơ chế cũ).
        Các kênh override bằng _send_dir sẵn có của mình."""
        return False

    def send_image_url(self, user_id: str, url: str, caption: str = "") -> None:
        """Gửi 1 ảnh từ URL công khai (vd QR VietQR động). Mặc định: gửi text
        kèm link (mọi kênh hiển thị được); các kênh override để gửi ảnh thật."""
        self.send_text(user_id, (caption + "\n" if caption else "") + url)

    def send_file(self, user_id: str, path, url: str, kind: str, caption: str = "") -> bool:
        """Gửi ẢNH/VIDEO/GHI ÂM cho khách (chủ đính kèm từ dashboard). Đây là
        điểm vào THỐNG NHẤT cho mọi loại media (chat_tools chỉ gọi hàm này).
        `path` = file local trên máy chủ; `url` = URL công khai (cần PUBLIC_BASE_URL
        để nền tảng NGOÀI tải về). Mặc định (kênh dùng URL công khai — Meta/TikTok/
        Shopee/Zalo OA):
          - ảnh → send_image_url(url)
          - video/ghi âm → gửi LINK (khách bấm mở).
        Kênh đọc/UPLOAD file local (Zalo Node, Telegram) override để gửi file THẬT
        (không phụ thuộc URL/tunnel). Trả True nếu gửi được."""
        if kind == "image":
            if not url:
                return False
            self.send_image_url(user_id, url, caption)
            return True
        if not url:
            return False
        label = {"video": "🎬 Video", "audio": "🎤 Ghi âm"}.get(kind, "📎 Tệp đính kèm")
        self.send_text(user_id, (caption + "\n" if caption else "") + f"{label}: {url}")
        return True

    # ── Thông báo chủ nhà ──────────────────────────────────────────

    @abstractmethod
    def notify_owner(self, text: str) -> None:
        """Gửi thông báo cho chủ nhà (nhóm Zalo / DM / kênh khác)."""
        raise NotImplementedError

    @abstractmethod
    def call_owner(self) -> None:
        """Gọi/đổ chuông báo chủ nhà (beep + Telegram, hoặc cơ chế khác)."""
        raise NotImplementedError
