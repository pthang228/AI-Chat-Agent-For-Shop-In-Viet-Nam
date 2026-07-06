"""
CÔNG CỤ CHAT dùng chung cho MỌI server kênh (đăng ký 1 dòng/kênh):

1. POST {prefix}/conversations/<uid>/send-media  (multipart "file")
   Chủ đính kèm ẢNH / VIDEO / GHI ÂM từ dashboard → lưu media/outbox/ →
   - Ảnh  : channel.send_image_url (mọi kênh đã có — Zalo tải về gửi file thật,
            Meta/TikTok/Shopee/OA gửi URL công khai, Telegram upload).
   - Video/Ghi âm: channel.send_file — Telegram upload THẬT; kênh khác gửi
            LINK công khai (khách bấm mở xem) → cần PUBLIC_BASE_URL.
   URL công khai serve qua cổng Meta 5006 (/media/... đã có sẵn).

2. POST {prefix}/conversations/<uid>/make-order
   "Chốt đơn" 1 chạm: AI bóc hội thoại hiện tại → tạo ĐƠN NHÁP trong Sổ đơn
   hàng (orders.create_from_conversation — cùng máy móc với bot tự chốt).

3. Câu trả lời mẫu (canned replies) — CHỈ đăng ký ở bridge (kho chung 1 chỗ):
   GET/POST /canned · DELETE /canned/<id>

Mọi route đều sau auth guard (Bearer) vì không nằm trong public list.
"""

import logging
import mimetypes
import uuid
from pathlib import Path

from flask import request, jsonify, send_from_directory

from app.core.config import Config

log = logging.getLogger("chat_tools")

OUTBOX_DIR = Path(Config.MEDIA_DIR) / "outbox"
MAX_MEDIA_MB = 25                      # trần dung lượng 1 tệp đính kèm
_ALLOWED = {                           # phần mở rộng theo loại (chặn file lạ)
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
    "video": {".mp4", ".mov", ".webm", ".m4v"},
    "audio": {".mp3", ".m4a", ".ogg", ".oga", ".wav", ".webm", ".aac"},
}


def _kind_of(filename: str, mime: str) -> str:
    """image | video | audio | '' (không nhận)."""
    mime = (mime or "").lower()
    for k in ("image", "video", "audio"):
        if mime.startswith(k + "/"):
            return k
    ext = Path(filename or "").suffix.lower()
    for k, exts in _ALLOWED.items():
        if ext in exts:
            return k
    return ""


def _public_media_base() -> str:
    """Gốc URL cho file media. Ưu tiên PUBLIC_BASE_URL (ngrok/domain — nền tảng
    NGOÀI như Meta/TikTok/Shopee/Zalo OA tải được); chưa có → host CỦA CHÍNH
    server đang xử lý (Zalo Node/localhost tải từ đúng bridge). request.host_url
    tự trả 'http://127.0.0.1:5005/' khi gọi vào bridge, '.../5006/' khi gọi meta…"""
    base = (Config.PUBLIC_BASE_URL or "").rstrip("/")
    return base or request.host_url.rstrip("/")


