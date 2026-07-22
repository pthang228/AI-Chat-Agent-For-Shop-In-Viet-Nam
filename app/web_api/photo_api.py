"""
API Thư viện ảnh — gắn vào bridge (5005). Bộ ảnh đặt tên để bot gửi khách.

  GET    /photos/sets                        (Bearer) → danh sách bộ ảnh
  POST   /photos/sets {name, keywords[]}     (Bearer) → tạo bộ
  POST   /photos/sets/<slug>/keywords        (Bearer) → sửa keywords
  DELETE /photos/sets/<slug>                 (Bearer) → xoá bộ (cả file)
  POST   /photos/sets/<slug>/upload          (Bearer, multipart "files") → thêm ảnh
  DELETE /photos/sets/<slug>/files/<name>    (Bearer) → xoá 1 ảnh
  GET    /photos/file/<slug>/<name>          (public) → serve ảnh bộ (cho <img>)
  GET    /photos/media/<cat>/<sub>/<name>    (public) → serve ảnh cũ rooms/price
                                              (cat: rooms|price — cho Test Bot preview)

Serve ảnh để PUBLIC vì <img> không gửi được Bearer header; đây là ảnh dịch vụ
shop vốn công khai (đã/ sẽ gửi cho khách qua chat).
"""

import logging
from pathlib import Path

from flask import request, send_from_directory

from app.core import photo_library as pl
from app.core.config import Config
from app.web_api.auth_api import _user_for_token, _bearer
from app.core.db import get_db

log = logging.getLogger("photo_api")

MEDIA_CATS = {
    "rooms": lambda: Path(Config.ROOMS_PHOTOS_DIR),
    "price": lambda: Path(Config.PRICE_PHOTOS_DIR),
}


def register_photo_routes(app):
    db = get_db()

    def _auth_or_401():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        return u, None

    def _pws(u):
        """Workspace (shop đang chọn, tôn trọng X-Shop) — multi-tenant bộ ảnh."""
        from app.web_api.auth_api import request_workspace
        return request_workspace(u)

    def _owned(slug, u):
        """Bộ ảnh thuộc shop của user? (không tồn tại/của shop khác → False)"""
        return pl.get_set(slug, tenant_ws=_pws(u)) is not None

    @app.route("/photos/sets")
    def photos_list():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, "sets": pl.list_sets(tenant_ws=_pws(u))}

    @app.route("/photos/sets", methods=["POST"])
    def photos_create():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        try:
            s = pl.create_set(data.get("name") or "", data.get("keywords") or [], tenant_ws=_pws(u))
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        log.info(f"[photos] {u['username']} tạo bộ ảnh '{s['name']}'")
        return {"ok": True, "set": s}

    @app.route("/photos/sets/<slug>/keywords", methods=["POST"])
    def photos_keywords(slug):
        u, err = _auth_or_401()
        if err:
            return err
        if not _owned(slug, u):
            return {"ok": False, "error": "Bộ ảnh không tồn tại"}, 404
        data = request.get_json(force=True, silent=True) or {}
        s = pl.update_keywords(slug, data.get("keywords") or [])
        if not s:
            return {"ok": False, "error": "Bộ ảnh không tồn tại"}, 404
        return {"ok": True, "set": s}

    @app.route("/photos/sets/<slug>", methods=["DELETE"])
    def photos_delete(slug):
        u, err = _auth_or_401()
        if err:
            return err
        if not _owned(slug, u):
            return {"ok": False, "error": "Bộ ảnh không tồn tại"}, 404
        pl.delete_set(slug)
        log.info(f"[photos] {u['username']} xoá bộ ảnh '{slug}'")
        return {"ok": True}

    @app.route("/photos/sets/<slug>/upload", methods=["POST"])
    def photos_upload(slug):
        u, err = _auth_or_401()
        if err:
            return err
        if not _owned(slug, u):
            return {"ok": False, "error": "Bộ ảnh không tồn tại"}, 404
        files = request.files.getlist("files")
        if not files:
            return {"ok": False, "error": "Chưa chọn file nào"}, 400
        saved, errors = [], []
        for f in files:
            try:
                saved.append(pl.add_photo(slug, f.filename, f.read()))
            except ValueError as e:
                errors.append(f"{f.filename}: {e}")
        log.info(f"[photos] {u['username']} upload {len(saved)} ảnh vào '{slug}'")
        return {"ok": True, "saved": saved, "errors": errors, "set": pl.get_set(slug)}

    @app.route("/photos/sets/<slug>/files/<path:name>", methods=["DELETE"])
    def photos_remove_file(slug, name):
        u, err = _auth_or_401()
        if err:
            return err
        if not _owned(slug, u):
            return {"ok": False, "error": "Bộ ảnh không tồn tại"}, 404
        pl.remove_photo(slug, name)
        return {"ok": True, "set": pl.get_set(slug)}

    # ── Serve ảnh (public — cho <img> trong web + preview Test Bot) ──

    @app.route("/photos/file/<slug>/<path:name>")
    def photos_file(slug, name):
        d = pl.set_dir(pl.slugify(slug))    # slugify lại → chặn traversal
        return send_from_directory(str(d), Path(name).name)

    @app.route("/photos/media/<cat>/<sub>/<path:name>")
    def photos_media(cat, sub, name):
        base_fn = MEDIA_CATS.get(cat)
        if not base_fn:
            return {"ok": False, "error": "Loại media không hợp lệ"}, 404
        sub_safe = Path(sub).name           # chặn traversal
        return send_from_directory(str(base_fn() / sub_safe), Path(name).name)

    return app
