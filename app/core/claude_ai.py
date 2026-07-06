"""
Xử lý AI — ưu tiên DeepSeek, fallback sang Groq.
"""

import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from openai import OpenAI
from app.core.config import Config

_WEEKDAY_VN = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]


def _today_context() -> str:
    now      = datetime.now()
    tomorrow = now + timedelta(days=1)
    d2       = now + timedelta(days=2)
    d3       = now + timedelta(days=3)

    def fmt(d): return f"{_WEEKDAY_VN[d.weekday()]}, {d.strftime('%d/%m/%Y')}"

    # Lịch 14 ngày để AI tra cứu trực tiếp (không cần tự tính)
    calendar_lines = []
    for i in range(14):
        d = now + timedelta(days=i)
        suffix = ""
        if i == 0: suffix = "  ← HÔM NAY"
        elif i == 1: suffix = "  ← NGÀY MAI"
        calendar_lines.append(
            f"  +{i:2d} ngày = {_WEEKDAY_VN[d.weekday()]}, {d.strftime('%d/%m/%Y')}{suffix}"
        )
    calendar_str = "\n".join(calendar_lines)

    return (
        f"!!!QUAN TRỌNG - THỜI GIAN THỰC TẾ TỪ MÁY CHỦ (KHÔNG ĐƯỢC TỰ TÍNH LẠI)!!!\n"
        f"Hôm nay = {fmt(now)}, {now.strftime('%H:%M')}\n"
        f"\n"
        f"LỊCH 14 NGÀY TỚI — dùng bảng này để chuyển mọi cách nói ngày sang dd/mm/yyyy:\n"
        f"{calendar_str}\n"
        f"\n"
        f"BẢNG QUY ĐỔI NHANH:\n"
        f"  'hôm nay' / 'tối nay' / 'chiều nay' / 'sáng nay' / 'đêm nay'  → {now.strftime('%d/%m/%Y')}\n"
        f"  'mai' / 'ngày mai' / 'tối mai' / 'chiều mai' / 'sáng mai'      → {tomorrow.strftime('%d/%m/%Y')}\n"
        f"  'ngày mốt' / 'ngày kia'                                         → {d2.strftime('%d/%m/%Y')}\n"
        f"  'thứ X tuần sau/tới' → tra cột LỊCH 14 NGÀY bên trên, tìm thứ X đó\n"
        f"\n"
        f"QUY TẮC BẮT BUỘC:\n"
        f"  - Khi khách nêu bất kỳ cách nói ngày nào → PHẢI tính ra dd/mm/yyyy và đặt vào checkin\n"
        f"  - TUYỆT ĐỐI KHÔNG hỏi 'bạn có muốn ngày X không?' hay xác nhận lại ngày\n"
        f"  - TUYỆT ĐỐI KHÔNG tự tính ngoài bảng. Chỉ dùng thông tin trên.\n"
        f"  - Giờ hiện tại {now.strftime('%H:%M')} — nếu khách hỏi lịch hôm nay, vẫn set checkin = {now.strftime('%d/%m/%Y')}\n"
        f"{'='*50}\n\n"
    )


# Marker chế độ LAI (persona + tri thức RAG) — đồng bộ với prompt_builder.HYBRID_MARKER
HYBRID_MARKER = "#NOVACHAT-HYBRID-V1"


def _load_system_prompt() -> str:
    # Prompt TUỲ CHỈNH (shop tạo bằng AI trong web → data/custom_prompt.txt) được
    # ưu tiên; chưa có → dùng prompt mặc định đi kèm code. Đọc lại MỖI request
    # nên lưu prompt mới trong web là áp dụng ngay, không cần restart.
    custom = Config.DATA_DIR / "custom_prompt.txt"
    try:
        if custom.exists():
            text = custom.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    p = Path(__file__).parent / "system_prompt.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "Bạn là trợ lý chăm sóc khách hàng homestay."


def _load_tech_rules() -> str:
    # Quy ước kỹ thuật (JSON <analysis>, intent, bảo mật) do CODE sở hữu — chế độ
    # lai luôn tự ghép vào để persona AI sinh ra không thể phá máy móc của brain.
    p = Path(__file__).parent / "tech_rules.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _memory_block(user_id: str, account: str) -> str:
    """TRÍ NHỚ AI VỀ KHÁCH (CRM) — có user_id thì tra, lỗi/không có → rỗng.
    Import trễ + nuốt lỗi: đường nóng của bot không được chết vì CRM."""
    if not user_id:
        return ""
    try:
        from app.core import customers
        return customers.memory_block(account or "", user_id)
    except Exception:
        return ""


