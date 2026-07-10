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
from app.web_api.api_guard import install_cors, install_auth_guard, submit as _submit, DedupCache

log = logging.getLogger("bridge")

# Trạng thái bật/tắt bot toàn cục (1 account hiện tại). Lưu ra file để giữ qua restart.
BOT_STATE_FILE = Config.DATA_DIR / "bot_state.json"


ALL_CHANNELS = ("zalo", "meta", "telegram", "tiktok", "shopee", "zalooa", "webchat")


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
        "avatar": getattr(conv, "avatar", "") or "",
        "owner_active": conv.is_owner_active(),
        "stage": conv.stage,
        "assigned_to": getattr(conv, "assigned_to", "") or "",
        "checkin": conv.checkin,
        "checkout": conv.checkout,
        "selected_room": conv.selected_room,
        "last_msg": last_msg,
        "msg_count": len(visible),
        "last_updated": conv.last_updated.isoformat(),
    }


def _ws():
    """Workspace (shop) của request hiện tại — None khi không token (test).
    Cache theo request (flask.g): guard đã xác thực và gắn g.auth_user nên
    thường KHÔNG tốn thêm query DB."""
    from flask import g, has_request_context
    if not has_request_context():
        return None
    ws = getattr(g, "_ws_cache", "__unset__")
    if ws != "__unset__":
        return ws
    u = getattr(g, "auth_user", None)
    if u is not None:
        from app.web_api.auth_api import workspace_of
        ws = workspace_of(u)
    else:
        from app.core import tenant
        ws = tenant.current_workspace_or_none()
    g._ws_cache = ws
    return ws


def _tenant_visible(conv) -> bool:
    """MULTI-TENANT: user đăng nhập có được thấy/đụng hội thoại này không.
    Dùng cho CẢ list (lọc hàng loạt) lẫn detail/send/toggle/delete (chống đoán
    user_id của shop khác). Import được từ mọi server kênh."""
    from app.core import tenant
    return tenant.visible(getattr(conv, "tenant", "") or "", _ws())


_can_see = _tenant_visible   # alias dùng nội bộ bridge


def install_tenant_conv_guard(app, conv_manager):
    """MULTI-TENANT chốt chặn TẬP TRUNG: mọi request đụng 1 hội thoại cụ thể
    ({prefix}/conversations/<user_id>[/send|toggle-bot|send-media|assign|
    make-order|broadcast-send|DELETE...]) đều bị kiểm tra quyền sở hữu tenant
    TRƯỚC khi vào handler — 1 chỗ cover mọi endpoint hiện tại + tương lai của
    server đó (kể cả chat_tools). Hội thoại CHƯA tồn tại → cho qua (handler tự
    xử lý 404/tạo mới)."""
    from urllib.parse import unquote

    @app.before_request
    def _tenant_conv_guard():
        if request.method == "OPTIONS":
            return None
        path = request.path
        if "/conversations/" not in path:
            return None
        uid = unquote(path.split("/conversations/", 1)[1].split("/", 1)[0])
        if not uid:
            return None
        conv = conv_manager._sessions.get(uid)
        if conv is not None and not _tenant_visible(conv):
            return {"ok": False, "error": "not found"}, 404
        return None


