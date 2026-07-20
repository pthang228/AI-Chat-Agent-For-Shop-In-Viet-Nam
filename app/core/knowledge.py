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
MAX_CHUNKS = 200                  # trần số mẩu FACT mỗi shop
MAX_STYLE_CHUNKS = 80             # trần số mẩu STYLE (mẫu hội thoại) mỗi shop
MAX_CONTENT_CHARS = 4000          # trần độ dài 1 mẩu

# 2 loại mẩu trong kho: 'fact' = thông tin tra cứu (giá/chính sách/FAQ);
# 'style' = mẫu hội thoại dạy GIỌNG + cách xử lý tình huống (số liệu đã thay
# placeholder lúc ingest — style KHÔNG bao giờ là nguồn số liệu).
KIND_FACT = "fact"
KIND_STYLE = "style"

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
            "keywords": kw, "pinned": bool(r["pinned"]),
            "kind": (r["kind"] if "kind" in r.keys() else KIND_FACT) or KIND_FACT,
            "intent": (r["intent"] if "intent" in r.keys() else "") or ""}


# ── ingest / add / list / clear ──────────────────────────────────────

def _sanitize(chunks: list, limit: int = MAX_CHUNKS, kind: str = KIND_FACT) -> list:
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
            "kind": KIND_STYLE if (c.get("kind") or kind) == KIND_STYLE else KIND_FACT,
            "intent": str(c.get("intent") or "").strip()[:60],
        })
    return cleaned


def _insert(db, chunks: list, shop: str):
    now = datetime.now().isoformat()
    db.conn.executemany(
        "INSERT INTO knowledge_chunks (shop, title, content, keywords, pinned, created_at, kind, intent)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [(shop, c["title"], c["content"], json.dumps(c["keywords"], ensure_ascii=False),
          c["pinned"], now, c.get("kind") or KIND_FACT, c.get("intent") or "") for c in chunks])


MAX_VERSIONS = 10   # số bản kho giữ lại để rollback (mỗi shop mỗi kind)


def _ensure_versions_table(db):
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_versions ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, shop TEXT NOT NULL, kind TEXT NOT NULL,"
        " snapshot TEXT NOT NULL, chunk_count INTEGER NOT NULL, created_at TEXT NOT NULL)")


def _snapshot(db, shop: str, kind: str):
    """Lưu BẢN CHỤP kho hiện tại (kind) TRƯỚC khi ghi đè — để 'Áp dụng' hỏng còn
    rollback được (não bot là tài sản chính của shop). Gọi TRONG db.lock của ingest.
    Kho đang rỗng → không snapshot (khỏi tạo bản trống vô nghĩa)."""
    _ensure_versions_table(db)
    rows = db.query(
        "SELECT title, content, keywords, pinned, kind, intent FROM knowledge_chunks "
        "WHERE shop=? AND kind=? ORDER BY id", (shop, kind))
    if not rows:
        return
    snap = json.dumps([{
        "title": r["title"], "content": r["content"],
        "keywords": r["keywords"], "pinned": r["pinned"],
        "kind": r["kind"], "intent": r["intent"],
    } for r in rows], ensure_ascii=False)
    db.conn.execute(
        "INSERT INTO knowledge_versions(shop, kind, snapshot, chunk_count, created_at)"
        " VALUES (?,?,?,?,?)", (shop, kind, snap, len(rows), datetime.now().isoformat()))
    # Chỉ giữ MAX_VERSIONS bản gần nhất mỗi (shop,kind)
    old = db.query(
        "SELECT id FROM knowledge_versions WHERE shop=? AND kind=? ORDER BY id DESC "
        "LIMIT -1 OFFSET ?", (shop, kind, MAX_VERSIONS))
    for r in old:
        db.conn.execute("DELETE FROM knowledge_versions WHERE id=?", (r["id"],))


def list_versions(shop: str = DEFAULT_SHOP, kind: str = None) -> list:
    """Danh sách bản kho đã lưu (mới nhất trước) để UI cho chọn khôi phục."""
    db = get_db()
    _ensure_versions_table(db)
    if kind:
        rows = db.query(
            "SELECT id, kind, chunk_count, created_at FROM knowledge_versions "
            "WHERE shop=? AND kind=? ORDER BY id DESC", (shop, kind))
    else:
        rows = db.query(
            "SELECT id, kind, chunk_count, created_at FROM knowledge_versions "
            "WHERE shop=? ORDER BY id DESC", (shop,))
    return [{"id": r["id"], "kind": r["kind"], "chunk_count": r["chunk_count"],
             "created_at": r["created_at"]} for r in rows]


