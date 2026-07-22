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

import base64
import hmac
import json
import time
import hashlib
import logging
import threading
from pathlib import Path

import requests as _req

from flask import Flask, request, jsonify, send_from_directory

from app.core.config import Config
from app.core import comments
from app.core.comment_store import CommentStore
from app.channels import meta_graph
from app.web_api.bridge import _load_bot_state, _channel_enabled  # dùng chung helper
from app.web_api.stats_util import compute_stats
from app.web_api.api_guard import install_cors, install_auth_guard, DedupCache, submit

log = logging.getLogger("meta_webhook")

_dedup = DedupCache(500)        # nhớ mid tin đã xử lý — Meta gửi lại khi ta 200 chậm
_feed_dedup = DedupCache(500)   # nhớ comment_id đã xử lý (webhook feed gửi lại)


def _fetch_meta_name(user_id, sender, page_id, platform, brain, conv_manager):
    """Gọi Graph API lấy tên + AVATAR khách, lưu vào conv (chạy nền, 1 lần khi thiếu).
    profile_pic là URL CDN công khai (có chữ ký, hết hạn sau vài ngày) — hết hạn thì
    lần fetch sau tự làm mới vì điều kiện gọi là 'thiếu name HOẶC avatar'."""
    try:
        token = brain.channel._token_for(page_id) if hasattr(brain.channel, "_token_for") else None
        if not token:
            return
        fields = "name,profile_pic" if platform == "fb" else "name,username,profile_pic"
        r = _req.get(
            f"https://graph.facebook.com/{Config.FB_GRAPH_VERSION}/{sender}",
            params={"fields": fields, "access_token": token},
            timeout=10,
        )
        log.debug(f"[meta name] {sender} → status={r.status_code} body={r.text[:200]}")
        if r.status_code == 200:
            data = r.json()
            name = data.get("name") or data.get("username") or ""
            pic = data.get("profile_pic") or ""
            conv = conv_manager.get(user_id)
            changed = False
            if name and not conv.name:
                conv.name = name
                changed = True
            if pic and pic != conv.avatar:
                conv.avatar = pic
                changed = True
            if changed:
                conv_manager.save()
                log.info(f"[meta profile] {sender} → '{name}' avatar={'có' if pic else 'không'}")
    except Exception as e:
        log.warning(f"[meta name] {sender}: {e}")


def _parse_signed_request(signed_request: str, secret: str) -> dict | None:
    """Giải mã signed_request Meta gửi (data deletion / deauthorize).
    Định dạng '<sig>.<payload>' base64url; sig = HMAC-SHA256(payload, app_secret).
    Trả payload dict nếu chữ ký hợp lệ, None nếu sai/hỏng."""
    try:
        sig_b64, payload_b64 = signed_request.split(".", 1)
        def _b64(s):  # base64url + thêm padding
            return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(sig_b64), expected):
            return None
        return json.loads(_b64(payload_b64).decode("utf-8"))
    except Exception:
        return None


def _delete_meta_user_data(conv_manager, psid: str) -> int:
    """Xoá MỌI dữ liệu của 1 người dùng Meta (PSID/IGSID) khỏi hệ thống — hội thoại
    (fb:/ig:) + hồ sơ CRM + trí nhớ AI + lịch sử. Dùng cho data-deletion callback."""
    if not psid:
        return 0
    from app.core.db import get_db
    db = get_db()
    account = str(getattr(conv_manager, "_account", "meta"))
    # user_id kênh Meta có dạng 'fb:<page>:<psid>' / 'ig:<page>:<igsid>' → khớp đuôi
    rows = db.query(
        "SELECT user_id FROM sessions WHERE account=? AND user_id LIKE ?",
        (account, f"%:{psid}"))
    uids = [r["user_id"] for r in rows]
    for uid in uids:
        try:
            conv_manager.reset(uid)   # xoá session (DB + cache RAM)
        except Exception:
            pass
        for tbl in ("customers", "customer_memory", "customer_history"):
            try:
                db.execute(f"DELETE FROM {tbl} WHERE account=? AND user_id=?", (account, uid))
            except Exception:
                pass
    log.info(f"[data-deletion] xoá {len(uids)} hội thoại Meta của psid={psid}")
    return len(uids)


