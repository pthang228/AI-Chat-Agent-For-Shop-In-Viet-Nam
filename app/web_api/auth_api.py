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

def _blocked(db, row) -> bool:
    """Shop bị QUẢN TRỊ NỀN TẢNG chặn? Staff bị chặn theo CHỦ workspace.
    DB cũ chưa có cột blocked → coi như không chặn."""
    try:
        if ("blocked" in row.keys()) and row["blocked"]:
            return True
        own = (row["owner_username"] if "owner_username" in row.keys() else "") or ""
        if own and role_of(row) == "staff":
            r = db.query("SELECT blocked FROM users WHERE username=?", (own,))
            return bool(r) and bool(r[0]["blocked"])
    except Exception:
        pass
    return False


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
    if u and _blocked(db, u[0]):
        return None   # shop bị chặn → token đang sống cũng vô hiệu
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


# ── TEAM: vai trò + workspace ────────────────────────────────────────
# role: owner (chủ shop, toàn quyền) | staff (nhân viên — chỉ hộp thư/khách/đơn).
# Staff thuộc workspace của owner_username: billing/kênh/app đều tính theo CHỦ.

def role_of(row) -> str:
    """Vai trò của user row — DB cũ chưa có cột role → coi là owner."""
    try:
        return (row["role"] if "role" in row.keys() else "") or "owner"
    except Exception:
        return "owner"


def workspace_of(row) -> str:
    """Username CHỦ workspace: staff → owner_username, owner → chính mình."""
    try:
        own = (row["owner_username"] if "owner_username" in row.keys() else "") or ""
    except Exception:
        own = ""
    return own if (role_of(row) == "staff" and own) else row["username"]


def current_workspace(db=None):
    """Username chủ workspace của request hiện tại (staff quy về chủ), hoặc None."""
    from app.core.db import get_db
    u = _user_for_token(db or get_db(), _bearer())
    return workspace_of(u) if u else None