def restore_version(version_id: int, shop: str = DEFAULT_SHOP) -> int:
    """Khôi phục kho về 1 bản đã lưu (chỉ bản CỦA shop này — chống rollback nhầm
    shop khác). Snapshot kho hiện tại TRƯỚC khi khôi phục (rollback cũng undo được).
    Trả số mẩu đã khôi phục, hoặc -1 nếu không tìm thấy bản."""
    db = get_db()
    _ensure_versions_table(db)
    rows = db.query(
        "SELECT kind, snapshot FROM knowledge_versions WHERE id=? AND shop=?",
        (version_id, shop))
    if not rows:
        return -1
    kind = rows[0]["kind"]
    try:
        chunks = json.loads(rows[0]["snapshot"]) or []
    except Exception:
        return -1
    cleaned = _sanitize(chunks, limit=(MAX_STYLE_CHUNKS if kind == KIND_STYLE else MAX_CHUNKS),
                        kind=kind)
    with db.lock:
        _snapshot(db, shop, kind)   # kho hiện tại thành 1 bản nữa (undo được)
        db.conn.execute("DELETE FROM knowledge_chunks WHERE shop=? AND kind=?", (shop, kind))
        _insert(db, cleaned, shop)
        db.conn.commit()
    return len(cleaned)


def ingest(chunks: list, shop: str = DEFAULT_SHOP, kind: str = KIND_FACT) -> int:
    """Thay TOÀN BỘ tri thức LOẠI kind của shop bằng danh sách mẩu mới.
    QUAN TRỌNG: chỉ xoá mẩu cùng kind — dạy lại não (fact) KHÔNG quét mất kho
    mẫu hội thoại (style) và ngược lại. SNAPSHOT kho cũ trước khi xoá (rollback
    được nếu bản mới hỏng). Trả số mẩu đã lưu."""
    cleaned = _sanitize(chunks, limit=(MAX_STYLE_CHUNKS if kind == KIND_STYLE else MAX_CHUNKS),
                        kind=kind)
    db = get_db()
    with db.lock:
        _snapshot(db, shop, kind)   # giữ bản cũ để rollback
        # DB cũ chưa migrate cột kind sẽ không có dòng kind≠fact — WHERE kind=? an toàn
        db.conn.execute("DELETE FROM knowledge_chunks WHERE shop=? AND kind=?", (shop, kind))
        _insert(db, cleaned, shop)
        db.conn.commit()
    return len(cleaned)


def add_chunks(chunks: list, shop: str = DEFAULT_SHOP, kind: str = KIND_FACT) -> int:
    """CỘNG THÊM mẩu vào kho (KHÔNG xoá mẩu cũ như ingest) — dùng khi bot học
    từ hội thoại được chủ duyệt. Tôn trọng trần theo kind/shop. Trả số đã thêm."""
    cap = MAX_STYLE_CHUNKS if kind == KIND_STYLE else MAX_CHUNKS
    room = cap - count(shop, kind=kind)
    if room <= 0:
        return 0
    cleaned = _sanitize(chunks, limit=room, kind=kind)
    if not cleaned:
        return 0
    db = get_db()
    with db.lock:
        _insert(db, cleaned, shop)
        db.conn.commit()
    return len(cleaned)


def list_chunks(shop: str = DEFAULT_SHOP, kind: str = None) -> list:
    """kind=None → TOÀN BỘ kho (mặc định cũ — caller cũ không đổi hành vi vì
    DB cũ toàn fact); kind='fact'/'style' → lọc đúng loại."""
    if kind:
        rows = get_db().query(
            "SELECT * FROM knowledge_chunks WHERE shop=? AND kind=? ORDER BY id",
            (shop, kind))
    else:
        rows = get_db().query(
            "SELECT * FROM knowledge_chunks WHERE shop=? ORDER BY id", (shop,))
    return [_row_to_chunk(r) for r in rows]


def delete_chunk(chunk_id: int, shop: str = DEFAULT_SHOP) -> bool:
    """Xoá 1 mẩu theo id (kèm shop để không xoá nhầm mẩu shop khác)."""
    db = get_db()
    with db.lock:
        cur = db.conn.execute(
            "DELETE FROM knowledge_chunks WHERE id=? AND shop=?", (chunk_id, shop))
        db.conn.commit()
        return cur.rowcount > 0


def clear(shop: str = DEFAULT_SHOP, kind: str = None):
    if kind:
        get_db().execute("DELETE FROM knowledge_chunks WHERE shop=? AND kind=?", (shop, kind))
    else:
        get_db().execute("DELETE FROM knowledge_chunks WHERE shop=?", (shop,))


def count(shop: str = DEFAULT_SHOP, kind: str = None) -> int:
    if kind:
        rows = get_db().query(
            "SELECT COUNT(*) AS n FROM knowledge_chunks WHERE shop=? AND kind=?",
            (shop, kind))
    else:
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


def retrieve(query: str, shop: str = DEFAULT_SHOP, k: int = 6,
             chunks: list = None) -> list:
    """Top-k mẩu FACT liên quan tới câu hỏi + LUÔN kèm mẩu pinned (thông tin nền,
    tối đa 4 — chống prompt phình khi shop ghim nhiều) — kho lớn cũng không mất
    mẩu ghim. chunks: truyền kho đã đọc sẵn để khỏi query DB lần 2. Kho trống → []."""
    if chunks is None:
        chunks = list_chunks(shop, kind=KIND_FACT)
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
    # Ghép pinned vào CUỐI (không trùng, tối đa 4) — bot luôn có thông tin nền,
    # còn hits[0] vẫn là mẩu khớp nhất (debug/test dựa vào thứ tự này)
    seen = {c["id"] for c in top}
    return top + [c for c in pinned if c["id"] not in seen][:4]