def create_bridge(brain, conv_manager) -> Flask:
    app = Flask(__name__)

    # MULTI-ACCOUNT Zalo cá nhân: mapping accId → chủ shop (phiên thật ở Node)
    from app.core.zalo_node_store import ZaloNodeStore
    zalo_store = ZaloNodeStore()

    # (bot_state đọc TƯƠI trong từng route qua _load_bot_state() — không giữ
    # snapshot lúc boot để tránh trạng thái lỗi thời khi copilot/kênh khác ghi file.)

    # CORS siết theo ALLOWED_ORIGINS + mở header Authorization (client gửi Bearer).
    install_cors(app)
    from app.web_api.security import install_security
    install_security(app)   # rate-limit login/đăng ký + trần chung + security headers

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

    # Sổ đơn hàng + thread nhắc đơn tới hạn (báo qua notify_owner kênh Zalo)
    from app.web_api.orders_api import register_orders_routes
    register_orders_routes(app)
    from app.core import orders as _orders
    _orders.start_reminder_thread(brain.channel.notify_owner)

    # Thanh toán: /payhook (đối soát SePay/Casso, bản local) + /orders/bank (QR shop)
    from app.web_api.payment_api import register_payment_routes
    register_payment_routes(app, notify_fn=brain.channel.notify_owner)

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
        # Đọc file TƯƠI: copilot/kênh khác có thể vừa ghi bot_state (đừng dùng
        # closure cũ nạp lúc boot → trả trạng thái lỗi thời).
        return {"enabled": _channel_enabled(_load_bot_state(), channel), "channel": channel or "all"}

    @app.route("/bot-toggle", methods=["POST"])
    def bot_toggle():
        """Bật/tắt bot RIÊNG TỪNG KÊNH. body {enabled: bool, channel?: str, app_name?: str}.
        channel rỗng/"all" = áp cho mọi kênh (vd lúc đăng xuất). Nhắn nhóm để chủ biết."""
        data = request.get_json(force=True, silent=True) or {}
        enabled = bool(data.get("enabled", True))
        channel = _norm_channel(data.get("channel") or "")
        app_name = _norm_text(data.get("app_name") or "")

        # MULTI-TENANT: công tắc GLOBAL / kênh cha trần (zalo, meta…) ảnh hưởng
        # MỌI shop → chỉ CHỦ NỀN TẢNG được bấm. Key per-bot "kênh:<id>" (bot/page/
        # site của riêng shop) thì shop nào cũng dùng được.
        if ":" not in channel:
            from app.core import tenant as _t
            ws = _ws()
            if ws and not _t.is_platform_admin(ws):
                return {"ok": False,
                        "error": "Chỉ quản trị nền tảng mới bật/tắt bot toàn cục — "
                                 "hãy bật/tắt từng kênh của shop bạn"}, 403

        state = _load_bot_state()   # đọc TƯƠI rồi sửa → không đua với ghi từ copilot
        chans = state.setdefault("channels", {})
        if not channel or channel == "all":
            for c in ALL_CHANNELS:
                chans[c] = enabled
            state["enabled"] = enabled
            scope = "tất cả kênh"
        else:
            chans[channel] = enabled
            scope = channel
        _save_bot_state(state)

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

    # uid đã hỏi Node avatar — dùng DedupCache (bounded 5000, thread-safe) thay set
    # vô hạn: 10k khách × không avatar → set phình mãi không co (memory leak).
    _av_asked = DedupCache(5000)

    def _backfill_zalo_avatars(missing):
        """Khách CŨ chưa có avatar (chưa nhắn tin mới) → hỏi Node /avatar/<uid>
        (Node gọi zca-js getUserInfo, có cache). Chạy nền, best-effort.
        Multi-acc: uid 'zl:<acc>:<zuid>' → hỏi đúng acc."""
        import requests as _rq
        node_url = getattr(brain.channel, "node_url", "") or "http://127.0.0.1:4000"
        _parse = getattr(brain.channel, "_parse", lambda u: ("default", str(u)))
        changed = False
        for uid in missing:
            try:
                _acc, _zuid = _parse(uid)
                r = _rq.get(f"{node_url}/avatar/{_zuid}", params={"acc": _acc}, timeout=10)
                av = (r.json() or {}).get("avatar") if r.status_code == 200 else ""
                if av:
                    conv_manager.get(uid).avatar = av
                    changed = True
                    log.info(f"[avatar] backfill {uid} → có ảnh")
            except Exception as e:
                log.debug(f"[avatar] backfill {uid}: {e}")
        if changed:
            conv_manager.save()

    @app.route("/conversations")
    def list_conversations():
        # Trả mảng (giữ shape cũ cho UI), mặc định 200 khách mới nhất —
        # 10k khách không đổ hết về mỗi lần web tự làm mới. ?limit=&offset=.
        try:
            limit = min(max(int(request.args.get("limit", 200)), 1), 1000)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 200, 0
        from app.core import tenant as _t
        ws = _ws()
        rows = [
            _conv_summary(uid, conv)
            for uid, conv in list(conv_manager._sessions.items())
            if _t.visible(getattr(conv, "tenant", "") or "", ws)   # chỉ shop của mình
        ]
        rows.sort(key=lambda r: r["last_updated"], reverse=True)
        # Khách thiếu avatar → backfill nền qua Node (mỗi uid chỉ hỏi 1 lần).
        # seen() vừa kiểm-vừa-nhớ atomic → chỉ giữ uid CHƯA hỏi.
        missing = [r["user_id"] for r in rows[offset:offset + limit]
                   if not r["avatar"] and not _av_asked.seen(r["user_id"])]
        if missing:
            _submit(_backfill_zalo_avatars, missing)
        return jsonify(rows[offset:offset + limit])

    @app.route("/conversations/<user_id>")
    def get_conversation(user_id):
        conv = conv_manager._sessions.get(user_id)
        if not conv or not _can_see(conv):
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
            "checkin": conv.checkin,
            "checkout": conv.checkout,
            "messages": msgs,
        })

    @app.route("/conversations/<user_id>/toggle-bot", methods=["POST"])
    def toggle_bot(user_id):
        """Bật/tắt bot cho 1 khách. body {bot_on: bool} — bot_on=False nghĩa là chủ tiếp quản."""
        data = request.get_json(force=True, silent=True) or {}
        bot_on = bool(data.get("bot_on", True))
        exist = conv_manager._sessions.get(user_id)
        if exist is not None and not _can_see(exist):
            return {"error": "not found"}, 404
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
        exist = conv_manager._sessions.get(user_id)
        if exist is not None and not _can_see(exist):
            return {"ok": False, "error": "not found"}, 404
        try:
            brain.channel.send_text(user_id, text)
        except Exception as e:
            log.error(f"[send] lỗi gửi {user_id}: {e}")
            return {"ok": False, "error": str(e)}, 500
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(text)
        conv.set_owner_active(True)   # chủ đang xử lý → bot dừng tự động trả lời
        conv_manager.save()
        # Bot học từ hội thoại: chủ trả lời tay → AI đề xuất mẩu tri thức (nền, chờ duyệt)
        from app.core import knowledge_learn
        _submit(knowledge_learn.suggest_from_reply, user_id, "zalo", list(conv.messages), text)
        return {"ok": True}

    @app.route("/conversations/<user_id>", methods=["DELETE"])
    def reset_conversation(user_id):
        exist = conv_manager._sessions.get(user_id)
        if exist is not None and not _can_see(exist):
            return {"error": "not found"}, 404
        conv_manager.reset(user_id)
        return {"ok": True}

    @app.route("/stats")
    def conv_stats():
        return jsonify(compute_stats(
            conv_manager, request.args.get("from"), request.args.get("to"),
            tenant_ws=_ws()))

    # ── MULTI-ACCOUNT Zalo: acc riêng của shop đang đăng nhập ───────────
    @app.route("/zalo/my-account")
    def zalo_my_account():
        """Acc Zalo của shop (mỗi shop 1 acc; chưa có → cấp mới). Chủ NỀN TẢNG
        dùng acc 'default' (tương thích bản cũ). UI dùng acc này gọi Node
        (?acc=) để quét QR / xem trạng thái / chọn nhóm."""
        from app.core import tenant as _tenant
        ws = _ws()
        if not ws:
            return {"ok": False, "error": "Cần đăng nhập"}, 401
        if ws == _tenant.default_owner():
            return {"ok": True, "acc": "default", "platform_admin": True}
        return {"ok": True, "acc": zalo_store.ensure_for_owner(ws),
                "platform_admin": False}

    @app.route("/incoming", methods=["POST"])
    def incoming():
        data = request.get_json(force=True, silent=True) or {}

        # Tin nhóm → bỏ qua (bot chỉ tư vấn 1-1)
        if data.get("isGroup"):
            return {"ok": True, "skipped": "group"}

        # MULTI-ACCOUNT: Node gửi kèm acc (mỗi shop 1 acc Zalo). Acc 'default'
        # (chủ nền tảng) giữ user_id uid TRẦN như cũ; acc shop → 'zl:<acc>:<uid>'.
        zuid = str(data.get("userId") or "").strip()
        acc = str(data.get("acc") or "default").strip() or "default"
        user_id = zuid if acc == "default" else f"zl:{acc}:{zuid}"
        text = (data.get("text") or "").strip()
        if not zuid:
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
                # Bot học từ hội thoại: chủ gõ tay trên điện thoại cũng là "trả lời tay"
                from app.core import knowledge_learn
                _submit(knowledge_learn.suggest_from_reply, user_id, "zalo",
                        list(conv.messages), text)
                return {"ok": True, "owner_takeover": True}
            return {"ok": True, "skipped": "self-echo"}

        # Bot kênh Zalo bị tắt → không auto-reply khách (per-acc: 'zalo:<acc>'
        # fallback lên 'zalo' — _channel_enabled đã hỗ trợ key kênh:id sẵn)
        _zl_key = "zalo" if acc == "default" else f"zalo:{acc}"
        if not _channel_enabled(_load_bot_state(), _zl_key):
            log.info(f"[Skip] bot_disabled ({_zl_key}) {user_id}")
            return {"ok": True, "skipped": "bot_disabled"}

        # Gói/quota AI: acc shop → theo gói CHỦ SHOP đó (channel_gate như mọi
        # kênh); acc default → gate toàn cục (chủ nền tảng) như cũ.
        from app.core import billing
        owner = zalo_store.get_owner_username(acc)
        if not billing.channel_gate(owner):
            log.info(f"[Skip] gói/quota chủ ({owner or 'nền tảng'}) → bỏ qua {user_id}")
            return {"ok": True, "skipped": "billing_expired"}

        conv = conv_manager.get(user_id)

        # MULTI-TENANT: đóng dấu shop sở hữu (acc default → chủ nền tảng)
        from app.core import tenant as _tenant
        _tenant.assign(conv_manager, user_id, owner)

        # (ctx acc set TRONG _run — thread-local không kế thừa sang thread pool)

        # Cập nhật tên + avatar hiển thị nếu Node truyền (zca-js kèm dName/avt)
        d_name = (data.get("dName") or "").strip()
        if d_name and d_name != conv.name:
            conv.name = d_name
        d_avatar = (data.get("avatar") or "").strip()
        if d_avatar and d_avatar != conv.avatar:
            conv.avatar = d_avatar

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
                if hasattr(brain.channel, "set_ctx"):
                    brain.channel.set_ctx(acc if acc != "default" else None)
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

        _submit(_run)
        return {"ok": True}

    # CRM Khách hàng (gộp mọi kênh — đọc thẳng SQLite dùng chung)
    from app.web_api.customers_api import register_customers_routes
    register_customers_routes(app)

    # Loyalty: mã giảm giá + điểm thưởng (đi cùng CRM/đơn hàng)
    from app.web_api.loyalty_api import register_loyalty_routes
    register_loyalty_routes(app)

    # Copilot quản trị — trợ lý AI giúp chủ shop cài đặt & vận hành
    from app.web_api.copilot_api import register_copilot_routes
    register_copilot_routes(app)

    # Tin nhắn hàng loạt (broadcast/remarketing) — chỉ chủ, staff bị guard chặn
    from app.web_api.broadcast_api import register_broadcast_routes
    register_broadcast_routes(app)

    # Liên hệ khẩn cấp & thông báo chủ shop (thay tự-gọi-điện) — chỉ chủ
    from app.web_api.notify_api import register_notify_routes
    register_notify_routes(app)

    # Quản trị NỀN TẢNG (danh sách mọi shop) — chỉ chủ nền tảng
    from app.web_api.admin_api import register_admin_routes
    register_admin_routes(app)

    # Lịch đặt chỗ per-shop (Google Sheets) — shop dán link, bot tra lịch riêng
    from app.web_api.sheets_api import register_sheets_routes
    register_sheets_routes(app)

    # Công cụ chat: gửi ảnh/video/ghi âm + chốt đơn 1 chạm + câu trả lời mẫu
    from app.web_api.chat_tools import register_chat_tools
    register_chat_tools(app, "", conv_manager, getattr(brain, "channel", None),
                        account=getattr(conv_manager, "_account", "zalo") or "zalo",
                        with_canned=True)

    # MULTI-TENANT: chốt chặn hội thoại theo shop (xem install_tenant_conv_guard)
    install_tenant_conv_guard(app, conv_manager)

    # Bảo vệ API quản trị bridge bằng Bearer token. Công khai: đăng nhập/đăng ký
    # Google, /incoming (Node localhost gọi vào), webhook đối soát tiền /payhook,
    # chat tư vấn landing /support/chat, phục vụ ảnh /photos + /media. Còn lại
    # (/conversations, /bot-toggle, /stats, billing, orders, prompt…) cần đăng nhập.
    install_auth_guard(
        app,
        public_exact={
            "/auth/login", "/auth/register", "/auth/google",
            "/auth/forgot", "/auth/reset",
            "/incoming", "/payhook", "/support/chat",
        },
        public_prefixes=("/photos/file", "/photos/media", "/media"),
        # Nhân viên (role=staff) chỉ làm hộp thư/khách/đơn — cấm phần quản trị
        staff_deny=(
            "/billing", "/prompt", "/team", "/broadcasts", "/copilot", "/notify",
            "/admin", "/zalo", "/sheets", "/orders/bank", "/bot-toggle",
            "POST /photos/sets", "DELETE /photos/sets",
            "DELETE /conversations",     # xoá hội thoại: chỉ chủ
        ),
    )

    return app
