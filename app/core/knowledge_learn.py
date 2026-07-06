"""
BOT HỌC TỪ HỘI THOẠI (bán tự động, CÓ DUYỆT) — bổ sung cơ sở tri thức RAG.

Luồng: khách hỏi câu bot không biết → CHỦ trả lời tay (gửi từ dashboard hoặc
gõ trực tiếp trên điện thoại - owner takeover) → AI đọc cặp hỏi-đáp + ngữ cảnh
→ bóc thành MẨU TRI THỨC ĐỀ XUẤT (title/content/keywords) → nằm ở hàng chờ
`knowledge_suggestions` → chủ DUYỆT trong web (Dạy AI) → mẩu mới được
knowledge.add_chunks() cộng vào kho. Không duyệt = không vào kho → bot không
tự học sai/học tin nhạy cảm.

Chống rác/tốn tiền AI:
  - Lọc rẻ trước khi gọi AI: phải có câu hỏi của khách + câu trả lời đủ dài.
  - AI được quyền trả {"skip": true} khi cặp hỏi-đáp không chứa thông tin
    tái sử dụng (chào hỏi, chốt đơn cá nhân, hẹn gặp...).
  - Dedup: câu hỏi đã có đề xuất pending/approved tương tự → bỏ qua.

API:
  suggest_from_reply(user_id, channel, messages, answer)  → dict | None
  list_suggestions(status, shop) / count_pending(shop)
  approve(sid, title?, content?, keywords?)  → mẩu vào kho + status approved
  reject(sid)
"""

import json
import logging
import re
from datetime import datetime

from app.core.db import get_db
from app.core import knowledge

log = logging.getLogger(__name__)

MIN_ANSWER_CHARS = 15     # trả lời quá ngắn ("ok", "dạ") → không đáng học
MIN_QUESTION_CHARS = 8
MAX_PENDING = 100         # trần hàng chờ mỗi shop (chống spam)
_CTX_MESSAGES = 12        # số tin gần nhất đưa AI làm ngữ cảnh

_EXTRACT_PROMPT = """Bạn là trợ lý xây CƠ SỞ TRI THỨC cho chatbot của một shop dịch vụ Việt Nam.
Chủ shop vừa TỰ TAY trả lời một câu khách hỏi (thường vì bot chưa biết thông tin này).
Nhiệm vụ: quyết định cặp hỏi-đáp này có chứa THÔNG TIN TÁI SỬ DỤNG cho khách sau
không (giá, chính sách, dịch vụ, giờ mở cửa, địa chỉ, quy định, khuyến mãi...).

Trả về DUY NHẤT một JSON (không giải thích, không markdown):
- Nếu KHÔNG đáng lưu (chào hỏi xã giao, thông tin cá nhân 1 khách, chốt đơn riêng lẻ,
  hẹn gặp, đùa vui, thông tin chỉ đúng 1 lần):  {"skip": true}
- Nếu ĐÁNG lưu:
{
  "title": "tiêu đề ngắn gọn của mẩu tri thức",
  "content": "thông tin viết lại RÕ RÀNG, ĐẦY ĐỦ, khách sau nào hỏi cũng dùng được (không xưng hô cá nhân, không 'bạn ơi')",
  "keywords": ["các cách khách hay hỏi về thông tin này", "3-8 cụm", "cả cách viết không dấu"]
}
Quy tắc: content chỉ chứa thông tin CHỦ SHOP nói — tuyệt đối không bịa thêm;
giữ nguyên con số/giá/tên riêng; viết tiếng Việt tự nhiên."""