def context_chunks(query: str, shop: str = DEFAULT_SHOP, k: int = 6,
                   budget: int | None = None) -> tuple:
    """Chọn mẩu đưa vào prompt cho 1 câu hỏi. Trả (chunks, mode):
    - Kho NHỎ (tổng content ≤ budget) → TRẢ HẾT (mode='full'): không retrieval,
      không bao giờ tra trượt — bot thấy toàn bộ dữ liệu shop.
    - Kho LỚN → retrieve top-k liên quan (mode='retrieval').
    - Kho trống → ([], 'empty').
    budget: ngân sách ký tự để nhồi hết (None = mặc định FULL_KB_CHAR_BUDGET).
      Model ĐẮT truyền budget nhỏ hơn (ai_models.kb_char_budget) → co lại, khỏi
      đốt tiền input; model rẻ (DeepSeek) giữ nguyên 24k.
    CHỈ mẩu FACT — mẫu hội thoại (style) đi block riêng qua style_block()."""
    chunks = list_chunks(shop, kind=KIND_FACT)
    if not chunks:
        return [], "empty"
    if budget is None or budget <= 0:
        budget = FULL_KB_CHAR_BUDGET
    total = sum(len(c.get("content") or "") for c in chunks)
    if total <= budget:
        # pinned trước cho quen mắt, rồi theo id — thứ tự ổn định
        chunks.sort(key=lambda c: (0 if c.get("pinned") else 1, c["id"]))
        return chunks, "full"
    # tái dùng kho đã đọc — khỏi query DB + parse JSON lần 2 mỗi tin nhắn
    hits = retrieve(query, shop, k, chunks=chunks)
    # TRẦN budget CẢ ở chế độ retrieval: top-6 + 4 pinned × 4000 ký tự có thể
    # tới ~40k — gấp nhiều lần sàn 6k của model đắt. Cắt cộng dồn theo content
    # (giữ tối thiểu 1 mẩu; hits[0] luôn là mẩu khớp nhất — pinned cuối bị cắt trước).
    out, used = [], 0
    for c in hits:
        n = len(c.get("content") or "")
        if out and used + n > budget:
            continue
        out.append(c)
        used += n
    return out, "retrieval"


def retrieve_style(query: str, shop: str = DEFAULT_SHOP, k: int = 2,
                   intent: str = "") -> list:
    """Top-k MẪU HỘI THOẠI (style) khớp tình huống hiện tại.
    Chấm điểm = keyword+IDF như fact, CỘNG bonus khi tag intent của mẩu trùng
    intent lượt trước (brain lưu conv.last_intent — tình huống thường kéo dài
    nhiều lượt nên tín hiệu này rẻ mà trúng). CHỈ trả mẩu có điểm > 0 —
    không nhét mẫu lạc đề cho đủ số."""
    chunks = list_chunks(shop, kind=KIND_STYLE)
    if not chunks:
        return []
    q_norm = " ".join(_tokens(query))
    q_tokens = set(_tokens(query)) - _STOPWORDS
    idf = _idf_map(chunks)
    intent = (intent or "").strip()
    scored = []
    for c in chunks:
        s = _score(c, q_tokens, q_norm, idf)
        if intent and c.get("intent") and c["intent"] == intent:
            s += 4.0
        scored.append((s, c))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [c for s, c in scored[:k] if s > 0]


def style_block(query: str, shop: str = DEFAULT_SHOP, k: int = 2,
                intent: str = "") -> str:
    """Block VÍ DỤ CÁCH TƯ VẤN cho system prompt — rỗng khi không có mẫu khớp."""
    return format_style_block(retrieve_style(query, shop, k, intent))


def format_style_block(chunks: list) -> str:
    """Đóng gói mẫu hội thoại vào prompt. RÀO CHẮN quan trọng nhất: ví dụ chỉ
    dạy GIỌNG + CÁCH XỬ LÝ — cấm chép số liệu từ ví dụ (số trong ví dụ đã bị
    thay placeholder lúc ingest, nhưng vẫn nói rõ cho model rẻ khỏi bịa)."""
    if not chunks:
        return ""
    parts = [
        "VÍ DỤ CÁCH TƯ VẤN (mẫu hội thoại thật của shop — chỉ để học GIỌNG ĐIỆU "
        "và CÁCH XỬ LÝ tình huống):\n"
        "- Bắt chước cách xưng hô, độ dài câu, cách dẫn dắt trong ví dụ.\n"
        "- TUYỆT ĐỐI KHÔNG lấy giá/số/tên phòng/chính sách từ ví dụ — chỗ [trong "
        "ngoặc vuông] là placeholder; mọi số liệu PHẢI tra ở DỮ LIỆU SHOP."
    ]
    for i, c in enumerate(chunks, 1):
        title = f" — {c['title']}" if c.get("title") else ""
        parts.append(f"(Ví dụ {i}{title})\n{c['content']}")
    return "\n\n".join(parts)


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
