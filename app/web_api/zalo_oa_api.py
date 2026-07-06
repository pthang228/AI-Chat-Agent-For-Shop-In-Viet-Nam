"""
Zalo OA — webhook nhận tin + API hội thoại + kết nối ĐA KHÁCH cho kênh Zalo OA.

Nhận tin qua WEBHOOK (Zalo đẩy về, khai trên developers.zalo.me → app →
Webhook, cần PUBLIC_BASE_URL như Meta/TikTok/Shopee):
  - GET  /zalooa/webhook → trang kiểm tra sống (Zalo xác minh domain riêng)
  - POST /zalooa/webhook → nhận event user_send_text → brain.handle
    (verify chữ ký X-ZEvent-Signature best-effort + DEDUP theo msg_id —
    Zalo có thể gửi lại event khi ta trả lời chậm)

Khách DÁN oa_id + access_token (+ refresh_token để hệ thống tự gia hạn ~25h)
trong web → /zalooa/connect xác thực best-effort → lưu ZaloOAStore.
Flask (cổng 5010) phục vụ web React. Tôn trọng nút bật/tắt bot
(data/bot_state.json) + owner-takeover, giống mọi kênh.
"""

import hashlib
import time
import logging
import threading
from collections import OrderedDict

import requests
from flask import Flask, request, jsonify

from app.core.config import Config
from app.web_api.bridge import _load_bot_state, _save_bot_state, _channel_enabled, _conv_summary, _tenant_visible
from app.web_api.stats_util import compute_stats
from app.web_api.api_guard import install_cors, install_auth_guard, submit

log = logging.getLogger("zalo_oa_api")

# Dedup webhook: Zalo gửi lại event nếu không nhận 200 kịp → nhớ msg_id gần đây.
_SEEN_MAX = 500
_seen_msgs: "OrderedDict[str, bool]" = OrderedDict()
_seen_lock = threading.Lock()


def _is_dup(msg_id: str) -> bool:
    if not msg_id:
        return False
    with _seen_lock:
        if msg_id in _seen_msgs:
            return True
        _seen_msgs[msg_id] = True
        while len(_seen_msgs) > _SEEN_MAX:
            _seen_msgs.popitem(last=False)
    return False


def _uid(oa_id, user_id):
    return f"oa:{oa_id}:{user_id}" if oa_id else f"oa:{user_id}"


def valid_signature(raw_body: bytes, header: str, timestamp: str,
                    app_id: str = None, secret: str = None) -> bool:
    """Chữ ký webhook Zalo: X-ZEvent-Signature = 'mac=' + sha256(appId + body +
    timestamp + OA_secret_key). Trả True khi khớp hoặc khi chưa cấu hình secret
    (dev mode)."""
    app_id = app_id if app_id is not None else Config.ZALO_OA_APP_ID
    secret = secret if secret is not None else Config.ZALO_OA_APP_SECRET
    if not (secret and app_id):
        return True          # chưa cấu hình → bỏ qua (dev/mock)
    if not header:
        return False
    mac = header.split("=", 1)[-1].strip()
    data = app_id.encode() + (raw_body or b"") + str(timestamp or "").encode() + secret.encode()
    return hashlib.sha256(data).hexdigest() == mac


def parse_event(payload: dict):
    """Payload webhook Zalo OA → list[(oa_id, user_id, text, msg_id, name)].

    Mapping field gói gọn ở đây. Chấp nhận các dạng:
      1. Event chuẩn Zalo: {"app_id", "event_name": "user_send_text",
         "sender": {"id": U}, "recipient": {"id": OA},
         "message": {"text", "msg_id"}, "timestamp"}
      2. Dạng phẳng (test/mock): {"event": "message", "oa_id", "sender_id",
         "text", "sender_name"?}
      3. {"events": [...]} — gộp nhiều sự kiện 1 request.
    Chỉ nhận sự kiện user_send_* (khách nhắn). oa_send_* (OA tự gửi — echo),
    follow/unfollow... → bỏ qua.
    """
    events = payload.get("events")
    if not isinstance(events, list):
        events = [payload]
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        oa_id, sender, text, msg_id, name = "", "", "", "", ""

        if "event_name" in ev:                 # dạng event chuẩn Zalo
            ename = str(ev.get("event_name") or "")
            if not ename.startswith("user_send"):
                continue                       # oa_send_* = echo; follow... = bỏ
            sender = str((ev.get("sender") or {}).get("id") or "").strip()
            oa_id = str((ev.get("recipient") or {}).get("id") or "").strip()
            msg = ev.get("message") or {}
            msg_id = str(msg.get("msg_id") or "")
            if ename == "user_send_text":
                text = str(msg.get("text") or "")
            # user_send_image/sticker/file... → text rỗng (bỏ nếu không phải tin đầu)
        else:                                   # dạng phẳng (mock/test)
            etype = str(ev.get("event") or ev.get("type") or "").lower()
            if etype and "message" not in etype:
                continue
            oa_id = str(ev.get("oa_id") or "").strip()
            sender = str(ev.get("sender_id") or ev.get("from_id") or "").strip()
            raw_msg = ev.get("message")
            if isinstance(raw_msg, dict):
                text = str(raw_msg.get("text") or "")
                msg_id = str(raw_msg.get("msg_id") or "")
            else:
                text = str(ev.get("text") or "")
                msg_id = str(ev.get("msg_id") or "")
            name = str(ev.get("sender_name") or "").strip()

        text = text.strip()
        if not sender:
            continue
        if oa_id and sender == oa_id:          # phòng hờ echo OA tự gửi
            continue
        out.append((oa_id, sender, text, msg_id, name))
    return out


