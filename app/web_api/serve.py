"""
Chạy Flask app bằng WSGI server production (waitress) thay dev server.

Vì sao waitress: thuần Python, chạy tốt trên Windows (gunicorn không hỗ trợ Windows),
đa luồng thật sự, không in cảnh báo "development server". Nếu máy chưa cài waitress
(pip install waitress) → tự rơi về Flask dev server để không chặn việc chạy thử.
"""

import logging

log = logging.getLogger(__name__)

# Mỗi tiến trình kênh phục vụ web UI + webhook — 16 luồng là dư cho 10k khách chat
# (mỗi request xử lý nhanh, brain chạy thread nền riêng).
THREADS = 16


def _check_production_secrets():
    """FAIL-CLOSED mã hoá at-rest: đã public (PUBLIC_BASE_URL đặt) mà thiếu
    NOVACHAT_SECRET_KEY → token 7 kênh + StringSession Telethon (TOÀN QUYỀN acc
    khách) sẽ ghi PLAINTEXT vào SQLite mà chỉ có 1 dòng log warning. Từ chối
    khởi động thay vì degrade thầm — cùng triết lý /payhook từ chối khi public
    thiếu SEPAY_API_KEY. Cố tình chấp nhận rủi ro: ALLOW_PLAINTEXT_SECRETS=1."""
    import os
    import sys
    from app.core.config import Config
    from app.core import secretbox
    if not Config.PUBLIC_BASE_URL:
        return                        # dev/local chưa public — degrade như cũ
    if secretbox.enabled():
        return
    if os.getenv("ALLOW_PLAINTEXT_SECRETS", "").strip() == "1":
        log.warning("[secretbox] Chạy PUBLIC mà KHÔNG mã hoá at-rest "
                    "(ALLOW_PLAINTEXT_SECRETS=1) — token/session nằm thô trong DB!")
        return
    msg = ("PUBLIC_BASE_URL đã đặt nhưng THIẾU NOVACHAT_SECRET_KEY (hoặc thiếu "
           "thư viện cryptography) → bí mật kênh sẽ nằm PLAINTEXT trong SQLite. "
           "Đặt NOVACHAT_SECRET_KEY trong .env (vd: openssl rand -hex 32) rồi "
           "khởi động lại. Cố tình bỏ qua: ALLOW_PLAINTEXT_SECRETS=1.")
    log.critical(f"[secretbox] TỪ CHỐI KHỞI ĐỘNG: {msg}")
    print(f"❌ {msg}")
    sys.exit(1)


def run(app, host: str, port: int):
    _check_production_secrets()
    try:
        from waitress import serve
    except ImportError:
        log.warning("waitress chưa cài (pip install waitress) → dùng Flask dev server")
        app.run(host=host, port=port, threaded=True, use_reloader=False)
        return
    print(f"🚀 waitress (production WSGI) phục vụ tại http://{host}:{port} ({THREADS} luồng)")
    serve(app, host=host, port=port, threads=THREADS)
