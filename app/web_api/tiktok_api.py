"""
TikTok — webhook nhận tin + API hội thoại + kết nối ĐA KHÁCH cho kênh TikTok.

Nhận tin qua WEBHOOK (TikTok đẩy về, cần PUBLIC_BASE_URL như Meta):
  - GET  /tiktok/webhook → xác minh khi khai webhook (echo challenge)
  - POST /tiktok/webhook → nhận sự kiện tin nhắn → brain.handle

Khách (homestay) DÁN access token TikTok Business trong web → /tiktok/connect
xác thực (best-effort) → lưu TikTokStore. Flask (cổng 5008) phục vụ web React.
Tôn trọng nút bật/tắt bot (data/bot_state.json) + owner-takeover, giống mọi kênh.
"""

import time
import json
import logging
import threading

import requests
from flask import Flask, request, jsonify

from app.core.config import Config
from app.web_api.bridge import _load_bot_state, _save_bot_state, _channel_enabled, _conv_summary
from app.web_api.stats_util import compute_stats
from app.web_api.api_guard import install_cors, install_auth_guard, DedupCache, submit

log = logging.getLogger("tiktok_api")

_dedup = DedupCache(500)   # nhớ message_id đã xử lý — TikTok gửi lại khi ta 200 chậm


def _uid(business_id, user_open_id):
    return f"tt:{business_id}:{user_open_id}" if business_id else f"tt:{user_open_id}"


def parse_event(payload: dict):
    """Payload webhook TikTok → list[(business_id, user_open_id, text, msg_id, name)].

    Mapping field gói gọn ở đây (spec TikTok có thể đổi khi được cấp quyền).
    Chấp nhận 2 dạng:
      1. {"event": "message", "business_id", "sender_id", "text", "message_id"?, "sender_name"?}
      2. {"events": [ {như trên}, ... ]}  (TikTok gộp nhiều sự kiện 1 request)
    Bỏ qua tin echo (sender_id == business_id — chính mình gửi).
    """
    events = payload.get("events")
    if not isinstance(events, list):
        events = [payload]
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        etype = str(ev.get("event") or ev.get("type") or "").lower()
        if etype and "message" not in etype:
            continue
        business_id = str(ev.get("business_id") or ev.get("account_id") or "").strip()
        sender = str(ev.get("sender_id") or ev.get("user_open_id") or ev.get("from_user_id") or "").strip()
        raw_msg = ev.get("message")
        if isinstance(raw_msg, dict):
            text = str(raw_msg.get("text") or "")
            msg_id = str(raw_msg.get("message_id") or raw_msg.get("msg_id") or raw_msg.get("id") or "")
        else:
            text = str(ev.get("text") or "")
            msg_id = str(ev.get("message_id") or ev.get("msg_id") or "")
        text = text.strip()
        name = str(ev.get("sender_name") or ev.get("nickname") or "").strip()
        if not sender:
            continue
        if business_id and sender == business_id:   # echo tin chính mình gửi
            continue
        out.append((business_id, sender, text, msg_id, name))
    return out


def handle_event(business_id, sender, text, name, brain, conv_manager, store=None):
    """Áp gate bật/tắt + owner-takeover rồi đẩy vào brain (chạy nền) — như Telegram."""
    user_id = _uid(business_id or None, sender)

    if name:
        conv_for_name = conv_manager.get(user_id)
        if name != conv_for_name.name:
            conv_for_name.name = name

    _ch_key = f"tiktok:{business_id}" if business_id else "tiktok"
    if not _channel_enabled(_load_bot_state(), _ch_key):
        log.info(f"[TT] bot đang TẮT ({_ch_key}) → bỏ qua {user_id}")
        return

    conv = conv_manager.get(user_id)
    if conv.is_owner_active():
        log.info(f"[TT] owner_active {user_id} → im lặng")
        return

    if not text and len(conv.messages) > 0:   # sticker/media không phải tin đầu
        return

    # Gói/quota AI của CHỦ account (ghi 1 lượt khi cho qua); chưa gắn chủ → gate toàn cục
    from app.core import billing
    owner = store.get_owner_username(business_id) if (store and business_id) else None
    if not billing.channel_gate(owner):
        log.info(f"[TT] gói/quota chủ ({owner}) không cho phép → bỏ qua {user_id}")
        return

    log.info(f"[TT] biz={business_id} {sender} | {text[:80]!r}")

    def _run():
        try:
            time.sleep(Config.REPLY_DELAY)
            brain.channel.set_ctx(business_id or None)   # notify/call báo đúng chủ account
            brain.handle(user_id, text)
        except Exception as e:
            log.error(f"[TT] lỗi xử lý {user_id}: {e}", exc_info=True)
            try:
                brain.channel.send_text(
                    user_id,
                    "Xin lỗi, hệ thống đang gặp sự cố nhỏ. Chủ nhà sẽ liên hệ lại bạn sớm! 🙏",
                )
            except Exception:
                pass

    submit(_run)


