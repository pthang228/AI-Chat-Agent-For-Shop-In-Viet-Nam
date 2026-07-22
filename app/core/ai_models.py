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
# Hệ số lời trên giá gốc. Mặc định 1.5 (+50%): giá bán usage phải NUÔI được
# hạ tầng + lượt trong-quota — markup 1.0 nghĩa là bán hộ nhà cung cấp không công.
MARKUP = float(os.getenv("AI_PRICE_MARKUP", "1.5"))

DEFAULT_MODEL = "deepseek-chat"

# provider → (base_url, tên biến env chứa key)
PROVIDERS = {
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "openai":   (None, "OPENAI_API_KEY"),   # None = base mặc định api.openai.com
    "groq":     ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),  # tương thích OpenAI
}

# key → nhãn UI, provider, model ID THẬT (gửi lên provider), giá USD / 1M token (in,out).
# Chỉ để model ID CÓ THẬT ở provider — model "đặt trước chưa phát hành" gây lỗi
# runtime bị nuốt im lặng (khách nhắn mới lộ). "internal": model DÙNG NỘI BỘ cho
# fallback (Groq), KHÔNG cho shop chọn nhưng VẪN ghi usage/tính tiền như model thường.
CATALOG = {
    # DeepSeek: model ID `deepseek-chat`/`deepseek-reasoner` NGỪNG PHỤC VỤ
    # 2026/07/24 → phải gửi ID mới `deepseek-v4-flash`/`deepseek-v4-pro`. Giữ
    # KEY catalog cũ (DB shop đã chọn + DEFAULT_MODEL + test tham chiếu theo key),
    # chỉ đổi "model" (ID gửi provider) + giá thật (api-docs.deepseek.com/pricing).
    "deepseek-chat":     {"label": "DeepSeek V4-Flash", "provider": "deepseek", "model": "deepseek-v4-flash", "in": 0.14, "out": 0.28},
    "deepseek-reasoner": {"label": "DeepSeek V4-Pro",   "provider": "deepseek", "model": "deepseek-v4-pro",   "in": 0.435, "out": 0.87},
    "gpt-5-nano":        {"label": "GPT-5 nano",      "provider": "openai",   "model": "gpt-5-nano",       "in": 0.05, "out": 0.40},
    "gpt-5-mini":        {"label": "GPT-5 mini",      "provider": "openai",   "model": "gpt-5-mini",       "in": 0.25, "out": 2.00},
    "gpt-5":             {"label": "GPT-5",           "provider": "openai",   "model": "gpt-5",            "in": 1.25, "out": 10.00},
    "gpt-4o-mini":       {"label": "GPT-4o mini",     "provider": "openai",   "model": "gpt-4o-mini",      "in": 0.15, "out": 0.60},
    "gpt-4o":            {"label": "GPT-4o",          "provider": "openai",   "model": "gpt-4o",           "in": 2.50, "out": 10.00},
    "gpt-4.1-mini":      {"label": "GPT-4.1 mini",    "provider": "openai",   "model": "gpt-4.1-mini",     "in": 0.40, "out": 1.60},
    "gpt-4.1":           {"label": "GPT-4.1",         "provider": "openai",   "model": "gpt-4.1",          "in": 2.00, "out": 8.00},
    "gpt-3.5-turbo":     {"label": "GPT-3.5 turbo",   "provider": "openai",   "model": "gpt-3.5-turbo",    "in": 0.50, "out": 1.50},
    # ── Fallback nội bộ (Groq) — không hiển thị/không cho chọn, chỉ dùng khi
    #    provider chính lỗi. Có mặt ở đây để chat() dựng đúng client + ghi usage.
    "groq-llama-70b":    {"label": "Llama 3.3 70B",   "provider": "groq", "model": "llama-3.3-70b-versatile", "in": 0.59, "out": 0.79, "internal": True},
    "groq-llama-8b":     {"label": "Llama 3.1 8B",    "provider": "groq", "model": "llama-3.1-8b-instant",    "in": 0.05, "out": 0.08, "internal": True},
    "groq-gemma2-9b":    {"label": "Gemma2 9B",       "provider": "groq", "model": "gemma2-9b-it",            "in": 0.20, "out": 0.20, "internal": True},
}