def _public_user(row) -> dict:
    # platform_admin: acc role='admin' chính danh HOẶC chủ nền tảng đầu tiên —
    # frontend hiện link /admin. Import trễ tránh vòng; lỗi → False.
    try:
        from app.core import tenant
        is_platform = tenant.is_platform_admin(row["username"])
    except Exception:
        is_platform = False
    return {
        "username": row["username"],
        "homestay": row["homestay"],
        "email": row["email"] or row["username"],
        "provider": row["provider"],
        "picture": row["picture"],
        # Cho frontend biết acc Google thuần (chưa đặt mật khẩu) → ẩn form đổi pw
        "has_password": bool(row["password_hash"]),
        "role": role_of(row),
        "workspace": workspace_of(row),
        "platform_admin": is_platform,
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
        if _blocked(db, u):
            return {"ok": False, "error": "Tài khoản đã bị khoá bởi quản trị nền tảng — "
                    "liên hệ hỗ trợ để mở lại", "code": "blocked"}, 403
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
        u = db.query("SELECT * FROM users WHERE username=?", (email,))[0]
        if _blocked(db, u):
            return {"ok": False, "error": "Tài khoản đã bị khoá bởi quản trị nền tảng — "
                    "liên hệ hỗ trợ để mở lại", "code": "blocked"}, 403
        token = _issue_token(db, email)
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

    # ── TEAM: quản lý nhân viên (chỉ CHỦ) ───────────────────────────

    def _owner_or_403():
        u, err = _auth_or_401()
        if err:
            return None, err
        if role_of(u) != "owner":
            return None, ({"ok": False, "error": "Chỉ chủ shop mới quản lý nhân viên"}, 403)
        return u, None

    def _member_row(r):
        return {"username": r["username"], "name": r["homestay"],
                "role": role_of(r), "created_at": r["created_at"]}

    @app.route("/team")
    def team_list():
        u, err = _owner_or_403()
        if err:
            return err
        rows = db.query(
            "SELECT * FROM users WHERE owner_username=? ORDER BY created_at",
            (u["username"],))
        return jsonify([_member_row(r) for r in rows])

    @app.route("/team", methods=["POST"])
    def team_add():
        u, err = _owner_or_403()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        name = (data.get("name") or "").strip()
        password = data.get("password") or ""
        if not email or "@" not in email:
            return {"ok": False, "error": "Email nhân viên không hợp lệ"}, 400
        if len(password) < 4:
            return {"ok": False, "error": "Mật khẩu tối thiểu 4 ký tự"}, 400
        if db.query("SELECT 1 FROM users WHERE username=?", (email,)):
            return {"ok": False, "error": "Email này đã có tài khoản"}, 409
        # Staff KHÔNG có billing riêng — quota/gói tính theo chủ workspace
        db.execute(
            "INSERT INTO users(username, password_hash, homestay, email, provider, picture,"
            " role, owner_username, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (email, hash_password(password), name or email, "", "password", "",
             "staff", u["username"], datetime.now().isoformat()))
        log.info(f"[team] {u['username']} thêm nhân viên {email}")
        r = db.query("SELECT * FROM users WHERE username=?", (email,))[0]
        return {"ok": True, "member": _member_row(r)}

    def _member_of(owner_username, member):
        rows = db.query("SELECT * FROM users WHERE username=? AND owner_username=?",
                        ((member or "").strip().lower(), owner_username))
        return rows[0] if rows else None

    @app.route("/team/<member>", methods=["PATCH"])
    def team_update(member):
        u, err = _owner_or_403()
        if err:
            return err
        m = _member_of(u["username"], member)
        if m is None:
            return {"ok": False, "error": "Không tìm thấy nhân viên này"}, 404
        data = request.get_json(force=True, silent=True) or {}
        name = data.get("name")
        password = data.get("password")
        if name is not None:
            db.execute("UPDATE users SET homestay=? WHERE username=?",
                       ((name or "").strip(), m["username"]))
        if password:
            if len(password) < 4:
                return {"ok": False, "error": "Mật khẩu tối thiểu 4 ký tự"}, 400
            db.execute("UPDATE users SET password_hash=? WHERE username=?",
                       (hash_password(password), m["username"]))
            # Đổi mật khẩu → huỷ mọi phiên đang đăng nhập của nhân viên đó
            db.execute("DELETE FROM auth_tokens WHERE username=?", (m["username"],))
        r = db.query("SELECT * FROM users WHERE username=?", (m["username"],))[0]
        return {"ok": True, "member": _member_row(r)}

    @app.route("/team/<member>", methods=["DELETE"])
    def team_remove(member):
        u, err = _owner_or_403()
        if err:
            return err
        m = _member_of(u["username"], member)
        if m is None:
            return {"ok": False, "error": "Không tìm thấy nhân viên này"}, 404
        db.execute("DELETE FROM auth_tokens WHERE username=?", (m["username"],))
        db.execute("DELETE FROM users WHERE username=?", (m["username"],))
        log.info(f"[team] {u['username']} xoá nhân viên {m['username']}")
        return {"ok": True}

    @app.route("/teammates")
    def teammates():
        """Danh sách thành viên workspace (chủ + nhân viên) — CẢ staff đọc được
        (khác /team owner-only) để hiện dropdown phân công hội thoại."""
        u, err = _auth_or_401()
        if err:
            return err
        ws = workspace_of(u)
        out = []
        owner_rows = db.query("SELECT * FROM users WHERE username=?", (ws,))
        if owner_rows:
            r = owner_rows[0]
            out.append({"username": r["username"], "name": r["homestay"] or r["username"],
                        "role": "owner"})
        for r in db.query("SELECT * FROM users WHERE owner_username=? ORDER BY created_at", (ws,)):
            out.append({"username": r["username"], "name": r["homestay"] or r["username"],
                        "role": role_of(r)})
        return jsonify(out)

    # ── App (kênh chat) của user — thay localStorage hb_apps ────────

    @app.route("/auth/apps")
    def auth_apps():
        u, err = _auth_or_401()
        if err:
            return err
        # Staff xem app của CHỦ workspace (chỉ đọc — thêm/xoá bị chặn bên dưới)
        rows = db.query(
            "SELECT id, name, channel, created_at, ai_model FROM user_apps "
            "WHERE username=? ORDER BY created_at",
            (workspace_of(u),))
        return jsonify([
            {"id": r["id"], "name": r["name"], "channel": r["channel"],
             "createdAt": r["created_at"], "ai_model": r["ai_model"] or ""}
            for r in rows
        ])

    @app.route("/auth/apps", methods=["POST"])
    def auth_apps_add():
        u, err = _auth_or_401()
        if err:
            return err
        if role_of(u) != "owner":
            return {"ok": False, "error": "Nhân viên không được thêm kênh"}, 403
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

    @app.route("/auth/apps/<app_id>/ai-model", methods=["POST"])
    def auth_apps_ai_model(app_id):
        """Chọn MÔ HÌNH AI riêng cho 1 chatbot (per-app) — rỗng = xoá override,
        bot dùng lại model chung của shop (billing.ai_model)."""
        u, err = _auth_or_401()
        if err:
            return err
        if role_of(u) != "owner":
            return {"ok": False, "error": "Nhân viên không được đổi model"}, 403
        from app.core import ai_models
        key = ((request.get_json(force=True, silent=True) or {}).get("model") or "").strip()
        if key and key not in ai_models.CATALOG:
            return {"ok": False, "error": "Mô hình không hợp lệ"}, 400
        if key and key not in ai_models.available_keys():
            return {"ok": False, "error": "Mô hình này máy chủ chưa cấu hình API key"}, 400
        # Chỉ chủ workspace sửa app CỦA MÌNH (giống DELETE bên dưới)
        if not db.query("SELECT 1 FROM user_apps WHERE username=? AND id=?",
                        (u["username"], app_id)):
            return {"ok": False, "error": "Không tìm thấy app"}, 404
        db.execute("UPDATE user_apps SET ai_model=? WHERE username=? AND id=?",
                   (key, u["username"], app_id))
        log.info(f"[auth] {u['username']} đổi model app {app_id} → '{key or '(mức shop)'}'")
        return {"ok": True, "ai_model": key}

    @app.route("/auth/apps/<app_id>", methods=["DELETE"])
    def auth_apps_remove(app_id):
        u, err = _auth_or_401()
        if err:
            return err
        if role_of(u) != "owner":
            return {"ok": False, "error": "Nhân viên không được xoá kênh"}, 403
        db.execute("DELETE FROM user_apps WHERE username=? AND id=?", (u["username"], app_id))
        return {"ok": True}

    return app
