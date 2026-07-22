"""
API Prompt Builder — gắn vào bridge (5005). Tất cả cần Bearer token.

  GET  /prompt/current                       → bộ não đang dùng (custom/default, mode lai/cũ)
  GET  /prompt/template                      → prompt mẫu chuẩn generic (shop chỉnh tay)
  POST /prompt/generate {links[], instructions, model?} → AI viết persona + mẩu tri thức (chậm 20-60s)
                                               (links: string URL hoặc {url, note};
                                                model: key ai_models shop chọn để dạy, rỗng = mặc định;
                                                hệ thống tự đính kèm cấu hình shop — TRỪ tài khoản ngân hàng)
  POST /prompt/apply {prompt, chunks?}       → shop ĐỒNG Ý → lưu, bot dùng ngay
                                               (có chunks → chế độ LAI: persona + RAG)
  GET  /prompt/knowledge                     → danh sách mẩu tri thức đang dùng
  GET  /prompt/suggestions                   → đề xuất tri thức bot học từ hội thoại (chờ duyệt)
  POST /prompt/suggestions/<id>/approve {title?, content?, keywords?} → duyệt (sửa được trước khi vào kho)
  POST /prompt/suggestions/<id>/reject       → bỏ đề xuất
  POST /prompt/test {message, history[]}     → chat THỬ với bot (AI thật + chẩn đoán;
                                               không lưu session, không gửi kênh nào)
  POST /prompt/restore-default               → quay về prompt mặc định (xoá tri thức lai)
"""

import logging
import re
import threading
import time
from pathlib import Path

from flask import request

from app.core import prompt_builder, knowledge, knowledge_learn, claude_ai
from app.core.config import Config
from app.web_api.auth_api import _user_for_token, _bearer
from app.core.db import get_db

TEST_HISTORY_MAX = 20   # trần lịch sử chat thử gửi lên (chống context phình)
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# COOLDOWN /prompt/health: mỗi lượt đốt ~11 call AI (10 câu + 1 giám khảo) —
# không giới hạn thì 1 user spam là cháy quota. In-process (dict RAM + lock)
# là ĐỦ vì /prompt/health chỉ chạy trên tiến trình bridge (không cần Redis).
HEALTH_COOLDOWN_SECONDS = 60
_health_last: dict = {}          # username → epoch lần chấm gần nhất
_health_lock = threading.Lock()


def _dir_photos(folder: Path, url_prefix: str, caption: str, limit: int = 4) -> list:
    if not folder.is_dir():
        return []
    return [{"url": f"{url_prefix}/{f.name}", "caption": caption}
            for f in sorted(folder.iterdir())
            if f.is_file() and f.suffix.lower() in _IMG_EXTS][:limit]


def _test_photos(message: str, out: dict, tenant_ws: str = None) -> list:
    """Ảnh bot SẼ gửi cho tin nhắn này (mô phỏng brain) — để Test Bot hiển thị.
    Ưu tiên bộ AI CHỦ ĐỘNG đính (send_photos từ thẻ [GUI_ANH]) → Thư viện ảnh
    match keyword → fallback rooms_photos/price_photos cũ. tenant_ws: chỉ tìm
    trong thư viện của shop đang test (khớp hành vi brain thật)."""
    from app.core import photo_library as pl
    photos = []
    ai_names = out.get("send_photos") or []
    if ai_names:
        def _k(x):
            return " ".join(re.findall(r"[a-z0-9]+", pl._norm(str(x))))
        by_key = {_k(s["name"]): s for s in pl.list_sets(tenant_ws) if s["files"]}
        for nm in ai_names:
            s = by_key.get(_k(nm))
            if s:
                for f in s["files"][:4]:
                    photos.append({"url": f"/photos/file/{s['slug']}/{f}", "caption": s["name"]})
        if photos:
            return photos[:8]
    intent = out.get("intent")
    if intent not in ("photo_request", "price_list_request"):
        return []
    for s in pl.find_sets(message, tenant_ws=tenant_ws):
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


