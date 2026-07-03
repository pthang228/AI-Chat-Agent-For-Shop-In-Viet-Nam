import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser } from "../auth.js";
import { promptApi } from "../promptApi.js";
import { IcHome, IcBack } from "../components/icons.jsx";
import BackLink from "../components/BackLink.jsx";

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

// Trang "Dạy AI": shop dán link dữ liệu (không giới hạn) + hướng dẫn bằng lời
// → AI viết prompt cực chi tiết → shop duyệt → lưu → bot dùng ngay.
export default function PromptBuilder() {
  const nav = useNavigate();
  const user = currentUser();
  const hostName = user?.homestay || user?.username || "";

  const [cur, setCur] = useState(null);        // prompt đang dùng
  const [showCur, setShowCur] = useState(false);
  const [links, setLinks] = useState([""]);
  const [instructions, setInstructions] = useState("");
  const [draft, setDraft] = useState(null);    // prompt AI vừa tạo (chờ duyệt)
  const [sources, setSources] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    const r = await promptApi.current();
    if (r.status === 401) { nav("/login"); return; }
    if (r.ok) setCur(r.body);
    else setCur("offline");
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  function setLink(i, v) { setLinks((ls) => ls.map((x, j) => (j === i ? v : x))); }
  function addLink() { setLinks((ls) => [...ls, ""]); }
  function rmLink(i) { setLinks((ls) => (ls.length > 1 ? ls.filter((_, j) => j !== i) : [""])); }

  async function doGenerate() {
    setMsg(""); setDraft(null); setSources([]); setBusy(true);
    const r = await promptApi.generate(links.filter((l) => l.trim()), instructions);
    setBusy(false);
    if (r.ok && r.body?.draft) {
      setDraft(r.body.draft);
      setSources(r.body.sources || []);
      setMsg("");
    } else {
      setMsg("❌ " + (r.body?.error || (r.status === 0 ? "Không kết nối được máy chủ (5005)" : "Tạo prompt thất bại")));
    }
  }

  async function doApply() {
    if (!confirm("Dùng prompt này cho bot? Bot sẽ trả lời khách theo prompt mới NGAY LẬP TỨC trên mọi kênh.")) return;
    setMsg("");
    const r = await promptApi.apply(draft);
    if (r.ok) {
      setMsg("✅ Đã lưu — bot đang dùng prompt mới!");
      setDraft(null); setSources([]);
      load();
    } else {
      setMsg("❌ " + (r.body?.error || "Lưu thất bại"));
    }
  }

  async function doRestore() {
    if (!confirm("Quay về prompt MẶC ĐỊNH của hệ thống? (prompt tuỳ chỉnh hiện tại được sao lưu lại)")) return;
    const r = await promptApi.restoreDefault();
    if (r.ok) { setMsg("✅ Đã khôi phục prompt mặc định."); load(); }
  }

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">
          <Link to="/"><span className="brand-mini"><IcBack width={18} height={18} /></span> <span className="brand-mini" style={{ marginLeft: -4 }}><IcHome width={18} height={18} /></span> NovaChat</Link>
        </div>
        <div className="user">
          <Link to="/settings" className="user-pill" title="Cài đặt tài khoản">
            <span className="avatar">{initials(hostName)}</span>{hostName}
          </Link>
        </div>
      </header>

      <main className="content narrow" style={{ maxWidth: 780 }}>
        <BackLink />
        <div className="dash-head" style={{ marginBottom: 18 }}>
          <div>
            <div className="hello">Trợ lý AI</div>
            <h1 className="page-title">Dạy AI về shop của bạn</h1>
            <p className="page-sub">
              Dán link dữ liệu (bảng giá, trang giới thiệu, Google Docs công khai…) + viết hướng dẫn.
              AI sẽ tự soạn "bộ não" cực chi tiết cho bot — bạn duyệt rồi mới dùng.
            </p>
          </div>
        </div>

        {/* Prompt đang dùng */}
        {cur && cur !== "offline" && (
          <div className="panel set-card" style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <div>
                <b>Prompt đang dùng:</b>{" "}
                {cur.source === "custom"
                  ? <span className="badge bot">✨ Tuỳ chỉnh {cur.updated_at ? `(lưu ${new Date(cur.updated_at).toLocaleString("vi-VN")})` : ""}</span>
                  : <span className="badge stage">Mặc định hệ thống</span>}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn-mini" onClick={() => setShowCur((v) => !v)}>
                  {showCur ? "Ẩn nội dung" : "Xem nội dung"}
                </button>
                {cur.source === "custom" && (
                  <button className="btn-mini danger" onClick={doRestore}>Khôi phục mặc định</button>
                )}
              </div>
            </div>
            {showCur && <pre className="prompt-pre">{cur.prompt}</pre>}
          </div>
        )}
        {cur === "offline" && (
          <div className="empty"><p>⚠️ Chưa kết nối được máy chủ (cổng 5005).</p></div>
        )}

        {/* Bước 1: link dữ liệu */}
        <div className="panel set-card" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, marginBottom: 4 }}>1️⃣ Link dữ liệu của shop <span className="hint" style={{ fontWeight: 400 }}>(không giới hạn số link)</span></h3>
          <p className="hint">Bảng giá, trang Facebook/website, Google Docs/Sheets đã "Xuất bản lên web", bài giới thiệu… Link phải mở được công khai (không cần đăng nhập).</p>
          {links.map((l, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <input style={{ flex: 1 }} placeholder="https://…" value={l}
                     onChange={(e) => setLink(i, e.target.value)} />
              <button className="btn-mini danger" onClick={() => rmLink(i)} title="Xoá link này">✕</button>
            </div>
          ))}
          <button className="btn-mini" style={{ marginTop: 10 }} onClick={addLink}>＋ Thêm link</button>
        </div>

        {/* Bước 2: hướng dẫn */}
        <div className="panel set-card" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, marginBottom: 4 }}>2️⃣ Hướng dẫn cho AI</h3>
          <p className="hint">Viết như dặn nhân viên mới: giọng điệu, điều phải nói / không được nói, khuyến mãi, quy trình chốt khách…</p>
          <textarea
            className="chat-input" rows={6} style={{ width: "100%", marginTop: 8 }}
            placeholder={"Ví dụ:\n- Xưng 'em' với khách, thân thiện, dùng emoji\n- Phòng 201 đang giảm 10% tháng này\n- Không nhận thú cưng, không hút thuốc\n- Khách hỏi giảm giá thêm thì mời liên hệ chủ..."}
            value={instructions} onChange={(e) => setInstructions(e.target.value)}
          />
        </div>

        {/* Bước 3: tạo */}
        <button className="btn-primary" onClick={doGenerate} disabled={busy}
                style={{ width: "100%", marginBottom: 16 }}>
          {busy ? "🪄 AI đang đọc dữ liệu & soạn prompt… (20–60 giây)" : "🪄 Tạo prompt bằng AI"}
        </button>

        {msg && <div className="savemsg" style={{ marginBottom: 14 }}>{msg}</div>}

        {/* Kết quả link đã đọc */}
        {sources.length > 0 && (
          <div className="panel set-card" style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 14, marginBottom: 6 }}>Kết quả đọc link</h3>
            {sources.map((s, i) => (
              <div key={i} className="hint" style={{ padding: "2px 0" }}>
                {s.ok ? "✅" : "❌"} {s.url} {!s.ok && <i>— {s.error}</i>}
              </div>
            ))}
          </div>
        )}

        {/* Bước 4: duyệt */}
        {draft !== null && (
          <div className="panel set-card draft-box">
            <h3 style={{ fontSize: 16, marginBottom: 6 }}>3️⃣ Prompt AI đề xuất — kiểm tra rồi duyệt</h3>
            <p className="hint">Bạn sửa trực tiếp bên dưới được. Chỉ khi bấm <b>"✅ Dùng prompt này"</b> bot mới thay đổi.</p>
            <textarea className="chat-input prompt-draft" value={draft}
                      onChange={(e) => setDraft(e.target.value)} />
            <div className="hint" style={{ textAlign: "right" }}>{draft.length.toLocaleString("vi-VN")} ký tự</div>
            <div style={{ display: "flex", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
              <button className="btn-primary sm" onClick={doApply}>✅ Dùng prompt này</button>
              <button className="btn-outline sm" style={{ width: "auto" }} onClick={doGenerate} disabled={busy}>↺ Tạo lại</button>
              <button className="btn-mini danger" onClick={() => { setDraft(null); setSources([]); }}>Huỷ</button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
