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
Nhiệm vụ: PHÂN LOẠI cặp hỏi-đáp rồi bóc thành mẩu tái sử dụng cho khách sau.

Có 2 loại mẩu:
- "fact"  = THÔNG TIN tra cứu: giá, chính sách, dịch vụ, giờ mở cửa, địa chỉ, quy định...
- "style" = CÁCH XỬ LÝ TÌNH HUỐNG đáng học theo: khách chê đắt, mặc cả, giận dỗi,
  đòi hủy, phân vân, so sánh nơi khác... — giá trị nằm ở CÁCH chủ shop nói,
  không phải con số.

Trả về DUY NHẤT một JSON (không giải thích, không markdown):
- Nếu KHÔNG đáng lưu (chào hỏi xã giao, thông tin cá nhân 1 khách, chốt đơn riêng lẻ,
  hẹn gặp, đùa vui, thông tin chỉ đúng 1 lần):  {"skip": true}
- Nếu là FACT:
{
  "kind": "fact",
  "title": "tiêu đề ngắn gọn của mẩu tri thức",
  "content": "thông tin viết lại RÕ RÀNG, ĐẦY ĐỦ, khách sau nào hỏi cũng dùng được (không xưng hô cá nhân, không 'bạn ơi')",
  "keywords": ["các cách khách hay hỏi về thông tin này", "3-8 cụm", "cả cách viết không dấu"]
}
- Nếu là STYLE:
{
  "kind": "style",
  "title": "tên tình huống ngắn (vd: Khách chê đắt)",
  "content": "đoạn thoại mẫu dạng:\\nKhách: ...\\nShop: ...\\n(giữ đúng giọng thật của chủ shop; MỌI con số/giá/tên phòng/ngày thay bằng placeholder trong ngoặc vuông như [giá phòng], [tên phòng], [ngày])",
  "keywords": ["các cách khách mở đầu tình huống này", "3-8 cụm", "cả viết không dấu"],
  "intent": "1 nhãn nếu khớp: availability_check|price_list_request|room_photos_request|contact_request|booking|complaint|bargain — không khớp thì \\"\\""
}
Quy tắc chung: chỉ dựa vào điều CHỦ SHOP nói — tuyệt đối không bịa thêm;
fact giữ nguyên con số/giá/tên riêng, style thì NGƯỢC LẠI phải thay hết số liệu
bằng placeholder; viết tiếng Việt tự nhiên."""


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
        kind = knowledge.KIND_STYLE if data.get("kind") == "style" else knowledge.KIND_FACT
        row = {
            "shop": shop, "channel": channel or "", "user_id": user_id or "",
            "question": question[:500], "answer": answer[:2000],
            "title": str(data.get("title") or "").strip()[:200],
            "content": content[:knowledge.MAX_CONTENT_CHARS],
            "keywords": [str(k).strip() for k in kw if str(k).strip()][:30],
            "kind": kind,
        }
        row["intent"] = str(data.get("intent") or "").strip()[:60] if kind == knowledge.KIND_STYLE else ""
        cur = db.execute(
            "INSERT INTO knowledge_suggestions (shop, channel, user_id, question, answer,"
            " title, content, keywords, status, created_at, kind, intent)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["shop"], row["channel"], row["user_id"], row["question"], row["answer"],
             row["title"], row["content"],
             json.dumps(row["keywords"], ensure_ascii=False),
             "pending", datetime.now().isoformat(), kind, row["intent"]))
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
            "status": r["status"], "created_at": r["created_at"],
            "kind": (r["kind"] if "kind" in r.keys() else knowledge.KIND_FACT) or knowledge.KIND_FACT,
            "intent": (r["intent"] if "intent" in r.keys() else "") or ""}


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


def approve(sid: int, title: str = None, content: str = None, keywords: list = None,
            shop: str = None) -> dict:
    """Duyệt đề xuất → CỘNG vào kho tri thức. Chủ sửa nội dung trước khi duyệt
    thì truyền title/content/keywords đè lên bản AI đề xuất.
    shop: MULTI-TENANT — chỉ duyệt được đề xuất CỦA shop mình (route truyền
    _shop(u)); shop khác/None (test) → không giới hạn. Chống shop A nhồi nội
    dung vào kho tri thức bot shop B (IDOR)."""
    db = get_db()
    if shop is not None:
        rows = db.query("SELECT * FROM knowledge_suggestions WHERE id=? AND shop=?", (sid, shop))
    else:
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
        "intent": s.get("intent") or "",
    }
    if not str(chunk["content"]).strip():
        raise ValueError("Nội dung mẩu tri thức trống")
    kind = s.get("kind") or knowledge.KIND_FACT
    added = knowledge.add_chunks([chunk], shop=s["shop"], kind=kind)
    if added == 0:
        cap = knowledge.MAX_STYLE_CHUNKS if kind == knowledge.KIND_STYLE else knowledge.MAX_CHUNKS
        raise ValueError(f"Kho đã đầy ({cap} mẩu) — xoá bớt rồi duyệt lại")
    db.execute("UPDATE knowledge_suggestions SET status='approved' WHERE id=?", (sid,))
    log.info(f"[KLearn] ĐÃ DUYỆT đề xuất #{sid} → kho tri thức ({chunk['title']!r})")
    return {**s, **chunk, "status": "approved"}


def reject(sid: int, shop: str = None):
    db = get_db()
    if shop is not None:
        rows = db.query("SELECT status FROM knowledge_suggestions WHERE id=? AND shop=?", (sid, shop))
    else:
        rows = db.query("SELECT status FROM knowledge_suggestions WHERE id=?", (sid,))
    if not rows:
        raise ValueError("Đề xuất không tồn tại")
    db.execute("UPDATE knowledge_suggestions SET status='rejected' WHERE id=?", (sid,))
    log.info(f"[KLearn] đã bỏ đề xuất #{sid}")


def learn_direct(question: str, answer: str, shop: str = knowledge.DEFAULT_SHOP) -> dict:
    """Bổ sung tri thức 1 CHẠM (Báo cáo não bot): chủ gõ câu trả lời cho câu bot
    bí → AI bóc thành mẩu chuẩn (title/keywords) → LƯU THẲNG vào kho fact (chủ
    chủ động gõ = đã duyệt). Trả chunk đã lưu; AI lỗi → fallback mẩu thô vẫn dùng được."""
    question = str(question or "").strip()
    answer = str(answer or "").strip()
    if len(answer) < 5:
        raise ValueError("Câu trả lời quá ngắn")
    chunk = None
    try:
        from app.core.claude_ai import _call_ai
        raw = _call_ai([
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content":
                f"CÂU KHÁCH HỎI: {question}\nCHỦ SHOP TRẢ LỜI TAY: {answer}\n\nTrả về JSON."},
        ])
        data = _parse_json_loose(raw)
        if isinstance(data, dict) and not data.get("skip") and str(data.get("content") or "").strip():
            kw = data.get("keywords") or []
            chunk = {
                "title": str(data.get("title") or "").strip()[:200],
                "content": str(data["content"]).strip()[:knowledge.MAX_CONTENT_CHARS],
                "keywords": [str(k).strip() for k in (kw if isinstance(kw, list) else [kw])
                             if str(k).strip()][:30],
                "kind": knowledge.KIND_STYLE if data.get("kind") == "style" else knowledge.KIND_FACT,
                "intent": str(data.get("intent") or "").strip()[:60],
            }
    except Exception as e:
        log.warning(f"[KLearn] learn_direct AI lỗi ({e}) → dùng mẩu thô")
    if chunk is None:   # AI chết/skip → vẫn lưu dạng thô: câu hỏi làm keyword
        chunk = {"title": question[:200] or "Bổ sung từ báo cáo",
                 "content": answer[:knowledge.MAX_CONTENT_CHARS],
                 "keywords": [question[:60]] if question else [],
                 "kind": knowledge.KIND_FACT, "intent": ""}
    added = knowledge.add_chunks([chunk], shop=shop, kind=chunk["kind"])
    if added == 0:
        raise ValueError("Kho tri thức đã đầy — xoá bớt rồi thử lại")
    log.info(f"[KLearn] learn_direct: +1 mẩu {chunk['title']!r} (shop={shop})")
    return chunk


# ── STYLE RAG: nạp mẫu hội thoại ─────────────────────────────────────

_STYLE_EXTRACT_PROMPT = """Bạn bóc MẪU HỘI THOẠI dạy chatbot cách tư vấn, từ đoạn chat thật giữa KHÁCH và SHOP (shop dịch vụ Việt Nam).
Mục tiêu: giữ lại GIỌNG ĐIỆU + CÁCH XỬ LÝ của shop để bot bắt chước — KHÔNG giữ số liệu.

