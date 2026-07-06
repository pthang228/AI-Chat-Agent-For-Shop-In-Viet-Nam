"""
Dashboard web cho chủ nhà — xem hội thoại, bật/tắt bot từng khách.
Chạy tích hợp trong main.py (daemon thread).

Truy cập: http://localhost:5000  (hoặc cổng DASHBOARD_PORT trong .env)
"""

import hashlib
import threading
from datetime import datetime
from functools import wraps

from flask import Flask, render_template_string, redirect, request, make_response

from app.channels.zalo_cookie import bot as bot_module   # dùng module-level reference để luôn thấy bot_module.conv_manager mới nhất
from app.core.config import Config

app = Flask(__name__)
app.secret_key = hashlib.md5(b"haru-mochi-dashboard").hexdigest()

# ── Auth helpers ──────────────────────────────────────────────────────────────

def _token(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def _is_authed() -> bool:
    if not Config.DASHBOARD_PASSWORD:
        return True   # Không đặt mật khẩu → bỏ qua xác thực
    return request.cookies.get("dash_auth") == _token(Config.DASHBOARD_PASSWORD)

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not _is_authed():
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper

# ── Template helpers ──────────────────────────────────────────────────────────

def _rel_time(dt: datetime) -> str:
    """Trả về chuỗi thời gian tương đối: '5 phút trước'."""
    diff = (datetime.now() - dt).total_seconds()
    if diff < 60:
        return f"{int(diff)} giây trước"
    if diff < 3600:
        return f"{int(diff // 60)} phút trước"
    if diff < 86400:
        return f"{int(diff // 3600)} giờ trước"
    return f"{int(diff // 86400)} ngày trước"

# ── HTML templates ────────────────────────────────────────────────────────────

BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f0f2f5; color: #1a1a1a; font-size: 14px; }
.navbar { background: #0068ff; color: #fff; padding: 12px 16px;
          display: flex; align-items: center; justify-content: space-between; }
.navbar h1 { font-size: 17px; font-weight: 600; }
.navbar a { color: #fff; text-decoration: none; font-size: 13px; opacity: .85; }
.container { max-width: 900px; margin: 0 auto; padding: 16px; }
.card { background: #fff; border-radius: 12px; padding: 14px 16px;
        margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.12); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 20px;
         font-size: 11px; font-weight: 600; }
.badge-bot  { background: #e6f4ea; color: #1a7f37; }
.badge-owner{ background: #fff0f0; color: #c0392b; }
.badge-stage{ background: #eef2ff; color: #3730a3; }
.btn { display: inline-block; padding: 6px 14px; border-radius: 8px;
       font-size: 13px; font-weight: 500; text-decoration: none; cursor: pointer;
       border: none; transition: opacity .15s; }
.btn:hover { opacity: .85; }
.btn-green  { background: #2ecc71; color: #fff; }
.btn-red    { background: #e74c3c; color: #fff; }
.btn-gray   { background: #bdc3c7; color: #fff; }
.btn-blue   { background: #0068ff; color: #fff; }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.meta { color: #666; font-size: 12px; margin-top: 4px; }
.preview { color: #444; margin-top: 6px; overflow: hidden;
           text-overflow: ellipsis; white-space: nowrap; }
.empty { text-align: center; color: #999; padding: 48px 16px; }
/* Chat bubbles */
.chat { padding: 8px 0; }
.msg { max-width: 78%; margin: 4px 0; padding: 8px 12px;
       border-radius: 12px; line-height: 1.45; word-break: break-word; }
.msg-user { background: #e9ecef; border-radius: 12px 12px 12px 2px; }
.msg-bot  { background: #0068ff; color: #fff; margin-left: auto;
            border-radius: 12px 12px 2px 12px; }
.msg-sys  { background: #fff3cd; font-size: 11px; color: #856404;
            border-radius: 6px; max-width: 100%; text-align: center;
            margin: 4px auto; }
.msg-wrap { display: flex; flex-direction: column; }
.msg-time { font-size: 10px; color: #999; margin-top: 2px; padding: 0 4px; }
.msg-time.right { text-align: right; }
/* Login */
.login-box { max-width: 360px; margin: 80px auto; }
.login-box h2 { text-align: center; margin-bottom: 24px; color: #0068ff; }
input[type=password] { width: 100%; padding: 10px 14px; border: 1px solid #ddd;
                        border-radius: 8px; font-size: 15px; margin-bottom: 12px; }
"""

LOGIN_HTML = """<!doctype html><html lang=vi><head>
<meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Đăng nhập — Shop Dashboard</title>
<style>{{ css }}</style></head><body>
<div class=container><div class=login-box>
  <h2>🏠 Shop Dashboard</h2>
  <div class=card>
    <form method=post>
      <input type=password name=password placeholder='Mật khẩu' autofocus>
      {% if error %}<p style='color:red;font-size:13px;margin-bottom:8px'>{{ error }}</p>{% endif %}
      <button class='btn btn-blue' style='width:100%'>Đăng nhập</button>
    </form>
  </div>
</div></div></body></html>"""

INDEX_HTML = """<!doctype html><html lang=vi><head>
<meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<meta http-equiv=refresh content=30>
<title>Dashboard — Shop Bot</title>
<style>{{ css }}</style></head><body>
<div class=navbar>
  <h1>🏠 Shop Bot</h1>
  <a href=/logout>Đăng xuất</a>
</div>
<div class=container>
  <p style='color:#666;font-size:12px;margin-bottom:12px'>
    {{ total }} cuộc hội thoại — tự làm mới sau 30 giây</p>

  {% if not sessions %}
    <div class=empty>Chưa có khách nào nhắn tin.</div>
  {% endif %}

  {% for s in sessions %}
  <div class=card>
    <div class=row>
      <strong style='font-size:13px'>{{ s.uid_short }}</strong>
      {% if s.owner_active %}
        <span class='badge badge-owner'>⛔ Chủ đang xử lý</span>
      {% else %}
        <span class='badge badge-bot'>🤖 Bot đang trả lời</span>
      {% endif %}
      <span class='badge badge-stage'>{{ s.stage }}</span>
      <span class=meta style='margin-left:auto'>{{ s.rel_time }}</span>
    </div>

    {% if s.checkin %}
    <div class=meta>📅 Check-in: {{ s.checkin }}{% if s.checkout and s.checkout != s.checkin %} → {{ s.checkout }}{% endif %}</div>
    {% endif %}

    {% if s.last_msg %}
    <div class=preview>💬 {{ s.last_msg }}</div>
    {% endif %}

    <div class=row style='margin-top:10px'>
      <a href='/conv/{{ s.user_id }}' class='btn btn-blue'>Xem chat</a>
      {% if s.owner_active %}
        <a href='/bot/on/{{ s.user_id }}' class='btn btn-green'>▶ Bật bot lại</a>
      {% else %}
        <a href='/bot/off/{{ s.user_id }}' class='btn btn-red'>⏸ Tắt bot</a>
      {% endif %}
      <a href='/reset/{{ s.user_id }}' class='btn btn-gray'
         onclick="return confirm('Reset hội thoại của khách này?')">🗑 Reset</a>
    </div>
  </div>
  {% endfor %}
</div></body></html>"""

CONV_HTML = """<!doctype html><html lang=vi><head>
<meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Chat — {{ uid_short }}</title>
<style>{{ css }}</style></head><body>
<div class=navbar>
  <h1>💬 {{ uid_short }}</h1>
  <a href=/>← Danh sách</a>
</div>
<div class=container>
  <div class=card style='margin-bottom:12px'>
    <div class=row>
      {% if owner_active %}
        <span class='badge badge-owner'>⛔ Chủ đang xử lý</span>
        <a href='/bot/on/{{ user_id }}' class='btn btn-green'>▶ Bật bot lại</a>
      {% else %}
        <span class='badge badge-bot'>🤖 Bot đang trả lời</span>
        <a href='/bot/off/{{ user_id }}' class='btn btn-red'>⏸ Tắt bot</a>
      {% endif %}
      {% if checkin %}<span class=meta>📅 {{ checkin }}</span>{% endif %}
      <a href='/reset/{{ user_id }}' class='btn btn-gray'
         onclick="return confirm('Reset hội thoại này?')" style='margin-left:auto'>🗑 Reset</a>
    </div>
  </div>

  {% if not messages %}
    <div class=empty>Chưa có tin nhắn nào.</div>
  {% endif %}

  {% for msg in messages %}
    {% if msg.role == 'user' %}
    <div class=msg-wrap>
      <div class='msg msg-user'>{{ msg.content }}</div>
      <span class=msg-time>Khách</span>
    </div>
    {% elif msg.role == 'assistant' %}
    <div class=msg-wrap>
      <div class='msg msg-bot'>{{ msg.content }}</div>
      <span class='msg-time right'>Bot</span>
    </div>
    {% else %}
    <div class=msg-wrap>
      <div class='msg msg-sys'>{{ msg.content }}</div>
    </div>
    {% endif %}
  {% endfor %}
  <div style='height:24px'></div>
</div></body></html>"""

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == Config.DASHBOARD_PASSWORD:
            resp = make_response(redirect("/"))
            resp.set_cookie("dash_auth", _token(pw), max_age=86400 * 7, httponly=True)
            return resp
        return render_template_string(LOGIN_HTML, css=BASE_CSS, error="Sai mật khẩu!")
    return render_template_string(LOGIN_HTML, css=BASE_CSS, error=None)


@app.route("/logout")
def logout():
    resp = make_response(redirect("/login"))
    resp.delete_cookie("dash_auth")
    return resp


@app.route("/")
@login_required
def index():
    rows = []
    for uid, conv in list(bot_module.conv_manager._sessions.items()):
        last_msg = ""
        for m in reversed(conv.messages):
            if m.get("role") in ("user", "assistant") and not m["content"].startswith("[HỆ THỐNG]"):
                last_msg = m["content"][:80]
                break
        rows.append({
            "user_id"     : uid,
            "uid_short"   : uid[-10:],
            "owner_active": conv.is_owner_active(),
            "stage"       : conv.stage,
            "checkin"     : conv.checkin,
            "checkout"    : conv.checkout,
            "last_msg"    : last_msg,
            "rel_time"    : _rel_time(conv.last_updated),
            "last_updated": conv.last_updated,
        })
    rows.sort(key=lambda x: x["last_updated"], reverse=True)
    return render_template_string(INDEX_HTML, css=BASE_CSS,
                                  sessions=rows, total=len(rows))


@app.route("/conv/<user_id>")
@login_required
def conversation(user_id):
    conv = bot_module.conv_manager._sessions.get(user_id)
    if not conv:
        return "Không tìm thấy hội thoại.", 404
    # Lọc bỏ tin nhắn hệ thống nội bộ
    msgs = [m for m in conv.messages if not m.get("content", "").startswith("[HỆ THỐNG]")]
    return render_template_string(
        CONV_HTML, css=BASE_CSS,
        user_id=user_id,
        uid_short=user_id[-10:],
        owner_active=conv.is_owner_active(),
        checkin=conv.checkin,
        messages=msgs,
    )


@app.route("/bot/on/<user_id>")
@login_required
def bot_on(user_id):
    """Bật bot lại cho khách (tắt owner_active)."""
    conv = bot_module.conv_manager.get(user_id)
    conv.set_owner_active(False)
    bot_module.conv_manager.save()
    return redirect(f"/conv/{user_id}")


@app.route("/bot/off/<user_id>")
@login_required
def bot_off(user_id):
    """Tắt bot cho khách (bật owner_active)."""
    conv = bot_module.conv_manager.get(user_id)
    conv.set_owner_active(True)
    bot_module.conv_manager.save()
    return redirect(f"/conv/{user_id}")


@app.route("/reset/<user_id>")
@login_required
def reset_conv(user_id):
    """Xóa toàn bộ lịch sử hội thoại của khách."""
    bot_module.conv_manager.reset(user_id)
    return redirect("/")


# ── Start helper ──────────────────────────────────────────────────────────────

def start_dashboard(port: int = None):
    """Khởi động Flask trong daemon thread — gọi từ main.py."""
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)   # Tắt request log của Flask
    app.run(
        host="0.0.0.0",
        port=port or Config.DASHBOARD_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