def _classify_sheet_link(url: str, note: str, owner: str = None) -> str:
    """Sheet là 'booking' (LỊCH ĐẶT CHỖ — nối cho bot tra realtime) hay 'data'
    (DỮ LIỆU TĨNH — AI đọc vào não)? Quyết định 3 lớp:
    1. Mô tả shop ghi rõ ràng → theo mô tả.
    2. Nội dung sheet nhiều ô Trống/Đã đặt → lịch.
    3. Mơ hồ → hỏi AI phân loại (1 câu, rẻ). Không đọc được → data (an toàn:
       fetch_link sẽ tự báo lỗi rõ nếu không đọc nổi)."""
    n = (note or "").lower()
    kw_book = bool(re.search(r"lịch|lich\b|đặt\s*ch|dat\s*ch|booking|calendar", n))
    kw_data = bool(re.search(r"bảng\s*giá|bang\s*gia|menu|giá\b|gia\b|dịch\s*vụ|dich\s*vu|danh\s*mục|chính\s*sách", n))
    # Chỉ theo mô tả khi RÕ RÀNG 1 phía; hỗn hợp ("bảng giá + lịch làm việc") →
    # rơi xuống lớp nội dung/AI, tránh nối nhầm sheet giá làm lịch đặt chỗ
    if kw_book and not kw_data:
        return "booking"
    if kw_data and not kw_book:
        return "data"
    from app.core.prompt_builder import _gsheet_text
    from app.core.sheets import extract_sheet_id
    sid = extract_sheet_id(url)
    txt = _gsheet_text(sid) if sid else ""
    if not txt:
        return "data"
    low = txt[:8000].lower()
    if len(re.findall(r"trống|đã đặt|da dat|booked", low)) >= 5:
        return "booking"
    try:
        from app.core import ai_models
        ans = ai_models.chat([{"role": "user", "content":
            f"Shop mô tả sheet: '{note or '(không ghi)'}'. 500 ký tự đầu nội dung:\n{txt[:500]}\n\n"
            "Đây là LỊCH ĐẶT CHỖ theo ngày/ca (thay đổi hằng ngày, bot phải tra trực tiếp) "
            "hay DỮ LIỆU TĨNH (bảng giá/danh mục/chính sách — nên dạy vào bộ não)? "
            "Trả lời đúng 1 từ: LICH hoặc DULIEU."}],
            owner=owner, max_tokens=5, temperature=0)
        up = (ans or "").upper()
        if "LICH" in up or "LỊCH" in up:   # AI hay trả có dấu — Ị ≠ I
            return "booking"
    except Exception as e:
        log.info(f"[prompt] AI phân loại sheet lỗi ({e}) → coi là dữ liệu")
    return "data"


def _connect_booking_sheet(db, ws: str, url: str, name: str) -> tuple:
    """Nối 1 sheet lịch vào shop_sheets. Trả (name, err):
    err=None khi ĐÃ NỐI (hoặc trùng — coi như nối rồi); err=lý do khi KHÔNG nối
    được (link lệch dạng, vượt trần) — caller phải báo ❌ thay vì '✅ đã nối' ảo.
    Cùng luật với POST /sheets (sheets_api) — kể cả trần MAX_SHEETS."""
    from app.core.sheets import extract_sheet_id
    from app.web_api.sheets_api import MAX_SHEETS
    from datetime import datetime
    sid = extract_sheet_id(url)
    name = (name or "").strip()[:60] or "Chi nhánh"
    if not sid:
        return name, "không bóc được sheet ID từ link (kiểm tra lại link)"
    if db.query("SELECT 1 FROM shop_sheets WHERE tenant=? AND sheet_id=?", (ws, sid)):
        return name, None    # đã nối từ trước
    n = db.query("SELECT COUNT(*) AS n FROM shop_sheets WHERE tenant=?", (ws,))[0]["n"]
    if n >= MAX_SHEETS:
        return name, f"shop đã đạt tối đa {MAX_SHEETS} sheet lịch — xoá bớt rồi thêm lại"
    db.execute("INSERT INTO shop_sheets(tenant, name, sheet_id, created_at) "
               "VALUES (?,?,?,?)", (ws, name, sid, datetime.now().isoformat()))
    log.info(f"[prompt] {ws} nối sheet lịch '{name}' ({sid[:12]}…) từ Dạy AI")
    return name, None


