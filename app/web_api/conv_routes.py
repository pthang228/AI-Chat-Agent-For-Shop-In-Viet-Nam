"""
Route factory HỘI THOẠI dùng chung cho các server kênh.

LÝ DO: nhóm route /X/conversations, /X/conversations/<id>, /send, /toggle-bot,
DELETE, /X/stats bị chép ~giống hệt qua 6 file *_api.py (telegram/tiktok/
zalooa/webchat/shopee/meta) — sửa 1 chỗ phải sửa 6 chỗ, rất dễ lệch nhau
(đã từng lệch shape). Gom về 1 factory, mỗi kênh chỉ truyền phần KHÁC BIỆT
nhỏ (prefix, tên query param, hook backfill avatar, cách set_ctx khi gửi tay).

GIỮ NGUYÊN 100% path + shape response — tests của từng kênh assert trực tiếp:
  - list  : {"total", "offset", "limit", "items"} (paged) hoặc mảng trần (meta)
  - detail: {"user_id","name","avatar","owner_active","stage","assigned_to",
             (+detail_extra như checkin/checkout của meta), "messages"}
  - send/toggle-bot/DELETE: {"ok": ...} như cũ

MULTI-TENANT: các route này vẫn được install_tenant_conv_guard (bridge) chặn
tập trung theo shop; ở đây chỉ lọc _tenant_visible cho danh sách + detail
(giữ đúng hành vi cũ của từng file).
"""

import logging

from flask import request, jsonify

from app.web_api.bridge import _conv_summary, _tenant_visible
from app.web_api.stats_util import compute_stats
from app.web_api.api_guard import submit

log = logging.getLogger("conv_routes")


