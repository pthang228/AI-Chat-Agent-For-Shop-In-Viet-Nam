"""
Webchat — API cho widget nhúng website khách hàng + quản trị kênh (Flask 5011).

KHÔNG có webhook bên thứ ba: widget (widget.js) trên web của chủ shop gọi
THẲNG về đây. 2 nhóm endpoint:

CÔNG KHAI (khách web lạ, KHÔNG Bearer — rate-limit theo IP, CORS mở "*" vì
widget chạy trên domain bất kỳ của khách hàng; gửi không preflight):
  POST /webchat/pub/send     {site, visitor, text, name?} → {ok, seq}
  GET  /webchat/pub/poll     ?site&visitor&since=N        → {ok, seq, messages[]}
  GET  /webchat/pub/history  ?site&visitor                → {ok, name, messages[]}
  GET  /widget.js            — file widget nhúng
  GET  /media/<path>         — ảnh phòng/bảng giá/outbox cho widget

QUẢN TRỊ (Bearer như mọi kênh): /webchat/sites (tạo site + mã nhúng, toggle,
xoá), /webchat/conversations..., /webchat/stats, /webchat/set-owner, chat_tools.

Bot trả lời KHÔNG đồng bộ: send chỉ queue brain chạy nền rồi trả seq hiện tại;
widget poll nhanh (1s trong lúc chờ) để lấy câu trả lời — cùng cơ chế với tin
chủ shop nhắn tay từ dashboard.
"""

import logging
import re
import threading
import time
from pathlib import Path

from flask import Flask, request, jsonify, send_file

from app.core.config import Config
from app.web_api.bridge import _load_bot_state, _save_bot_state, _channel_enabled, _conv_summary
from app.web_api.stats_util import compute_stats
from app.web_api.api_guard import install_cors, install_auth_guard, submit

log = logging.getLogger("webchat_api")

WIDGET_FILE = Path(__file__).parent / "static" / "webchat_widget.js"

MAX_MSG_CHARS = 1000
VISITOR_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")

# Rate-limit theo IP (widget công khai trên internet) — như support_api
RATE_WINDOW = 600       # 10 phút
RATE_MAX = 60           # tối đa 60 tin / IP / 10 phút (thoải mái cho 1 khách thật)
_hits: dict = {}
_hlock = threading.Lock()


def _rate_ok(ip: str) -> bool:
    now = time.time()
    with _hlock:
        arr = [t for t in _hits.get(ip, []) if now - t < RATE_WINDOW]
        if len(arr) >= RATE_MAX:
            _hits[ip] = arr
            return False
        arr.append(now)
        _hits[ip] = arr
        return True


def _uid(site_id, visitor):
    return f"web:{site_id}:{visitor}"


PUBLIC_PREFIXES = ("/webchat/pub/", "/widget.js", "/media/")


