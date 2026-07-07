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
  add_chunks(chunks, shop) — CỘNG THÊM mẩu (bot học từ hội thoại, sau khi chủ duyệt)
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
    "muon", "can", "biet", "c!", "vay", "ha", "ak", "ạ", "e", "minh",
}

# Chuẩn hoá teencode/viết tắt tiếng Việt (không dấu) → dạng đầy đủ ĐỂ MATCH tốt hơn.
# Khách gõ rất tắt ("co ship k", "ib e", "bn tien") — map để keyword khớp được.
# (Seed từ danh sách teencode phổ biến; giá trị đã BỎ DẤU để khớp corpus không dấu.)
_SYNONYMS = {
    # phủ định
    "k": "khong", "ko": "khong", "kh": "khong", "hong": "khong", "hok": "khong",
    "hem": "khong", "kg": "khong", "khg": "khong", "hong": "khong",
    # hỏi số lượng / giá
    "bn": "bao nhieu", "nhiu": "nhieu", "may": "bao nhieu",
    "ntn": "nhu the nao", "ny": "nhu the nao",
    # nhắn tin / liên hệ
    "ib": "nhan tin", "inbox": "nhan tin", "rep": "tra loi",
    "sdt": "so dien thoai", "dt": "dien thoai", "sđt": "so dien thoai",
    "stk": "so tai khoan", "ck": "chuyen khoan", "tk": "tai khoan",
    # thời gian
    "gio": "gio giac", "bh": "bay gio", "bjo": "bay gio", "hnay": "hom nay",
    "trc": "truoc", "sau": "sau",
    # xưng hô / thường gặp
    "e": "em", "a": "anh", "b": "ban", "dc": "duoc", "đc": "duoc",
    "vs": "voi", "j": "gi", "z": "vay", "v": "vay", "wa": "qua", "qá": "qua",
    "r": "roi", "rui": "roi", "uk": "u", "uh": "u", "ah": "a",
    # gõ sai phổ biến
    "phog": "phong", "gia": "gia",
    # bán hàng
    "sp": "san pham", "cty": "cong ty", "dat": "dat",
    "ship": "ship giao hang", "freeship": "mien phi ship",
}


def _norm(s: str) -> str:
    """lowercase + bỏ dấu tiếng Việt (NFD strip combining, đ→d)."""
    s = (s or "").lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _tokens(s: str) -> list:
    """Token không dấu + MỞ RỘNG teencode/viết tắt (k→khong, bn→bao nhieu…)
    để câu hỏi gõ tắt của khách vẫn khớp keyword/nội dung."""
    out = []
    for t in re.findall(r"[a-z0-9]+", _norm(s)):
        expanded = _SYNONYMS.get(t)
        if expanded:
            out.extend(expanded.split())
        else:
            out.append(t)
    return out


def _idf_map(chunks: list) -> dict:
    """IDF (BM25-style) theo tần suất TÀI LIỆU của token trong title+content.
    Corpus mỗi shop nhỏ (≤200 mẩu) → tính lại mỗi lần retrieve rất rẻ.
    Chuẩn hoá về ~0..1: từ HIẾM (đặc trưng: số phòng, tên dịch vụ riêng) → gần 1;
    từ PHỔ BIẾN (xuất hiện mọi mẩu: 'phong', 'gia') → gần 0 → không gây nhiễu."""
    import math
    n = len(chunks) or 1
    df = {}
    for c in chunks:
        seen = set(_tokens(c.get("title", ""))) | set(_tokens(c.get("content", "")))
        for t in seen:
            df[t] = df.get(t, 0) + 1
    denom = math.log(n + 1) or 1.0
    return {t: math.log((n + 1) / (d + 0.5)) / denom for t, d in df.items()}


def _row_to_chunk(r) -> dict:
    try:
        kw = json.loads(r["keywords"])
    except Exception:
        kw = []
    return {"id": r["id"], "title": r["title"], "content": r["content"],
            "keywords": kw, "pinned": bool(r["pinned"])}


# ── ingest / add / list / clear ──────────────────────────────────────

def _sanitize(chunks: list, limit: int = MAX_CHUNKS) -> list:
    """Làm sạch mẩu đầu vào (dùng chung cho ingest lẫn add_chunks)."""
    cleaned = []
    for c in (chunks or [])[:limit]:
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
    return cleaned


def _insert(db, chunks: list, shop: str):
    now = datetime.now().isoformat()
    db.conn.executemany(
        "INSERT INTO knowledge_chunks (shop, title, content, keywords, pinned, created_at)"
        " VALUES (?,?,?,?,?,?)",
        [(shop, c["title"], c["content"], json.dumps(c["keywords"], ensure_ascii=False),
          c["pinned"], now) for c in chunks])


def ingest(chunks: list, shop: str = DEFAULT_SHOP) -> int:
    """Thay TOÀN BỘ tri thức của shop bằng danh sách mẩu mới. Trả số mẩu đã lưu."""
    cleaned = _sanitize(chunks)
    db = get_db()
    with db.lock:
        db.conn.execute("DELETE FROM knowledge_chunks WHERE shop=?", (shop,))
        _insert(db, cleaned, shop)
        db.conn.commit()
    return len(cleaned)


def add_chunks(chunks: list, shop: str = DEFAULT_SHOP) -> int:
    """CỘNG THÊM mẩu vào kho (KHÔNG xoá mẩu cũ như ingest) — dùng khi bot học
    từ hội thoại được chủ duyệt. Tôn trọng trần MAX_CHUNKS/shop. Trả số đã thêm."""
    room = MAX_CHUNKS - count(shop)
    if room <= 0:
        return 0
    cleaned = _sanitize(chunks, limit=room)
    if not cleaned:
        return 0
    db = get_db()
    with db.lock:
        _insert(db, cleaned, shop)
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