def _fetch_oa_profile(user_id, oa_id, sender, conv_manager, channel):
    """Gọi Zalo OA API lấy tên + avatar khách (chạy nền, 1 lần khi thiếu).
    GET /oa/user/detail?data={"user_id":...} header access_token → display_name + avatar."""
    try:
        token = channel._token_for(oa_id) if hasattr(channel, "_token_for") else None
        if not token:
            return
        import json as _json
        r = requests.get(
            f"{Config.ZALO_OA_API_BASE.rstrip('/')}/oa/user/detail",
            headers={"access_token": token},
            params={"data": _json.dumps({"user_id": sender})},
            timeout=10,
        )
        j = r.json() if r.content else {}
        if r.status_code != 200 or j.get("error"):
            log.debug(f"[OA profile] {sender} → {r.status_code} err={j.get('error')}")
            return
        info = j.get("data") or {}
        name = str(info.get("display_name") or "").strip()
        # avatar: URL trực tiếp hoặc dict avatars {"120":..,"240":..} tuỳ phiên bản API
        avatar = info.get("avatar") or ""
        if not avatar and isinstance(info.get("avatars"), dict):
            avatar = info["avatars"].get("240") or info["avatars"].get("120") or ""
        conv = conv_manager.get(user_id)
        changed = False
        if name and not conv.name:
            conv.name = name
            changed = True
        if avatar and avatar != conv.avatar:
            conv.avatar = str(avatar)
            changed = True
        if changed:
            conv_manager.save()
            log.info(f"[OA profile] {sender} → '{name}' avatar={'có' if avatar else 'không'}")
    except Exception as e:
        log.warning(f"[OA profile] {sender}: {e}")


def handle_event(oa_id, sender, text, name, brain, conv_manager, store=None):
    """Áp gate bật/tắt + owner-takeover rồi đẩy vào brain (chạy nền) — như Shopee."""
    user_id = _uid(oa_id or None, sender)

    if name:
        conv_for_name = conv_manager.get(user_id)
        if name != conv_for_name.name:
            conv_for_name.name = name

    # Thiếu tên/avatar → hỏi Zalo (nền, không chặn trả lời khách)
    conv_check = conv_manager.get(user_id)
    if not conv_check.name or not getattr(conv_check, "avatar", ""):
        submit(_fetch_oa_profile, user_id, oa_id, sender, conv_manager, brain.channel)

    _ch_key = f"zalooa:{oa_id}" if oa_id else "zalooa"
    if not _channel_enabled(_load_bot_state(), _ch_key):
        log.info(f"[OA] bot đang TẮT ({_ch_key}) → bỏ qua {user_id}")
        return

    conv = conv_manager.get(user_id)
    if conv.is_owner_active():
        log.info(f"[OA] owner_active {user_id} → im lặng")
        return

    if not text and len(conv.messages) > 0:   # sticker/ảnh không phải tin đầu
        return

    # Gói/quota AI của CHỦ OA (ghi 1 lượt khi cho qua); chưa gắn chủ → gate toàn cục
    from app.core import billing
    owner = store.get_owner_username(oa_id) if (store and oa_id) else None
    if not billing.channel_gate(owner):
        log.info(f"[OA] gói/quota chủ ({owner}) không cho phép → bỏ qua {user_id}")
        return

    # MULTI-TENANT: đóng dấu shop sở hữu hội thoại (chủ OA này)
    from app.core import tenant
    tenant.assign(conv_manager, user_id, owner)

    log.info(f"[OA] oa={oa_id} {sender} | {text[:80]!r}")

    def _run():
        try:
            time.sleep(Config.REPLY_DELAY)
            brain.channel.set_ctx(oa_id or None)   # notify/call báo đúng chủ OA
            brain.handle(user_id, text)
        except Exception as e:
            log.error(f"[OA] lỗi xử lý {user_id}: {e}", exc_info=True)
            try:
                brain.channel.send_text(
                    user_id,
                    "Xin lỗi, hệ thống đang gặp sự cố nhỏ. Shop sẽ liên hệ lại bạn sớm! 🙏",
                )
            except Exception:
                pass

    submit(_run)