# Chuỗi model Groq thử lần lượt khi provider chính lỗi (rẻ→đắt độ tin cậy).
GROQ_FALLBACK_KEYS = ["groq-llama-70b", "groq-llama-8b", "groq-gemma2-9b"]


def public_catalog() -> dict:
    """CATALOG BỎ model nội bộ (fallback) — dùng cho UI + validate lựa chọn của shop."""
    return {k: m for k, m in CATALOG.items() if not m.get("internal")}


# ── Trần giá model theo HẠNG gói ─────────────────────────────────────
# Quota đếm LƯỢT (không đếm token) nên shop gói rẻ chọn model đắt là nền tảng
# lỗ tiền LLM trực tiếp (starter 250k/tháng × 6.000 lượt GPT-4o ≈ 1,8-3tr giá
# vốn). Trần theo giá USD/1M token (in, out); None = không trần (business).
TIER_PRICE_CAPS = {
    "trial":    {"in": 0.30, "out": 0.60},   # trial như starter — chống farm acc đốt model đắt
    "starter":  {"in": 0.30, "out": 0.60},   # DeepSeek V3.2 / GPT-5 nano / GPT-4o mini
    "pro":      {"in": 0.60, "out": 2.50},   # + Reasoner / GPT-5 mini / GPT-4.1 mini / GPT-3.5
    "business": None,                        # mọi model
}


def allowed_for_tier(key: str, tier: str) -> bool:
    """Model key này có nằm trong trần giá của hạng gói không (chỉ xét model
    public — model nội bộ fallback do nền tảng trả, không qua trần)."""
    m = public_catalog().get(key)
    if not m:
        return False
    cap = TIER_PRICE_CAPS.get(tier or "trial", TIER_PRICE_CAPS["trial"])
    if cap is None:
        return True
    return m["in"] <= cap["in"] and m["out"] <= cap["out"]


def min_tier_for(key: str) -> str:
    """Hạng gói THẤP NHẤT được dùng model này (cho UI grey-out + báo lỗi rõ)."""
    for t in ("starter", "pro", "business"):
        if allowed_for_tier(key, t):
            return t
    return "business"


def _api_key(provider: str) -> str:
    _, env_name = PROVIDERS.get(provider, (None, ""))
    return getattr(Config, env_name, "") or os.getenv(env_name, "")


def available_keys() -> list:
    """Các model shop CHỌN ĐƯỢC ngay (server có API key + không phải model nội bộ)."""
    return [k for k, m in public_catalog().items() if _api_key(m["provider"])]


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
    """Bảng giá cho UI: nhãn + giá VNĐ/1M token + có sẵn key chưa (bỏ model nội bộ)."""
    ok = set(available_keys())
    out = []
    for k, m in public_catalog().items():
        pin, pout = price_vnd_1m(k)
        out.append({"key": k, "label": m["label"], "provider": m["provider"],
                    "in_vnd": pin, "out_vnd": pout, "available": k in ok,
                    "default": k == DEFAULT_MODEL, "min_tier": min_tier_for(k)})
    return out


# Ngân sách ký tự KB nhồi vào prompt cho model RẺ (DeepSeek). Model ĐẮT hơn thì
# co lại (tránh đốt tiền input khi shop chọn GPT). Xem knowledge.FULL_KB_CHAR_BUDGET.
_KB_BUDGET_FULL = 24_000
_KB_BUDGET_FLOOR = 6_000
_KB_REF_PRICE_IN = 0.30       # ~giá input DeepSeek — dưới mức này = nhồi hết


