"""
Cầu nối Python ← Node: nhận tin khách từ Node service (zca-js) rồi đưa vào
"não bộ" (brain.handle). Đây là "onMessage" của kênh Zalo-Node.

Node POST sang  http://127.0.0.1:5005/incoming  với body:
  { userId, uidFrom, text, isSelf, isGroup, dName, ownId }
"""

import json
import time
import logging
import threading

from flask import Flask, request, jsonify

from app.core.config import Config
from app.web_api.stats_util import compute_stats

log = logging.getLogger("bridge")

# Trạng thái bật/tắt bot toàn cục (1 account hiện tại). Lưu ra file để giữ qua restart.
BOT_STATE_FILE = Config.DATA_DIR / "bot_state.json"


ALL_CHANNELS = ("zalo", "meta", "telegram", "tiktok", "shopee")


def _norm_channel(ch: str) -> str:
    """Chuẩn hoá tên kênh. Key per-bot 'kênh:<id>' chỉ lower phần kênh —
    GIỮ NGUYÊN <id> (bot_id/business_id có thể phân biệt hoa thường)."""
    ch = (ch or "").strip()
    if ":" in ch:
        parent, rest = ch.split(":", 1)
        parent = parent.lower()
        parent = "meta" if parent in ("messenger", "instagram") else parent
        return f"{parent}:{rest}"
    ch = ch.lower()
    return "meta" if ch in ("messenger", "instagram") else ch


def _load_bot_state() -> dict:
    try:
        if BOT_STATE_FILE.exists():
            return {"enabled": True, "channels": {}, **json.loads(BOT_STATE_FILE.read_text(encoding="utf-8"))}
    except Exception as e:
        log.error(f"[bot_state] load lỗi: {e}")
    return {"enabled": True, "channels": {}}


def _channel_enabled(state: dict, channel: str) -> bool:
    """Bật/tắt theo thứ tự ưu tiên: per-bot → per-channel → global.
    channel có thể là 'zalo', 'meta', 'telegram', hoặc 'telegram:<bot_id>'."""
    channel = _norm_channel(channel)
    chans = state.get("channels") or {}
    if channel and channel in chans:
        return bool(chans[channel])
    # per-bot key "telegram:123" → fallback lên channel cha "telegram"
    if ":" in channel:
        parent = channel.split(":")[0]
        if parent in chans:
            return bool(chans[parent])
    return bool(state.get("enabled", True))


def _save_bot_state(state: dict) -> None:
    # Ghi ra file tạm rồi rename để tránh file bị corrupt khi nhiều process ghi cùng lúc
    try:
        tmp = BOT_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(BOT_STATE_FILE)
    except Exception as e:
        log.error(f"[bot_state] save lỗi: {e}")


