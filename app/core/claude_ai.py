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


def _call_ai(messages: list) -> str:
    # Thử DeepSeek trước
    if Config.DEEPSEEK_API_KEY:
        try:
            client = OpenAI(
                api_key=Config.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
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
            client = Groq(api_key=Config.GROQ_API_KEY)
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


def analyze_message(user_message: str, history: list[dict]) -> dict:
    messages = [{"role": "system", "content": _today_context() + _load_system_prompt()}]
    messages += list(history)
    messages.append({"role": "user", "content": user_message})

    full_text = _call_ai(messages)

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
            analysis = json.loads(analysis_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    if "[BOOKING_CONFIRMED]" in reply:
        analysis["booking_confirmed"] = True
        reply = reply.replace("[BOOKING_CONFIRMED]", "").strip()

    return {"reply": reply, **analysis}