def create_tiktok_api(brain, conv_manager, channel, store=None) -> Flask:
    app = Flask(__name__)
    install_cors(app)
    install_auth_guard(
        app,
        public_exact={"/tiktok/webhook", "/tiktok/config"},
        public_prefixes=("/media/outbox",),
        # Nhân viên: chỉ hộp thư — cấm kết nối/ngắt account, đặt chủ
        staff_deny=(
            "/tiktok/connect", "DELETE /tiktok/accounts", "POST /tiktok/accounts",
            "/tiktok/set-owner", "DELETE /tiktok/conversations",
        ),
    )

    # Công cụ chat: gửi ảnh/video/ghi âm + chốt đơn 1 chạm (dashboard)
    from app.web_api.chat_tools import register_chat_tools
    register_chat_tools(app, "/tiktok", conv_manager, channel, account="tiktok")

    @app.route("/health")
    def health():
        return {"ok": True}

    @app.route("/tiktok/config")
    def tt_config():
        return {
            "env_configured": bool(channel.access_token),
            "verify_token": Config.TIKTOK_VERIFY_TOKEN,
            "webhook_path": "/tiktok/webhook",
            "public_base_url": Config.PUBLIC_BASE_URL,
        }

    # ── Webhook TikTok ─────────────────────────────────────────────────

    @app.route("/tiktok/webhook", methods=["GET"])
    def tt_verify():
        """Xác minh khi khai webhook: echo challenge (chấp nhận cả kiểu hub.* của Meta
        lẫn ?challenge= của TikTok) nếu verify token khớp."""
        token = request.args.get("hub.verify_token") or request.args.get("verify_token") or ""
        challenge = request.args.get("hub.challenge") or request.args.get("challenge") or ""
        if Config.TIKTOK_VERIFY_TOKEN and token and token != Config.TIKTOK_VERIFY_TOKEN:
            return "verify token mismatch", 403
        return challenge or "ok", 200

    @app.route("/tiktok/webhook", methods=["POST"])
    def tt_receive():
        payload = request.get_json(force=True, silent=True) or {}
        # Một số nền tảng xác minh bằng POST {"challenge": X} → echo lại
        if "challenge" in payload and "event" not in payload and "events" not in payload:
            return jsonify({"challenge": payload["challenge"]})
        for business_id, sender, text, msg_id, name in parse_event(payload):
            if _dedup.seen(msg_id):
                log.info(f"[TT] bỏ qua tin trùng msg_id={msg_id}")
                continue
            handle_event(business_id, sender, text, name, brain, conv_manager, store)
        return {"ok": True}

    # ── Kết nối ĐA KHÁCH: dán access token trong web ───────────────────

    @app.route("/tiktok/connect", methods=["POST"])
    def tt_connect():
        if store is None:
            return {"ok": False, "error": "store chưa sẵn sàng"}, 500
        data = request.get_json(force=True, silent=True) or {}
        token = (data.get("access_token") or "").strip()
        business_id = (data.get("business_id") or "").strip()
        name = (data.get("name") or "").strip()
        if not token:
            return {"ok": False, "error": "thiếu access_token"}, 400
        if not business_id:
            return {"ok": False, "error": "thiếu business_id"}, 400

        from app.web_api.auth_api import current_username
        owner = current_username()   # chủ homestay đang đăng nhập (để tính quota/gói)

        # Xác thực best-effort: hỏi TikTok thông tin account. API chưa mở cho app
        # này thì vẫn lưu (verified=false) để dùng được ngay khi TikTok duyệt.
        verified = False
        try:
            r = requests.get(
                f"{Config.TIKTOK_API_BASE.rstrip('/')}/business/get/",
                headers={"Access-Token": token},
                params={"business_id": business_id, "fields": json.dumps(["username", "display_name"])},
                timeout=15,
            )
            if r.status_code == 200 and r.json().get("code") == 0:
                info = r.json().get("data", {})
                name = name or info.get("display_name", "")
                verified = True
                store.upsert(business_id, access_token=token, name=name,
                             username=info.get("username", ""), owner_username=owner)
        except Exception as e:
            log.warning(f"[TT connect] không xác thực được token ({e}) — vẫn lưu")
        if not verified:
            store.upsert(business_id, access_token=token, name=name, owner_username=owner)
        return {"ok": True, "verified": verified, "account": {
            "business_id": business_id, "name": name,
        }}

    @app.route("/tiktok/accounts")
    def tt_accounts():
        accounts = store.list_accounts() if store else []
        state = _load_bot_state()
        for a in accounts:
            a["bot_enabled"] = _channel_enabled(state, f"tiktok:{a['business_id']}")
        return jsonify(accounts)

    @app.route("/tiktok/accounts/<business_id>", methods=["DELETE"])
    def tt_remove(business_id):
        if store:
            store.remove(business_id)
        return {"ok": True}

    @app.route("/tiktok/accounts/<business_id>/toggle", methods=["POST"])
    def tt_account_toggle(business_id):
        """Bật/tắt riêng 1 account TikTok. body {enabled: bool}."""
        data = request.get_json(force=True, silent=True) or {}
        enabled = bool(data.get("enabled", True))
        state = _load_bot_state()
        state.setdefault("channels", {})[f"tiktok:{business_id}"] = enabled
        _save_bot_state(state)
        log.info(f"[TT] account {business_id} toggle → enabled={enabled}")
        return {"ok": True, "business_id": business_id, "enabled": enabled}

    @app.route("/tiktok/set-owner", methods=["POST"])
    def tt_set_owner():
        """ADMIN chọn chủ = 1 người ĐÃ nhắn account (như Telegram).
        body {user_id: 'tt:<biz>:<open_id>', name?}."""
        data = request.get_json(force=True, silent=True) or {}
        uid = (data.get("user_id") or "").strip()
        name = data.get("name") or ""
        parts = uid.split(":")
        if len(parts) >= 3 and store:
            store.set_owner(parts[1], ":".join(parts[2:]), name)
            return {"ok": True}
        return {"ok": False, "error": "user_id không hợp lệ"}, 400

    # ── Thống kê ───────────────────────────────────────────────────────

    @app.route("/tiktok/stats")
    def tt_stats():
        business_id = request.args.get("business_id", "")

        def _flt(u):
            if not u.startswith("tt:"):
                return False
            if business_id:
                parts = u.split(":")
                return len(parts) >= 3 and parts[1] == business_id
            return True

        return jsonify(compute_stats(
            conv_manager, request.args.get("from"), request.args.get("to"),
            uid_filter=_flt))

    # ── Hội thoại (lọc theo account) ───────────────────────────────────

    @app.route("/tiktok/conversations")
    def tt_conversations():
        business_id = request.args.get("business_id", "")
        try:
            limit = min(max(int(request.args.get("limit", 50)), 1), 200)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 50, 0
        rows = []
        for uid, conv in list(conv_manager._sessions.items()):
            if not uid.startswith("tt:"):
                continue
            parts = uid.split(":")
            uid_biz = parts[1] if len(parts) >= 3 else ""
            if business_id and uid_biz != business_id:
                continue
            rows.append(_conv_summary(uid, conv))
        rows.sort(key=lambda r: r["last_updated"], reverse=True)
        total = len(rows)
        return jsonify({"total": total, "offset": offset, "limit": limit,
                        "items": rows[offset:offset + limit]})

    @app.route("/tiktok/conversations/<user_id>")
    def tt_conversation(user_id):
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
            "avatar": getattr(conv, "avatar", "") or "",
            "owner_active": conv.is_owner_active(),
            "stage": conv.stage,
            "assigned_to": getattr(conv, "assigned_to", "") or "",
            "messages": msgs,
        })

    @app.route("/tiktok/conversations/<user_id>/send", methods=["POST"])
    def tt_send_message(user_id):
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "tin trống"}, 400
        parts = user_id.split(":")
        business_id = parts[1] if len(parts) >= 3 else None
        try:
            channel.set_ctx(business_id)
            channel.send_text(user_id, text)
        except Exception as e:
            log.error(f"[tt send] lỗi gửi {user_id}: {e}")
            return {"ok": False, "error": str(e)}, 500
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(text)
        conv.set_owner_active(True)
        conv_manager.save()
        # Bot học từ hội thoại: chủ trả lời tay → AI đề xuất mẩu tri thức (nền, chờ duyệt)
        from app.core import knowledge_learn
        submit(knowledge_learn.suggest_from_reply, user_id, "tiktok", list(conv.messages), text)
        return {"ok": True}

    @app.route("/tiktok/conversations/<user_id>/toggle-bot", methods=["POST"])
    def tt_toggle_bot(user_id):
        data = request.get_json(force=True, silent=True) or {}
        bot_on = bool(data.get("bot_on", True))
        conv = conv_manager.get(user_id)
        conv.set_owner_active(not bot_on)
        conv_manager.save()
        return {"ok": True, "bot_on": bot_on, "owner_active": conv.is_owner_active()}

    @app.route("/tiktok/conversations/<user_id>", methods=["DELETE"])
    def tt_reset(user_id):
        conv_manager.reset(user_id)
        return {"ok": True}

    return app