def register_conversation_routes(
    app, prefix, conv_manager, channel, *,
    channel_name,           # "telegram"/"tiktok"/... — dùng cho knowledge_learn + log
    uid_prefix,             # "tg:"/"tt:"/... — None = không lọc theo prefix (meta)
    id_param,               # tên query param lọc theo bot: "bot_id"/"business_id"/...
    set_ctx_bare=True,      # gửi tay uid 2 phần (không id bot): True → set_ctx(None)
                            # reset về acc .env; Telegram giữ hành vi cũ = False (không đụng ctx)
    send_fn=None,           # override cách gửi (meta: brain.channel.send_text, không set_ctx)
    collect_missing=None,   # fn(uid, conv) -> bool: uid cần backfill tên/avatar (telegram)
    backfill=None,          # fn(list[uid]): tự lo chạy nền (kênh tự quyết thread/submit)
    list_style="paged",     # "paged" (mặc định, limit 50/200) | "array" (meta: 200/1000, mảng trần)
    detail_extra=(),        # field bổ sung trong detail (meta: ("checkin","checkout"))
    with_stats=True,        # meta có /meta/stats riêng (không lọc id_param) → False
):
    """Đăng ký nhóm route hội thoại chuẩn cho 1 server kênh Flask."""

    # endpoint= bắt buộc unique theo app — dùng channel_name để 2 lần gọi
    # register trên cùng app (nếu có) không đụng nhau.
    ep = channel_name

    @app.route(f"{prefix}/conversations", endpoint=f"{ep}_conversations")
    def _conversations():
        bid = request.args.get(id_param, "")
        # meta giữ shape MẢNG + trần cao hơn (UI cũ đọc mảng); các kênh khác paged
        d_limit, m_limit = (200, 1000) if list_style == "array" else (50, 200)
        try:
            limit = min(max(int(request.args.get("limit", d_limit)), 1), m_limit)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = d_limit, 0
        rows = []
        missing = []
        # list() bắt buộc: thread webhook có thể thêm session trong lúc lặp
        for uid, conv in list(conv_manager._sessions.items()):
            if uid_prefix and not uid.startswith(uid_prefix):
                continue
            parts = uid.split(":")
            uid_bid = parts[1] if len(parts) >= 3 else ""
            if bid and uid_bid != bid:
                continue
            if not _tenant_visible(conv):   # multi-tenant: chỉ shop của mình
                continue
            rows.append(_conv_summary(uid, conv))
            if collect_missing and collect_missing(uid, conv):
                missing.append(uid)
        if missing and backfill:
            backfill(missing)   # kênh tự lo chạy nền (không block response)
        rows.sort(key=lambda r: r["last_updated"], reverse=True)
        if list_style == "array":
            return jsonify(rows[offset:offset + limit])
        total = len(rows)
        return jsonify({"total": total, "offset": offset, "limit": limit,
                        "items": rows[offset:offset + limit]})

    @app.route(f"{prefix}/conversations/<user_id>", endpoint=f"{ep}_conversation")
    def _conversation(user_id):
        conv = conv_manager._sessions.get(user_id)
        if not conv or not _tenant_visible(conv):
            return {"error": "not found"}, 404
        msgs = [
            {"role": m.get("role"), "content": m.get("content", "")}
            for m in conv.messages
            if not m.get("content", "").startswith("[HỆ THỐNG]")
        ]
        out = {
            "user_id": user_id,
            "name": getattr(conv, "name", ""),
            "avatar": getattr(conv, "avatar", "") or "",
            "owner_active": conv.is_owner_active(),
            "stage": conv.stage,
            "assigned_to": getattr(conv, "assigned_to", "") or "",
        }
        for k in detail_extra:                # meta: checkin/checkout
            out[k] = getattr(conv, k)
        out["messages"] = msgs
        return jsonify(out)

    @app.route(f"{prefix}/conversations/<user_id>/send", methods=["POST"],
               endpoint=f"{ep}_conv_send")
    def _send_message(user_id):
        """Chủ gửi tin thủ công từ dashboard → gửi thật qua kênh + lưu lịch sử."""
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "tin trống"}, 400
        try:
            if send_fn is not None:
                send_fn(user_id, text)
            else:
                # set_ctx đúng bot/acc để gửi qua đúng token
                parts = user_id.split(":")
                bid = parts[1] if len(parts) >= 3 else None
                if bid or set_ctx_bare:
                    channel.set_ctx(bid)
                channel.send_text(user_id, text)
        except Exception as e:
            log.error(f"[{channel_name} send] lỗi gửi {user_id}: {e}")
            return {"ok": False, "error": str(e)}, 500
        conv = conv_manager.get(user_id)
        conv.add_assistant_message(text)
        conv.set_owner_active(True)   # chủ đang xử lý → bot dừng tự trả lời
        conv_manager.save()
        # Bot học từ hội thoại: chủ trả lời tay → AI đề xuất mẩu tri thức (nền, chờ duyệt)
        from app.core import knowledge_learn
        submit(knowledge_learn.suggest_from_reply, user_id, channel_name,
               list(conv.messages), text)
        return {"ok": True}

    @app.route(f"{prefix}/conversations/<user_id>/toggle-bot", methods=["POST"],
               endpoint=f"{ep}_conv_toggle_bot")
    def _toggle_bot(user_id):
        data = request.get_json(force=True, silent=True) or {}
        bot_on = bool(data.get("bot_on", True))
        conv = conv_manager.get(user_id)
        conv.set_owner_active(not bot_on)   # bot bật ↔ owner_active tắt
        conv_manager.save()
        return {"ok": True, "bot_on": bot_on, "owner_active": conv.is_owner_active()}

    @app.route(f"{prefix}/conversations/<user_id>", methods=["DELETE"],
               endpoint=f"{ep}_conv_reset")
    def _reset(user_id):
        conv_manager.reset(user_id)
        return {"ok": True}

    if with_stats:
        @app.route(f"{prefix}/stats", endpoint=f"{ep}_stats")
        def _stats():
            bid = request.args.get(id_param, "")

            def _flt(u):
                if not u.startswith(uid_prefix):
                    return False
                if bid:
                    parts = u.split(":")
                    return len(parts) >= 3 and parts[1] == bid
                return True

            return jsonify(compute_stats(
                conv_manager, request.args.get("from"), request.args.get("to"),
                uid_filter=_flt))
