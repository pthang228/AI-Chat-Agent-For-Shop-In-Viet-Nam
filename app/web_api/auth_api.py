"""
Auth THẬT cho web dashboard — thay localStorage (hb_users) bằng SQLite + token.

Gắn vào bridge (cổng 5005, tiến trình "não bộ" luôn chạy) qua register_auth_routes(app).
  POST /auth/register {username,password,homestay}      → {token, user}
  POST /auth/login    {username,password}               → {token, user}
  POST /auth/google   {credential}  (id_token từ GIS)   → {token, user}
       — token được XÁC THỰC PHÍA SERVER qua Google tokeninfo (không tin client).
  GET  /auth/me                    (Bearer)             → {user}
  POST /auth/logout                (Bearer)             → xoá token thiết bị này
  POST /auth/update   {homestay,email}      (Bearer)
  POST /auth/password {old_password,new_password} (Bearer)
  GET/POST/DELETE /auth/apps[...]  (Bearer)             → app kênh của user (thay hb_apps)

Mật khẩu: PBKDF2-HMAC-SHA256 (stdlib, 200k vòng, salt riêng từng user).
Token phiên: secrets.token_hex(32), mỗi thiết bị 1 token, hạn 30 ngày.
"""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta

import requests
from flask import request, jsonify

from app.core.db import get_db

log = logging.getLogger("auth_api")

PBKDF2_ITERS = 200_000
TOKEN_TTL_DAYS = 30
GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"


# ── Mật khẩu ────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                            bytes.fromhex(salt), PBKDF2_ITERS)
    return f"pbkdf2${PBKDF2_ITERS}${salt}${h.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, expect = stored.split("$")
        h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(h.hex(), expect)
    except Exception:
        return False


# ── Token phiên ─────────────────────────────────────────────────────

def _issue_token(db, username: str) -> str:
    token = secrets.token_hex(32)
    db.execute("INSERT INTO auth_tokens(token, username, created_at) VALUES (?,?,?)",
               (token, username, datetime.now().isoformat()))
    return token

def _user_for_token(db, token: str):
    if not token:
        return None
    rows = db.query("SELECT * FROM auth_tokens WHERE token=?", (token,))
    if not rows:
        return None
    created = datetime.fromisoformat(rows[0]["created_at"])
    if datetime.now() - created > timedelta(days=TOKEN_TTL_DAYS):
        db.execute("DELETE FROM auth_tokens WHERE token=?", (token,))
        return None
    u = db.query("SELECT * FROM users WHERE username=?", (rows[0]["username"],))
    return u[0] if u else None

def _bearer():
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.startswith("Bearer ") else ""


def current_username(db=None):
    """Username của token Bearer trong request hiện tại, hoặc None (chưa đăng nhập).
    Dùng ở các endpoint connect kênh để gắn kênh với chủ tài khoản."""
    from app.core.db import get_db
    u = _user_for_token(db or get_db(), _bearer())
    return u["username"] if u else None


def _public_user(row) -> dict:
    return {
        "username": row["username"],
        "homestay": row["homestay"],
        "email": row["email"] or row["username"],
        "provider": row["provider"],
        "picture": row["picture"],
        # Cho frontend biết acc Google thuần (chưa đặt mật khẩu) → ẩn form đổi pw
        "has_password": bool(row["password_hash"]),
    }


