"""
Shopee — webhook nhận tin + API hội thoại + kết nối ĐA KHÁCH cho kênh Shopee.

Nhận tin qua WEBHOOK PUSH (Shopee đẩy về, khai trên open.shopee.com → App →
Push mechanism, cần PUBLIC_BASE_URL như Meta/TikTok):
  - GET  /shopee/webhook → trang kiểm tra sống (Shopee không echo challenge)
  - POST /shopee/webhook → nhận push code 10 (tin nhắn mới) → brain.handle

Khách (shop) DÁN shop_id + access_token trong web → /shopee/connect xác thực
(best-effort) → lưu ShopeeStore. Flask (cổng 5009) phục vụ web React.
Tôn trọng nút bật/tắt bot (data/bot_state.json) + owner-takeover, giống mọi kênh.
"""

import hashlib
import hmac
import time
import logging
import threading   # test cũ patch sp.threading.Thread (nay dispatch dùng submit)

import requests
from flask import Flask, request, jsonify

from app.core.config import Config
from app.web_api.bridge import _load_bot_state, _save_bot_state, _channel_enabled, _conv_summary, _tenant_visible
from app.web_api.stats_util import compute_stats
from app.web_api.api_guard import install_cors, install_auth_guard, DedupCache, submit

log = logging.getLogger("shopee_api")

_dedup = DedupCache(500)   # nhớ message_id đã xử lý — Shopee gửi lại push khi ta 200 chậm


def valid_signature(raw_body: bytes, authorization: str) -> bool:
    """Chữ ký push Shopee: Authorization = HMAC-SHA256(partner_key, url|body).
    Best-effort: chưa cấu hình partner_key → cho qua; đã cấu hình nhưng CHƯA bật
    Config.SHOPEE_WEBHOOK_STRICT → cho qua (spec push chưa kiểm chứng với app được
    duyệt). Bật strict + lệch → chặn."""
    key = Config.SHOPEE_PARTNER_KEY
    if not key or not Config.SHOPEE_WEBHOOK_STRICT:
        return True
    base = request.url + "|" + (raw_body or b"").decode("utf-8", "ignore")
    expected = hmac.new(key.encode(), base.encode(), hashlib.sha256).hexdigest()
    got = (authorization or "").split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, got)


def _uid(shop_id, buyer_id):
    return f"sp:{shop_id}:{buyer_id}" if shop_id else f"sp:{buyer_id}"


def parse_event(payload: dict):
    """Payload webhook push Shopee → list[(shop_id, buyer_id, text, msg_id, name)].

    Mapping field gói gọn ở đây (spec Shopee có thể đổi khi app được duyệt).
    Chấp nhận các dạng:
      1. Push chuẩn Shopee: {"code": 10, "shop_id": X, "data": {"type": "message",
         "content": {"from_id": ..., "to_id": ..., "message_type": "text",
                     "content": {"text": ...}, "from_user_name"?}}}
      2. Dạng phẳng (test/mock): {"event": "message", "shop_id", "sender_id",
         "text", "sender_name"?}
      3. {"events": [...]} — gộp nhiều sự kiện 1 request.
    Bỏ qua tin echo (from_id == shop_id — shop tự gửi).
    """
    events = payload.get("events")
    if not isinstance(events, list):
        events = [payload]
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        shop_id, sender, text, msg_id, name = "", "", "", "", ""

        if "code" in ev:                       # dạng push chuẩn Shopee
            if ev.get("code") != 10:           # 10 = new message
                continue
            shop_id = str(ev.get("shop_id") or "").strip()
            data = ev.get("data") or {}
            if str(data.get("type") or "message") != "message":
                continue
            c = data.get("content") or {}
            sender = str(c.get("from_id") or "").strip()
            msg_id = str(c.get("message_id") or c.get("msg_id") or "")
            mtype = str(c.get("message_type") or "text")
            inner = c.get("content") or {}
            if mtype == "text":
                text = str((inner.get("text") if isinstance(inner, dict) else inner) or "")
            name = str(c.get("from_user_name") or c.get("from_username") or "").strip()
        else:                                   # dạng phẳng (mock/test)
            etype = str(ev.get("event") or ev.get("type") or "").lower()
            if etype and "message" not in etype:
                continue
            shop_id = str(ev.get("shop_id") or "").strip()
            sender = str(ev.get("sender_id") or ev.get("from_id") or ev.get("buyer_id") or "").strip()
            raw_msg = ev.get("message")
            if isinstance(raw_msg, dict):
                text = str(raw_msg.get("text") or "")
                msg_id = str(raw_msg.get("message_id") or raw_msg.get("msg_id") or "")
            else:
                text = str(ev.get("text") or "")
                msg_id = str(ev.get("msg_id") or "")
            name = str(ev.get("sender_name") or ev.get("username") or "").strip()

        text = text.strip()
        if not sender:
            continue
        if shop_id and sender == shop_id:      # echo tin shop tự gửi
            continue
        out.append((shop_id, sender, text, msg_id, name))
    return out


