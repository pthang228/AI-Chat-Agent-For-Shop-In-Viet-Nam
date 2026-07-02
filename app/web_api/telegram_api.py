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
from app.web_api.bridge import _load_bot_state, _save_bot_state, _channel_enabled, _conv_summary
from app.web_api.stats_util import compute_stats

log = logging.getLogger("telegram_api")

# Registry poller đang chạy: key ("__env__" hoặc bot_id) -> Event dừng
_pollers: dict = {}
_plock = threading.Lock()

# Sau bao nhiêu lỗi 401/403 liên tiếp thì dừng poller (token bị thu hồi/sai)
_MAX_AUTH_FAILURES = 5


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

    # Cập nhật tên hiển thị của khách (lấy từ tin Telegram)
    if name:
        conv_for_name = conv_manager.get(user_id)
        if name != conv_for_name.name:
            conv_for_name.name = name

    # Kiểm tra per-bot trước ("telegram:bot_id"), fallback lên channel rồi global
    _ch_key = f"telegram:{bot_id}" if bot_id else "telegram"
    if not _channel_enabled(_load_bot_state(), _ch_key):
        log.info(f"[TG] bot đang TẮT ({_ch_key}) → bỏ qua {user_id}")
        return

    conv = conv_manager.get(user_id)
    if conv.is_owner_active():
        log.info(f"[TG] owner_active {user_id} → im lặng")
        return

    # Gói dịch vụ của CHỦ bot: hết hạn / hết quota AI tháng → ngừng trả lời
    # (ghi 1 lượt AI khi cho qua). Bot chưa gắn chủ → gate toàn cục.
    from app.core import billing
    owner = store.get_owner_username(bot_id) if (store and bot_id) else None
    if not billing.channel_gate(owner):
        log.info(f"[TG] gói/quota chủ ({owner}) không cho phép → bỏ qua {user_id}")
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


def poll_loop(key, token, bot_id, brain, conv_manager, store=None, stop=None):
    """Long-poll getUpdates (1 thread/bot). Tự dừng nếu token sai liên tục."""
    base = f"https://api.telegram.org/bot{token}"
    offset = None
    auth_failures = 0
    while not (stop and stop()):
        try:
            r = requests.get(f"{base}/getUpdates",
                             params={"timeout": 50, "offset": offset}, timeout=60)

            if r.status_code == 429:
                # Rate-limit: đọc Retry-After từ Telegram, không spam
                retry_after = 3
                try:
                    retry_after = int(r.json().get("parameters", {}).get("retry_after", 3))
                except Exception:
                    pass
                log.warning(f"[TG poll {key}] rate-limited 429, chờ {retry_after}s")
                time.sleep(retry_after)
                continue

            if r.status_code in (401, 403):
                auth_failures += 1
                log.error(f"[TG poll {key}] {r.status_code} lần {auth_failures}/{_MAX_AUTH_FAILURES}")
                if auth_failures >= _MAX_AUTH_FAILURES:
                    log.error(f"[TG poll {key}] dừng poller — token không còn hợp lệ")
                    with _plock:
                        _pollers.pop(key, None)  # xóa khỏi registry → supervisor không restart
                    return
                time.sleep(5)
                continue

            if r.status_code >= 400:
                log.error(f"[TG poll {key}] {r.status_code}: {r.text[:200]}")
                time.sleep(3)
                continue

            auth_failures = 0  # reset sau request thành công
            for up in r.json().get("result", []):
                offset = up["update_id"] + 1
                handle_update(up, brain, conv_manager, bot_id=bot_id, store=store)

        except Exception as e:
            log.error(f"[TG poll {key}] lỗi mạng: {e}")
            time.sleep(3)


def _supervised_poll(key, token, bot_id, brain, conv_manager, store, stop_event):
    """Wrapper tự restart poll_loop nếu crash ngoài dự kiến."""
    while not stop_event.is_set():
        try:
            poll_loop(key, token, bot_id, brain, conv_manager, store, stop_event.is_set)
        except Exception as e:
            log.error(f"[TG poller {key}] crash ngoài dự kiến: {e}", exc_info=True)
        if stop_event.is_set():
            break
        with _plock:
            if key not in _pollers:
                break  # token hỏng → đã tự xóa khỏi registry, không restart
        log.info(f"[TG poller {key}] sẽ restart sau 10s")
        time.sleep(10)
    log.info(f"[TG poller {key}] đã dừng hoàn toàn")