def create_webchat_api(brain, conv_manager, channel, store=None) -> Flask:
    app = Flask(__name__)
    install_cors(app)
    install_auth_guard(
        app,
        public_exact={"/webchat/config", "/widget.js"},
        public_prefixes=PUBLIC_PREFIXES,
        # Nhân viên: chỉ hộp thư — cấm tạo/xoá site, đặt chủ
        staff_deny=(
            "POST /webchat/sites", "DELETE /webchat/sites",
            "/webchat/set-owner", "DELETE /webchat/conversations",
        ),
    )

    # Widget chạy trên DOMAIN BẤT KỲ của khách hàng → route công khai phải mở
    # CORS "*" (đè add_cors vốn chỉ cho ALLOWED_ORIGINS). Route quản trị giữ nguyên.
    @app.after_request
    def _public_cors(resp):
        p = request.path
        if any(p.startswith(x) for x in PUBLIC_PREFIXES) or p == "/widget.js":
            resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    # Công cụ chat: gửi ảnh/video/ghi âm + chốt đơn 1 chạm (dashboard)
    from app.web_api.chat_tools import register_chat_tools
    register_chat_tools(app, "/webchat", conv_manager, channel, account="webchat")

    @app.route("/health")
    def health():
        return {"ok": True}

    @app.route("/webchat/config")
    def wc_config():
        return {
            "public_base_url": Config.PUBLIC_BASE_URL,
            "sites": len(store.list_sites()) if store else 0,
        }

    # ── Widget + media (công khai) ─────────────────────────────────────

    @app.route("/widget.js")
    def wc_widget():
        if not WIDGET_FILE.exists():
            return "// widget chưa build", 404, {"Content-Type": "application/javascript"}
        resp = send_file(WIDGET_FILE, mimetype="application/javascript")
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp

    @app.route("/media/<path:rel>")
    def wc_media(rel):
        base = Path(Config.MEDIA_DIR).resolve()
        target = (base / rel).resolve()
        if base not in target.parents and target != base:   # chặn ../ traversal
            return {"error": "forbidden"}, 403
        if not target.is_file():
            return {"error": "not found"}, 404
        return send_file(target)

    # ── Khách web nhắn (công khai, rate-limit) ─────────────────────────

    def _site_ok(site_id) -> bool:
        return bool(site_id) and store is not None and store.exists(site_id)

    @app.route("/webchat/pub/send", methods=["POST"])
    def wc_send():
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
        if not _rate_ok(ip):
            return {"ok": False, "error": "rate"}, 429
        data = request.get_json(force=True, silent=True) or {}
        site = str(data.get("site") or "").strip()
        visitor = str(data.get("visitor") or "").strip()
        text = str(data.get("text") or "").strip()[:MAX_MSG_CHARS]
        name = str(data.get("name") or "").strip()[:60]
        if not _site_ok(site):
            return {"ok": False, "error": "site không tồn tại"}, 404
        if not VISITOR_RE.match(visitor):
            return {"ok": False, "error": "visitor không hợp lệ"}, 400
        if not text:
            return {"ok": False, "error": "tin trống"}, 400

        user_id = _uid(site, visitor)
        conv = conv_manager.get(user_id)
        if name and name != conv.name:
            conv.name = name
        elif not conv.name:
            conv.name = f"Khách web #{visitor[:5]}"

        seq_now = channel.last_seq(user_id)
        log.info(f"[Webchat] site={site} {visitor} | {text[:80]!r}")

        # Gate bật/tắt + owner-takeover + gói/quota — NHƯNG webchat là hộp thư
        # của CHÍNH MÌNH: tin khách phải được LƯU kể cả khi bot im (chủ trả lời
        # tay từ dashboard), khác các kênh webhook (nền tảng giữ hộ inbox).
        gated = None
        if not _channel_enabled(_load_bot_state(), f"webchat:{site}"):
            gated = "bot tắt"
        elif conv.is_owner_active():
            gated = "owner_active"
        else:
            from app.core import billing
            owner = store.get_owner_username(site)
            if not billing.channel_gate(owner):
                gated = f"gói/quota chủ ({owner})"

        if gated:
            log.info(f"[Webchat] {gated} → bot im lặng {user_id}")
            conv.add_user_message(text)
            conv_manager.save()
            return {"ok": True, "seq": seq_now, "bot": False}

        def _run():
            try:
                time.sleep(Config.REPLY_DELAY)
                brain.channel.set_ctx(site)     # notify/call báo đúng chủ site
                brain.handle(user_id, text)
                conv_manager.save()   # flush ngay: /history của widget đọc từ DB sau restart
            except Exception as e:
                log.error(f"[Webchat] lỗi xử lý {user_id}: {e}", exc_info=True)
                try:
                    brain.channel.send_text(
                        user_id,
                        "Xin lỗi, hệ thống đang gặp sự cố nhỏ. Shop sẽ liên hệ lại bạn sớm! 🙏",
                    )
                except Exception:
                    pass

        submit(_run)
        return {"ok": True, "seq": seq_now, "bot": True}

    @app.route("/webchat/pub/poll")
    def wc_poll():
        site = request.args.get("site", "").strip()
        visitor = request.args.get("visitor", "").strip()
        if not _site_ok(site) or not VISITOR_RE.match(visitor):
            return {"ok": False, "error": "bad params"}, 400
        try:
            since = max(int(request.args.get("since", 0)), 0)
        except ValueError:
            since = 0
        msgs, seq = channel.fetch(_uid(site, visitor), since)
        return {"ok": True, "seq": seq, "messages": msgs}

    @app.route("/webchat/pub/history")
    def wc_history():
        site = request.args.get("site", "").strip()
        visitor = request.args.get("visitor", "").strip()
        if not _site_ok(site) or not VISITOR_RE.match(visitor):
            return {"ok": False, "error": "bad params"}, 400
        conv = conv_manager._sessions.get(_uid(site, visitor))
        msgs = [
            {"role": m.get("role"), "content": m.get("content", "")}
            for m in (conv.messages if conv else [])
            if not m.get("content", "").startswith("[HỆ THỐNG]")
        ]
        return {"ok": True, "name": (store.get(site) or {}).get("name", ""),
                "messages": msgs, "seq": channel.last_seq(_uid(site, visitor))}

    # ── Quản trị site (Bearer) ─────────────────────────────────────────

    def _snippet(sid) -> str:
        base = (Config.PUBLIC_BASE_URL or request.host_url).rstrip("/")
        return f'<script src="{base}/widget.js" data-site="{sid}" defer></script>'

    @app.route("/webchat/sites")
    def wc_sites():
        sites = store.list_sites() if store else []
        state = _load_bot_state()
        for s in sites:
            s["bot_enabled"] = _channel_enabled(state, f"webchat:{s['site_id']}")
            s["snippet"] = _snippet(s["site_id"])
        return jsonify(sites)

    @app.route("/webchat/sites", methods=["POST"])
    def wc_create_site():
        if store is None:
            return {"ok": False, "error": "store chưa sẵn sàng"}, 500
        data = request.get_json(force=True, silent=True) or {}
        name = (data.get("name") or "").strip()
        from app.web_api.auth_api import current_username
        sid = store.create(name, owner_username=current_username())
        return {"ok": True, "site": {"site_id": sid, "name": store.get(sid).get("name", ""),
                                     "snippet": _snippet(sid)}}

    @app.route("/webchat/sites/<site_id>", methods=["DELETE"])
    def wc_remove_site(site_id):
        if store:
            store.remove(site_id)
        return {"ok": True}

    @app.route("/webchat/sites/<site_id>/toggle", methods=["POST"])
    def wc_toggle_site(site_id):
        data = request.get_json(force=True, silent=True) or {}
        enabled = bool(data.get("enabled", True))
        state = _load_bot_state()
        state.setdefault("channels", {})[f"webchat:{site_id}"] = enabled
        _save_bot_state(state)
        log.info(f"[Webchat] {site_id} toggle → enabled={enabled}")
        return {"ok": True, "site_id": site_id, "enabled": enabled}

    @app.route("/webchat/set-owner", methods=["POST"])
    def wc_set_owner():
        """Chọn chủ = 1 visitor ĐÃ nhắn site này (⭐ Đặt làm chủ) — nhận notify
        khi mở widget. body {user_id: 'web:<site>:<visitor>', name?}."""
        data = request.get_json(force=True, silent=True) or {}
        uid = (data.get("user_id") or "").strip()
        parts = uid.split(":")
        if len(parts) >= 3 and store:
            store.set_owner(parts[1], ":".join(parts[2:]), data.get("name") or "")
            return {"ok": True}
        return {"ok": False, "error": "user_id không hợp lệ"}, 400

    # ── Thống kê + hội thoại (Bearer) ──────────────────────────────────

    @app.route("/webchat/stats")
    def wc_stats():
        site_id = request.args.get("site_id", "")

        def _flt(u):
            if not u.startswith("web:"):
                return False
            if site_id:
                parts = u.split(":")
                return len(parts) >= 3 and parts[1] == site_id
            return True

        return jsonify(compute_stats(
            conv_manager, request.args.get("from"), request.args.get("to"),
            uid_filter=_flt))

    @app.route("/webchat/conversations")
    def wc_conversations():
        site_id = request.args.get("site_id", "")
        try:
            limit = min(max(int(request.args.get("limit", 50)), 1), 200)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 50, 0
        rows = []
        for uid, conv in list(conv_manager._sessions.items()):
            if not uid.startswith("web:"):
                continue
            parts = uid.split(":")
            uid_site = parts[1] if len(parts) >= 3 else ""
            if site_id and uid_site != site_id:
                continue
            rows.append(_conv_summary(uid, conv))
        rows.sort(key=lambda r: r["last_updated"], reverse=True)
        total = len(rows)
        return jsonify({"total": total, "offset": offset, "limit": limit,
                        "items": rows[offset:offset + limit]})

    @app.route("/webchat/conversations/<user_id>")
    def wc_conversation(user_id):
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

    @app.route("/webchat/conversations/<user_id>/send", methods=["POST"])
    def wc_send_message(user_id):
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "tin trống"}, 400
        parts = user_id.split(":")
        site_id = parts[1] if len(parts) >= 3 else None
        try:
            channel.set_ctx(site_id)
            channel.send_text(user_id, text)
        except Exception as e:
            log.error(f"[webchat send] lỗi gửi {user_id}: {e}")
            return {"ok": False, "error": str(e)}, 500
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(text)
        conv.set_owner_active(True)
        conv_manager.save()
        # Bot học từ hội thoại: chủ trả lời tay → AI đề xuất mẩu tri thức (nền)
        from app.core import knowledge_learn
        submit(knowledge_learn.suggest_from_reply, user_id, "webchat", list(conv.messages), text)
        return {"ok": True}

    @app.route("/webchat/conversations/<user_id>/toggle-bot", methods=["POST"])
    def wc_toggle_bot(user_id):
        data = request.get_json(force=True, silent=True) or {}
        bot_on = bool(data.get("bot_on", True))
        conv = conv_manager.get(user_id)
        conv.set_owner_active(not bot_on)
        conv_manager.save()
        return {"ok": True, "bot_on": bot_on, "owner_active": conv.is_owner_active()}

    @app.route("/webchat/conversations/<user_id>", methods=["DELETE"])
    def wc_reset(user_id):
        conv_manager.reset(user_id)
        return {"ok": True}

    return app