def _compose_system(user_message: str, history: list,
                    user_id: str = None, account: str = None) -> tuple:
    """Ghép system prompt + thông tin chẩn đoán (cho trang Test bot).
    Chế độ LAI: persona (ngắn) + DỮ LIỆU SHOP tra theo câu hỏi (RAG) + TRÍ NHỚ
    KHÁCH (CRM) + quy ước kỹ thuật. Prompt cũ (không marker): giữ nguyên + memory.
    Trả (system_str, debug) — debug = {mode, chunks[], system_chars}."""
    memory = _memory_block(user_id, account)
    base = _load_system_prompt()
    if not base.startswith(HYBRID_MARKER):
        system = _today_context() + base + (("\n\n" + memory) if memory else "")
        return system, {"mode": "legacy", "chunks": [], "system_chars": len(system)}

    from app.core import knowledge  # import trễ — tránh vòng lặp import khi test mock
    persona = base[len(HYBRID_MARKER):].lstrip("\n")
    # Query tra cứu = tin hiện tại + tin user gần nhất (câu follow-up "giá bao nhiêu?"
    # cần ngữ cảnh phòng vừa nhắc ở tin trước)
    prev_user = ""
    for m in reversed(history or []):
        if m.get("role") == "user":
            prev_user = str(m.get("content") or "")
            break
    # Kho nhỏ → nhồi TOÀN BỘ (0 tra trượt); kho lớn → retrieve top-k liên quan.
    hits, kb_mode = knowledge.context_chunks(f"{prev_user}\n{user_message}".strip())
    kb_block = knowledge.format_block(hits)
    parts = [_today_context() + persona]
    if kb_block:
        parts.append(kb_block)
    if memory:
        parts.append(memory)
    tech = _load_tech_rules()
    if tech:
        parts.append(tech)
    system = "\n\n".join(parts)
    return system, {
        "mode": "hybrid",
        "kb_mode": kb_mode,   # 'full' (nhồi hết) | 'retrieval' (tra top-k) | 'empty'
        "chunks": [{"title": h.get("title") or "(không tiêu đề)"} for h in hits],
        "system_chars": len(system),
    }


def _build_system_prompt(user_message: str, history: list,
                         user_id: str = None, account: str = None) -> str:
    return _compose_system(user_message, history, user_id, account)[0]


def _call_ai(messages: list) -> str:
    # Thử DeepSeek trước
    if Config.DEEPSEEK_API_KEY:
        try:
            client = OpenAI(
                api_key=Config.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
                timeout=Config.AI_TIMEOUT,   # tránh treo thread vô hạn khi AI chậm
            )
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
            )
            print("[AI] Dùng DeepSeek")
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"[AI] DeepSeek lỗi ({e}), chuyển sang Groq...")

    # Fallback: Groq
    from groq import Groq
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it"]
    last_error = None
    for model in models:
        try:
            client = Groq(api_key=Config.GROQ_API_KEY, timeout=Config.AI_TIMEOUT)
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
            )
            print(f"[AI] Groq fallback — model: {model}")
            return response.choices[0].message.content or ""
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                last_error = e
                continue
            raise
    raise last_error


def _parse_ai_output(full_text: str) -> dict:
    """Bóc <analysis> JSON + thẻ [BOOKING_CONFIRMED] khỏi output AI."""
    analysis_match = re.search(r"<analysis>(.*?)</analysis>", full_text, re.DOTALL)
    reply = re.sub(r"<analysis>.*?</analysis>", "", full_text, flags=re.DOTALL).strip()

    analysis = {
        "intent": "other",
        "checkin": None,
        "checkout": None,
        "booking_confirmed": False,
    }
    if analysis_match:
        try:
            parsed = json.loads(analysis_match.group(1).strip())
            # AI đôi khi trả JSON array/số/chuỗi trong <analysis> → json.loads
            # KHÔNG raise nhưng parsed không phải dict → `**analysis` sẽ TypeError
            # làm mất câu trả lời của khách. Chỉ nhận khi là dict.
            if isinstance(parsed, dict):
                analysis = parsed
        except (json.JSONDecodeError, ValueError):
            pass

    if "[BOOKING_CONFIRMED]" in reply:
        analysis["booking_confirmed"] = True
        reply = reply.replace("[BOOKING_CONFIRMED]", "").strip()

    return {"reply": reply, **analysis}


def analyze_message(user_message: str, history: list[dict],
                    user_id: str = None, account: str = None) -> dict:
    messages = [{"role": "system",
                 "content": _build_system_prompt(user_message, history, user_id, account)}]
    messages += list(history)
    messages.append({"role": "user", "content": user_message})
    return _parse_ai_output(_call_ai(messages))


def analyze_with_debug(user_message: str, history: list[dict]) -> dict:
    """Như analyze_message nhưng kèm 'debug' (mode, mẩu tri thức đã tra, cỡ context)
    — dùng cho trang Test bot của shop, KHÔNG lưu session, không gửi kênh nào."""
    system, dbg = _compose_system(user_message, history)
    messages = [{"role": "system", "content": system}]
    messages += list(history)
    messages.append({"role": "user", "content": user_message})
    out = _parse_ai_output(_call_ai(messages))
    out["debug"] = dbg
    return out