def kb_char_budget(model_key: str | None) -> int:
    """Ngân sách ký tự KB cho model đang dùng: model rẻ (≈DeepSeek) → nhồi hết
    (24k); model đắt → co theo tỉ lệ giá input, sàn 6k (vượt sàn thì retrieve top-k
    thay vì nhồi toàn bộ KB mỗi tin → khỏi đốt tiền input với GPT)."""
    m = CATALOG.get(model_key or "") or CATALOG[DEFAULT_MODEL]
    price_in = m.get("in") or _KB_REF_PRICE_IN
    if price_in <= _KB_REF_PRICE_IN:
        return _KB_BUDGET_FULL
    return max(_KB_BUDGET_FLOOR, int(_KB_BUDGET_FULL * _KB_REF_PRICE_IN / price_in))


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


# account (kênh nhận tin) → channel trong user_apps — để tra model PER-APP.
# Zalo cá nhân dùng account="1" (số tài khoản) nên map cả "1" lẫn "zalo".
ACCOUNT_CHANNEL = {
    "1": "zalo", "zalo": "zalo", "meta": "meta", "instagram": "meta",
    "telegram": "telegram", "shopee": "shopee",
    "zalooa": "zalooa", "webchat": "webchat",
}


def model_for(owner: str | None, account: str | None = None) -> str:
    """Model cho 1 lượt gọi: override PER-APP (user_apps.ai_model theo kênh của
    account) thắng; không có/không hợp lệ → model mức SHOP (model_for_owner)."""
    if owner and account:
        try:
            ch = ACCOUNT_CHANNEL.get(str(account).strip().lower())
            if ch:
                from app.core.db import get_db
                rows = get_db().query(
                    "SELECT ai_model FROM user_apps WHERE username=? AND channel=? "
                    "AND ai_model!='' ORDER BY created_at LIMIT 1", (owner, ch))
                key = (rows[0]["ai_model"] if rows else "") or ""
                if key in CATALOG and _api_key(CATALOG[key]["provider"]):
                    return key
        except Exception:
            pass
    return model_for_owner(owner)


def client_for(model_key: str, timeout: float | None = None):
    """Dựng (client OpenAI-compatible, model_id thật) cho 1 model trong CATALOG.
    Điểm DUY NHẤT dựng client theo provider — chat() và prompt_builder (Dạy AI)
    dùng chung, đổi provider/key chỉ sửa ở đây. Thiếu key → raise."""
    m = CATALOG.get(model_key) or CATALOG[DEFAULT_MODEL]
    api_key = _api_key(m["provider"])
    if not api_key:
        raise RuntimeError(f"Thiếu API key cho provider {m['provider']}")
    base_url, _ = PROVIDERS[m["provider"]]
    # max_retries=0: timeout truyền vào là trần MỖI-LƯỢT; SDK mặc định retry 2 lần
    # → khách chờ tới 3× timeout khi provider sập (circuit-breaker mới lo phần
    # sập kéo dài, KHÔNG cần SDK tự retry chồng lên).
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=0,
                  timeout=timeout or Config.AI_TIMEOUT), m["model"]


def chat(messages: list, owner: str | None = None, model_key: str | None = None,
         max_tokens: int = 1024, temperature: float = 0.7,
         timeout: float | None = None, account: str | None = None) -> str:
    """Gọi chat theo model CỦA SHOP (hoặc PER-APP nếu có account) + ghi token vào
    billing. Lỗi → raise (caller tự fallback — claude_ai giữ chuỗi DeepSeek→Groq cũ)."""
    key = model_key or model_for(owner, account)
    # CHỐT CHẶN RUNTIME theo hạng gói: kể cả khi DB còn ghi model đắt (chọn từ
    # trước khi hạ gói / API cũ), lượt gọi vẫn hạ về mặc định — không gate model
    # nội bộ (fallback Groq do nền tảng trả tiền).
    if owner and key in public_catalog():
        try:
            from app.core import billing
            tier = billing.tier_of(owner)
            if not allowed_for_tier(key, tier):
                log.info(f"[AIModels] {key} vượt hạng gói ({tier}) của {owner} → {DEFAULT_MODEL}")
                key = DEFAULT_MODEL
        except Exception:
            pass
    m = CATALOG.get(key) or CATALOG[DEFAULT_MODEL]
    client, _model_id = client_for(key, timeout)
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