def start_poller(key, token, bot_id, brain, conv_manager, store=None) -> bool:
    """Bật 1 poller có giám sát (nếu chưa chạy). key='__env__' cho bot .env."""
    with _plock:
        if key in _pollers:
            return False
        stop = threading.Event()
        _pollers[key] = stop
    threading.Thread(
        target=_supervised_poll,
        args=(key, token, bot_id, brain, conv_manager, store, stop),
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

    @app.route("/tg/pollers")
    def tg_pollers():
        """Danh sách poller đang chạy — dùng để debug bot có online không."""
        with _plock:
            active = list(_pollers.keys())
        return {"ok": True, "active": active, "count": len(active)}

    @app.route("/tg/stats")
    def tg_stats():
        bot_id = request.args.get("bot_id", "")

        def _flt(u):
            if not u.startswith("tg:"):
                return False
            if bot_id:
                parts = u.split(":")
                return len(parts) >= 3 and parts[1] == bot_id
            return True

        return jsonify(compute_stats(
            conv_manager, request.args.get("from"), request.args.get("to"),
            uid_filter=_flt))

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
        from app.web_api.auth_api import current_username
        owner = current_username()   # chủ homestay đang đăng nhập (để tính quota/gói)
        store.upsert(bot_id, token=token, username=username, name=name, owner_username=owner)
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
        state = _load_bot_state()
        for b in bots:
            u = b.get("username")
            b["link"] = f"https://t.me/{u}" if u else None
            b["owner_link"] = f"https://t.me/{u}?start={code}" if u else None
            b["bot_enabled"] = _channel_enabled(state, f"telegram:{b['bot_id']}")
        return jsonify(bots)

    @app.route("/tg/bots/<bot_id>", methods=["DELETE"])
    def tg_remove(bot_id):
        if store:
            store.remove(bot_id)
        stop_poller(bot_id)
        return {"ok": True}

    @app.route("/tg/bots/<bot_id>/toggle", methods=["POST"])
    def tg_bot_toggle(bot_id):
        """Bật/tắt riêng 1 bot Telegram. body {enabled: bool}."""
        data = request.get_json(force=True, silent=True) or {}
        enabled = bool(data.get("enabled", True))
        state = _load_bot_state()
        state.setdefault("channels", {})[f"telegram:{bot_id}"] = enabled
        _save_bot_state(state)
        log.info(f"[TG] bot {bot_id} toggle → enabled={enabled}")
        return {"ok": True, "bot_id": bot_id, "enabled": enabled}

    @app.route("/tg/bots/<bot_id>/status")
    def tg_bot_status(bot_id):
        state = _load_bot_state()
        return {"ok": True, "bot_id": bot_id,
                "enabled": _channel_enabled(state, f"telegram:{bot_id}")}

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

    def _backfill_tg_names(missing):
        """Gọi Telegram getChat để lấy tên cho các khách chưa có tên (chạy nền)."""
        changed = False
        for uid in missing:
            parts = uid.split(":")
            if len(parts) < 3:
                continue
            bid, chat_id = parts[1], parts[2]
            bot = store.get(bid) if store else None
            token = bot.get("token") if bot else None
            if not token:
                continue
            try:
                r = requests.get(
                    f"https://api.telegram.org/bot{token}/getChat",
                    params={"chat_id": chat_id},
                    timeout=10,
                )
                if r.status_code == 200:
                    res = r.json().get("result", {})
                    name = " ".join(x for x in [res.get("first_name"), res.get("last_name")] if x)
                    if not name:
                        name = res.get("username", "")
                    if name:
                        conv = conv_manager.get(uid)
                        if not conv.name:
                            conv.name = name
                            changed = True
            except Exception as e:
                log.debug(f"[tg name] {uid}: {e}")
        if changed:
            conv_manager.save()

    @app.route("/tg/conversations")
    def tg_conversations():
        bot_id = request.args.get("bot_id", "")
        try:
            limit = min(max(int(request.args.get("limit", 50)), 1), 200)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 50, 0
        rows = []
        missing_names = []
        for uid, conv in list(conv_manager._sessions.items()):
            if not uid.startswith("tg:"):
                continue
            parts = uid.split(":")
            uid_bot = parts[1] if len(parts) >= 3 else ""
            if bot_id and uid_bot != bot_id:
                continue
            rows.append(_conv_summary(uid, conv))
            if not conv.name:
                missing_names.append(uid)
        if missing_names:
            threading.Thread(target=_backfill_tg_names, args=(missing_names,), daemon=True).start()
        rows.sort(key=lambda r: r["last_updated"], reverse=True)
        total = len(rows)
        return jsonify({"total": total, "offset": offset, "limit": limit,
                        "items": rows[offset:offset + limit]})

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
            "name": getattr(conv, "name", ""),
            "owner_active": conv.is_owner_active(),
            "stage": conv.stage,
            "messages": msgs,
        })

    @app.route("/tg/conversations/<user_id>/send", methods=["POST"])
    def tg_send_message(user_id):
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "tin trống"}, 400
        # set_ctx đúng bot để gửi qua đúng token
        parts = user_id.split(":")
        bot_id = parts[1] if len(parts) >= 3 else None
        try:
            if bot_id:
                channel.set_ctx(bot_id)
            channel.send_text(user_id, text)
        except Exception as e:
            log.error(f"[tg send] lỗi gửi {user_id}: {e}")
            return {"ok": False, "error": str(e)}, 500
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(text)
        conv.set_owner_active(True)
        conv_manager.save()
        return {"ok": True}

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
