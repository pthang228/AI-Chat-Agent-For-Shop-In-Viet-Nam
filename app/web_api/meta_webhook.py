"""
Webhook Meta (Facebook Messenger + Instagram) — "onMessage" của kênh Meta.

Meta đẩy tin khách về đây qua HTTPS (cần PUBLIC_BASE_URL = ngrok/domain):
  - GET  /fb/webhook   → xác minh đăng ký (hub.challenge)
  - POST /fb/webhook   → nhận sự kiện tin nhắn → brain.handle
  - GET  /media/<path> → phục vụ ảnh cho Messenger/IG tải về (Send API cần URL công khai)

Phân biệt nền tảng theo `object` của payload: "page" → Messenger, "instagram" → IG.
user_id đưa vào brain có tiền tố "fb:" / "ig:" (xem app/channels/meta.py).

Tôn trọng nút BẬT/TẮT bot toàn cục (đọc data/bot_state.json mỗi tin) và owner-takeover.
"""

import hmac
import time
import hashlib
import logging
import threading
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

from app.core.config import Config
from app.channels import meta_graph
from app.web_api.bridge import _load_bot_state  # dùng chung trạng thái bật/tắt toàn cục

log = logging.getLogger("meta_webhook")


def create_meta_webhook(brain, conv_manager, store=None) -> Flask:
    app = Flask(__name__)

    # CORS để web React (cổng 5173) gọi được các API /meta/*
    @app.after_request
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    @app.route("/health")
    def health():
        return {"ok": True}

    # ── Luồng "Kết nối Facebook" (OAuth) cho khách tự gắn Page ──────────

    @app.route("/meta/config")
    def meta_config():
        """UI hỏi: app đã cấu hình chưa + app_id để mở FB Login."""
        return {
            "app_id": Config.FB_APP_ID,
            "configured": bool(Config.FB_APP_ID and Config.FB_APP_SECRET),
        }

    @app.route("/meta/connect", methods=["POST"])
    def meta_connect():
        """Nhận user token (từ FB Login ở UI) → liệt kê Page → lưu token + subscribe."""
        if store is None:
            return {"ok": False, "error": "store chưa sẵn sàng"}, 500
        data = request.get_json(force=True, silent=True) or {}
        short = (data.get("userToken") or "").strip()
        if not short:
            return {"ok": False, "error": "thiếu userToken"}, 400
        try:
            long_token = meta_graph.exchange_long_lived_user_token(short)
            pages = meta_graph.list_pages(long_token)
        except Exception as e:
            log.error(f"[meta/connect] lỗi: {e}")
            return {"ok": False, "error": str(e)}, 502

        result = []
        for pg in pages:
            pid = str(pg.get("id"))
            tok = pg.get("access_token")
            iga = pg.get("instagram_business_account") or {}
            store.upsert(pid, name=pg.get("name"), access_token=tok,
                         ig_id=iga.get("id"), ig_username=iga.get("username"))
            subscribed = meta_graph.subscribe_page(pid, tok) if tok else False
            result.append({
                "page_id": pid, "name": pg.get("name"),
                "ig_username": iga.get("username"), "subscribed": subscribed,
            })
        return {"ok": True, "pages": result}

    @app.route("/meta/pages")
    def meta_pages():
        return jsonify(store.list_pages() if store else [])

    @app.route("/meta/pages/<page_id>", methods=["DELETE"])
    def meta_remove(page_id):
        if store:
            store.remove(page_id)
        return {"ok": True}

    # Ảnh phòng/bảng giá — Messenger/IG tải qua URL công khai
    @app.route("/media/<path:filename>")
    def media(filename):
        return send_from_directory(str(Path(Config.MEDIA_DIR).resolve()), filename)

    # ── Xác minh webhook (Meta gọi GET lúc đăng ký) ──
    @app.route("/fb/webhook", methods=["GET"])
    def verify():
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == Config.FB_VERIFY_TOKEN:
            log.info("[Meta] webhook đã xác minh")
            return challenge or "", 200
        log.warning("[Meta] verify token không khớp")
        return "verify token mismatch", 403

    # ── Nhận sự kiện (Meta POST) ──
    @app.route("/fb/webhook", methods=["POST"])
    def receive():
        raw = request.get_data()
        if not _valid_signature(raw, request.headers.get("X-Hub-Signature-256", "")):
            log.warning("[Meta] sai chữ ký webhook → bỏ qua")
            return "bad signature", 403

        data = request.get_json(force=True, silent=True) or {}
        obj = data.get("object")
        platform = "ig" if obj == "instagram" else "fb"
        for entry in data.get("entry", []):
            entry_id = str(entry.get("id") or "")
            # IG: entry.id = id tài khoản IG → map về page_id; FB: entry.id = page_id
            if platform == "ig" and store:
                page_id = store.page_for_ig(entry_id) or entry_id
            else:
                page_id = entry_id
            for ev in entry.get("messaging", []):
                _dispatch(platform, page_id, ev)
        return "EVENT_RECEIVED", 200

    def _valid_signature(raw: bytes, header: str) -> bool:
        secret = Config.FB_APP_SECRET
        if not secret:
            return True  # chưa cấu hình secret (dev/mock) → bỏ qua kiểm tra
        if not header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header)

    def _dispatch(platform: str, page_id: str, ev: dict):
        sender = str((ev.get("sender") or {}).get("id") or "")
        if not sender:
            return
        msg = ev.get("message") or {}
        if msg.get("is_echo"):
            return  # tin do Page tự gửi → bỏ qua
        text = (msg.get("text") or "").strip()
        if not text:
            return  # scaffold: chỉ xử lý text (sticker/ảnh/postback để sau)

        # user_id đa Page: platform:page_id:recipient → trả lời đúng token Page
        user_id = f"{platform}:{page_id}:{sender}"

        # Bot tắt toàn cục (đọc lại file mỗi tin để đồng bộ cả khi bridge Zalo đổi)
        if not _load_bot_state().get("enabled", True):
            log.info(f"[Meta] bot đang TẮT → bỏ qua {user_id}")
            return

        conv = conv_manager.get(user_id)
        if conv.is_owner_active():
            log.info(f"[Meta] owner_active {user_id} → im lặng")
            return

        log.info(f"[Meta][{platform}] page={page_id} {sender} | {text[:80]!r}")

        def _run():
            try:
                time.sleep(Config.REPLY_DELAY)
                brain.handle(user_id, text)
            except Exception as e:
                log.error(f"[Meta] lỗi xử lý {user_id}: {e}", exc_info=True)
                try:
                    brain.channel.send_text(
                        user_id,
                        "Xin lỗi, hệ thống đang gặp sự cố nhỏ. Chủ nhà sẽ liên hệ lại bạn sớm! 🙏",
                    )
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    return app