def handle_event(shop_id, sender, text, name, brain, conv_manager, store=None):
    """Áp gate bật/tắt + owner-takeover rồi đẩy vào brain (chạy nền) — như TikTok."""
    user_id = _uid(shop_id or None, sender)

    if name:
        conv_for_name = conv_manager.get(user_id)
        if name != conv_for_name.name:
            conv_for_name.name = name

    _ch_key = f"shopee:{shop_id}" if shop_id else "shopee"
    if not _channel_enabled(_load_bot_state(), _ch_key):
        log.info(f"[SP] bot đang TẮT ({_ch_key}) → bỏ qua {user_id}")
        return

    conv = conv_manager.get(user_id)
    if conv.is_owner_active():
        log.info(f"[SP] owner_active {user_id} → im lặng")
        return

    if not text and len(conv.messages) > 0:   # sticker/đơn hàng không phải tin đầu
        return

    # Gói/quota AI của CHỦ shop (ghi 1 lượt khi cho qua); chưa gắn chủ → gate toàn cục
    from app.core import billing
    owner = store.get_owner_username(shop_id) if (store and shop_id) else None
    if not billing.channel_gate(owner):
        log.info(f"[SP] gói/quota chủ ({owner}) không cho phép → bỏ qua {user_id}")
        return

    # MULTI-TENANT: đóng dấu shop sở hữu hội thoại (chủ shop Shopee này)
    from app.core import tenant
    tenant.assign(conv_manager, user_id, owner)

    log.info(f"[SP] shop={shop_id} {sender} | {text[:80]!r}")

    def _run():
        try:
            time.sleep(Config.REPLY_DELAY)
            brain.channel.set_ctx(shop_id or None)   # notify/call báo đúng chủ shop
            brain.handle(user_id, text)
        except Exception as e:
            log.error(f"[SP] lỗi xử lý {user_id}: {e}", exc_info=True)
            try:
                brain.channel.send_text(
                    user_id,
                    "Xin lỗi, hệ thống đang gặp sự cố nhỏ. Shop sẽ liên hệ lại bạn sớm! 🙏",
                )
            except Exception:
                pass

    submit(_run)


