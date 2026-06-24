"""
Kênh Zalo (cá nhân) — cài đặt giao diện Channel bằng thư viện zlapi.

Phần ĐẶC THÙ ZALO nằm ở đây:
  - nhận tin (onMessage), chống echo (tin bot tự gửi vọng về), owner-takeover
  - gửi text/ảnh qua zlapi, thông báo nhóm chủ nhà, gọi điện (beep + Telegram)

Phần LOGIC XỬ LÝ (intent, Sheets, booking...) nằm ở brain.py — dùng chung mọi kênh.
ZaloChannel chỉ nhận tin → gọi self.brain.handle(user_id, text), rồi brain ra lệnh
gửi lại qua các primitive của Channel mà class này cài đặt.
"""

import time
import hashlib
import threading
import logging
from collections import deque
from pathlib import Path

from zlapi import ZaloAPI
from zlapi.models import Message, ThreadType

from app.core.config import Config
from app.core.conversation import ConversationManager
from app.core.channel import Channel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# Reference module-level để dashboard.py luôn thấy conv_manager mới nhất.
# main.py sẽ gán lại đúng account; ZaloChannel cũng giữ self.conv_manager cùng instance.
conv_manager = ConversationManager()


class ZaloChannel(ZaloAPI, Channel):

    def __init__(self, *args, account: int = 1, conv_manager: ConversationManager = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._account = account   # 1 hoặc 2 — dùng để xác định gọi cho ai
        self.conv_manager = conv_manager or globals()["conv_manager"]
        self.brain = None         # main.py gán Brain sau khi khởi tạo
        # Cache fingerprint (thread_id, md5, timestamp) của các tin TEXT bot vừa gửi.
        # Dùng để nhận ra echo text Zalo trả về.
        self._bot_sent_cache: deque = deque(maxlen=100)
        # Cache (thread_id, timestamp) của các lần bot gửi ảnh (sendLocalImage).
        # Dùng để nhận ra echo MessageObject Zalo trả về cho ảnh.
        self._bot_image_threads: deque = deque(maxlen=200)

    # ================================================================== #
    # NHẬN TIN
    # ================================================================== #

    def onMessage(self, mid=None, author_id=None, message=None,
                  message_object=None, thread_id=None, thread_type=ThreadType.USER):

        # ── Bỏ qua hoàn toàn tin nhắn từ nhóm ─────────────────────────
        # Bot chỉ tư vấn khách qua tin nhắn 1-1.
        # Nếu không lọc, 2 bot sẽ nhận tin của nhau trong nhóm chủ và loop vô tận.
        if thread_type == ThreadType.GROUP:
            return

        # ── Tin nhắn từ chính account bot ──────────────────────────────
        if author_id == self.uid():
            # Trích xuất text bất kể message là str, Message object, hay None
            if isinstance(message, str):
                msg_text = message.strip()
            elif message is not None:
                # Message object của zlapi — thử lấy attribute .text, fallback str()
                msg_text = (getattr(message, "text", None) or str(message)).strip()
            else:
                msg_text = ""

            log.info(
                f"[SelfMsg] type={type(message).__name__} "
                f"thread_id={thread_id} "
                f"text_cache={len(self._bot_sent_cache)} "
                f"img_cache={len(self._bot_image_threads)} "
                f"text={msg_text[:60]!r}"
            )

            # Echo text: fingerprint khớp
            if self._is_bot_echo(thread_id, msg_text):
                log.info("[Echo] Text fingerprint khớp → bỏ qua echo")
                return

            # Echo ảnh: MessageObject (sendLocalImage) → bot vừa gửi ảnh tới thread này
            if not isinstance(message, str) and self._is_bot_image_echo(thread_id):
                log.info("[Echo] Image echo (MessageObject) → bỏ qua")
                return

            log.info("[Echo] KHÔNG khớp → coi là chủ nhà tự nhắn")

            # Không phải echo → chủ nhà đang tự tay nhắn cho khách từ app Zalo
            if thread_id:
                conv = self.conv_manager.get(thread_id)
                if not conv.is_owner_active():
                    conv.set_owner_active(True)
                    self.conv_manager.save()   # lưu ngay — trạng thái quan trọng
                    log.info(
                        f"[OwnerTakeover] Chủ nhà tự tay nhắn khách {thread_id} "
                        f"→ bot dừng auto-reply trong {48}h"
                    )
            return

        # ── Tin nhắn từ khách ──────────────────────────────────────────
        # Kiểm tra xem chủ nhà có đang tiếp quản khách này không (tự reset sau 48h)
        conv = self.conv_manager.get(author_id)
        if conv.is_owner_active():
            log.info(f"[Skip] Chủ nhà đang xử lý {author_id} → bỏ qua tin nhắn bot")
            return

        text = str(message).strip() if isinstance(message, str) else ""
        if not text:
            # Tin nhắn không có text (sticker, reaction, media...) — chỉ rep nếu là khách mới
            if len(conv.messages) > 0:
                return  # Không phải tin đầu tiên → bỏ qua
            log.info(f"[MSG] author={author_id} — sticker/non-text, khách mới → gửi greeting")
        else:
            log.info(f"[MSG] author={author_id} thread_id={thread_id} type={thread_type} | {text[:80]}")

        # Độ trễ tự nhiên trước khi reply
        time.sleep(Config.REPLY_DELAY)

        try:
            self.brain.handle(author_id, text)
        except Exception as e:
            log.error(f"Lỗi xử lý tin nhắn từ {author_id}: {e}", exc_info=True)
            self.send_text(
                author_id,
                "Xin lỗi, hệ thống đang gặp sự cố nhỏ. Chủ nhà sẽ liên hệ lại bạn sớm! 🙏",
            )

    # ================================================================== #
    # GIAO DIỆN Channel — gửi cho khách
    # ================================================================== #

    def send_text(self, user_id: str, text: str) -> None:
        """Gửi text cho khách, tự chia nhỏ nếu quá 2000 ký tự."""
        MAX_LEN = 2000
        chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
        for chunk in chunks:
            self._track_sent(user_id, chunk)   # lưu trước khi gửi
            self.sendMessage(Message(text=chunk), user_id, ThreadType.USER)
            if len(chunks) > 1:
                time.sleep(0.5)

    def send_room_photos(self, user_id: str, room_names: list[str]) -> None:
        """
        Gửi ảnh từng phòng.
        Tìm theo thư mục con: rooms_photos/201/, rooms_photos/202/, ...
        Tên thư mục = số phòng (vd: "Phòng 201" → thư mục "201")
        """
        base_dir = Path(Config.ROOMS_PHOTOS_DIR)
        log.info(f"[Photo] send_room_photos: rooms={room_names} base_dir={base_dir.resolve()}")
        if not base_dir.exists():
            log.warning(f"[Photo] Thư mục ảnh không tồn tại: {base_dir.resolve()}")
            return

        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
        sent_any = False

        for phong in room_names:
            # "Phòng 201" → "201", "201" → "201"
            so_phong = phong.strip().split()[-1]
            folder = base_dir / so_phong

            if not folder.exists() or not folder.is_dir():
                log.warning(f"[Photo] Không tìm thấy thư mục: {folder.resolve()}")
                continue

            photos = sorted([
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS
            ])[:5]  # Tối đa 5 ảnh/phòng

            if not photos:
                log.warning(f"[Photo] Thư mục {folder} không có ảnh")
                continue

            log.info(f"[Photo] Tìm thấy {len(photos)} ảnh trong {folder}, bắt đầu gửi...")

            # Gửi caption 1 lần rồi gửi từng ảnh
            self.send_text(user_id, f"📸 Ảnh {phong}:")
            time.sleep(0.3)

            for photo_path in photos:
                try:
                    log.info(f"[Photo] Đang gửi: {photo_path.name}")
                    w, h = self._image_size(photo_path)
                    self.sendLocalImage(str(photo_path), user_id, ThreadType.USER, width=w, height=h)
                    time.sleep(0.8)
                    sent_any = True
                    log.info(f"[Photo] ✓ Gửi xong: {photo_path.name} ({w}x{h})")
                except Exception as e:
                    log.error(f"[Photo] ✗ Lỗi gửi {photo_path.name}: {e}")

        if not sent_any:
            self.send_text(
                user_id,
                "📷 Ảnh phòng đang được cập nhật. Bạn muốn mình mô tả chi tiết hơn không?",
            )

    def send_price_photos(self, user_id: str) -> None:
        """Gửi ảnh bảng giá từ price_photos/haru/ và price_photos/mochi/."""
        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
        base = Path(Config.PRICE_PHOTOS_DIR)
        sent_any = False

        for folder_name, label in [("haru", "Haru Staycation"), ("mochi", "Mochi Home")]:
            folder = base / folder_name
            if not folder.exists():
                continue
            photos = sorted([
                f for f in folder.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS
            ])
            if not photos:
                continue
            self.send_text(user_id, f"📋 Bảng giá {label}:")
            time.sleep(0.3)
            for p in photos:
                try:
                    w, h = self._image_size(p)
                    self.sendLocalImage(str(p), user_id, ThreadType.USER, width=w, height=h)
                    time.sleep(0.8)
                    sent_any = True
                except Exception as e:
                    log.error(f"Không gửi được ảnh bảng giá {p}: {e}")

        if not sent_any:
            self.send_text(
                user_id,
                "📋 Bảng giá đang được cập nhật. Bạn có thể hỏi mình giá từng phòng nhé!",
            )

    # ================================================================== #
    # GIAO DIỆN Channel — thông báo chủ nhà
    # ================================================================== #

    def notify_owner(self, text: str) -> None:
        """Gửi thông báo cho chủ nhà — ưu tiên nhóm, fallback DM."""
        sent = False
        if Config.OWNER_GROUP_ID:
            try:
                self.sendMessage(Message(text=text), Config.OWNER_GROUP_ID, ThreadType.GROUP)
                log.info("Đã gửi thông báo vào nhóm chủ nhà")
                sent = True
            except Exception as e:
                log.error(f"Không gửi được vào nhóm: {e}")
        if not sent and Config.OWNER_ZALO_ID:
            try:
                self.sendMessage(Message(text=text), Config.OWNER_ZALO_ID, ThreadType.USER)
                log.info("Đã gửi thông báo DM chủ nhà")
            except Exception as e:
                log.error(f"Không gửi được DM chủ nhà: {e}")

    def call_owner(self) -> None:
        """Beep trên máy tính + đẩy chuông điện thoại qua Telegram."""
        import winsound

        def _beep():
            try:
                for _ in range(5):
                    winsound.Beep(1000, 600)
                    time.sleep(0.2)
            except Exception:
                pass
        threading.Thread(target=_beep, daemon=True).start()
        log.info("[Call] Đã phát beep thông báo")

        if Config.TELEGRAM_TARGET_ID and Path(Config.TG_SESSION + ".session").exists():
            threading.Thread(target=self._telethon_call, daemon=True).start()

    def _telethon_call(self):
        """
        Gọi Telegram cho chủ nhà, cứ 3 phút gọi lại nếu không bắt máy.
        Dừng khi bắt máy hoặc sau 10 lần (30 phút).
        """
        import asyncio, os, hashlib, random
        from telethon import TelegramClient, events
        from telethon.tl import types
        from telethon.tl.functions.phone import RequestCallRequest, DiscardCallRequest
        from telethon.tl.types import PhoneCallProtocol, PhoneCallDiscardReasonHangup

        target_id = int(Config.TELEGRAM_TARGET_ID)

        async def _one_call(client) -> bool:
            """Gọi 1 lần. Trả về True nếu bắt máy, False nếu bỏ lỡ."""
            g_a = os.urandom(256)
            g_a_hash = hashlib.sha256(g_a).digest()
            answered = asyncio.Event()

            @client.on(events.Raw(types.UpdatePhoneCall))
            async def _on_call_update(update):
                if isinstance(update.phone_call, types.PhoneCallAccepted):
                    answered.set()

            try:
                result = await client(RequestCallRequest(
                    user_id=target_id,
                    random_id=random.randint(0, 2**31 - 1),
                    g_a_hash=g_a_hash,
                    protocol=PhoneCallProtocol(
                        udp_p2p=True,
                        udp_reflector=True,
                        min_layer=92,
                        max_layer=92,
                        library_versions=["5.0.0"],
                    ),
                ))
                # Chờ tối đa 30s — nếu bắt máy thì answered.set()
                try:
                    await asyncio.wait_for(answered.wait(), timeout=30)
                    was_answered = True
                    log.info("[Telegram] ✅ Chủ nhà đã bắt máy!")
                except asyncio.TimeoutError:
                    was_answered = False
                    log.info("[Telegram] Không bắt máy (timeout 30s)")

                # Cúp máy — bỏ qua lỗi nếu peer đã thay đổi sau khi bắt máy
                try:
                    await client(DiscardCallRequest(
                        peer=result.phone_call,
                        duration=0,
                        reason=PhoneCallDiscardReasonHangup(),
                        connection_id=0,
                    ))
                except Exception:
                    pass  # Khi đã bắt máy, peer object thay đổi — bỏ qua lỗi này

                return was_answered
            except Exception as e:
                log.error(f"[Telegram] Lỗi trong cuộc gọi: {e}")
                return False
            finally:
                client.remove_event_handler(_on_call_update)

        async def _call_loop():
            client = TelegramClient(
                Config.TG_SESSION,
                2040,
                "b18441a1ff607e10a989891a5462e627",
            )
            await client.connect()
            try:
                for attempt in range(10):  # tối đa 10 lần = 30 phút
                    log.info(f"[Telegram] Gọi lần {attempt + 1}/10 → {target_id}")
                    answered = await _one_call(client)
                    if answered:
                        break
                    if attempt < 9:
                        log.info("[Telegram] Chờ 3 phút rồi gọi lại...")
                        await asyncio.sleep(180)
            finally:
                await client.disconnect()

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_call_loop())
        except Exception as e:
            log.error(f"[Telegram] asyncio lỗi: {e}")
        finally:
            loop.close()

    # ================================================================== #
    # Helper đặc thù Zalo — chống echo, đọc ảnh
    # ================================================================== #

    @staticmethod
    def _image_size(path) -> tuple[int, int]:
        """Đọc kích thước thật của ảnh để gửi đúng tỉ lệ gốc."""
        try:
            from PIL import Image
            with Image.open(path) as img:
                return img.size  # (width, height)
        except Exception:
            return (2560, 1440)  # fallback 16:9 nếu không đọc được

    def _is_bot_echo(self, thread_id: str, msg_text: str) -> bool:
        """Kiểm tra msg_text có phải echo của tin bot vừa gửi không.
        So sánh MD5 fingerprint trong cache 60 giây gần nhất.

        Ưu tiên match cả thread_id lẫn fingerprint.
        Nếu fingerprint khớp nhưng thread_id lệch → vẫn coi là echo
        (Zalo đôi khi echo với thread_id khác) và log cảnh báo.
        """
        if not msg_text:
            return False
        fp = hashlib.md5(msg_text.encode("utf-8", errors="ignore")).hexdigest()
        now = time.time()
        fp_match_other_tid = None
        for tid, stored_fp, ts in self._bot_sent_cache:
            if stored_fp == fp and now - ts < 60:
                if tid == thread_id:
                    return True           # Khớp hoàn toàn
                else:
                    fp_match_other_tid = tid   # Fingerprint khớp, thread_id lệch
        if fp_match_other_tid is not None:
            log.warning(
                f"[Echo] Fingerprint khớp nhưng thread_id lệch "
                f"(stored={fp_match_other_tid}, echo={thread_id}) → vẫn bỏ qua echo"
            )
            return True
        return False

    def _track_sent(self, thread_id: str, text: str):
        """Lưu fingerprint tin text bot vừa gửi để nhận ra echo sau này."""
        fp = hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()
        self._bot_sent_cache.append((thread_id, fp, time.time()))

    def sendLocalImage(self, path, thread_id, thread_type, **kwargs):
        """Override: ghi nhận việc gửi ảnh trước khi thực sự gửi.
        Zalo sẽ echo MessageObject về — cần biết để phân biệt với chủ nhà tự gửi ảnh.
        """
        self._bot_image_threads.append((thread_id, time.time()))
        return super().sendLocalImage(path, thread_id, thread_type, **kwargs)

    def _is_bot_image_echo(self, thread_id: str, window: int = 60) -> bool:
        """Kiểm tra bot có vừa gửi ảnh tới thread_id này trong N giây không."""
        now = time.time()
        for tid, ts in self._bot_image_threads:
            if tid == thread_id and now - ts < window:
                return True
        return False


# Alias tương thích ngược — code/cũ có thể vẫn import HomestayBot
HomestayBot = ZaloChannel
