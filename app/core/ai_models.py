"""
DANH MỤC MÔ HÌNH AI + gọi chat + tính tiền theo token (per-shop).

Mỗi shop chọn 1 mô hình trong Gói dịch vụ (billing.ai_model). Mọi chỗ dùng AI
của shop (bot trả lời, test bot…) đi qua chat() ở đây → tự ghi token vào billing
(record_token_usage) để hiển thị "đã tiêu bao nhiêu" và trừ ví khi chạy chế độ
VƯỢT QUOTA (tính theo usage — bật/tắt + giới hạn tháng trong Gói dịch vụ).

Giá niêm yết = giá gốc nhà cung cấp (USD/1M token) × AI_PRICE_MARKUP × AI_USD_VND.
Chỉnh markup/tỷ giá trong .env — bảng giá UI và tiền trừ ví tự khớp nhau.
"""

import os
import logging

from openai import OpenAI

from app.core.config import Config

log = logging.getLogger(__name__)

USD_VND = float(os.getenv("AI_USD_VND", "26500"))
MARKUP = float(os.getenv("AI_PRICE_MARKUP", "1.0"))   # hệ số lời trên giá gốc

DEFAULT_MODEL = "deepseek-chat"

# provider → (base_url, tên biến env chứa key)
PROVIDERS = {
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "openai":   (None, "OPENAI_API_KEY"),   # None = base mặc định api.openai.com
}

# key → nhãn UI, provider, model ID thật, giá USD / 1M token (input, output)
CATALOG = {
    "deepseek-chat":     {"label": "DeepSeek V3.2",  "provider": "deepseek", "model": "deepseek-chat",     "in": 0.26, "out": 0.38},
    "deepseek-v4-flash": {"label": "DeepSeek V4 Flash", "provider": "deepseek", "model": "deepseek-v4-flash", "in": 0.10, "out": 0.20},
    "deepseek-v4-pro":   {"label": "DeepSeek V4 Pro", "provider": "deepseek", "model": "deepseek-v4-pro",  "in": 1.30, "out": 2.60},
    "gpt-5-nano":        {"label": "GPT-5 nano",      "provider": "openai",   "model": "gpt-5-nano",       "in": 0.05, "out": 0.40},
    "gpt-5-mini":        {"label": "GPT-5 mini",      "provider": "openai",   "model": "gpt-5-mini",       "in": 0.25, "out": 2.00},
    "gpt-5":             {"label": "GPT-5",           "provider": "openai",   "model": "gpt-5",            "in": 1.25, "out": 10.00},
    "gpt-4o-mini":       {"label": "GPT-4o mini",     "provider": "openai",   "model": "gpt-4o-mini",      "in": 0.15, "out": 0.60},
    "gpt-4o":            {"label": "GPT-4o",          "provider": "openai",   "model": "gpt-4o",           "in": 2.50, "out": 10.00},
    "gpt-4.1-mini":      {"label": "GPT-4.1 mini",    "provider": "openai",   "model": "gpt-4.1-mini",     "in": 0.40, "out": 1.60},
    "gpt-4.1":           {"label": "GPT-4.1",         "provider": "openai",   "model": "gpt-4.1",          "in": 2.00, "out": 8.00},
    "gpt-3.5-turbo":     {"label": "GPT-3.5 turbo",   "provider": "openai",   "model": "gpt-3.5-turbo",    "in": 0.50, "out": 1.50},
}


def _api_key(provider: str) -> str:
    _, env_name = PROVIDERS.get(provider, (None, ""))
    return getattr(Config, env_name, "") or os.getenv(env_name, "")


def available_keys() -> list:
    """Các model DÙNG ĐƯỢC ngay (server có API key của provider đó)."""
    return [k for k, m in CATALOG.items() if _api_key(m["provider"])]


def price_vnd_1m(key: str) -> tuple[int, int]:
    """(giá input, giá output) VNĐ / 1M token — ĐÃ nhân markup + tỷ giá."""
    m = CATALOG[key]
    return (round(m["in"] * USD_VND * MARKUP), round(m["out"] * USD_VND * MARKUP))


def cost_vnd(key: str, tokens_in: int, tokens_out: int) -> float:
    """Chi phí VNĐ của 1 lượt gọi (đã markup)."""
    m = CATALOG.get(key) or CATALOG[DEFAULT_MODEL]
    usd = (tokens_in * m["in"] + tokens_out * m["out"]) / 1_000_000
    return usd * USD_VND * MARKUP


def catalog_for_ui() -> list:
    """Bảng giá cho UI: nhãn + giá VNĐ/1M token + có sẵn key chưa."""
    ok = set(available_keys())
    out = []
    for k, m in CATALOG.items():
        pin, pout = price_vnd_1m(k)
        out.append({"key": k, "label": m["label"], "provider": m["provider"],
                    "in_vnd": pin, "out_vnd": pout, "available": k in ok,
                    "default": k == DEFAULT_MODEL})
    return out


def model_for_owner(owner: str | None) -> str:
    """Model shop đã chọn (billing.ai_model) — không hợp lệ/thiếu key → mặc định."""
    if not owner:
        return DEFAULT_MODEL
    try:
        from app.core.db import get_db
        rows = get_db().query("SELECT ai_model FROM billing WHERE username=?", (owner,))
        key = (rows[0]["ai_model"] if rows else "") or ""
        if key in CATALOG and _api_key(CATALOG[key]["provider"]):
            return key
    except Exception:
        pass
    return DEFAULT_MODEL


def chat(messages: list, owner: str | None = None, model_key: str | None = None,
         max_tokens: int = 1024, temperature: float = 0.7,
         timeout: float | None = None) -> str:
    """Gọi chat theo model CỦA SHOP + ghi token vào billing. Lỗi → raise
    (caller tự fallback — claude_ai giữ chuỗi DeepSeek→Groq cũ)."""
    key = model_key or model_for_owner(owner)
    m = CATALOG.get(key) or CATALOG[DEFAULT_MODEL]
    api_key = _api_key(m["provider"])
    if not api_key:
        raise RuntimeError(f"Thiếu API key cho provider {m['provider']}")
    base_url, _ = PROVIDERS[m["provider"]]
    client = OpenAI(api_key=api_key, base_url=base_url,
                    timeout=timeout or Config.AI_TIMEOUT)
    resp = client.chat.completions.create(
        model=m["model"], messages=messages,
        max_tokens=max_tokens, temperature=temperature)
    try:
        u = resp.usage
        if owner and u:
            from app.core import billing
            billing.record_token_usage(owner, key,
                                       u.prompt_tokens or 0, u.completion_tokens or 0)
    except Exception as e:
        log.error(f"[AIModels] ghi usage lỗi: {e}")
    log.info(f"[AIModels] {key} owner={owner or '-'}")
    return resp.choices[0].message.content or ""