Trả về DUY NHẤT một JSON:
- Đoạn chat không có gì đáng học (xã giao, quá ngắn, toàn bot nói):  {"skip": true}
- Có tình huống đáng học:
{
  "title": "tên tình huống ngắn (vd: Khách chê đắt / Khách phân vân 2 phòng)",
  "content": "thoại mẫu rút gọn 2-8 lượt, dạng:\\nKhách: ...\\nShop: ...\\nQUAN TRỌNG: MỌI con số, giá, tên phòng/dịch vụ cụ thể, ngày giờ thay bằng placeholder [giá phòng], [tên phòng], [ngày]...",
  "keywords": ["các cách khách mở đầu tình huống này", "3-8 cụm", "cả viết không dấu"],
  "intent": "1 nhãn nếu khớp: availability_check|price_list_request|room_photos_request|contact_request|booking|complaint|bargain — không thì \\"\\""
}
Giữ đúng văn phong tin nhắn thật của SHOP (xưng hô, emoji, độ dài câu). Không bịa thêm lượt thoại."""


def extract_style_from_messages(messages: list, shop: str = knowledge.DEFAULT_SHOP,
                                save: bool = True) -> dict | None:
    """Nút "⭐ Lưu làm mẫu": chủ chọn hội thoại đẹp → AI bóc 1 mẩu style (đã
    sanitize số liệu) → LƯU THẲNG vào kho style (chủ bấm nút = đã duyệt).
    Trả chunk đã lưu, hoặc None (không đáng học / lỗi)."""
    try:
        convo = "\n".join(
            f"{'KHÁCH' if m.get('role') == 'user' else 'SHOP'}: {str(m.get('content') or '')[:400]}"
            for m in (messages or [])[-_CTX_MESSAGES:] if m.get("content"))
        if len(convo) < 40:
            return None
        from app.core.claude_ai import _call_ai   # import trễ — test mock được
        raw = _call_ai([
            {"role": "system", "content": _STYLE_EXTRACT_PROMPT},
            {"role": "user", "content": f"ĐOẠN CHAT:\n{convo}\n\nTrả về JSON."},
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
        chunk = {
            "title": str(data.get("title") or "").strip()[:200],
            "content": content[:knowledge.MAX_CONTENT_CHARS],
            "keywords": [str(k).strip() for k in kw if str(k).strip()][:30],
            "intent": str(data.get("intent") or "").strip()[:60],
            "kind": knowledge.KIND_STYLE,
        }
        if save:
            added = knowledge.add_chunks([chunk], shop=shop, kind=knowledge.KIND_STYLE)
            if added == 0:
                raise ValueError(f"Kho mẫu đã đầy ({knowledge.MAX_STYLE_CHUNKS}) — xoá bớt trước")
        log.info(f"[StyleLearn] mẫu hội thoại mới: {chunk['title']!r} (shop={shop})")
        return chunk
    except ValueError:
        raise
    except Exception as e:
        log.error(f"[StyleLearn] extract_style lỗi: {e}", exc_info=True)
        return None


_STYLE_GEN_PROMPT = """Bạn tạo BỘ MẪU HỘI THOẠI dạy chatbot cách tư vấn cho một shop dịch vụ Việt Nam.
Đầu vào là (a) transcript hội thoại thật do chủ shop dán, HOẶC (b) mô tả giọng/cách tư vấn mong muốn.