def register_auth_routes(app):
    db = get_db()

    def _auth_or_401():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        return u, None

    # ── Đăng ký / đăng nhập ─────────────────────────────────────────

    @app.route("/auth/register", methods=["POST"])
    def auth_register():
        from app.core import billing
        data = request.get_json(force=True, silent=True) or {}
        username = (data.get("username") or "").strip().lower()
        password = data.get("password") or ""
        homestay = (data.get("homestay") or "").strip()
        promo = (data.get("promo") or "").strip()
        if not username or not password:
            return {"ok": False, "error": "Vui lòng nhập email và mật khẩu"}, 400
        if len(password) < 4:
            return {"ok": False, "error": "Mật khẩu tối thiểu 4 ký tự"}, 400
        if promo and not billing._promo_ok(promo):
            return {"ok": False, "error": "Mã giới thiệu không đúng"}, 400
        if db.query("SELECT 1 FROM users WHERE username=?", (username,)):
            return {"ok": False, "error": "Tài khoản đã tồn tại"}, 409
        db.execute(
            "INSERT INTO users(username, password_hash, homestay, email, provider, picture, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (username, hash_password(password), homestay, "", "password", "",
             datetime.now().isoformat()))
        billing.ensure_billing(username, promo=promo)   # dùng thử 3 ngày (7 nếu có mã)
        token = _issue_token(db, username)
        u = db.query("SELECT * FROM users WHERE username=?", (username,))[0]
        log.info(f"[auth] đăng ký {username}")
        return {"ok": True, "token": token, "user": _public_user(u)}

    @app.route("/auth/login", methods=["POST"])
    def auth_login():
        data = request.get_json(force=True, silent=True) or {}
        username = (data.get("username") or "").strip().lower()
        password = data.get("password") or ""
        rows = db.query("SELECT * FROM users WHERE username=?", (username,))
        if not rows:
            return {"ok": False, "error": "Sai email hoặc mật khẩu", "code": "not_found"}, 401
        u = rows[0]
        if not u["password_hash"] or not verify_password(password, u["password_hash"]):
            return {"ok": False, "error": "Sai email hoặc mật khẩu"}, 401
        token = _issue_token(db, username)
        return {"ok": True, "token": token, "user": _public_user(u)}

    @app.route("/auth/google", methods=["POST"])
    def auth_google():
        """Nhận id_token (credential) từ Google Identity Services, xác thực
        PHÍA SERVER qua Google tokeninfo rồi mới cấp phiên."""
        data = request.get_json(force=True, silent=True) or {}
        credential = (data.get("credential") or "").strip()
        if not credential:
            return {"ok": False, "error": "Thiếu credential Google"}, 400
        try:
            r = requests.get(GOOGLE_TOKENINFO, params={"id_token": credential}, timeout=10)
        except Exception as e:
            return {"ok": False, "error": f"Không gọi được Google để xác thực: {e}"}, 502
        if r.status_code != 200:
            return {"ok": False, "error": "Google từ chối token đăng nhập"}, 401
        info = r.json()
        email = (info.get("email") or "").strip().lower()
        if not email or info.get("email_verified") not in ("true", True):
            return {"ok": False, "error": "Email Google chưa xác minh"}, 401
        name = info.get("name") or ""
        picture = info.get("picture") or ""
        rows = db.query("SELECT * FROM users WHERE username=?", (email,))
        if not rows:
            db.execute(
                "INSERT INTO users(username, password_hash, homestay, email, provider, picture, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (email, None, name, email, "google", picture, datetime.now().isoformat()))
        else:
            db.execute("UPDATE users SET picture=?, provider=CASE WHEN provider='' THEN 'google' ELSE provider END "
                       "WHERE username=?", (picture, email))
        from app.core import billing
        billing.ensure_billing(email)   # user mới → dùng thử 3 ngày (nhập mã sau ở trang Gói dịch vụ)
        token = _issue_token(db, email)
        u = db.query("SELECT * FROM users WHERE username=?", (email,))[0]
        log.info(f"[auth] Google login {email}")
        return {"ok": True, "token": token, "user": _public_user(u)}

    # ── Phiên / hồ sơ ───────────────────────────────────────────────

    @app.route("/auth/me")
    def auth_me():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, "user": _public_user(u)}

    @app.route("/auth/logout", methods=["POST"])
    def auth_logout():
        token = _bearer()
        if token:
            db.execute("DELETE FROM auth_tokens WHERE token=?", (token,))
        return {"ok": True}

    @app.route("/auth/update", methods=["POST"])
    def auth_update():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        homestay = data.get("homestay")
        email = data.get("email")
        if email is not None:
            email = (email or "").strip()
            if email and "@" not in email:
                return {"ok": False, "error": "Email không hợp lệ"}, 400
            db.execute("UPDATE users SET email=? WHERE username=?", (email, u["username"]))
        if homestay is not None:
            db.execute("UPDATE users SET homestay=? WHERE username=?",
                       ((homestay or "").strip(), u["username"]))
        u2 = db.query("SELECT * FROM users WHERE username=?", (u["username"],))[0]
        return {"ok": True, "user": _public_user(u2)}

    @app.route("/auth/password", methods=["POST"])
    def auth_password():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        old_pw = data.get("old_password") or ""
        new_pw = data.get("new_password") or ""
        if len(new_pw) < 4:
            return {"ok": False, "error": "Mật khẩu mới tối thiểu 4 ký tự"}, 400
        # Acc Google chưa có mật khẩu → cho ĐẶT mật khẩu lần đầu (không cần pw cũ)
        if u["password_hash"] and not verify_password(old_pw, u["password_hash"]):
            return {"ok": False, "error": "Mật khẩu hiện tại không đúng"}, 401
        db.execute("UPDATE users SET password_hash=? WHERE username=?",
                   (hash_password(new_pw), u["username"]))
        return {"ok": True}

    # ── App (kênh chat) của user — thay localStorage hb_apps ────────

    @app.route("/auth/apps")
    def auth_apps():
        u, err = _auth_or_401()
        if err:
            return err
        rows = db.query(
            "SELECT id, name, channel, created_at FROM user_apps WHERE username=? ORDER BY created_at",
            (u["username"],))
        return jsonify([
            {"id": r["id"], "name": r["name"], "channel": r["channel"], "createdAt": r["created_at"]}
            for r in rows
        ])

    @app.route("/auth/apps", methods=["POST"])
    def auth_apps_add():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        name = (data.get("name") or "").strip() or "App chưa đặt tên"
        channel = (data.get("channel") or "zalo").strip()
        # Chống trùng khi migrate từ localStorage chạy lại
        dup = db.query(
            "SELECT id FROM user_apps WHERE username=? AND name=? AND channel=?",
            (u["username"], name, channel))
        if dup:
            return {"ok": True, "app": {"id": dup[0]["id"], "name": name, "channel": channel},
                    "duplicated": True}
        app_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO user_apps(id, username, name, channel, created_at) VALUES (?,?,?,?,?)",
            (app_id, u["username"], name, channel, datetime.now().isoformat()))
        return {"ok": True, "app": {"id": app_id, "name": name, "channel": channel}}

    @app.route("/auth/apps/<app_id>", methods=["DELETE"])
    def auth_apps_remove(app_id):
        u, err = _auth_or_401()
        if err:
            return err
        db.execute("DELETE FROM user_apps WHERE username=? AND id=?", (u["username"], app_id))
        return {"ok": True}

    return app
