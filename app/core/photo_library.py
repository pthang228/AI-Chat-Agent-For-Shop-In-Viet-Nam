"""
Thư viện ảnh — bộ ảnh ĐẶT TÊN để bot gửi khách khi hỏi trúng (kiểu AloChat).

Shop tạo bộ ("Bảng giá", "Phòng 301", "Menu món chính"...), gắn keywords các cách
khách hay hỏi, upload nhiều ảnh. Khi khách nhắn photo_request/price_list_request,
brain match tin nhắn với tên/keywords (bỏ dấu) → channel.send_photo_folder(bộ đó).
Không match → cơ chế cũ (media/rooms_photos, media/price_photos) chạy y nguyên.

File trên đĩa: media/photo_library/<slug>/*.jpg — metadata trong SQLite (photo_sets).
"""

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from app.core.config import Config
from app.core.db import get_db

LIBRARY_DIR = Path(getattr(Config, "PHOTO_LIBRARY_DIR", None)
                   or Path(Config.ROOMS_PHOTOS_DIR).parent / "photo_library")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_SETS = 100
MAX_FILES_PER_SET = 30


def _norm(s: str) -> str:
    s = (s or "").lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def slugify(name: str) -> str:
    s = _norm(name)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "bo-anh"


def set_dir(slug: str) -> Path:
    return LIBRARY_DIR / slug


def _files(slug: str) -> list:
    d = set_dir(slug)
    if not d.is_dir():
        return []
    return sorted(f.name for f in d.iterdir()
                  if f.is_file() and f.suffix.lower() in IMAGE_EXTS)


def _row(r) -> dict:
    try:
        kw = json.loads(r["keywords"])
    except Exception:
        kw = []
    return {"slug": r["slug"], "name": r["name"], "keywords": kw,
            "files": _files(r["slug"])}


# ── CRUD ─────────────────────────────────────────────────────────────

def _tenant_where(tenant_ws):
    """Mảnh WHERE multi-tenant (chủ nền tảng thấy cả bộ ảnh cũ tenant='')."""
    from app.core import tenant as _t
    if not tenant_ws:
        return "", ()
    if tenant_ws == _t.default_owner():
        return " WHERE (tenant=? OR tenant='')", (tenant_ws,)
    return " WHERE tenant=?", (tenant_ws,)


def list_sets(tenant_ws: str = None) -> list:
    tw, tp = _tenant_where(tenant_ws)
    return [_row(r) for r in get_db().query(
        f"SELECT * FROM photo_sets{tw} ORDER BY created_at", tp)]


def get_set(slug: str, tenant_ws: str = None) -> dict | None:
    rows = get_db().query("SELECT * FROM photo_sets WHERE slug=?", (slug,))
    if not rows:
        return None
    if tenant_ws:
        from app.core import tenant as _t
        row_tenant = (rows[0]["tenant"] if "tenant" in rows[0].keys() else "") or ""
        if not _t.visible(row_tenant, tenant_ws):
            return None
    return _row(rows[0])


def create_set(name: str, keywords: list = None, tenant_ws: str = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Tên bộ ảnh trống")
    if len(list_sets(tenant_ws)) >= MAX_SETS:
        raise ValueError(f"Tối đa {MAX_SETS} bộ ảnh")
    slug = slugify(name)
    # slug là PK TOÀN CỤC: 2 shop cùng đặt "Bảng giá" → shop sau thêm hậu tố
    # (thư mục ảnh media/photo_library/<slug> tách theo slug nên không lẫn file)
    base_slug, i = slug, 2
    while get_db().query("SELECT 1 FROM photo_sets WHERE slug=?", (slug,)):
        owner_row = get_db().query("SELECT tenant FROM photo_sets WHERE slug=?", (slug,))
        row_tenant = (owner_row[0]["tenant"] if owner_row and "tenant" in owner_row[0].keys() else "") or ""
        if tenant_ws and row_tenant != tenant_ws:
            slug = f"{base_slug}-{i}"; i += 1
            continue
        raise ValueError(f"Bộ ảnh '{name}' đã tồn tại")
    kw = [str(k).strip() for k in (keywords or []) if str(k).strip()][:20]
    get_db().execute(
        "INSERT INTO photo_sets (slug, name, keywords, created_at, tenant) VALUES (?,?,?,?,?)",
        (slug, name, json.dumps(kw, ensure_ascii=False), datetime.now().isoformat(),
         tenant_ws or ""))
    set_dir(slug).mkdir(parents=True, exist_ok=True)
    return get_set(slug)


def update_keywords(slug: str, keywords: list) -> dict | None:
    kw = [str(k).strip() for k in (keywords or []) if str(k).strip()][:20]
    get_db().execute("UPDATE photo_sets SET keywords=? WHERE slug=?",
                     (json.dumps(kw, ensure_ascii=False), slug))
    return get_set(slug)


def delete_set(slug: str):
    get_db().execute("DELETE FROM photo_sets WHERE slug=?", (slug,))
    d = set_dir(slug)
    if d.is_dir():
        for f in d.iterdir():
            try:
                f.unlink()
            except OSError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass


def safe_filename(filename: str) -> str | None:
    """Tên file an toàn để lưu; None nếu không phải ảnh cho phép."""
    name = Path(filename or "").name          # chặn path traversal
    ext = Path(name).suffix.lower()
    if ext not in IMAGE_EXTS:
        return None
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(name).stem).strip("-")[:60] or "anh"
    return f"{stem}{ext}"


def add_photo(slug: str, filename: str, data: bytes) -> str:
    """Lưu 1 ảnh vào bộ. Trả tên file đã lưu."""
    if not get_set(slug):
        raise ValueError("Bộ ảnh không tồn tại")
    if len(_files(slug)) >= MAX_FILES_PER_SET:
        raise ValueError(f"Mỗi bộ tối đa {MAX_FILES_PER_SET} ảnh")
    name = safe_filename(filename)
    if not name:
        raise ValueError(f"Chỉ nhận ảnh {'/'.join(sorted(e[1:] for e in IMAGE_EXTS))}")
    d = set_dir(slug)
    d.mkdir(parents=True, exist_ok=True)
    target = d / name
    i = 1
    while target.exists():                    # trùng tên → đánh số
        target = d / f"{Path(name).stem}-{i}{Path(name).suffix}"
        i += 1
    target.write_bytes(data)
    return target.name


def remove_photo(slug: str, filename: str):
    name = Path(filename or "").name
    f = set_dir(slug) / name
    if f.is_file():
        f.unlink()


# ── Match với tin nhắn khách ─────────────────────────────────────────

def find_sets(text: str, limit: int = 2, tenant_ws: str = None) -> list:
    """Bộ ảnh match tin nhắn khách — CHỈ nhận khi tên bộ hoặc 1 keyword nằm NGUYÊN
    CỤM (bỏ dấu) trong câu (an toàn: không match vu vơ theo từng từ).
    tenant_ws: MULTI-TENANT — chỉ tìm trong bộ ảnh của shop này.
    Trả list set (có files), điểm cao trước."""
    q = " ".join(re.findall(r"[a-z0-9]+", _norm(text)))
    if not q:
        return []
    scored = []
    for s in list_sets(tenant_ws):
        if not s["files"]:
            continue
        score = 0
        name_n = " ".join(re.findall(r"[a-z0-9]+", _norm(s["name"])))
        if len(name_n) >= 3 and name_n in q:
            score += 10
        for kw in s["keywords"]:
            kw_n = " ".join(re.findall(r"[a-z0-9]+", _norm(kw)))
            if len(kw_n) >= 3 and kw_n in q:
                score += 5
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:limit]]