def create_shopee_api(brain, conv_manager, channel, store=None) -> Flask:
    app = Flask(__name__)
    install_cors(app)
    from app.web_api.security import install_security
    install_security(app, enable_global_limit=False)  # headers + rate-limit endpoint nhạy cảm (webhook không dính trần chung)
    install_auth_guard(
        app,
        public_exact={"/shopee/webhook", "/shopee/config"},
        public_prefixes=("/media/outbox",),
        # Nhân viên: chỉ hộp thư — cấm kết nối/ngắt shop, đặt chủ
        staff_deny=(
            "/shopee/connect", "DELETE /shopee/shops", "POST /shopee/shops",
            "/shopee/set-owner", "DELETE /shopee/conversations",
        ),
    )

    # Công cụ chat: gửi ảnh/video/ghi âm + chốt đơn 1 chạm (dashboard)
    from app.web_api.chat_tools import register_chat_tools
    register_chat_tools(app, "/shopee", conv_manager, channel, account="shopee")

    # MULTI-TENANT: chốt chặn tập trung — mọi thao tác lên 1 hội thoại phải
    # thuộc shop của user đăng nhập (cover cả chat_tools send-media/assign...)
    from app.web_api.bridge import install_tenant_conv_guard
    install_tenant_conv_guard(app, conv_manager)

    @app.route("/health")
    def health():
        return {"ok": True}

    @app.route("/shopee/config")
    def sp_config():
        return {
            "env_configured": bool(channel.access_token),
            "partner_configured": bool(Config.SHOPEE_PARTNER_ID and Config.SHOPEE_PARTNER_KEY),
            "webhook_path": "/shopee/webhook",
            "public_base_url": Config.PUBLIC_BASE_URL,
        }

    # ── Webhook Shopee ─────────────────────────────────────────────────

    @app.route("/shopee/webhook", methods=["GET"])
    def sp_verify():
        """Shopee không dùng challenge — GET chỉ để kiểm tra URL sống khi khai."""
        return "ok", 200

    @app.route("/shopee/webhook", methods=["POST"])
    def sp_receive():
        raw = request.get_data() or b""
        if not valid_signature(raw, request.headers.get("Authorization", "")):
            log.warning("[SP] CHẶN push sai chữ ký (SHOPEE_WEBHOOK_STRICT bật)")
            return {"ok": False, "error": "bad signature"}, 403
        payload = request.get_json(force=True, silent=True) or {}
        for shop_id, sender, text, msg_id, name in parse_event(payload):
            if _dedup.seen(msg_id):
                log.info(f"[SP] bỏ qua push trùng msg_id={msg_id}")
                continue
            handle_event(shop_id, sender, text, name, brain, conv_manager, store)
        return {"ok": True}

    # ── Kết nối ĐA KHÁCH: dán shop_id + access_token trong web ─────────

    @app.route("/shopee/connect", methods=["POST"])
    def sp_connect():
        if store is None:
            return {"ok": False, "error": "store chưa sẵn sàng"}, 500
        data = request.get_json(force=True, silent=True) or {}
        token = (data.get("access_token") or "").strip()
        shop_id = (data.get("shop_id") or "").strip()
        refresh = (data.get("refresh_token") or "").strip()
        name = (data.get("name") or "").strip()
        if not token:
            return {"ok": False, "error": "thiếu access_token"}, 400
        if not shop_id:
            return {"ok": False, "error": "thiếu shop_id"}, 400

        from app.web_api.auth_api import current_username
        owner = current_username()   # chủ shop đang đăng nhập (để tính quota/gói)

        # Xác thực best-effort: hỏi Shopee thông tin shop. App chưa được duyệt
        # thì vẫn lưu (verified=false) để dùng được ngay khi Shopee duyệt.
        verified = False
        try:
            path = "/api/v2/shop/get_shop_info"
            ts = int(time.time())
            r = requests.get(
                f"{Config.SHOPEE_API_BASE.rstrip('/')}{path}",
                params={
                    "partner_id": Config.SHOPEE_PARTNER_ID,
                    "timestamp": ts,
                    "sign": channel._sign(path, ts, token, shop_id),
                    "access_token": token,
                    "shop_id": shop_id,
                },
                timeout=15,
            )
            if r.status_code == 200 and not (r.json() or {}).get("error"):
                info = r.json() or {}
                name = name or str(info.get("shop_name") or "")
                verified = True
                store.upsert(shop_id, access_token=token, refresh_token=refresh or None,
                             name=name, owner_username=owner)
        except Exception as e:
            log.warning(f"[SP connect] không xác thực được token ({e}) — vẫn lưu")
        if not verified:
            store.upsert(shop_id, access_token=token, refresh_token=refresh or None,
                         name=name, owner_username=owner)
        return {"ok": True, "verified": verified, "shop": {
            "shop_id": shop_id, "name": name,
        }}

    @app.route("/shopee/shops")
    def sp_shops():
        shops = store.list_shops() if store else []
        state = _load_bot_state()
        for s in shops:
            s["bot_enabled"] = _channel_enabled(state, f"shopee:{s['shop_id']}")
        return jsonify(shops)

    @app.route("/shopee/shops/<shop_id>", methods=["DELETE"])
    def sp_remove(shop_id):
        if store:
            store.remove(shop_id)
        return {"ok": True}

    @app.route("/shopee/shops/<shop_id>/toggle", methods=["POST"])
    def sp_shop_toggle(shop_id):
        """Bật/tắt riêng 1 shop Shopee. body {enabled: bool}."""
        data = request.get_json(force=True, silent=True) or {}
        enabled = bool(data.get("enabled", True))
        state = _load_bot_state()
        state.setdefault("channels", {})[f"shopee:{shop_id}"] = enabled
        _save_bot_state(state)
        log.info(f"[SP] shop {shop_id} toggle → enabled={enabled}")
        return {"ok": True, "shop_id": shop_id, "enabled": enabled}

    @app.route("/shopee/set-owner", methods=["POST"])
    def sp_set_owner():
        """ADMIN chọn chủ = 1 người ĐÃ nhắn shop (như TikTok).
        body {user_id: 'sp:<shop_id>:<buyer_id>', name?}."""
        data = request.get_json(force=True, silent=True) or {}
        uid = (data.get("user_id") or "").strip()
        name = data.get("name") or ""
        parts = uid.split(":")
        if len(parts) >= 3 and store:
            store.set_owner(parts[1], ":".join(parts[2:]), name)
            return {"ok": True}
        return {"ok": False, "error": "user_id không hợp lệ"}, 400

    # ── Thống kê ───────────────────────────────────────────────────────

    @app.route("/shopee/stats")
    def sp_stats():
        shop_id = request.args.get("shop_id", "")

        def _flt(u):
            if not u.startswith("sp:"):
                return False
            if shop_id:
                parts = u.split(":")
                return len(parts) >= 3 and parts[1] == shop_id
            return True

        return jsonify(compute_stats(
            conv_manager, request.args.get("from"), request.args.get("to"),
            uid_filter=_flt))

    # ── Hội thoại (lọc theo shop) ──────────────────────────────────────

    @app.route("/shopee/conversations")
    def sp_conversations():
        shop_id = request.args.get("shop_id", "")
        try:
            limit = min(max(int(request.args.get("limit", 50)), 1), 200)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 50, 0
        rows = []
        for uid, conv in list(conv_manager._sessions.items()):
            if not uid.startswith("sp:"):
                continue
            parts = uid.split(":")
            uid_shop = parts[1] if len(parts) >= 3 else ""
            if shop_id and uid_shop != shop_id:
                continue
            if not _tenant_visible(conv):   # multi-tenant: chỉ shop của mình
                continue
            rows.append(_conv_summary(uid, conv))
        rows.sort(key=lambda r: r["last_updated"], reverse=True)
        total = len(rows)
        return jsonify({"total": total, "offset": offset, "limit": limit,
                        "items": rows[offset:offset + limit]})

    @app.route("/shopee/conversations/<user_id>")
    def sp_conversation(user_id):
        conv = conv_manager._sessions.get(user_id)
        if not conv or not _tenant_visible(conv):
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

    @app.route("/shopee/conversations/<user_id>/send", methods=["POST"])
    def sp_send_message(user_id):
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "tin trống"}, 400
        parts = user_id.split(":")
        shop_id = parts[1] if len(parts) >= 3 else None
        try:
            channel.set_ctx(shop_id)
            channel.send_text(user_id, text)
        except Exception as e:
            log.error(f"[sp send] lỗi gửi {user_id}: {e}")
            return {"ok": False, "error": str(e)}, 500
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(text)
        conv.set_owner_active(True)
        conv_manager.save()
        # Bot học từ hội thoại: chủ trả lời tay → AI đề xuất mẩu tri thức (nền, chờ duyệt)
        from app.core import knowledge_learn
        submit(knowledge_learn.suggest_from_reply, user_id, "shopee", list(conv.messages), text)
        return {"ok": True}

    @app.route("/shopee/conversations/<user_id>/toggle-bot", methods=["POST"])
    def sp_toggle_bot(user_id):
        data = request.get_json(force=True, silent=True) or {}
        bot_on = bool(data.get("bot_on", True))
        conv = conv_manager.get(user_id)
        conv.set_owner_active(not bot_on)
        conv_manager.save()
        return {"ok": True, "bot_on": bot_on, "owner_active": conv.is_owner_active()}

    @app.route("/shopee/conversations/<user_id>", methods=["DELETE"])
    def sp_reset(user_id):
        conv_manager.reset(user_id)
        return {"ok": True}

    return app