def register_chat_tools(app, prefix: str, conv_manager, channel, account: str,
                        with_canned: bool = False):
    pf = prefix.rstrip("/")

    # Serve file media/outbox công khai (Zalo Node/khách tải về; <img>/<video>
    # không gửi Bearer được). Chặn traversal bằng Path(name).name.
    @app.route("/media/outbox/<path:name>", endpoint=f"ct_outbox_{account}")
    def outbox_file(name):
        return send_from_directory(str(OUTBOX_DIR.resolve()), Path(name).name)

    @app.route(f"{pf}/conversations/<user_id>/send-media", methods=["POST"],
               endpoint=f"ct_send_media_{account}")
    def send_media(user_id):
        f = request.files.get("file")
        if f is None or not f.filename:
            return {"ok": False, "error": "thiếu file"}, 400
        kind = _kind_of(f.filename, f.mimetype)
        if not kind:
            return {"ok": False, "error": "Chỉ nhận ảnh / video / ghi âm"}, 400

        ext = Path(f.filename).suffix.lower() or mimetypes.guess_extension(f.mimetype or "") or ".bin"
        OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{ext}"
        path = OUTBOX_DIR / name
        f.save(path)
        if path.stat().st_size > MAX_MEDIA_MB * 1024 * 1024:
            path.unlink(missing_ok=True)
            return {"ok": False, "error": f"Tệp quá lớn (tối đa {MAX_MEDIA_MB}MB)"}, 400

        url = f"{_public_media_base()}/media/outbox/{name}"
        caption = (request.form.get("caption") or "").strip()

        # set_ctx đa khách (tiktok/shopee/oa/tg) — parse account id từ user_id
        parts = user_id.split(":")
        if hasattr(channel, "set_ctx"):
            channel.set_ctx(parts[1] if len(parts) >= 3 else None)
        try:
            # Điểm vào THỐNG NHẤT: send_file xử lý mọi loại (ảnh qua URL/upload/path
            # tuỳ kênh; video/ghi âm upload thật ở TG, link ở kênh URL, không hỗ trợ ở Zalo cá nhân)
            sent_real = bool(channel.send_file(user_id, path, url, kind, caption))
        except Exception as e:
            log.error(f"[media] gửi {kind} {user_id} lỗi: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}, 500
        if not sent_real:
            kind_vn = {"image": "ảnh", "video": "video", "audio": "ghi âm"}.get(kind, "tệp")
            return {"ok": False, "error":
                    f"Kênh này chưa gửi được {kind_vn} (Zalo cá nhân chỉ gửi được ảnh; "
                    f"video/ghi âm hãy dùng Telegram, hoặc cấu hình PUBLIC_BASE_URL cho các kênh khác)."}, 502

        label = {"image": "[Đã gửi ảnh 📷]", "video": "[Đã gửi video 🎬]",
                 "audio": "[Đã gửi ghi âm 🎤]"}[kind]
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(label + (f" {caption}" if caption else ""))
        conv.set_owner_active(True)   # chủ đang xử lý → bot ngừng auto-reply
        conv_manager.save()
        return {"ok": True, "kind": kind, "url": url}

    @app.route(f"{pf}/conversations/<user_id>/assign", methods=["POST"],
               endpoint=f"ct_assign_{account}")
    def assign_conv(user_id):
        """PHÂN CÔNG hội thoại cho 1 nhân viên (team inbox). body {username}
        — rỗng = bỏ phân công. Không đổi last_updated (không xáo thứ tự inbox)."""
        if user_id not in conv_manager._sessions:
            return {"ok": False, "error": "Không tìm thấy hội thoại"}, 404
        d = request.get_json(force=True, silent=True) or {}
        username = (d.get("username") or "").strip().lower()
        conv = conv_manager.get(user_id)
        conv.assigned_to = username
        conv_manager.save()
        log.info(f"[assign] {account} {user_id} → {username or '(bỏ gán)'}")
        return {"ok": True, "assigned_to": username}

    @app.route(f"{pf}/conversations/<user_id>/broadcast-send", methods=["POST"],
               endpoint=f"ct_bc_send_{account}")
    def broadcast_send(user_id):
        """Gửi 1 tin BROADCAST cho khách này (worker Tin nhắn hàng loạt ở bridge
        gọi HTTP nội bộ vào đây). Chạy trên ĐÚNG tiến trình kênh → dùng channel +
        store + conv cache của chính nó (không hỏng token/outbox cross-process).
        Khác /send: KHÔNG bật owner_active (bot vẫn auto-reply khi khách trả lời)."""
        d = request.get_json(force=True, silent=True) or {}
        text = (d.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "nội dung trống"}, 400
        if user_id not in conv_manager._sessions:
            return {"ok": False, "error": "Không tìm thấy hội thoại"}, 404
        parts = user_id.split(":")
        if hasattr(channel, "set_ctx"):
            channel.set_ctx(parts[1] if len(parts) >= 3 else None)
        try:
            channel.send_text(user_id, text)
        except Exception as e:
            log.error(f"[broadcast] gửi {account} {user_id} lỗi: {e}")
            return {"ok": False, "error": str(e)[:300]}, 502
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(text)
        conv_manager.save()
        return {"ok": True}

    @app.route(f"{pf}/conversations/<user_id>/make-order", methods=["POST"],
               endpoint=f"ct_make_order_{account}")
    def make_order(user_id):
        """Chốt đơn 1 chạm: AI bóc hội thoại → đơn NHÁP (duyệt ở mục Đơn hàng)."""
        conv = conv_manager._sessions.get(user_id)
        if not conv or not conv.messages:
            return {"ok": False, "error": "Hội thoại trống — chưa có gì để chốt"}, 400
        from app.core import orders
        o = orders.create_from_conversation(user_id, conv, channel=account)
        if not o:
            return {"ok": False, "error": "Không tạo được đơn (xem log)"}, 500
        log.info(f"[chốt đơn] {account} {user_id} → {o['code']}")
        return {"ok": True, "order": {
            "id": o["id"], "code": o["code"], "total": o.get("total") or 0,
            "customer_name": o.get("customer_name") or "",
        }}

    # ── Câu trả lời mẫu (kho CHUNG — chỉ gắn ở bridge 5005) ─────────
    if with_canned:
        from app.core.db import get_db
        db = get_db()

        @app.route("/canned")
        def canned_list():
            rows = db.query("SELECT id, title, content FROM canned_replies ORDER BY id")
            return jsonify([dict(r) for r in rows])

        @app.route("/canned", methods=["POST"])
        def canned_add():
            from datetime import datetime
            d = request.get_json(force=True, silent=True) or {}
            content = (d.get("content") or "").strip()
            if not content:
                return {"ok": False, "error": "nội dung trống"}, 400
            title = (d.get("title") or "").strip()[:60] or content[:30]
            cur = db.execute(
                "INSERT INTO canned_replies (title, content, created_at) VALUES (?,?,?)",
                (title, content[:2000], datetime.now().isoformat()))
            return {"ok": True, "id": cur.lastrowid, "title": title}

        @app.route("/canned/<int:cid>", methods=["DELETE"])
        def canned_del(cid):
            db.execute("DELETE FROM canned_replies WHERE id=?", (cid,))
            return {"ok": True}

    return app