def _parse_json_loose(raw: str):
    raw = re.sub(r"^```[a-z]*\n?", "", (raw or "").strip())
    raw = re.sub(r"\n?```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _last_user_question(messages: list, answer: str) -> str:
    """Câu khách hỏi GẦN NHẤT trước câu trả lời tay của chủ. messages có thể đã
    chứa answer (dashboard add_assistant_message trước khi gọi đây) — bỏ qua nó."""
    for m in reversed(messages or []):
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        if m.get("role") == "assistant":
            continue
        if m.get("role") == "user":
            return content
    return ""


def _similar_exists(db, shop: str, question: str) -> bool:
    """Đã có đề xuất (pending/approved) cho câu hỏi gần giống → bỏ, đỡ trùng."""
    qn = knowledge._norm(question)
    if not qn:
        return False
    rows = db.query(
        "SELECT question FROM knowledge_suggestions WHERE shop=? AND status IN ('pending','approved') "
        "ORDER BY id DESC LIMIT 200", (shop,))
    for r in rows:
        if knowledge._norm(r["question"]) == qn:
            return True
    return False


def suggest_from_reply(user_id: str, channel: str, messages: list, answer: str,
                       shop: str = knowledge.DEFAULT_SHOP):
    """Chủ vừa trả lời tay → AI bóc mẩu tri thức đề xuất (chờ duyệt).
    Trả dict đề xuất đã lưu, hoặc None (không đáng học/lỗi — không ném exception,
    caller là background worker)."""
    try:
        answer = str(answer or "").strip()
        if len(answer) < MIN_ANSWER_CHARS:
            return None
        question = _last_user_question(messages, answer)
        if len(question) < MIN_QUESTION_CHARS:
            return None
        db = get_db()
        # MULTI-TENANT: caller (8 hook send) không truyền shop → tự tra tenant
        # của hội thoại để đề xuất vào ĐÚNG kho tri thức của shop đó.
        if shop == knowledge.DEFAULT_SHOP:
            try:
                from app.core import tenant as _tenant
                rows = db.query("SELECT tenant FROM sessions WHERE user_id=? LIMIT 1",
                                (user_id,))
                if rows:
                    shop = _tenant.shop_key((rows[0]["tenant"] or "") or None)
            except Exception:
                pass
        pending = db.query(
            "SELECT COUNT(*) AS n FROM knowledge_suggestions WHERE shop=? AND status='pending'",
            (shop,))[0]["n"]
        if pending >= MAX_PENDING:
            log.warning(f"[KLearn] hàng chờ đầy ({pending}) → bỏ qua")
            return None
        if _similar_exists(db, shop, question):
            log.info(f"[KLearn] câu hỏi đã có đề xuất tương tự → bỏ qua: {question[:60]!r}")
            return None

        convo = "\n".join(
            f"{'KHÁCH' if m.get('role') == 'user' else 'SHOP'}: {m.get('content', '')}"
            for m in (messages or [])[-_CTX_MESSAGES:] if m.get("content"))
        from app.core.claude_ai import _call_ai   # import trễ — test mock được
        raw = _call_ai([
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content":
                f"NGỮ CẢNH HỘI THOẠI GẦN NHẤT:\n{convo}\n\n"
                f"CÂU KHÁCH HỎI: {question}\n"
                f"CHỦ SHOP TRẢ LỜI TAY: {answer}\n\nTrả về JSON."},
        ])
        data = _parse_json_loose(raw)
        if not isinstance(data, dict) or data.get("skip"):
            return None
        content = str(data.get("content") or "").strip()
        if not content:
            return None
        kw = data.get("keywords") or []
        if not isinstance(kw, list):
            kw = [str(kw)]
        row = {
            "shop": shop, "channel": channel or "", "user_id": user_id or "",
            "question": question[:500], "answer": answer[:2000],
            "title": str(data.get("title") or "").strip()[:200],
            "content": content[:knowledge.MAX_CONTENT_CHARS],
            "keywords": [str(k).strip() for k in kw if str(k).strip()][:30],
        }
        cur = db.execute(
            "INSERT INTO knowledge_suggestions (shop, channel, user_id, question, answer,"
            " title, content, keywords, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (row["shop"], row["channel"], row["user_id"], row["question"], row["answer"],
             row["title"], row["content"], json.dumps(row["keywords"], ensure_ascii=False),
             "pending", datetime.now().isoformat()))
        row["id"] = cur.lastrowid
        row["status"] = "pending"
        log.info(f"[KLearn] đề xuất tri thức mới #{row['id']}: {row['title']!r} "
                 f"(từ {channel} {user_id})")
        return row
    except Exception as e:
        log.error(f"[KLearn] suggest_from_reply lỗi: {e}", exc_info=True)
        return None


# ── Hàng chờ duyệt ───────────────────────────────────────────────────

def _row_to_dict(r) -> dict:
    try:
        kw = json.loads(r["keywords"])
    except Exception:
        kw = []
    return {"id": r["id"], "shop": r["shop"], "channel": r["channel"],
            "user_id": r["user_id"], "question": r["question"], "answer": r["answer"],
            "title": r["title"], "content": r["content"], "keywords": kw,
            "status": r["status"], "created_at": r["created_at"]}


def list_suggestions(status: str = "pending", shop: str = knowledge.DEFAULT_SHOP) -> list:
    rows = get_db().query(
        "SELECT * FROM knowledge_suggestions WHERE shop=? AND status=? ORDER BY id DESC",
        (shop, status))
    return [_row_to_dict(r) for r in rows]


def count_pending(shop: str = knowledge.DEFAULT_SHOP) -> int:
    rows = get_db().query(
        "SELECT COUNT(*) AS n FROM knowledge_suggestions WHERE shop=? AND status='pending'",
        (shop,))
    return rows[0]["n"] if rows else 0


def approve(sid: int, title: str = None, content: str = None, keywords: list = None) -> dict:
    """Duyệt đề xuất → CỘNG vào kho tri thức. Chủ sửa nội dung trước khi duyệt
    thì truyền title/content/keywords đè lên bản AI đề xuất."""
    db = get_db()
    rows = db.query("SELECT * FROM knowledge_suggestions WHERE id=?", (sid,))
    if not rows:
        raise ValueError("Đề xuất không tồn tại")
    s = _row_to_dict(rows[0])
    if s["status"] != "pending":
        raise ValueError(f"Đề xuất đã được xử lý ({s['status']})")
    chunk = {
        "title": (title if title is not None else s["title"]) or "",
        "content": (content if content is not None else s["content"]) or "",
        "keywords": keywords if isinstance(keywords, list) else s["keywords"],
    }
    if not str(chunk["content"]).strip():
        raise ValueError("Nội dung mẩu tri thức trống")
    added = knowledge.add_chunks([chunk], shop=s["shop"])
    if added == 0:
        raise ValueError(f"Kho tri thức đã đầy ({knowledge.MAX_CHUNKS} mẩu) — xoá bớt rồi duyệt lại")
    db.execute("UPDATE knowledge_suggestions SET status='approved' WHERE id=?", (sid,))
    log.info(f"[KLearn] ĐÃ DUYỆT đề xuất #{sid} → kho tri thức ({chunk['title']!r})")
    return {**s, **chunk, "status": "approved"}


def reject(sid: int):
    db = get_db()
    rows = db.query("SELECT status FROM knowledge_suggestions WHERE id=?", (sid,))
    if not rows:
        raise ValueError("Đề xuất không tồn tại")
    db.execute("UPDATE knowledge_suggestions SET status='rejected' WHERE id=?", (sid,))
    log.info(f"[KLearn] đã bỏ đề xuất #{sid}")
