import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { register } from "../auth.js";

export default function Register() {
  const nav = useNavigate();
  const [homestay, setH] = useState("");
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [confirm, setC] = useState("");
  const [err, setErr] = useState("");

  function submit(e) {
    e.preventDefault();
    setErr("");
    if (password !== confirm) { setErr("Mật khẩu nhập lại không khớp"); return; }
    try {
      register({ username, password, homestay });
      nav("/");
    } catch (e) {
      setErr(e.message);
    }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <h1>🏠 Đăng ký</h1>
        <p className="sub">Tạo tài khoản để bắt đầu</p>

        <label>Tên homestay / cơ sở</label>
        <input value={homestay} onChange={(e) => setH(e.target.value)} placeholder="vd: Haru Staycation" autoFocus />

        <label>Tên đăng nhập</label>
        <input value={username} onChange={(e) => setU(e.target.value)} placeholder="vd: haru_home" />

        <label>Mật khẩu</label>
        <input type="password" value={password} onChange={(e) => setP(e.target.value)} placeholder="tối thiểu 4 ký tự" />

        <label>Nhập lại mật khẩu</label>
        <input type="password" value={confirm} onChange={(e) => setC(e.target.value)} placeholder="••••••" />

        {err && <div className="err">{err}</div>}

        <button className="btn-primary" type="submit">Đăng ký</button>
        <p className="switch">Đã có tài khoản? <Link to="/login">Đăng nhập</Link></p>
      </form>
    </div>
  );
}