Sinh 4-10 mẫu, mỗi mẫu 1 TÌNH HUỐNG khác nhau mà khách hay gặp (hỏi giá, chê đắt,
mặc cả, phân vân, đòi hủy, giục trả lời, khách giận, hỏi đường/chỗ gửi xe...).

ĐỊNH DẠNG BẮT BUỘC — NDJSON: MỖI DÒNG là MỘT object JSON hoàn chỉnh, KHÔNG mảng
bao ngoài, KHÔNG dấu phẩy cuối dòng, KHÔNG markdown/code fence, không lời dẫn:
{"title": "tên tình huống", "content": "Khách: ...\\nShop: ...", "keywords": ["cách khách mở đầu", "..."], "intent": "nhãn hoặc rỗng"}

Quy tắc content: 2-6 lượt thoại; đúng giọng từ transcript/mô tả (xưng hô, emoji,
câu ngắn kiểu tin nhắn); MỌI số liệu/giá/tên riêng thay bằng placeholder [giá], [tên phòng], [ngày].
intent chọn trong: availability_check|price_list_request|room_photos_request|contact_request|booking|complaint|bargain hoặc rỗng."""


def generate_style_set(source_text: str, shop: str = knowledge.DEFAULT_SHOP,
                       model_key: str = None, owner: str = None) -> list:
    """Sinh bộ mẫu hội thoại từ transcript dán vào / mô tả giọng.
    Output NDJSON từng dòng (+ tự viết-tiếp khi chạm trần token qua _call_ai_long)
    → bị cắt cụt chỉ mất dòng cuối, không vỡ cả bộ. KHÔNG tự lưu — trả list
    chunk để UI preview, chủ chọn rồi mới lưu."""
    source_text = str(source_text or "").strip()
    if len(source_text) < 20:
        raise ValueError("Nội dung quá ngắn — dán transcript hoặc mô tả kỹ hơn")
    from app.core.prompt_builder import _call_ai_long   # tái dùng viết-tiếp 10 vòng
    raw = _call_ai_long([
        {"role": "system", "content": _STYLE_GEN_PROMPT},
        {"role": "user", "content": source_text[:30_000]},
    ], model_key=model_key, owner=owner)
    chunks = []
    for line in (raw or "").splitlines():
        line = line.strip().rstrip(",")
        if not line or line in ("[", "]") or line.startswith("```"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue   # dòng cuối bị cắt cụt / rác → bỏ đúng dòng đó
        if not isinstance(d, dict) or not str(d.get("content") or "").strip():
            continue
        kw = d.get("keywords") or []
        if not isinstance(kw, list):
            kw = [str(kw)]
        chunks.append({
            "title": str(d.get("title") or "").strip()[:200],
            "content": str(d.get("content")).strip()[:knowledge.MAX_CONTENT_CHARS],
            "keywords": [str(k).strip() for k in kw if str(k).strip()][:30],
            "intent": str(d.get("intent") or "").strip()[:60],
            "kind": knowledge.KIND_STYLE,
        })
    return chunks
