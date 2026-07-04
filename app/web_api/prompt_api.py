"""
API Prompt Builder — gắn vào bridge (5005). Tất cả cần Bearer token.

  GET  /prompt/current                       → bộ não đang dùng (custom/default, mode lai/cũ)
  GET  /prompt/template                      → prompt mẫu chuẩn generic (shop chỉnh tay)
  POST /prompt/generate {links[], instructions} → AI viết persona + mẩu tri thức (chậm 20-60s)
  POST /prompt/apply {prompt, chunks?}       → shop ĐỒNG Ý → lưu, bot dùng ngay
                                               (có chunks → chế độ LAI: persona + RAG)
  GET  /prompt/knowledge                     → danh sách mẩu tri thức đang dùng
  POST /prompt/test {message, history[]}     → chat THỬ với bot (AI thật + chẩn đoán;
                                               không lưu session, không gửi kênh nào)
  POST /prompt/restore-default               → quay về prompt mặc định (xoá tri thức lai)
"""

import logging
import re
from pathlib import Path

from flask import request

from app.core import prompt_builder, knowledge, claude_ai
from app.core.config import Config
from app.web_api.auth_api import _user_for_token, _bearer
from app.core.db import get_db

TEST_HISTORY_MAX = 20   # trần lịch sử chat thử gửi lên (chống context phình)
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _dir_photos(folder: Path, url_prefix: str, caption: str, limit: int = 4) -> list:
    if not folder.is_dir():
        return []
    return [{"url": f"{url_prefix}/{f.name}", "caption": caption}
            for f in sorted(folder.iterdir())
            if f.is_file() and f.suffix.lower() in _IMG_EXTS][:limit]


def _test_photos(message: str, out: dict) -> list:
    """Ảnh bot SẼ gửi cho tin nhắn này (mô phỏng brain) — để Test Bot hiển thị.
    Ưu tiên Thư viện ảnh (bộ đặt tên) → fallback rooms_photos/price_photos cũ."""
    intent = out.get("intent")
    if intent not in ("photo_request", "price_list_request"):
        return []
    from app.core import photo_library as pl
    photos = []
    for s in pl.find_sets(message):
        for f in s["files"][:4]:
            photos.append({"url": f"/photos/file/{s['slug']}/{f}", "caption": s["name"]})
    if photos:
        return photos[:8]
    if intent == "price_list_request":
        base = Path(Config.PRICE_PHOTOS_DIR)
        for folder, label in [("haru", "Bảng giá Haru"), ("mochi", "Bảng giá Mochi")]:
            photos += _dir_photos(base / folder, f"/photos/media/price/{folder}", label)
    else:
        rooms = list(dict.fromkeys(re.findall(r"\b([123]\d{2})\b", message))) \
                or [str(r).strip() for r in (out.get("room_numbers") or []) if str(r).strip()]
        base = Path(Config.ROOMS_PHOTOS_DIR)
        for r in rooms[:3]:
            photos += _dir_photos(base / r, f"/photos/media/rooms/{r}", f"Phòng {r}")
    return photos[:8]

log = logging.getLogger("prompt_api")


def register_prompt_routes(app):
    db = get_db()

    def _auth_or_401():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        return u, None

    @app.route("/prompt/current")
    def prompt_current():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, **prompt_builder.current()}

    @app.route("/prompt/template")
    def prompt_template():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, "template": prompt_builder.template()}

    @app.route("/prompt/generate", methods=["POST"])
    def prompt_generate():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        links = data.get("links") or []
        instructions = data.get("instructions") or ""
        if not isinstance(links, list):
            return {"ok": False, "error": "links phải là danh sách"}, 400
        try:
            r = prompt_builder.generate(links, instructions)
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        except Exception as e:
            log.error(f"[prompt] generate lỗi: {e}", exc_info=True)
            return {"ok": False, "error": f"Tạo prompt thất bại: {e}"}, 502
        log.info(f"[prompt] {u['username']} tạo bộ não ({r['mode']}, {len(r['draft'])} ký tự, "
                 f"{len(r['chunks'])} mẩu, {len(links)} link)")
        return {"ok": True, **r}

    @app.route("/prompt/apply", methods=["POST"])
    def prompt_apply():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        chunks = data.get("chunks")
        if chunks is not None and not isinstance(chunks, list):
            return {"ok": False, "error": "chunks phải là danh sách"}, 400
        try:
            r = prompt_builder.apply(data.get("prompt") or "", chunks=chunks)
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        log.info(f"[prompt] {u['username']} ĐÃ ÁP DỤNG bộ não mới ({r['mode']}, {r['chunk_count']} mẩu)")
        return {"ok": True, **r}

    @app.route("/prompt/knowledge")
    def prompt_knowledge():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, "chunks": knowledge.list_chunks()}

    @app.route("/prompt/test", methods=["POST"])
    def prompt_test():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        message = str(data.get("message") or "").strip()
        if not message:
            return {"ok": False, "error": "Thiếu tin nhắn thử"}, 400
        history = data.get("history") or []
        if not isinstance(history, list):
            return {"ok": False, "error": "history phải là danh sách"}, 400
        # Lọc + cắt lịch sử (stateless — UI giữ hội thoại thử, gửi lên mỗi lần)
        history = [
            {"role": m["role"], "content": str(m.get("content") or "")}
            for m in history
            if isinstance(m, dict) and m.get("role") in ("user", "assistant")
        ][-TEST_HISTORY_MAX:]
        try:
            out = claude_ai.analyze_with_debug(message, history)
        except Exception as e:
            log.error(f"[prompt] test lỗi: {e}", exc_info=True)
            return {"ok": False, "error": f"Gọi AI thất bại: {e}"}, 502
        out["photos"] = _test_photos(message, out)   # ảnh bot sẽ gửi (preview)
        log.info(f"[prompt] {u['username']} test bot: '{message[:60]}' → intent={out.get('intent')}"
                 f" ({len(out['photos'])} ảnh)")
        return {"ok": True, **out}

    @app.route("/prompt/restore-default", methods=["POST"])
    def prompt_restore():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, **prompt_builder.restore_default()}

    return app
