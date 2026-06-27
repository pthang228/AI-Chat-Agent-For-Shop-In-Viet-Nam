"""
Telegram — "onMessage" + API hội thoại + kết nối ĐA KHÁCH cho kênh Telegram bot.

Nhận tin bằng LONG-POLLING (getUpdates) → KHÔNG cần public URL/webhook/deploy.
Mỗi bot (mỗi homestay) 1 poller riêng (1 thread). Khách DÁN token trong web →
/tg/connect xác thực (getMe) → lưu store + bật poller ngay.

Flask (cổng 5007) phục vụ web React: /tg/connect, /tg/bots, /tg/conversations...
Tôn trọng nút bật/tắt bot toàn cục (data/bot_state.json) + owner-takeover.
"""

import time
import logging
import threading

import requests
from flask import Flask, request, jsonify

from app.core.config import Config
from app.core import telegram_owner, telegram_login
from app.web_api.bridge import _load_bot_state, _channel_enabled, _conv_summary

log = logging.getLogger("telegram_api")

# Registry poller đang chạy: key ("__env__" hoặc bot_id) -> Event dừng
_pollers: dict = {}
_plock = threading.Lock()


def parse_message(update: dict):
    """Update Telegram → (chat_id, text, name) cho chat 1-1; None nếu bỏ qua."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    chat = msg.get("chat") or {}
    if chat.get("type") != "private":   # bot chỉ tư vấn 1-1, bỏ group/channel
        return None
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if chat_id is None:
        return None
    name = " ".join(x for x in [chat.get("first_name"), chat.get("last_name")] if x) or chat.get("username") or ""
    return str(chat_id), text, name


def _uid(bot_id, chat_id):
    return f"tg:{bot_id}:{chat_id}" if bot_id else f"tg:{chat_id}"


def _try_register_owner(chat_id, text, name, brain, conv_manager, bot_id, store) -> bool:
    """Chủ nhắn '/start <mã>' hoặc '/chunha' → tự lưu làm chủ. True nếu đã xử lý."""
    t = (text or "").strip()
    if not (t.startswith("/start") or t.startswith("/chunha")):
        return False
    parts = t.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    setup = (Config.TELEGRAM_OWNER_SETUP_CODE or "").strip()
    is_owner_cmd = t.startswith("/chunha") or (setup and code == setup)
    uid = _uid(bot_id, chat_id)
    if is_owner_cmd:
        if bot_id and store:
            store.set_owner(bot_id, chat_id, name)
        else:
            telegram_owner.set_owner(chat_id, name)
        try:
            brain.channel.send_text(uid,
                f"✅ Đã đăng ký bạn ({name or chat_id}) làm CHỦ NHÀ. Bạn sẽ nhận báo + cuộc gọi khi khách cần.")
        except Exception:
            pass
        return True
    if t.startswith("/start"):   # khách bấm vào bot → chào, không vào brain
        try:
            brain.channel.send_text(uid,
                "Xin chào! Mình là trợ lý đặt phòng. Bạn cần hỏi phòng, giá hay đặt phòng ạ? 😊")
        except Exception:
            pass
        return True
    return False


def handle_update(update, brain, conv_manager, bot_id=None, store=None):
    """Áp gate bật/tắt + owner-takeover rồi đẩy vào brain (chạy nền)."""
    parsed = parse_message(update)
    if not parsed:
        return
    chat_id, text, name = parsed
    if not text:
        return

    if text.startswith("/"):     # /start, /chunha → đăng ký chủ / chào
        _try_register_owner(chat_id, text, name, brain, conv_manager, bot_id, store)
        return

    user_id = _uid(bot_id, chat_id)

    if not _channel_enabled(_load_bot_state(), "telegram"):
        log.info(f"[TG] bot đang TẮT → bỏ qua {user_id}")
        return

    conv = conv_manager.get(user_id)
    if conv.is_owner_active():
        log.info(f"[TG] owner_active {user_id} → im lặng")
        return

    log.info(f"[TG] bot={bot_id} {chat_id} | {text[:80]!r}")

    def _run():
        try:
            time.sleep(Config.REPLY_DELAY)
            brain.channel.set_ctx(bot_id)     # cho notify/call báo đúng chủ của bot này
            brain.handle(user_id, text)
        except Exception as e:
            log.error(f"[TG] lỗi xử lý {user_id}: {e}", exc_info=True)
            try:
                brain.channel.send_text(
                    user_id,
                    "Xin lỗi, hệ thống đang gặp sự cố nhỏ. Chủ nhà sẽ liên hệ lại bạn sớm! 🙏",
                )
            except Exception:
                pass

    threading.Thread(target=_run, daemon=True).start()


def poll_loop(token, bot_id, brain, conv_manager, store=None, stop=None):
    """Long-poll getUpdates vô hạn (1 thread/bot). stop() để dừng."""
    base = f"https://api.telegram.org/bot{token}"
    offset = None
    while not (stop and stop()):
        try:
            r = requests.get(f"{base}/getUpdates",
                             params={"timeout": 50, "offset": offset}, timeout=60)
            if r.status_code >= 400:
                log.error(f"[TG poll bot={bot_id}] {r.status_code}: {r.text[:200]}")
                time.sleep(3); continue
            for up in r.json().get("result", []):
                offset = up["update_id"] + 1
                handle_update(up, brain, conv_manager, bot_id=bot_id, store=store)
        except Exception as e:
            log.error(f"[TG poll bot={bot_id}] lỗi: {e}")
            time.sleep(3)


def start_poller(key, token, bot_id, brain, conv_manager, store=None) -> bool:
    """Bật 1 poller cho bot (nếu chưa chạy). key='__env__' cho bot .env."""
    with _plock:
        if key in _pollers:
            return False
        stop = threading.Event()
        _pollers[key] = stop
    threading.Thread(
        target=poll_loop,
        args=(token, bot_id, brain, conv_manager, store, stop.is_set),
        daemon=True,
    ).start()
    log.info(f"[TG] bật poller {key} (bot_id={bot_id})")
    return True


def stop_poller(key):
    with _plock:
        ev = _pollers.pop(key, None)
    if ev:
        ev.set()


def create_telegram_api(brain, conv_manager, channel, store=None) -> Flask:
    app = Flask(__name__)

    @app.after_request
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    @app.route("/health")
    def health():
        return {"ok": True}

    @app.route("/tg/config")
    def tg_config():
        """Thông tin chung: mã đăng ký chủ + bot .env (nếu có)."""
        return {
            "setup_code": Config.TELEGRAM_OWNER_SETUP_CODE,
            "env_configured": bool(channel.token),
        }

    # ── Kết nối ĐA KHÁCH: dán token bot trong web ──────────────────────
    @app.route("/tg/connect", methods=["POST"])
    def tg_connect():
        if store is None:
            return {"ok": False, "error": "store chưa sẵn sàng"}, 500
        data = request.get_json(force=True, silent=True) or {}
        token = (data.get("token") or "").strip()
        if not token:
            return {"ok": False, "error": "thiếu token"}, 400
        # Xác thực token bằng getMe
        try:
            me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
        except Exception as e:
            return {"ok": False, "error": f"không gọi được Telegram: {e}"}, 502
        if not me.get("ok"):
            return {"ok": False, "error": "Token không hợp lệ (getMe thất bại)"}, 400
        res = me["result"]
        bot_id = str(res["id"])
        username = res.get("username", "")
        name = res.get("first_name", "")
        store.upsert(bot_id, token=token, username=username, name=name)
        start_poller(bot_id, token, bot_id, brain, conv_manager, store)
        return {"ok": True, "bot": {
            "bot_id": bot_id, "username": username, "name": name,
            "link": f"https://t.me/{username}" if username else None,
            "owner_link": f"https://t.me/{username}?start={Config.TELEGRAM_OWNER_SETUP_CODE}" if username else None,
        }}

    @app.route("/tg/bots")
    def tg_bots():
        bots = store.list_bots() if store else []
        code = Config.TELEGRAM_OWNER_SETUP_CODE
        for b in bots:   # bổ sung link cho UI
            u = b.get("username")
            b["link"] = f"https://t.me/{u}" if u else None
            b["owner_link"] = f"https://t.me/{u}?start={code}" if u else None
        return jsonify(bots)

    @app.route("/tg/bots/<bot_id>", methods=["DELETE"])
    def tg_remove(bot_id):
        if store:
            store.remove(bot_id)
        stop_poller(bot_id)
        return {"ok": True}

    @app.route("/tg/set-owner", methods=["POST"])
    def tg_set_owner():
        """ADMIN tự chọn chủ = 1 người ĐÃ nhắn bot (Telegram chặn bot nhắn người
        chưa tương tác). body {user_id: 'tg:<bot>:<chat>' hoặc 'tg:<chat>', name?}."""
        data = request.get_json(force=True, silent=True) or {}
        uid = (data.get("user_id") or "").strip()
        name = data.get("name") or ""
        parts = uid.split(":")
        if len(parts) >= 3:                       # tg:bot:chat (đa khách)
            bot_id, chat_id = parts[1], ":".join(parts[2:])
            if store:
                store.set_owner(bot_id, chat_id, name)
        elif len(parts) == 2:                     # tg:chat (1 bot .env)
            telegram_owner.set_owner(parts[1], name)
        else:
            return {"ok": False, "error": "user_id không hợp lệ"}, 400
        return {"ok": True}

    # ── Đăng nhập acc GỌI (Telethon) bằng QR — theo từng bot ───────────
    def _save_if_done(bot_id, st):
        """Khi đăng nhập xong → cất session vào store rồi dọn phiên."""
        if st.get("state") == "done" and store:
            res = telegram_login.take_result(bot_id)
            if res:
                session, profile = res
                store.set_caller_session(bot_id, session, profile)

    @app.route("/tg/caller")
    def tg_caller():
        """Trạng thái acc gọi của 1 bot (đã đăng nhập QR chưa)."""
        bot_id = request.args.get("bot_id", "")
        b = store.get(bot_id) if (store and bot_id) else {}
        return {
            "logged_in": bool(b.get("caller_session")),
            "name": b.get("caller_name", ""),
            "username": b.get("caller_username", ""),
        }

    @app.route("/tg/caller/qr-login", methods=["POST"])
    def tg_caller_qr():
        data = request.get_json(force=True, silent=True) or {}
        bot_id = (data.get("bot_id") or "").strip()
        if not bot_id:
            return {"ok": False, "error": "thiếu bot_id"}, 400
        return jsonify(telegram_login.start_login(bot_id))

    @app.route("/tg/caller/login-status")
    def tg_caller_login_status():
        bot_id = request.args.get("bot_id", "")
        st = telegram_login.status(bot_id)
        _save_if_done(bot_id, st)
        return jsonify(st)

    @app.route("/tg/caller/password", methods=["POST"])
    def tg_caller_password():
        data = request.get_json(force=True, silent=True) or {}
        bot_id = (data.get("bot_id") or "").strip()
        pw = data.get("password") or ""
        if not bot_id:
            return {"ok": False, "error": "thiếu bot_id"}, 400
        res = telegram_login.submit_password(bot_id, pw)
        if res.get("ok"):
            _save_if_done(bot_id, telegram_login.status(bot_id))
        return jsonify(res)

    @app.route("/tg/caller/logout", methods=["POST"])
    def tg_caller_logout():
        data = request.get_json(force=True, silent=True) or {}
        bot_id = (data.get("bot_id") or "").strip()
        if store and bot_id:
            store.clear_caller_session(bot_id)
        telegram_login.stop_login(bot_id)
        return {"ok": True}

    # ── Hội thoại (lọc theo bot) ───────────────────────────────────────

    @app.route("/tg/conversations")
    def tg_conversations():
        bot_id = request.args.get("bot_id", "")
        rows = []
        for uid, conv in list(conv_manager._sessions.items()):
            if not uid.startswith("tg:"):
                continue
            parts = uid.split(":")
            uid_bot = parts[1] if len(parts) >= 3 else ""
            if bot_id and uid_bot != bot_id:
                continue
            rows.append(_conv_summary(uid, conv))
        rows.sort(key=lambda r: r["last_updated"], reverse=True)
        return jsonify(rows)

    @app.route("/tg/conversations/<user_id>")
    def tg_conversation(user_id):
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
            "owner_active": conv.is_owner_active(),
            "stage": conv.stage,
            "messages": msgs,
        })

    @app.route("/tg/conversations/<user_id>/toggle-bot", methods=["POST"])
    def tg_toggle_bot(user_id):
        data = request.get_json(force=True, silent=True) or {}
        bot_on = bool(data.get("bot_on", True))
        conv = conv_manager.get(user_id)
        conv.set_owner_active(not bot_on)
        conv_manager.save()
        return {"ok": True, "bot_on": bot_on, "owner_active": conv.is_owner_active()}

    @app.route("/tg/conversations/<user_id>", methods=["DELETE"])
    def tg_reset(user_id):
        conv_manager.reset(user_id)
        return {"ok": True}

    return app
