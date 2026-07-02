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


def run(app, host: str, port: int):
    try:
        from waitress import serve
    except ImportError:
        log.warning("waitress chưa cài (pip install waitress) → dùng Flask dev server")
        app.run(host=host, port=port, threaded=True, use_reloader=False)
        return
    print(f"🚀 waitress (production WSGI) phục vụ tại http://{host}:{port} ({THREADS} luồng)")
    serve(app, host=host, port=port, threads=THREADS)
