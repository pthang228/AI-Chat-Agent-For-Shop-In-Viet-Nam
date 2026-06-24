import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { login } from "../auth.js";

export default function Login() {
  const nav = useNavigate();
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [err, setErr] = useState("");

  function submit(e) {
    e.preventDefault();
    setErr("");
    try {
      login({ username, password });
      nav("/");
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <h1>🏠 Homestay Bot</h1>
        <p className="sub">Đăng nhập để quản lý các app của bạn</p>

        <label>Tên đăng nhập</label>
        <input value={username} onChange={(e) => setU(e.target.value)} placeholder="vd: haru_home" autoFocus />

        <label>Mật khẩu</label>
        <input type="password" value={password} onChange={(e) => setP(e.target.value)} placeholder="••••••" />

        {err && <div className="err">{err}</div>}

        <button className="btn-primary" type="submit">Đăng nhập</button>
        <p className="switch">Chưa có tài khoản? <Link to="/register">Đăng ký</Link></p>
      </form>
    </div>
  );
}