def create_zalo_oa_api(brain, conv_manager, channel, store=None) -> Flask:
    app = Flask(__name__)
    install_cors(app)
    install_auth_guard(
        app,
        public_exact={"/zalooa/webhook", "/zalooa/config"},
        public_prefixes=("/media/outbox",),
        # Nhân viên: chỉ hộp thư — cấm kết nối/ngắt OA, đặt chủ
        staff_deny=(
            "/zalooa/connect", "DELETE /zalooa/accounts", "POST /zalooa/accounts",
            "/zalooa/set-owner", "DELETE /zalooa/conversations",
        ),
    )

    # Công cụ chat: gửi ảnh/video/ghi âm + chốt đơn 1 chạm (dashboard)
    from app.web_api.chat_tools import register_chat_tools
    register_chat_tools(app, "/zalooa", conv_manager, channel, account="zalooa")

    # MULTI-TENANT: chốt chặn tập trung — mọi thao tác lên 1 hội thoại phải
    # thuộc shop của user đăng nhập (cover cả chat_tools send-media/assign...)
    from app.web_api.bridge import install_tenant_conv_guard
    install_tenant_conv_guard(app, conv_manager)

    @app.route("/health")
    def health():
        return {"ok": True}

    @app.route("/zalooa/config")
    def oa_config():
        return {
            "env_configured": bool(channel.access_token),
            "app_configured": bool(Config.ZALO_OA_APP_ID and Config.ZALO_OA_APP_SECRET),
            "webhook_path": "/zalooa/webhook",
            "public_base_url": Config.PUBLIC_BASE_URL,
        }

    # ── Webhook Zalo OA ────────────────────────────────────────────────

    @app.route("/zalooa/webhook", methods=["GET"])
    def oa_verify():
        """Zalo xác minh domain qua meta tag/file riêng — GET chỉ để kiểm tra URL sống."""
        return "ok", 200

    @app.route("/zalooa/webhook", methods=["POST"])
    def oa_receive():
        raw = request.get_data() or b""
        payload = request.get_json(force=True, silent=True) or {}
        # Chữ ký X-ZEvent-Signature — verify best-effort như Meta: lệch thì log
        # để chẩn đoán nhưng chưa chặn (tránh rớt tin khi Zalo đổi công thức).
        sig = request.headers.get("X-ZEvent-Signature", "")
        if not valid_signature(raw, sig, payload.get("timestamp")):
            log.warning("[OA] CHẶN webhook sai chữ ký X-ZEvent-Signature")
            return {"ok": False, "error": "bad signature"}, 403
        for oa_id, sender, text, msg_id, name in parse_event(payload):
            if _is_dup(msg_id):
                log.info(f"[OA] bỏ qua event trùng msg_id={msg_id}")
                continue
            handle_event(oa_id, sender, text, name, brain, conv_manager, store)
        return {"ok": True}

    # ── Kết nối ĐA KHÁCH: dán oa_id + access_token trong web ───────────

    @app.route("/zalooa/connect", methods=["POST"])
    def oa_connect():
        if store is None:
            return {"ok": False, "error": "store chưa sẵn sàng"}, 500
        data = request.get_json(force=True, silent=True) or {}
        token = (data.get("access_token") or "").strip()
        oa_id = (data.get("oa_id") or "").strip()
        refresh = (data.get("refresh_token") or "").strip()
        name = (data.get("name") or "").strip()
        if not token:
            return {"ok": False, "error": "thiếu access_token"}, 400

        from app.web_api.auth_api import current_username
        owner = current_username()   # chủ đang đăng nhập (để tính quota/gói)

        # Xác thực best-effort: hỏi Zalo thông tin OA (đồng thời tự lấy oa_id +
        # tên OA nếu khách không điền). Lỗi mạng/token → vẫn lưu (verified=false).
        verified = False
        try:
            r = requests.get(
                f"{Config.ZALO_OA_API_BASE.rstrip('/')}/oa/getoa",
                headers={"access_token": token}, timeout=15,
            )
            j = r.json() if r.content else {}
            if r.status_code == 200 and not j.get("error"):
                info = j.get("data") or {}
                oa_id = oa_id or str(info.get("oa_id") or "")
                name = name or str(info.get("name") or "")
                verified = True
        except Exception as e:
            log.warning(f"[OA connect] không xác thực được token ({e}) — vẫn lưu")
        if not oa_id:
            return {"ok": False, "error": "thiếu oa_id (token không tự tra được)"}, 400
        store.upsert(oa_id, access_token=token, refresh_token=refresh or None,
                     name=name, owner_username=owner)
        return {"ok": True, "verified": verified, "oa": {
            "oa_id": oa_id, "name": name,
        }}

    @app.route("/zalooa/accounts")
    def oa_accounts():
        oas = store.list_oas() if store else []
        state = _load_bot_state()
        for s in oas:
            s["bot_enabled"] = _channel_enabled(state, f"zalooa:{s['oa_id']}")
        return jsonify(oas)

    @app.route("/zalooa/accounts/<oa_id>", methods=["DELETE"])
    def oa_remove(oa_id):
        if store:
            store.remove(oa_id)
        return {"ok": True}

    @app.route("/zalooa/accounts/<oa_id>/toggle", methods=["POST"])
    def oa_toggle(oa_id):
        """Bật/tắt riêng 1 OA. body {enabled: bool}."""
        data = request.get_json(force=True, silent=True) or {}
        enabled = bool(data.get("enabled", True))
        state = _load_bot_state()
        state.setdefault("channels", {})[f"zalooa:{oa_id}"] = enabled
        _save_bot_state(state)
        log.info(f"[OA] {oa_id} toggle → enabled={enabled}")
        return {"ok": True, "oa_id": oa_id, "enabled": enabled}

    @app.route("/zalooa/set-owner", methods=["POST"])
    def oa_set_owner():
        """ADMIN chọn chủ = 1 người ĐÃ nhắn OA (như Shopee/TikTok).
        body {user_id: 'oa:<oa_id>:<user_id>', name?}."""
        data = request.get_json(force=True, silent=True) or {}
        uid = (data.get("user_id") or "").strip()
        name = data.get("name") or ""
        parts = uid.split(":")
        if len(parts) >= 3 and store:
            store.set_owner(parts[1], ":".join(parts[2:]), name)
            return {"ok": True}
        return {"ok": False, "error": "user_id không hợp lệ"}, 400

    # ── Thống kê ───────────────────────────────────────────────────────

    @app.route("/zalooa/stats")
    def oa_stats():
        oa_id = request.args.get("oa_id", "")

        def _flt(u):
            if not u.startswith("oa:"):
                return False
            if oa_id:
                parts = u.split(":")
                return len(parts) >= 3 and parts[1] == oa_id
            return True

        return jsonify(compute_stats(
            conv_manager, request.args.get("from"), request.args.get("to"),
            uid_filter=_flt))

    # ── Hội thoại (lọc theo OA) ────────────────────────────────────────

    @app.route("/zalooa/conversations")
    def oa_conversations():
        oa_id = request.args.get("oa_id", "")
        try:
            limit = min(max(int(request.args.get("limit", 50)), 1), 200)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 50, 0
        rows = []
        for uid, conv in list(conv_manager._sessions.items()):
            if not uid.startswith("oa:"):
                continue
            parts = uid.split(":")
            uid_oa = parts[1] if len(parts) >= 3 else ""
            if oa_id and uid_oa != oa_id:
                continue
            if not _tenant_visible(conv):   # multi-tenant: chỉ shop của mình
                continue
            rows.append(_conv_summary(uid, conv))
        rows.sort(key=lambda r: r["last_updated"], reverse=True)
        total = len(rows)
        return jsonify({"total": total, "offset": offset, "limit": limit,
                        "items": rows[offset:offset + limit]})

    @app.route("/zalooa/conversations/<user_id>")
    def oa_conversation(user_id):
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

    @app.route("/zalooa/conversations/<user_id>/send", methods=["POST"])
    def oa_send_message(user_id):
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "tin trống"}, 400
        parts = user_id.split(":")
        oa_id = parts[1] if len(parts) >= 3 else None
        try:
            channel.set_ctx(oa_id)
            channel.send_text(user_id, text)
        except Exception as e:
            log.error(f"[oa send] lỗi gửi {user_id}: {e}")
            return {"ok": False, "error": str(e)}, 500
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(text)
        conv.set_owner_active(True)
        conv_manager.save()
        # Bot học từ hội thoại: chủ trả lời tay → AI đề xuất mẩu tri thức (nền, chờ duyệt)
        from app.core import knowledge_learn
        submit(knowledge_learn.suggest_from_reply, user_id, "zalooa", list(conv.messages), text)
        return {"ok": True}

    @app.route("/zalooa/conversations/<user_id>/toggle-bot", methods=["POST"])
    def oa_toggle_bot(user_id):
        data = request.get_json(force=True, silent=True) or {}
        bot_on = bool(data.get("bot_on", True))
        conv = conv_manager.get(user_id)
        conv.set_owner_active(not bot_on)
        conv_manager.save()
        return {"ok": True, "bot_on": bot_on, "owner_active": conv.is_owner_active()}

    @app.route("/zalooa/conversations/<user_id>", methods=["DELETE"])
    def oa_reset(user_id):
        conv_manager.reset(user_id)
        return {"ok": True}

    return app
