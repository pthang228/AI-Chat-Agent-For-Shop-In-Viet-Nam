"""
API "Bài viết & bình luận" Facebook — gắn vào meta_webhook (cổng 5006, nơi có
MetaStore token từng Page + auth guard sẵn). Tất cả cần Bearer token.

  GET  /posts?page_id=                     → bài viết của Page (Graph, mới nhất trước)
  GET  /posts/<post_id>/comments?page_id=  → bình luận 1 bài (kèm cờ has_phone)
  POST /comments/<cid>/reply {page_id, message}         → trả lời công khai
  POST /comments/<cid>/hide {page_id, hidden}           → ẩn/hiện
  POST /comments/<cid>/private-reply {page_id, message} → nhắn riêng (1 lần/bình luận)
  GET  /posts/settings?page_id=            → cài đặt tự động của Page
  POST /posts/settings {page_id, ...}      → lưu + RE-SUBSCRIBE field "feed"
                                             (Page nối trước đây chưa đăng ký feed)
"""

import logging

from flask import request, jsonify

from app.core import comments
from app.channels import meta_graph

log = logging.getLogger("posts_api")


def register_posts_routes(app, store, comment_store):
    """store = MetaStore (token Page); comment_store = CommentStore (cài đặt)."""

    def _owns_page(page_id) -> bool:
        """MULTI-TENANT: user đăng nhập có sở hữu Page này không (chống shop A
        đọc/trả lời/ẩn bình luận Page shop B). Quản trị nền tảng → mọi Page.
        Page chưa gắn chủ (kết nối trước khi có owner) → chỉ quản trị nền tảng."""
        from app.web_api.auth_api import current_username
        from app.core import tenant as _t
        u = current_username()
        if u is None:          # không có ngữ cảnh đăng nhập (test/guard tắt) → cho qua
            return True
        if _t.is_platform_admin(u):
            return True
        owner = store.get_owner_username(page_id) if store else None
        return owner == u

    def _token_or_400(page_id):
        if not page_id:
            return None, ({"ok": False, "error": "thiếu page_id"}, 400)
        if not _owns_page(page_id):     # kiểm quyền sở hữu TRƯỚC khi trả token
            return None, ({"ok": False, "error": "not found"}, 404)
        token = store.get_token(page_id) if store else None
        if not token:
            return None, ({"ok": False, "error": "Page chưa kết nối (không có token)"}, 400)
        return token, None

    @app.route("/posts")
    def posts_list():
        page_id = request.args.get("page_id", "").strip()
        token, err = _token_or_400(page_id)
        if err:
            return err
        try:
            return jsonify({"ok": True, "items": comments.list_posts(page_id, token)})
        except Exception as e:
            log.error(f"[posts] list {page_id}: {e}")
            return {"ok": False, "error": str(e)}, 502

    @app.route("/posts/<path:post_id>/comments")
    def post_comments(post_id):
        page_id = request.args.get("page_id", "").strip()
        token, err = _token_or_400(page_id)
        if err:
            return err
        try:
            return jsonify({"ok": True, "items": comments.list_comments(post_id, token)})
        except Exception as e:
            log.error(f"[posts] comments {post_id}: {e}")
            return {"ok": False, "error": str(e)}, 502

    @app.route("/comments/<path:comment_id>/reply", methods=["POST"])
    def comment_reply(comment_id):
        data = request.get_json(force=True, silent=True) or {}
        token, err = _token_or_400((data.get("page_id") or "").strip())
        if err:
            return err
        message = (data.get("message") or "").strip()
        if not message:
            return {"ok": False, "error": "tin trống"}, 400
        ok = comments.reply_comment(comment_id, token, message)
        return {"ok": ok} if ok else ({"ok": False, "error": "Graph từ chối (xem log)"}, 502)

    @app.route("/comments/<path:comment_id>/hide", methods=["POST"])
    def comment_hide(comment_id):
        data = request.get_json(force=True, silent=True) or {}
        token, err = _token_or_400((data.get("page_id") or "").strip())
        if err:
            return err
        hidden = bool(data.get("hidden", True))
        ok = comments.hide_comment(comment_id, token, hidden)
        return ({"ok": True, "hidden": hidden} if ok
                else ({"ok": False, "error": "Graph từ chối (xem log)"}, 502))

    @app.route("/comments/<path:comment_id>/private-reply", methods=["POST"])
    def comment_private(comment_id):
        data = request.get_json(force=True, silent=True) or {}
        token, err = _token_or_400((data.get("page_id") or "").strip())
        if err:
            return err
        message = (data.get("message") or "").strip()
        if not message:
            return {"ok": False, "error": "tin trống"}, 400
        ok = comments.private_reply(comment_id, token, message)
        return {"ok": ok} if ok else (
            {"ok": False, "error": "Graph từ chối (mỗi bình luận chỉ nhắn riêng được 1 lần)"}, 502)

    # ── Cài đặt tự động hoá bình luận theo Page ─────────────────────

    @app.route("/posts/settings")
    def settings_get():
        page_id = request.args.get("page_id", "").strip()
        if not page_id:
            return {"ok": False, "error": "thiếu page_id"}, 400
        if not _owns_page(page_id):
            return {"ok": False, "error": "not found"}, 404
        return {"ok": True, "settings": comment_store.get(page_id)}

    @app.route("/posts/settings", methods=["POST"])
    def settings_set():
        data = request.get_json(force=True, silent=True) or {}
        page_id = (data.get("page_id") or "").strip()
        if not page_id:
            return {"ok": False, "error": "thiếu page_id"}, 400
        if not _owns_page(page_id):
            return {"ok": False, "error": "not found"}, 404
        saved = comment_store.set(page_id, data)
        # Page nối TRƯỚC khi có tính năng này chưa subscribe field "feed" →
        # re-subscribe để Meta bắt đầu đẩy bình luận về (best-effort).
        subscribed = False
        token = store.get_token(page_id) if store else None
        if token:
            subscribed = meta_graph.subscribe_page(page_id, token)
        return {"ok": True, "settings": saved, "feed_subscribed": subscribed}

    return app