def _score(chunk: dict, q_tokens: set, q_norm: str, idf: dict) -> float:
    """Chấm điểm mẩu với câu hỏi. Hai loại tín hiệu:
    - KEYWORDS curated (chủ/AI đã ghi 'cách khách hay hỏi') = tín hiệu ĐỘ CHÍNH XÁC
      CAO → bonus CỐ ĐỊNH mạnh (cụm khớp +5, đủ token +3), không đụng IDF.
    - Title/content overlap = tín hiệu NHIỄU → nhân IDF: từ đặc trưng (số phòng
      '301', tên dịch vụ riêng) điểm cao; từ phổ biến ('phong','gia' có ở mọi mẩu)
      điểm ~0 → hết nhiễu 'mẩu nào cũng khớp'."""
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
        w = idf.get(t, 1.0)          # token lạ (chỉ có trong câu hỏi) → coi như hiếm
        if t in title_tokens:
            s += 2.0 * w
        if t in content_tokens:
            s += 1.0 * w
    return s


# Ngưỡng "kho đủ nhỏ để nhồi HẾT vào prompt" (ký tự content, ~8k token).
# Kho dưới ngưỡng → đưa TOÀN BỘ dữ liệu shop vào MỌI tin nhắn, bỏ retrieval
# → bot "học hết", 0 rủi ro tra trượt câu hỏi đặc thù. Đại đa số shop nằm
# dưới ngưỡng này (24k ký tự ≈ 40-60 mẩu chi tiết); chi phí thêm không đáng kể
# (DeepSeek ~6,5đ/1M token input). Shop cực lớn vượt ngưỡng → retrieve top-k
# (chống prompt phình + lost-in-middle) nhưng LUÔN kèm các mẩu ghim.
FULL_KB_CHAR_BUDGET = 24_000


def retrieve(query: str, shop: str = DEFAULT_SHOP, k: int = 6) -> list:
    """Top-k mẩu liên quan tới câu hỏi + LUÔN kèm mẩu pinned (thông tin nền) —
    kho lớn cũng không bao giờ mất mẩu ghim. Kho trống → []."""
    chunks = list_chunks(shop)
    if not chunks:
        return []
    q_norm = " ".join(_tokens(query))
    q_tokens = set(_tokens(query)) - _STOPWORDS
    idf = _idf_map(chunks)
    scored = [(_score(c, q_tokens, q_norm, idf), c) for c in chunks]
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    top = [c for s, c in scored[:k] if s > 0]
    pinned = [c for c in chunks if c["pinned"]]
    if not top:
        return pinned[:k] if pinned else chunks[:1]
    # Ghép pinned vào CUỐI (không trùng) — bot luôn có thông tin nền của shop,
    # còn hits[0] vẫn là mẩu khớp nhất (debug/test dựa vào thứ tự này)
    seen = {c["id"] for c in top}
    return top + [c for c in pinned if c["id"] not in seen]


def context_chunks(query: str, shop: str = DEFAULT_SHOP, k: int = 6) -> tuple:
    """Chọn mẩu đưa vào prompt cho 1 câu hỏi. Trả (chunks, mode):
    - Kho NHỎ (tổng content ≤ FULL_KB_CHAR_BUDGET) → TRẢ HẾT (mode='full'):
      không retrieval, không bao giờ tra trượt — bot thấy toàn bộ dữ liệu shop.
    - Kho LỚN → retrieve top-k liên quan (mode='retrieval').
    - Kho trống → ([], 'empty')."""
    chunks = list_chunks(shop)
    if not chunks:
        return [], "empty"
    total = sum(len(c.get("content") or "") for c in chunks)
    if total <= FULL_KB_CHAR_BUDGET:
        # pinned trước cho quen mắt, rồi theo id — thứ tự ổn định
        chunks.sort(key=lambda c: (0 if c.get("pinned") else 1, c["id"]))
        return chunks, "full"
    return retrieve(query, shop, k), "retrieval"


def format_block(chunks: list) -> str:
    """Đóng gói các mẩu thành block đưa vào system prompt. Mở đầu bằng quy tắc
    GROUNDING mạnh (model rẻ như DeepSeek hay tin 'kiến thức có sẵn' hơn dữ liệu
    → phải nói rõ CHỈ dùng dữ liệu này, KHÔNG bịa số/giá/chính sách)."""
    if not chunks:
        return ""
    parts = [
        "DỮ LIỆU SHOP (nguồn thông tin DUY NHẤT để trả lời):\n"
        "- CHỈ trả lời dựa vào dữ liệu đánh số [1],[2]... bên dưới. KHÔNG dùng kiến "
        "thức có sẵn ngoài dữ liệu này.\n"
        "- TUYỆT ĐỐI KHÔNG tự bịa giá, số phòng, chính sách, địa chỉ, SĐT... "
        "Thiếu thông tin → nói chưa có và báo chủ shop (theo quy ước unknown_question).\n"
        "- Con số (giá, phòng, giờ) phải LẤY ĐÚNG từ dữ liệu, không suy đoán."
    ]
    for i, c in enumerate(chunks, 1):
        title = f" {c['title']}" if c.get("title") else ""
        parts.append(f"[{i}]{title}\n{c['content']}")
    return "\n\n".join(parts)