def create_meta_webhook(brain, conv_manager, store=None, comment_store=None) -> Flask:
    app = Flask(__name__)

    # Webhook đối soát tiền (SePay/Casso) — gắn Ở ĐÂY vì 5006 là cổng duy nhất
    # public qua ngrok: khai <PUBLIC_BASE_URL>/payhook trên SePay. Bank-info API
    # thì ở bridge 5005 (cần auth), nên with_bank_api=False. Notify lazy để không
    # đòi brain.channel lúc khởi tạo (tests dùng brain giả).
    from app.web_api.payment_api import register_payment_routes

    def _pay_notify(text):
        ch = getattr(brain, "channel", None)
        if ch:
            ch.notify_owner(text)

    register_payment_routes(app, notify_fn=_pay_notify, with_bank_api=False)

    # Bài viết & bình luận Facebook (list/reply/ẩn/nhắn riêng + cài đặt tự động)
    from app.web_api.posts_api import register_posts_routes
    comment_store = comment_store or CommentStore()
    register_posts_routes(app, store, comment_store)

    # Công cụ chat: gửi ảnh/video/ghi âm + chốt đơn 1 chạm (dashboard)
    from app.web_api.chat_tools import register_chat_tools
    register_chat_tools(app, "/meta", conv_manager, getattr(brain, "channel", None), account="meta")

    # MULTI-TENANT: chốt chặn tập trung — mọi thao tác lên 1 hội thoại phải
    # thuộc shop của user đăng nhập (cover cả chat_tools send-media/assign...)
    from app.web_api.bridge import install_tenant_conv_guard
    install_tenant_conv_guard(app, conv_manager)

    # CORS siết theo ALLOWED_ORIGINS + mở header Authorization (client gửi Bearer).
    install_cors(app)
    from app.web_api.security import install_security
    install_security(app, enable_global_limit=False)  # headers + rate-limit endpoint nhạy cảm (webhook không dính trần chung)
    # Bảo vệ: mọi API /meta/* quản trị cần Bearer token; webhook nền tảng + phục
    # vụ media + payhook (SePay gọi) + config thì công khai. Cổng 5006 phơi ra
    # internet qua ngrok nên đây là lỗ hổng cần bịt nhất.
    install_auth_guard(
        app,
        # Meta gọi thẳng (không token): webhook + data-deletion + deauthorize callback
        public_exact={"/fb/webhook", "/meta/config", "/payhook",
                      "/meta/data-deletion", "/meta/deauthorize", "/meta/deletion-status"},
        public_prefixes=("/media",),
        # Nhân viên: chỉ hộp thư + trả lời bình luận — cấm kết nối/ngắt Page,
        # cài đặt tự động hoá, xoá hội thoại
        staff_deny=(
            "/meta/connect", "DELETE /meta/pages", "/posts/settings",
            "DELETE /meta/conversations",
        ),
    )

    @app.route("/health")
    def health():
        # health SÂU dùng chung: chạm DB + kiểm disk, 503 khi hỏng (api_guard)
        from app.web_api.api_guard import health_payload
        return health_payload()

    # ── Data Deletion + Deauthorize (BẮT BUỘC cho App Review Meta) ──────
    # App Review đòi 2 callback này để duyệt khách LẠ dùng được (pages_messaging /
    # instagram_manage_messages). Meta POST signed_request khi user gỡ app / yêu
    # cầu xoá dữ liệu. Khai URL ở Meta Developers → Settings → Basic.

    @app.route("/meta/data-deletion", methods=["POST"])
    def meta_data_deletion():
        """Meta gọi khi user yêu cầu xoá dữ liệu → xoá thật + trả URL trạng thái."""
        signed = request.form.get("signed_request", "")
        data = _parse_signed_request(signed, Config.FB_APP_SECRET) if Config.FB_APP_SECRET else None
        if data is None:
            return {"error": "signed_request không hợp lệ"}, 400
        psid = str(data.get("user_id") or "")
        submit(_delete_meta_user_data, conv_manager, psid)   # xoá nền, trả lời Meta ngay
        # Mã xác nhận để user tra cứu trạng thái (Meta hiển thị cho user)
        code = hashlib.sha256(f"{psid}:{int(time.time())}".encode()).hexdigest()[:16]
        base = (Config.PUBLIC_BASE_URL or request.host_url).rstrip("/")
        return {"url": f"{base}/meta/deletion-status?code={code}", "confirmation_code": code}

    @app.route("/meta/deletion-status")
    def meta_deletion_status():
        """Trang trạng thái xoá dữ liệu (Meta/khách mở để xác nhận)."""
        code = request.args.get("code", "")
        return (
            "<!doctype html><meta charset=utf-8>"
            "<title>Yêu cầu xoá dữ liệu — NovaChat</title>"
            "<div style='font-family:sans-serif;max-width:560px;margin:60px auto;padding:0 20px'>"
            "<h2>✅ Đã xử lý yêu cầu xoá dữ liệu</h2>"
            "<p>Toàn bộ dữ liệu hội thoại và hồ sơ liên quan tới tài khoản của bạn "
            "trên NovaChat đã được xoá khỏi hệ thống.</p>"
            f"<p style='color:#888'>Mã xác nhận: <code>{code}</code></p>"
            "<p>Nếu cần hỗ trợ thêm, vui lòng liên hệ quản trị viên shop.</p></div>"
        )

    @app.route("/meta/deauthorize", methods=["POST"])
    def meta_deauthorize():
        """Meta gọi khi user gỡ ứng dụng → dọn dữ liệu người đó (best-effort)."""
        signed = request.form.get("signed_request", "")
        data = _parse_signed_request(signed, Config.FB_APP_SECRET) if Config.FB_APP_SECRET else None
        if data is None:
            return {"error": "signed_request không hợp lệ"}, 400
        submit(_delete_meta_user_data, conv_manager, str(data.get("user_id") or ""))
        return {"ok": True}

    # ── Luồng "Kết nối Facebook" (OAuth) cho khách tự gắn Page ──────────

    @app.route("/meta/config")
    def meta_config():
        """UI hỏi: app đã cấu hình chưa + app_id để mở FB Login + có bật IG không."""
        return {
            "app_id": Config.FB_APP_ID,
            "configured": bool(Config.FB_APP_ID and Config.FB_APP_SECRET),
            "enable_ig": Config.FB_ENABLE_IG,   # frontend xin thêm quyền IG khi bật
            "enable_comments": Config.FB_ENABLE_COMMENTS,  # xin thêm quyền bình luận khi bật
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
            meta_graph.debug_token(long_token)   # chẩn đoán: token thuộc ai + quyền gì
            pages = meta_graph.list_pages(long_token)
        except Exception as e:
            log.error(f"[meta/connect] lỗi: {e}")
            return {"ok": False, "error": str(e)}, 502

        from app.web_api.auth_api import current_username
        owner = current_username()   # chủ homestay đang đăng nhập (để tính quota/gói)
        result = []
        for pg in pages:
            pid = str(pg.get("id"))
            tok = pg.get("access_token")
            iga = pg.get("instagram_business_account") or {}
            store.upsert(pid, name=pg.get("name"), access_token=tok,
                         ig_id=iga.get("id"), ig_username=iga.get("username"),
                         owner_username=owner)
            subscribed = meta_graph.subscribe_page(pid, tok) if tok else False
            result.append({
                "page_id": pid, "name": pg.get("name"),
                "ig_username": iga.get("username"), "subscribed": subscribed,
            })
        return {"ok": True, "pages": result}

    # MULTI-TENANT: guard sở hữu dùng chung (api_guard) — chống shop A xem/xoá
    # Page của shop B, và chặn stats/fetch-names gộp dữ liệu chéo tenant.
    from app.web_api.api_guard import own_account_or_404, filter_owned, tenant_ctx

    @app.route("/meta/pages")
    def meta_pages():
        return jsonify(filter_owned(store, store.list_pages(), "page_id") if store else [])

    @app.route("/meta/stats")
    def meta_stats():
        ws, is_admin = tenant_ctx()
        return jsonify(compute_stats(
            conv_manager, request.args.get("from"), request.args.get("to"),
            uid_filter=lambda u: u.startswith(("fb:", "ig:")),
            tenant_ws=None if (is_admin or ws is None) else ws))

    @app.route("/meta/fetch-names", methods=["POST"])
    def meta_fetch_names():
        """Thủ công fetch tên từ Graph API cho tất cả khách Meta chưa có tên."""
        # list() BẮT BUỘC: thread webhook có thể thêm session mới (get()) trong lúc
        # lặp → RuntimeError "dict changed size during iteration" (crash 500 đúng lúc
        # nhiều tin đến — chính lúc admin hay bấm fetch tên).
        from app.web_api.bridge import _tenant_visible
        missing = [
            uid for uid, conv in list(conv_manager._sessions.items())
            if uid.startswith(("fb:", "ig:")) and not conv.name
            and _tenant_visible(conv)   # multi-tenant: chỉ khách của shop mình
        ]
        results = {}
        for uid in missing:
            parts = uid.split(":")
            platform = parts[0]
            page_id = parts[1] if len(parts) >= 3 else ""
            sender = parts[2] if len(parts) >= 3 else ""
            token = brain.channel._token_for(page_id) if hasattr(brain.channel, "_token_for") else None
            if not token:
                results[uid] = "no_token"
                continue
            try:
                fields = "name,username"
                r = _req.get(
                    f"https://graph.facebook.com/{Config.FB_GRAPH_VERSION}/{sender}",
                    params={"fields": fields, "access_token": token},
                    timeout=10,
                )
                results[uid] = {"status": r.status_code, "body": r.json()}
                if r.status_code == 200:
                    data = r.json()
                    name = data.get("name") or data.get("username") or ""
                    if name:
                        conv_manager.get(uid).name = name
            except Exception as e:
                results[uid] = str(e)
        conv_manager.save()
        return jsonify({"checked": len(missing), "results": results})

    @app.route("/meta/pages/<page_id>", methods=["DELETE"])
    def meta_remove(page_id):
        deny = own_account_or_404(store, page_id)
        if deny:
            return deny
        if store:
            store.remove(page_id)
        return {"ok": True}

    # ── Hội thoại khách, TÁCH RIÊNG theo từng Page ──────────────────────
    # user_id = "<platform>:<page_id>:<sender>" → lọc theo page_id để mỗi
    # Page (mỗi homestay) có danh sách khách riêng.
    # Dùng route factory chung (conv_routes) với phần đặc thù Meta:
    #  - list_style="array": UI cũ đọc MẢNG trần (không bọc {total,items})
    #  - uid_prefix=None: uid có cả fb:/ig: → lọc theo page_id (phần tử [1]) là đủ
    #  - detail kèm checkin/checkout (dashboard Meta hiển thị lịch đặt)
    #  - send qua brain.channel (không set_ctx — token chọn theo page trong uid)
    #  - with_stats=False: /meta/stats riêng ở trên (lọc fb:/ig:, không query param)
    from app.web_api.conv_routes import register_conversation_routes
    register_conversation_routes(
        app, "/meta", conv_manager, None,
        channel_name="meta", uid_prefix=None, id_param="page_id",
        list_style="array", detail_extra=("checkin", "checkout"),
        send_fn=lambda user_id, text: brain.channel.send_text(user_id, text),
        with_stats=False,
    )

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
        data = request.get_json(force=True, silent=True) or {}
        obj = data.get("object")
        platform = "ig" if obj == "instagram" else "fb"
        if not _valid_signature(raw, request.headers.get("X-Hub-Signature-256", ""), platform):
            log.warning(f"[Meta] CHẶN webhook sai chữ ký ({platform})")
            return "bad signature", 403
        for entry in data.get("entry", []):
            entry_id = str(entry.get("id") or "")
            # IG: entry.id = id tài khoản IG → map về page_id; FB: entry.id = page_id
            if platform == "ig" and store:
                page_id = store.page_for_ig(entry_id) or entry_id
            else:
                page_id = entry_id
            # Messenger (và IG qua FB-login): tin trong mảng "messaging"
            for ev in entry.get("messaging", []):
                _dispatch(platform, page_id, ev)
            # Instagram Login: tin trong "changes" field=messages, value giống 1 ev
            for ch in entry.get("changes", []):
                field = ch.get("field")
                val = ch.get("value")
                if not isinstance(val, dict):
                    continue
                # Bình luận trên Page (mục Bài viết & bình luận) → tự động hoá
                if field == "feed":
                    _dispatch_feed(page_id, val)
                    continue
                if field != "messages":
                    continue
                sender_id = str((val.get("sender") or {}).get("id") or "")
                if sender_id and sender_id == entry_id:
                    continue  # tin do chính tài khoản IG gửi (echo) → bỏ
                _dispatch(platform, page_id, val)
        return "EVENT_RECEIVED", 200

    def _dispatch_feed(page_id: str, value: dict):
        """Bình luận mới → áp cài đặt tự động của Page (ẩn SĐT/trả lời/nhắn riêng).
        Chạy NỀN (webhook trả 200 ngay); dedup theo comment_id (Meta gửi lại)."""
        comment_id = str(value.get("comment_id") or "")
        if not comment_id or _feed_dedup.seen(comment_id):
            return
        token = store.get_token(page_id) if store else None
        settings = comment_store.get(page_id)
        if not token or not any(
                settings.get(k) for k in ("auto_hide_phone", "auto_reply", "private_reply")):
            return   # Page chưa bật tự động hoá nào → khỏi tốn công

        def _notify(text):
            ch = getattr(brain, "channel", None)
            if ch:
                ch.notify_owner(text)

        submit(comments.handle_feed_change, page_id, value, token, settings, _notify)

    def _valid_signature(raw: bytes, header: str, platform: str = "fb") -> bool:
        """Xác thực X-Hub-Signature-256 = sha256(HMAC(FB_APP_SECRET, body)).
        - Chưa cấu hình secret → cho qua (dev/mock).
        - Khớp → cho qua.
        - Lệch: Messenger (fb) CHẶN (chữ ký ký bằng FB_APP_SECRET, ổn định);
          Instagram (ig) có thể ký bằng secret khác → chỉ CHẶN khi bật
          Config.FB_WEBHOOK_STRICT, mặc định nới (log) để không rớt tin IG."""
        secret = Config.FB_APP_SECRET
        if not secret:
            return True
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if header and hmac.compare_digest(expected, header):
            return True
        if platform == "ig" and not Config.FB_WEBHOOK_STRICT:
            log.warning(f"[Meta][ig] chữ ký lệch (nới cho IG — bật FB_WEBHOOK_STRICT để chặn): "
                        f"nhận={header[:20]!r}")
            return True
        return False

    def _dispatch(platform: str, page_id: str, ev: dict):
        sender = str((ev.get("sender") or {}).get("id") or "")
        if not sender:
            return
        msg = ev.get("message") or {}
        if msg.get("is_echo"):
            return  # tin do Page tự gửi → bỏ qua
        mid = str(msg.get("mid") or "")
        if _dedup.seen(mid):
            log.info(f"[Meta] bỏ qua tin trùng mid={mid}")
            return
        text = (msg.get("text") or "").strip()

        # Postback (khách bấm nút/menu): payload chính là "câu khách nói" →
        # đưa vào brain như text bình thường (title là fallback cho nút cũ
        # không khai payload). Dedup riêng theo mid postback nếu Meta gửi kèm.
        postback = ev.get("postback") or {}
        if not text and postback:
            pb_mid = str(postback.get("mid") or "")
            if pb_mid and _dedup.seen(pb_mid):
                return
            text = str(postback.get("payload") or postback.get("title") or "").strip()

        # Đính kèm (ảnh/sticker/video...) — Meta để trong message.attachments.
        # Sticker nhận diện qua payload.sticker_id (nút Like 👍 cũng là sticker).
        attachments = msg.get("attachments") or []
        is_sticker = bool(msg.get("sticker_id")) or any(
            (a.get("payload") or {}).get("sticker_id") for a in attachments)
        image_urls = [
            str((a.get("payload") or {}).get("url") or "")
            for a in attachments
            if a.get("type") == "image" and not (a.get("payload") or {}).get("sticker_id")
        ] if not is_sticker else []

        if not text and not attachments:
            return  # sự kiện không có gì xử lý (delivery/read...) → bỏ

        # user_id đa Page: platform:page_id:recipient → trả lời đúng token Page
        user_id = f"{platform}:{page_id}:{sender}"

        # Lưu tên khách nếu chưa có (gọi Graph API 1 lần, nền, không block)
        conv_check = conv_manager.get(user_id)
        if not conv_check.name or not getattr(conv_check, "avatar", ""):
            _uid, _snd, _pg, _pf = user_id, sender, page_id, platform
            submit(_fetch_meta_name, _uid, _snd, _pg, _pf, brain, conv_manager)

        # Bot bị tắt (đọc lại file mỗi tin để đồng bộ khi đổi từ web).
        # PER-PAGE trước: "meta:<page_id>" (nút Trợ lý AI của TỪNG shop) —
        # _channel_enabled tự fallback lên cờ "meta" toàn cục khi không có key.
        if not _channel_enabled(_load_bot_state(),
                                f"meta:{page_id}" if page_id else "meta"):
            log.info(f"[Meta] bot đang TẮT → bỏ qua {user_id}")
            return

        conv = conv_manager.get(user_id)
        if conv.is_owner_active():
            log.info(f"[Meta] owner_active {user_id} → im lặng")
            return

        owner = store.get_owner_username(page_id) if (store and page_id) else None
        from app.core import tenant

        # ── Đường MEDIA (ảnh/sticker, KHÔNG có text) — trả lời CỐ ĐỊNH, không
        # gọi AI → KHÔNG đi qua billing.channel_gate (gate ghi 1 lượt AI khi cho
        # qua; trừ quota cho câu trả lời mẫu là trừ oan chủ shop — cùng nguyên
        # tắc gate-last của đường text bên dưới).
        if not text and attachments:
            # MULTI-TENANT: vẫn đóng dấu shop sở hữu (assign miễn phí, không tốn lượt)
            tenant.assign(conv_manager, user_id, owner)

            if is_sticker:
                # Sticker/Like: khách MỚI (chưa có hội thoại) → route như tin rỗng
                # (brain gửi greeting cố định); khách CŨ → im lặng như trước NHƯNG
                # lưu marker để chủ xem inbox thấy đầy đủ diễn biến.
                if len(conv.messages) == 0:
                    log.info(f"[Meta] sticker từ khách mới {user_id} → greeting")
                    submit(brain.handle, user_id, "")   # brain: text rỗng = greeting cố định
                else:
                    conv.add_user_message("[Sticker]")
                    conv_manager.save()
                    log.info(f"[Meta] sticker từ khách cũ {user_id} → lưu marker, im lặng")
                return

            # Ảnh (hoặc file/video — chưa có vision pipeline nên KHÔNG đưa vào AI):
            # (a) lưu marker + URL vào hội thoại để chủ mở inbox thấy ngay ảnh,
            # (b) trả khách 1 câu lịch sự cố định, (c) báo chủ kèm link ảnh.
            marker = "[Khách gửi ảnh]" + ("".join(f" {u}" for u in image_urls if u) or "")
            conv.add_user_message(marker)
            reply = ("Mình đã nhận được ảnh của anh/chị ạ 🙏 Anh/chị mô tả thêm "
                     "bằng chữ giúp mình nhé, hoặc chủ shop sẽ xem ảnh và trả lời ngay ạ!")
            ch = getattr(brain, "channel", None)
            if ch:
                try:
                    ch.send_text(user_id, reply)
                    conv.add_assistant_message(reply)
                except Exception as e:
                    log.error(f"[Meta] lỗi gửi reply ảnh {user_id}: {e}")
                try:
                    ch.notify_owner(
                        f"📷 Khách {conv.name or sender} (Meta) gửi ảnh: "
                        + (", ".join(u for u in image_urls if u) or "(không lấy được URL)"))
                except Exception as e:
                    log.warning(f"[Meta] lỗi notify chủ về ảnh {user_id}: {e}")
            conv_manager.save()
            return

        # Gói/quota AI của CHỦ Page (ghi 1 lượt khi cho qua); chưa gắn chủ → gate
        # toàn cục. GATE-LAST: phải đứng SAU mọi đường return sớm ở trên để tin
        # bị drop không trừ quota oan.
        from app.core import billing
        if not billing.channel_gate(owner):
            log.info(f"[Meta] gói/quota chủ ({owner}) không cho phép → bỏ qua {user_id}")
            return

        # MULTI-TENANT: đóng dấu shop sở hữu hội thoại (chủ Page này)
        tenant.assign(conv_manager, user_id, owner)

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

        submit(_run)

    return app
