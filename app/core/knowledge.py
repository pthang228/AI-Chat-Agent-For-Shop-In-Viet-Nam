"""
Kho tri thức RAG cho chế độ "Dạy AI" lai (persona nhỏ + facts tra cứu theo câu hỏi).

Vì sao KHÔNG dùng vector DB/embeddings:
  - Corpus mỗi shop chỉ ~20-200 mẩu → quét hết + chấm điểm thuần Python < 1ms.
  - Việc "hiểu ngữ nghĩa" đã làm 1 LẦN lúc INGEST: AI sinh sẵn keywords/từ đồng nghĩa
    cho từng mẩu (các cách khách hay hỏi) → lúc QUERY chỉ cần match từ khóa bỏ dấu.
  - 0 dependency mới, đọc từ SQLite mỗi lần retrieve → tiến trình kênh nào cũng
    thấy tri thức mới NGAY khi shop bấm lưu (giống custom_prompt.txt).

API:
  ingest(chunks, shop)   — thay toàn bộ tri thức của shop (atomic)
  retrieve(query, shop, k) — top-k mẩu liên quan; không match → mẩu pinned
  list_chunks(shop) / clear(shop) / count(shop)
"""

import json
import re
import unicodedata
from datetime import datetime

from app.core.db import get_db

DEFAULT_SHOP = "default"          # backend hiện single-tenant; key sẵn cho multi-shop
MAX_CHUNKS = 200                  # trần số mẩu mỗi shop
MAX_CONTENT_CHARS = 4000          # trần độ dài 1 mẩu

# Từ quá phổ biến trong câu hỏi tiếng Việt — bỏ khi chấm điểm để đỡ nhiễu
_STOPWORDS = {
    "khong", "co", "cho", "minh", "ban", "oi", "a", "va", "la", "cua", "duoc",
    "nao", "gi", "the", "nhe", "nha", "voi", "hoi", "xin", "em", "anh", "chi",
    "shop", "ad", "admin", "di", "day", "do", "thi", "ma", "nhu", "nay",
}


def _norm(s: str) -> str:
    """lowercase + bỏ dấu tiếng Việt (NFD strip combining, đ→d)."""
    s = (s or "").lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens(s: str) -> list:
    return re.findall(r"[a-z0-9]+", _norm(s))


def _row_to_chunk(r) -> dict:
    try:
        kw = json.loads(r["keywords"])
    except Exception:
        kw = []
    return {"id": r["id"], "title": r["title"], "content": r["content"],
            "keywords": kw, "pinned": bool(r["pinned"])}


# ── ingest / list / clear ────────────────────────────────────────────

def ingest(chunks: list, shop: str = DEFAULT_SHOP) -> int:
    """Thay TOÀN BỘ tri thức của shop bằng danh sách mẩu mới. Trả số mẩu đã lưu."""
    cleaned = []
    for c in (chunks or [])[:MAX_CHUNKS]:
        content = str(c.get("content") or "").strip()[:MAX_CONTENT_CHARS]
        if not content:
            continue
        kw = c.get("keywords") or []
        if not isinstance(kw, list):
            kw = [str(kw)]
        cleaned.append({
            "title": str(c.get("title") or "").strip()[:200],
            "content": content,
            "keywords": [str(k).strip() for k in kw if str(k).strip()][:30],
            "pinned": 1 if c.get("pinned") else 0,
        })
    db = get_db()
    now = datetime.now().isoformat()
    with db.lock:
        db.conn.execute("DELETE FROM knowledge_chunks WHERE shop=?", (shop,))
        db.conn.executemany(
            "INSERT INTO knowledge_chunks (shop, title, content, keywords, pinned, created_at)"
            " VALUES (?,?,?,?,?,?)",
            [(shop, c["title"], c["content"], json.dumps(c["keywords"], ensure_ascii=False),
              c["pinned"], now) for c in cleaned])
        db.conn.commit()
    return len(cleaned)


def list_chunks(shop: str = DEFAULT_SHOP) -> list:
    rows = get_db().query(
        "SELECT * FROM knowledge_chunks WHERE shop=? ORDER BY id", (shop,))
    return [_row_to_chunk(r) for r in rows]


def clear(shop: str = DEFAULT_SHOP):
    get_db().execute("DELETE FROM knowledge_chunks WHERE shop=?", (shop,))


def count(shop: str = DEFAULT_SHOP) -> int:
    rows = get_db().query(
        "SELECT COUNT(*) AS n FROM knowledge_chunks WHERE shop=?", (shop,))
    return rows[0]["n"] if rows else 0


# ── retrieve ─────────────────────────────────────────────────────────

def _score(chunk: dict, q_tokens: set, q_norm: str) -> float:
    """keywords khớp cả cụm +5, token keyword +3, title +2, content +1."""
    s = 0.0
    for kw in chunk["keywords"]:
        kw_norm = _norm(kw)
        if not kw_norm:
            continue
        if len(kw_norm) >= 4 and kw_norm in q_norm:   # cả cụm nằm trong câu hỏi
            s += 5
            continue
        kt = [t for t in _tokens(kw) if t not in _STOPWORDS]
        if kt and all(t in q_tokens for t in kt):     # đủ mọi token của keyword
            s += 3
    title_tokens = set(_tokens(chunk["title"])) - _STOPWORDS
    content_tokens = set(_tokens(chunk["content"])) - _STOPWORDS
    for t in q_tokens:
        if t in title_tokens:
            s += 2
        if t in content_tokens:
            s += 1
    return s


def retrieve(query: str, shop: str = DEFAULT_SHOP, k: int = 4) -> list:
    """Top-k mẩu liên quan tới câu hỏi. Không mẩu nào match → trả mẩu pinned
    (thông tin chung) để bot vẫn có nền; kho trống → []."""
    chunks = list_chunks(shop)
    if not chunks:
        return []
    q_norm = " ".join(_tokens(query))
    q_tokens = set(_tokens(query)) - _STOPWORDS
    scored = [(_score(c, q_tokens, q_norm), c) for c in chunks]
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    top = [c for s, c in scored[:k] if s > 0]
    if top:
        return top
    pinned = [c for c in chunks if c["pinned"]]
    return pinned[:k] if pinned else chunks[:1]


def format_block(chunks: list) -> str:
    """Đóng gói các mẩu thành block đưa vào system prompt."""
    if not chunks:
        return ""
    parts = ["DỮ LIỆU SHOP — tra cứu cho câu hỏi hiện tại. CHỈ dùng thông tin dưới đây; "
             "thiếu thông tin thì nói chưa có và báo chủ shop, TUYỆT ĐỐI KHÔNG bịa:"]
    for i, c in enumerate(chunks, 1):
        title = f" {c['title']}" if c.get("title") else ""
        parts.append(f"[{i}]{title}\n{c['content']}")
    return "\n\n".join(parts)