def _shop_config_context(ws: str) -> str:
    """Gom DỮ LIỆU CẤU HÌNH SHOP (hệ thống tự đính kèm khi Dạy AI) theo workspace:
    liên hệ khẩn cấp, câu trả lời mẫu, lịch đặt chỗ đã nối, bộ ảnh. TUYỆT ĐỐI
    KHÔNG gồm tài khoản ngân hàng/QR (bank_*). Lỗi bảng nào bỏ qua bảng đó."""
    db = get_db()
    parts = []
    # (a) Liên hệ khẩn cấp + KHI NÀO BÁO/GỌI CHỦ (notify_config — cả events)
    try:
        from app.core import notify
        cfg = notify.get_config(ws)
        SHARE_VI = {"off": "KHÔNG bao giờ đưa số cho khách",
                    "strict": "chỉ đưa khi khách hỏi thẳng xin số/gặp chủ",
                    "ask": "đưa khi khách xin gặp người thật HOẶC bot không trả lời được",
                    "greeting": "luôn kèm số ở tin nhắn chào đầu tiên"}
        MODE_VI = {"off": "KHÔNG báo", "notify": "hệ thống NHẮN TIN cho chủ",
                   "call": "hệ thống NHẮN + GỌI ĐIỆN cho chủ ngay"}
        contact = [x for x in (
            f"SĐT khẩn: {cfg['emergency_phone']}" if cfg["emergency_phone"] else "",
            f"Zalo: {cfg['emergency_zalo']}" if cfg["emergency_zalo"] else "",
            f"Telegram: {cfg['emergency_tele']}" if cfg["emergency_tele"] else "") if x]
        if contact:
            parts.append("LIÊN HỆ KHẨN CẤP CỦA SHOP (chế độ đưa số cho khách: "
                         f"{SHARE_VI.get(cfg['share_mode'], cfg['share_mode'])}): "
                         + " · ".join(contact))
        ev = cfg.get("events") or {}
        ev_lines = [f"- {label}: {MODE_VI.get(ev.get(key, default), ev.get(key, default))}"
                    for key, (label, default) in notify.EVENTS.items()]
        if ev_lines:
            parts.append("KHI NÀO HỆ THỐNG BÁO CHỦ SHOP (bot trấn an khách đúng theo "
                         "cấu hình này — vd khách xin gặp chủ thì nói 'đã báo, chủ sẽ "
                         "liên hệ ngay' nếu chế độ là nhắn/gọi):\n" + "\n".join(ev_lines))
    except Exception:
        pass
    # (b) Câu trả lời mẫu: KHÔNG đưa vào đây nữa — đã được GHÉP CỨNG thành 1 mẩu
    # tri thức nguyên văn sau generate (xem endpoint) → tránh bơm kép làm AI
    # sinh mẩu trùng nội dung
    # (c) Lịch đặt chỗ (Google Sheets) đã nối — bot tra trực tiếp khi khách hỏi
    try:
        rows = db.query("SELECT name FROM shop_sheets WHERE tenant=? ORDER BY id", (ws,))
        if rows:
            parts.append("SHOP ĐÃ NỐI GOOGLE SHEET LỊCH ĐẶT CHỖ (bot tự tra khi khách hỏi "
                         "lịch trống — KHÔNG cần bịa lịch): "
                         + ", ".join(r["name"] or "Chi nhánh" for r in rows))
    except Exception:
        pass
    # (d) Bộ ảnh trong Thư viện ảnh — bot gửi khi khách hỏi trúng tên/keywords
    try:
        import json as _json
        rows = db.query("SELECT name, keywords FROM photo_sets "
                        "WHERE tenant=? ORDER BY created_at", (ws,))
        lines = []
        for r in rows:
            try:
                kw = ", ".join(_json.loads(r["keywords"] or "[]"))
            except Exception:
                kw = ""
            lines.append(f"- {r['name']}" + (f" (khách hay hỏi: {kw})" if kw else ""))
        if lines:
            parts.append("BỘ ẢNH SHOP ĐÃ UPLOAD (bot tự gửi ảnh khi khách hỏi trúng):\n"
                         + "\n".join(lines))
    except Exception:
        pass
    return "\n\n".join(parts)