def _norm_text(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _looks_like_recent_bot_reply(conv, text: str, recent: int = 8) -> bool:
    incoming = _norm_text(text)
    if not incoming:
        return True
    for msg in reversed(conv.messages[-recent:]):
        if msg.get("role") != "assistant":
            continue
        if _norm_text(msg.get("content", "")) == incoming:
            return True
    return False


def _conv_summary(uid, conv):
    """Tóm tắt 1 hội thoại cho danh sách (giống dashboard cũ)."""
    last_msg = ""
    for m in reversed(conv.messages):
        c = m.get("content", "")
        if m.get("role") in ("user", "assistant") and not c.startswith("[HỆ THỐNG]"):
            last_msg = c[:100]
            break
    visible = [m for m in conv.messages if not m.get("content", "").startswith("[HỆ THỐNG]")]
    return {
        "user_id": uid,
        "name": getattr(conv, "name", ""),
        "owner_active": conv.is_owner_active(),
        "stage": conv.stage,
        "checkin": conv.checkin,
        "checkout": conv.checkout,
        "selected_room": conv.selected_room,
        "last_msg": last_msg,
        "msg_count": len(visible),
        "last_updated": conv.last_updated.isoformat(),
    }


def create_bridge(brain, conv_manager) -> Flask:
    app = Flask(__name__)

    bot_state = _load_bot_state()

    # CORS thủ công (không cần flask_cors) để web React (cổng 5173) gọi được API này.
    @app.after_request
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return resp

    # Auth thật (users/token/apps trong SQLite) — web React đăng nhập qua đây
    from app.web_api.auth_api import register_auth_routes
    register_auth_routes(app)

    # Gói dịch vụ & nạp tiền
    from app.web_api.billing_api import register_billing_routes
    register_billing_routes(app)

    # Prompt Builder — shop gửi link dữ liệu + hướng dẫn → AI viết prompt
    from app.web_api.prompt_api import register_prompt_routes
    register_prompt_routes(app)

    # Thư viện ảnh — bộ ảnh đặt tên để bot gửi khách
    from app.web_api.photo_api import register_photo_routes
    register_photo_routes(app)

    # Chat tư vấn dịch vụ (bong bóng chat góc web, không cần đăng nhập)
    from app.web_api.support_api import register_support_routes
    register_support_routes(app)

    @app.route("/health")
    def health():
        return {"ok": True}

    # ── Bật/tắt bot toàn cục (nút trên màn hình chính) ─────────────────

    @app.route("/bot-status")
    def bot_status():
        """Trạng thái bot. ?channel=zalo|meta|telegram → của riêng kênh đó (mặc định: cờ chung)."""
        channel = _norm_channel(request.args.get("channel", ""))
        return {"enabled": _channel_enabled(bot_state, channel), "channel": channel or "all"}

    @app.route("/bot-toggle", methods=["POST"])
    def bot_toggle():
        """Bật/tắt bot RIÊNG TỪNG KÊNH. body {enabled: bool, channel?: str, app_name?: str}.
        channel rỗng/"all" = áp cho mọi kênh (vd lúc đăng xuất). Nhắn nhóm để chủ biết."""
        data = request.get_json(force=True, silent=True) or {}
        enabled = bool(data.get("enabled", True))
        channel = _norm_channel(data.get("channel") or "")
        app_name = _norm_text(data.get("app_name") or "")

        chans = bot_state.setdefault("channels", {})
        if not channel or channel == "all":
            for c in ALL_CHANNELS:
                chans[c] = enabled
            bot_state["enabled"] = enabled
            scope = "tất cả kênh"
        else:
            chans[channel] = enabled
            scope = channel
        _save_bot_state(bot_state)

        label = f" {app_name}" if app_name else f" ({scope})"
        if enabled:
            msg = f"🟢 Bot{label} đã được BẬT — AI sẽ tự động tư vấn khách."
        else:
            msg = f"🔴 Bot{label} đã được TẮT — admin tự trả lời khách, AI tạm dừng."
        try:
            brain.channel.notify_owner(msg)
        except Exception as e:
            log.error(f"[bot-toggle] báo nhóm lỗi: {e}")
        log.info(f"[bot-toggle] channel={channel or 'all'} enabled={enabled}")
        return {"ok": True, "enabled": enabled, "channel": channel or "all"}

    # ── API hội thoại (thay cho dashboard.py) ──────────────────────────

    @app.route("/conversations")
    def list_conversations():
        # Trả mảng (giữ shape cũ cho UI), mặc định 200 khách mới nhất —
        # 10k khách không đổ hết về mỗi lần web tự làm mới. ?limit=&offset=.
        try:
            limit = min(max(int(request.args.get("limit", 200)), 1), 1000)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 200, 0
        rows = [
            _conv_summary(uid, conv)
            for uid, conv in list(conv_manager._sessions.items())
        ]
        rows.sort(key=lambda r: r["last_updated"], reverse=True)
        return jsonify(rows[offset:offset + limit])

    @app.route("/conversations/<user_id>")
    def get_conversation(user_id):
        conv = conv_manager._sessions.get(user_id)
        if not conv:
            return {"error": "not found"}, 404
        msgs = [
            {"role": m.get("role"), "content": m.get("content", "")}
            for m in conv.messages
            if not m.get("content", "").startswith("[HỆ THỐNG]")
        ]
        return jsonify({
            "user_id": user_id,
            "name": getattr(conv, "name", ""),
            "owner_active": conv.is_owner_active(),
            "stage": conv.stage,
            "checkin": conv.checkin,
            "checkout": conv.checkout,
            "messages": msgs,
        })

    @app.route("/conversations/<user_id>/toggle-bot", methods=["POST"])
    def toggle_bot(user_id):
        """Bật/tắt bot cho 1 khách. body {bot_on: bool} — bot_on=False nghĩa là chủ tiếp quản."""
        data = request.get_json(force=True, silent=True) or {}
        bot_on = bool(data.get("bot_on", True))
        conv = conv_manager.get(user_id)
        conv.set_owner_active(not bot_on)  # bot bật ↔ owner_active tắt
        conv_manager.save()
        return {"ok": True, "bot_on": bot_on, "owner_active": conv.is_owner_active()}

    @app.route("/conversations/<user_id>/send", methods=["POST"])
    def send_message(user_id):
        """Chủ nhà gửi tin thủ công từ dashboard → gửi thật qua kênh + lưu vào lịch sử."""
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "tin trống"}, 400
        try:
            brain.channel.send_text(user_id, text)
        except Exception as e:
            log.error(f"[send] lỗi gửi {user_id}: {e}")
            return {"ok": False, "error": str(e)}, 500
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(text)
        conv.set_owner_active(True)   # chủ đang xử lý → bot dừng tự động trả lời
        conv_manager.save()
        return {"ok": True}

    @app.route("/conversations/<user_id>", methods=["DELETE"])
    def reset_conversation(user_id):
        conv_manager.reset(user_id)
        return {"ok": True}

    @app.route("/stats")
    def conv_stats():
        return jsonify(compute_stats(
            conv_manager, request.args.get("from"), request.args.get("to")))

    @app.route("/incoming", methods=["POST"])
    def incoming():
        data = request.get_json(force=True, silent=True) or {}

        # Tin nhóm → bỏ qua (bot chỉ tư vấn 1-1)
        if data.get("isGroup"):
            return {"ok": True, "skipped": "group"}

        user_id = str(data.get("userId") or "").strip()
        text = (data.get("text") or "").strip()
        if not user_id:
            return {"ok": False, "error": "missing userId"}, 400

        # Tin do chính tài khoản này gửi:
        #  - ownerTyped=True → chủ nhà tự tay nhắn khách → bật owner-takeover (bot dừng 48h)
        #  - còn lại         → echo tin bot tự gửi (Node đã lọc msgId) → bỏ qua
        if data.get("isSelf"):
            if data.get("ownerTyped"):
                conv = conv_manager.get(user_id)
                if not text:
                    return {"ok": True, "skipped": "self-non-text"}
                channel = getattr(brain, "channel", None)
                is_recent_echo = (
                    hasattr(channel, "is_recent_bot_echo")
                    and channel.is_recent_bot_echo(user_id, text)
                )
                if is_recent_echo or _looks_like_recent_bot_reply(conv, text):
                    log.info(f"[Echo] self message from bot {user_id} -> skip owner_takeover")
                    return {"ok": True, "skipped": "self-echo"}
                if not conv.is_owner_active():
                    conv.set_owner_active(True)
                    conv_manager.save()
                    log.info(f"[OwnerTakeover] Chủ nhà tự nhắn {user_id} → bot dừng auto-reply 48h")
                return {"ok": True, "owner_takeover": True}
            return {"ok": True, "skipped": "self-echo"}

        # Bot kênh Zalo bị tắt → không auto-reply khách
        if not _channel_enabled(bot_state, "zalo"):
            log.info(f"[Skip] bot_disabled {user_id}")
            return {"ok": True, "skipped": "bot_disabled"}

        # Gói dịch vụ hết hạn → bot ngừng tự trả lời (gia hạn trong web → chạy lại)
        from app.core import billing
        if not billing.has_active_subscription():
            log.info(f"[Skip] billing_expired {user_id}")
            return {"ok": True, "skipped": "billing_expired"}

        conv = conv_manager.get(user_id)

        # Cập nhật tên hiển thị nếu Node truyền dName
        d_name = (data.get("dName") or "").strip()
        if d_name and d_name != conv.name:
            conv.name = d_name

        # Chủ nhà đang tiếp quản → bot im lặng
        if conv.is_owner_active():
            log.info(f"[Skip] owner_active {user_id}")
            return {"ok": True, "skipped": "owner_active"}

        # Tin không có text (sticker/media) — chỉ rep nếu là khách mới
        if not text and len(conv.messages) > 0:
            return {"ok": True, "skipped": "non-text non-first"}

        log.info(f"[MSG] {user_id} | {text[:80]!r}")

        # Xử lý nền để trả HTTP về Node ngay (brain gọi AI + gửi nhiều tin, chậm)
        def _run():
            try:
                time.sleep(Config.REPLY_DELAY)
                brain.handle(user_id, text)
            except Exception as e:
                log.error(f"[Brain] lỗi xử lý {user_id}: {e}", exc_info=True)
                try:
                    brain.channel.send_text(
                        user_id,
                        "Xin lỗi, hệ thống đang gặp sự cố nhỏ. Chủ nhà sẽ liên hệ lại bạn sớm! 🙏",
                    )
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    return app