def register_prompt_routes(app):
    db = get_db()

    def _auth_or_401():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        return u, None

    def _shop(u) -> str:
        """Khoá NÃO BOT của user đăng nhập (multi-tenant): chủ nền tảng giữ não
        'default' cũ; shop khác dùng não riêng theo username chủ workspace."""
        from app.core import tenant
        from app.web_api.auth_api import request_workspace as workspace_of
        return tenant.shop_key(workspace_of(u))

    @app.route("/prompt/current")
    def prompt_current():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, **prompt_builder.current(shop=_shop(u))}

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
        # Mỗi phần tử: string URL hoặc {url, note} (note = shop mô tả link, tuỳ chọn)
        if not all(isinstance(it, (str, dict)) for it in links):
            return {"ok": False, "error": "mỗi link phải là chuỗi hoặc {url, note}"}, 400
        # Model shop chọn để DẠY (tuỳ chọn) — rỗng = mặc định hệ thống
        from app.core import ai_models
        model = (data.get("model") or "").strip()
        if model and model not in ai_models.CATALOG:
            return {"ok": False, "error": "Mô hình không hợp lệ"}, 400
        if model and model not in ai_models.available_keys():
            return {"ok": False, "error": "Mô hình này máy chủ chưa cấu hình API key"}, 400
        # Log THÔ những gì trình duyệt gửi — để chẩn đoán "0 link" (link đi nhầm
        # nhánh lịch? ô link trống? bản UI cũ?)
        log.info(f"[prompt] generate body: links={[(l if isinstance(l, str) else l.get('url','?')) for l in links]}"
                 f" model={model!r} instr={len(instructions)} ký tự")
        from app.web_api.auth_api import request_workspace as workspace_of
        ws = workspace_of(u)
        # Link Google Sheets → TỰ NHẬN DIỆN theo mô tả shop ghi + nội dung sheet:
        # LỊCH ĐẶT CHỖ → nối cho bot tra realtime (không nhét vào não — lịch đổi
        # hằng ngày); DỮ LIỆU TĨNH → giữ lại cho AI đọc như link thường.
        routed_sources, kept = [], []
        for lk in links:
            lurl = lk if isinstance(lk, str) else (lk.get("url") or "")
            lnote = "" if isinstance(lk, str) else (lk.get("note") or "")
            if "docs.google.com/spreadsheets" in lurl.lower():
                kind = _classify_sheet_link(lurl, lnote, owner=ws)
                log.info(f"[prompt] nhận diện sheet {lurl[:60]}… ('{lnote[:40]}') → {kind}")
                if kind == "booking":
                    name, err = _connect_booking_sheet(get_db(), ws, lurl, lnote)
                    if err:
                        # KHÔNG nối được → báo ❌ thật, không dạy AI "đã nối" ảo
                        routed_sources.append({
                            "url": lurl, "ok": False,
                            "error": f"nhận diện là LỊCH ĐẶT CHỖ nhưng chưa nối được: {err}"})
                        continue
                    instructions = ((instructions + "\n\n") if instructions else "") + (
                        f"Shop đã nối Google Sheet lịch đặt chỗ '{name}' — bot tự tra khi "
                        f"khách hỏi lịch trống, KHÔNG bịa lịch.")
                    routed_sources.append({
                        "url": lurl, "ok": True,
                        "info": f"📅 nhận diện là LỊCH ĐẶT CHỖ → đã nối ('{name}'), bot tra trực tiếp — không nhét vào não"})
                    continue
            kept.append(lk)
        links = kept
        # Gom cấu hình shop (liên hệ khẩn, câu mẫu, lịch, bộ ảnh — KHÔNG bank_*)
        extra_context = _shop_config_context(ws)
        try:
            r = prompt_builder.generate(links, instructions, model=model or None,
                                        owner=ws, extra_context=extra_context)
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        except Exception as e:
            log.error(f"[prompt] generate lỗi: {e}", exc_info=True)
            return {"ok": False, "error": f"Tạo prompt thất bại: {e}"}, 502
        # CÂU TRẢ LỜI MẪU → mẩu tri thức CỐ ĐỊNH ghép thẳng (không qua AI —
        # AI sinh não có thể lược mất mục nó coi là "tham khảo"; ghép tay thì
        # đảm bảo 100% vào kho, shop xoá được trong bước duyệt nếu không muốn)
        try:
            if True:   # ghép cả khi chunks rỗng (não chế độ cũ) — câu mẫu không được sót
                rows = db.query("SELECT title, content FROM canned_replies "
                                "WHERE tenant=? ORDER BY id LIMIT 30", (ws,))
                if rows:
                    r.setdefault("chunks", [])
                    r["chunks"].append({
                        "title": "Câu trả lời mẫu của shop",
                        "content": "Chủ shop đã soạn sẵn các câu trả lời sau — khi khách "
                                   "hỏi đúng ý thì trả lời theo NGUYÊN VĂN nội dung:\n"
                                   + "\n".join(f"- {row['title']}: {row['content']}" for row in rows),
                        "keywords": [row["title"] for row in rows if row["title"]][:15],
                        "pinned": False,
                    })
        except Exception as e:
            log.error(f"[prompt] ghép câu mẫu lỗi: {e}")
        if routed_sources:
            r["sources"] = routed_sources + (r.get("sources") or [])
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
            r = prompt_builder.apply(data.get("prompt") or "", chunks=chunks, shop=_shop(u))
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        log.info(f"[prompt] {u['username']} ĐÃ ÁP DỤNG bộ não mới ({r['mode']}, {r['chunk_count']} mẩu)")
        return {"ok": True, **r}

    @app.route("/prompt/knowledge")
    def prompt_knowledge():
        u, err = _auth_or_401()
        if err:
            return err
        # CHỈ mẩu fact — kho MẪU HỘI THOẠI (style) có endpoint /prompt/style riêng
        return {"ok": True, "chunks": knowledge.list_chunks(shop=_shop(u), kind=knowledge.KIND_FACT)}

    # ── STYLE RAG: kho mẫu hội thoại (dạy GIỌNG + cách xử lý tình huống) ──

    @app.route("/prompt/style")
    def prompt_style_list():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True,
                "chunks": knowledge.list_chunks(shop=_shop(u), kind=knowledge.KIND_STYLE),
                "max": knowledge.MAX_STYLE_CHUNKS}

    @app.route("/prompt/style/<int:cid>", methods=["DELETE"])
    def prompt_style_delete(cid):
        u, err = _auth_or_401()
        if err:
            return err
        if not knowledge.delete_chunk(cid, shop=_shop(u)):
            return {"ok": False, "error": "Không tìm thấy mẫu"}, 404
        return {"ok": True}

    @app.route("/prompt/style/generate", methods=["POST"])
    def prompt_style_generate():
        """Dán transcript / mô tả giọng → AI sinh bộ mẫu (NDJSON, chống cắt cụt).
        KHÔNG lưu — trả preview để chủ chọn rồi gọi /prompt/style/add."""
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        try:
            chunks = knowledge_learn.generate_style_set(
                data.get("text") or "", shop=_shop(u),
                model_key=data.get("model") or None, owner=u["username"])
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        except Exception as e:
            log.error(f"[prompt] style-generate lỗi: {e}", exc_info=True)
            return {"ok": False, "error": f"AI lỗi: {e}"}, 502
        log.info(f"[prompt] {u['username']} sinh {len(chunks)} mẫu hội thoại (preview)")
        return {"ok": True, "chunks": chunks}

    @app.route("/prompt/style/add", methods=["POST"])
    def prompt_style_add():
        """Lưu các mẫu chủ đã chọn từ preview (hoặc tự soạn tay)."""
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        chunks = data.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            return {"ok": False, "error": "chunks phải là danh sách có ít nhất 1 mẫu"}, 400
        added = knowledge.add_chunks(chunks, shop=_shop(u), kind=knowledge.KIND_STYLE)
        if added == 0:
            return {"ok": False,
                    "error": f"Kho mẫu đã đầy ({knowledge.MAX_STYLE_CHUNKS}) — xoá bớt trước"}, 400
        log.info(f"[prompt] {u['username']} lưu {added} mẫu hội thoại vào kho style")
        return {"ok": True, "added": added,
                "chunks": knowledge.list_chunks(shop=_shop(u), kind=knowledge.KIND_STYLE)}

    # ── DẠY AI v2: phỏng vấn / báo cáo câu bí / chấm điểm não ────────

    _INTERVIEW_PROMPT = (
        "Bạn là nhân viên onboarding của NovaChat, PHỎNG VẤN chủ shop Việt Nam để thu thập "
        "thông tin dạy chatbot bán hàng. Cách hỏi: MỖI LẦN ĐÚNG 1 CÂU, ngắn gọn thân thiện, "
        "ưu tiên: (1) shop bán gì/ngành gì, (2) giá các món/dịch vụ chính, (3) chính sách "
        "khách hay hỏi (ship/cọc/đổi trả/đặt lịch), (4) giờ giấc + địa chỉ, (5) giọng điệu "
        "muốn bot xưng hô, (6) tình huống khó xử lý sao (chê đắt, hủy...). Đoán được ngành "
        "rồi thì hỏi sâu đặc thù ngành đó. Sau 6-10 câu trả lời có nội dung, hoặc khi chủ "
        "shop nói kiểu 'xong/đủ rồi', hãy KẾT THÚC.\n"
        "Trả về DUY NHẤT một JSON:\n"
        '- Còn hỏi tiếp: {"done": false, "question": "câu hỏi kế tiếp"}\n'
        '- Kết thúc:     {"done": true, "summary": "bản tổng hợp MỌI thông tin đã khai thác, '
        "viết thành đoạn hướng dẫn dạy bot: dữ liệu shop, giá, chính sách, giọng điệu... "
        'giữ đúng con số chủ shop nói, không bịa"}'
    )

    @app.route("/prompt/interview", methods=["POST"])
    def prompt_interview():
        """Chat phỏng vấn: nhận history [{role,content}] → câu hỏi kế / bản tổng hợp."""
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        history = data.get("history") or []
        if not isinstance(history, list):
            return {"ok": False, "error": "history phải là danh sách"}, 400
        from app.core.claude_ai import _call_ai
        msgs = [{"role": "system", "content": _INTERVIEW_PROMPT}]
        for m in history[-30:]:
            role = "assistant" if m.get("role") == "assistant" else "user"
            msgs.append({"role": role, "content": str(m.get("content") or "")[:1500]})
        if not history:
            msgs.append({"role": "user", "content": "(bắt đầu phỏng vấn — hãy chào và hỏi câu đầu tiên)"})
        try:
            raw = _call_ai(msgs, owner=u["username"])
        except Exception as e:
            return {"ok": False, "error": f"AI lỗi: {e}"}, 502
        out = knowledge_learn._parse_json_loose(raw)
        if not isinstance(out, dict) or (not out.get("question") and not out.get("summary")):
            # AI trả text trần → coi là câu hỏi tiếp theo (đừng chết phiên phỏng vấn)
            out = {"done": False, "question": (raw or "").strip()[:600]}
        return {"ok": True, "done": bool(out.get("done")),
                "question": str(out.get("question") or "")[:800],
                "summary": str(out.get("summary") or "")[:8000]}

    @app.route("/prompt/report")
    def prompt_report():
        """BÁO CÁO NÃO BOT: câu bot bí (unknown_question) 14 ngày, gộp câu gần giống."""
        u, err = _auth_or_401()
        if err:
            return err
        from datetime import datetime, timedelta
        from app.core.db import get_db
        since = (datetime.now() - timedelta(days=14)).isoformat()
        rows = get_db().query(
            "SELECT id, question, created_at FROM bot_misses "
            "WHERE shop=? AND resolved=0 AND created_at>=? ORDER BY id DESC LIMIT 300",
            (_shop(u), since))
        groups = {}   # câu chuẩn hoá → {question, count, ids, last}
        for r in rows:
            key = " ".join(knowledge._tokens(r["question"]))[:120]
            g = groups.setdefault(key, {"question": r["question"], "count": 0,
                                        "ids": [], "last": r["created_at"]})
            g["count"] += 1
            g["ids"].append(r["id"])
        top = sorted(groups.values(), key=lambda g: -g["count"])[:15]
        return {"ok": True, "misses": top,
                "total": sum(g["count"] for g in groups.values())}

    @app.route("/prompt/report/answer", methods=["POST"])
    def prompt_report_answer():
        """1 CHẠM: chủ trả lời câu bot bí → AI bóc thành mẩu tri thức, lưu thẳng kho."""
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        try:
            chunk = knowledge_learn.learn_direct(
                data.get("question") or "", data.get("answer") or "", shop=_shop(u))
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        ids = [int(i) for i in (data.get("ids") or []) if str(i).isdigit()]
        if ids:
            from app.core.db import get_db
            get_db().execute(
                f"UPDATE bot_misses SET resolved=1 WHERE id IN ({','.join('?' * len(ids))}) AND shop=?",
                (*ids, _shop(u)))
        log.info(f"[prompt] {u['username']} bổ sung tri thức từ báo cáo ({chunk['title']!r})")
        return {"ok": True, "chunk": chunk}

    # ── Versioning kho tri thức (rollback khi "Áp dụng" hỏng) ────────
    @app.route("/prompt/versions")
    def prompt_versions():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, "versions": knowledge.list_versions(shop=_shop(u))}

    @app.route("/prompt/versions/<int:vid>/restore", methods=["POST"])
    def prompt_version_restore(vid):
        u, err = _auth_or_401()
        if err:
            return err
        n = knowledge.restore_version(vid, shop=_shop(u))
        if n < 0:
            return {"ok": False, "error": "Không tìm thấy bản kho này"}, 404
        log.info(f"[prompt] {u['username']} KHÔI PHỤC kho về bản {vid} ({n} mẩu)")
        return {"ok": True, "restored": n,
                "chunks": knowledge.list_chunks(shop=_shop(u), kind=knowledge.KIND_FACT)}

    _JUDGE_PROMPT = (
        "Bạn chấm điểm chatbot của shop, có ĐỐI CHIẾU DỮ LIỆU THẬT của shop (phần "
        "'DỮ LIỆU SHOP' người dùng đưa) — đây là NGUỒN SỰ THẬT DUY NHẤT.\n"
        "Câu trả lời ĐẠT khi: đúng trọng tâm câu hỏi VÀ mọi con số/giá/tên/chính sách "
        "nêu ra ĐỀU KHỚP dữ liệu shop.\n"
        "KHÔNG ĐẠT khi: (a) BỊA số/giá/thông tin KHÔNG có trong dữ liệu shop (lỗi nặng "
        "nhất — thà nói chưa có còn hơn bịa); (b) né tránh/chung chung/lạc đề; (c) nói "
        "'chưa có thông tin' TRONG KHI dữ liệu shop CÓ thông tin đó.\n"
        "Lưu ý: nếu dữ liệu shop THỰC SỰ không có thông tin để trả lời câu đó, thì việc "
        "bot nói 'chưa có, để báo chủ' là ĐẠT (thành thật, không bịa).\n"
        'Trả về DUY NHẤT JSON array: [{"i": số thứ tự, "ok": true/false, '
        '"note": "lý do ngắn — ghi rõ nếu BỊA số"}]'
    )

    @app.route("/prompt/health", methods=["POST"])
    def prompt_health():
        """CHẤM ĐIỂM NÃO: chạy bộ câu hỏi ngành qua não thật → AI giám khảo chấm.
        Chậm (10 câu × AI + 1 lượt chấm ≈ 30-90s) — UI hiện tiến trình."""
        u, err = _auth_or_401()
        if err:
            return err
        # Rate-limit per-user: gọi lại trong 60s → 429 (ghi mốc TRƯỚC khi chạy
        # để 2 request song song không cùng lọt qua)
        now = time.time()
        with _health_lock:
            waited = now - _health_last.get(u["username"], 0)
            if waited < HEALTH_COOLDOWN_SECONDS:
                wait = int(HEALTH_COOLDOWN_SECONDS - waited) + 1
                return {"ok": False, "error":
                        f"Vui lòng chờ {wait} giây rồi chấm lại "
                        f"(mỗi lượt chấm tốn ~11 lần gọi AI)"}, 429
            _health_last[u["username"]] = now
        from concurrent.futures import ThreadPoolExecutor
        from app.core import industry as _ind
        from app.core.db import get_db
        from app.core.claude_ai import analyze_with_debug, _call_ai
        rows = get_db().query("SELECT industry FROM users WHERE username=?", (u["username"],))
        ind_key = (rows[0]["industry"] if rows else "") or _ind.DEFAULT_KEY
        questions = _ind.test_questions(ind_key)[:10]
        shop = _shop(u)

        def _ask(q):
            try:
                return analyze_with_debug(q, [], shop=shop).get("reply", "")
            except Exception as e:
                return f"(lỗi AI: {e})"
        with ThreadPoolExecutor(max_workers=4) as ex:
            replies = list(ex.map(_ask, questions))

        qa = "\n\n".join(f"[{i + 1}] KHÁCH: {q}\nBOT: {r[:600]}"
                         for i, (q, r) in enumerate(zip(questions, replies)))
        # GROUND TRUTH cho giám khảo: dữ liệu THẬT của shop (fact KB) → phát hiện bot
        # BỊA số/giá không có trong kho (trước đây judge không thấy data → bịa vẫn "ĐẠT").
        try:
            facts = knowledge.list_chunks(shop=shop, kind=knowledge.KIND_FACT)
            kb_ref = knowledge.format_block(facts)[:8000] if facts else "(shop chưa dạy dữ liệu nào)"
        except Exception:
            kb_ref = "(không đọc được dữ liệu shop)"
        judge_input = f"DỮ LIỆU SHOP (nguồn sự thật để đối chiếu):\n{kb_ref}\n\n═══\n\nCÂU HỎI & TRẢ LỜI CẦN CHẤM:\n{qa}"
        verdicts = []
        try:
            raw = _call_ai([{"role": "system", "content": _JUDGE_PROMPT},
                            {"role": "user", "content": judge_input}], owner=u["username"])
            import json as _json, re as _re
            m = _re.search(r"\[.*\]", raw or "", _re.DOTALL)
            if m:
                verdicts = _json.loads(m.group(0))
        except Exception as e:
            log.warning(f"[health] giám khảo lỗi: {e}")
        vmap = {int(v.get("i", 0)): v for v in verdicts if isinstance(v, dict)}
        items = []
        for i, (q, r) in enumerate(zip(questions, replies), 1):
            v = vmap.get(i, {})
            items.append({"question": q, "reply": r[:400],
                          "ok": bool(v.get("ok", False)), "note": str(v.get("note") or "")[:200]})
        passed = sum(1 for it in items if it["ok"])
        log.info(f"[health] {u['username']} ({ind_key}): {passed}/{len(items)} đạt")
        return {"ok": True, "industry": ind_key, "industry_label": _ind.label(ind_key),
                "passed": passed, "total": len(items), "items": items}

    # ── Bot học từ hội thoại — hàng chờ duyệt ────────────────────────

    @app.route("/prompt/suggestions")
    def prompt_suggestions():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True,
                "suggestions": knowledge_learn.list_suggestions("pending", shop=_shop(u)),
                "pending": knowledge_learn.count_pending(shop=_shop(u))}

    @app.route("/prompt/suggestions/<int:sid>/approve", methods=["POST"])
    def prompt_suggestion_approve(sid):
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        try:
            s = knowledge_learn.approve(
                sid, title=data.get("title"), content=data.get("content"),
                keywords=data.get("keywords") if isinstance(data.get("keywords"), list) else None,
                shop=_shop(u))   # MULTI-TENANT: chỉ duyệt đề xuất của shop mình
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        log.info(f"[prompt] {u['username']} duyệt đề xuất tri thức #{sid}")
        return {"ok": True, "suggestion": s, "pending": knowledge_learn.count_pending(shop=_shop(u))}

    @app.route("/prompt/suggestions/<int:sid>/reject", methods=["POST"])
    def prompt_suggestion_reject(sid):
        u, err = _auth_or_401()
        if err:
            return err
        try:
            knowledge_learn.reject(sid, shop=_shop(u))   # MULTI-TENANT: chỉ shop mình
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        return {"ok": True, "pending": knowledge_learn.count_pending(shop=_shop(u))}

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
        # Model CHỈ ĐỊNH để thử (rỗng = model shop đang dùng)
        from app.core import ai_models
        model_key = (data.get("model") or "").strip()
        if model_key and model_key not in ai_models.CATALOG:
            return {"ok": False, "error": "Mô hình không hợp lệ"}, 400
        if model_key and model_key not in ai_models.available_keys():
            return {"ok": False, "error": "Mô hình này máy chủ chưa cấu hình API key"}, 400
        try:
            out = claude_ai.analyze_with_debug(message, history, shop=_shop(u),
                                               model_key=model_key or None)
        except Exception as e:
            log.error(f"[prompt] test lỗi: {e}", exc_info=True)
            return {"ok": False, "error": f"Gọi AI thất bại: {e}"}, 502
        # KHÁCH HỎI LỊCH → Test Bot cũng TRA GOOGLE SHEET THẬT như kênh thật
        # (mô phỏng brain flow — trước đây Test Bot bỏ qua bước này nên AI tự bịa
        # "còn chỗ", shop không thử được luồng lịch)
        try:
            # Bắt "hỏi lịch" bằng ĐÚNG bộ nhận diện của brain (dùng chung
            # AVAIL_KEYWORDS/mentions_availability) — Test Bot khớp production
            from app.core.brain import mentions_availability
            _low = message.lower()
            if mentions_availability(_low) and out.get("intent") in ("other", "unknown_question", None):
                out["intent"] = "availability_check"
            if out.get("intent") == "availability_check":
                from app.core.sheets import format_availability_for_ai
                from app.core.brain import _infer_date_from_text
                from app.web_api.auth_api import request_workspace as workspace_of
                ws = workspace_of(u)
                ci = out.get("checkin") or _infer_date_from_text(message)
                co = out.get("checkout") or ci
                if not ci:
                    out["reply"] = "Bạn muốn kiểm tra lịch ngày nào ạ? 📅"
                else:
                    log.info(f"[prompt] test bot TRA LỊCH: {ci} → {co} (shop {ws})")
                    ctx = format_availability_for_ai(ci, co, tenant=ws)
                    if "[KHONG_CO_SHEET]" in ctx:
                        out["reply"] = (f"Mình đã ghi nhận bạn muốn ngày {ci} rồi nha! 📅 "
                                        "Chủ shop sẽ kiểm tra lịch và xác nhận sớm nhất 😊\n\n"
                                        "(Ghi chú test: shop chưa nối Google Sheet lịch — "
                                        "nối ở Bước 2 trang Dạy AI để bot tự tra)")
                    elif "[CHUA_CO_LICH]" in ctx:
                        out["reply"] = (f"Ngày {ci} hệ thống chưa ghi nhận booking nào — "
                                        "các phòng vẫn còn trống bạn ơi! 😊 "
                                        "Bạn muốn đặt phòng nào thì báo mình nhé!")
                    elif "KHÔNG có ca trống" in ctx or "NGHIÊM CẤM" in ctx:
                        out["reply"] = (f"Dạ ngày {ci} không còn ca trống nào bạn ơi 😢 "
                                        "Bạn thử ngày khác nhé!")
                    else:
                        out["reply"] = (f"Dạ, mình kiểm tra cho bạn nè! 😊\n\n{ctx}\n\n"
                                        "Bạn muốn đặt phòng nào thì báo mình nhé!")
                    if isinstance(out.get("debug"), dict):
                        out["debug"]["sheet_checked"] = True
        except Exception as e:
            log.error(f"[prompt] test tra lịch lỗi: {e}", exc_info=True)
        from app.web_api.auth_api import request_workspace as _rw
        out["photos"] = _test_photos(message, out, tenant_ws=_rw(u))   # ảnh bot sẽ gửi (preview)
        log.info(f"[prompt] {u['username']} test bot: '{message[:60]}' → intent={out.get('intent')}"
                 f" ({len(out['photos'])} ảnh)")
        return {"ok": True, **out}

    @app.route("/prompt/restore-default", methods=["POST"])
    def prompt_restore():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, **prompt_builder.restore_default(shop=_shop(u))}

    return app
