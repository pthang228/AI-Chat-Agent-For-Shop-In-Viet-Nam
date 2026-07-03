import { useState, useEffect } from "react";
import { meta, loadFbSdk, fbLogin, buildScope } from "../metaApi.js";
import GuideBox from "./GuideBox.jsx";

// Màn "Kết nối Facebook" cho 1 app kênh Messenger/Instagram.
// Khách bấm đăng nhập FB → chọn Page → backend lưu token + subscribe webhook.
export default function MetaConnect() {
  const [cfg, setCfg] = useState(null);       // {app_id, configured} | "offline"
  const [pages, setPages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function refreshPages() {
    const r = await meta.pages();
    if (r.ok && Array.isArray(r.body)) setPages(r.body);
  }

  useEffect(() => {
    let alive = true;
    meta.config().then((r) => {
      if (!alive) return;
      if (r.ok && r.body) { setCfg(r.body); refreshPages(); }
      else setCfg("offline");
    });
    return () => { alive = false; };
  }, []);

  async function connect() {
    setMsg(""); setBusy(true);
    try {
      const FB = await loadFbSdk(cfg.app_id);
      const userToken = await fbLogin(FB, buildScope(cfg.enable_ig));
      const r = await meta.connect(userToken);
      if (r.ok && r.body?.ok) {
        const n = r.body.pages?.length || 0;
        setMsg(`✅ Đã kết nối ${n} Page` + (r.body.pages?.some(p => !p.subscribed) ? " (vài Page chưa subscribe được — kiểm tra quyền)" : ""));
        await refreshPages();
      } else {
        setMsg("❌ " + (r.body?.error || "Kết nối thất bại"));
      }
    } catch (e) {
      setMsg("❌ " + e.message);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(pageId) {
    if (!confirm("Ngắt kết nối Page này?")) return;
    await meta.removePage(pageId);
    refreshPages();
  }

  if (cfg === null) return <div className="connect"><div className="status muted">Đang tải…</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được máy chủ Meta (cổng 5006)</div>
        <p className="hint">Chạy <code>python scripts/run_meta.py</code> rồi tải lại trang.</p>
      </div>
    );

  if (!cfg.configured)
    return (
      <div className="connect">
        <div className="status warn">⚙️ Chưa cấu hình Meta App</div>
        <p className="hint">
          Cần điền <code>FB_APP_ID</code> và <code>FB_APP_SECRET</code> trong <code>.env</code> (đây là app
          của bạn — vendor — làm 1 lần cho mọi khách), rồi chạy lại máy chủ Meta.
        </p>
      </div>
    );

  return (
    <div className="connect">
      <div className="status ok">🔗 Kết nối Facebook{cfg.enable_ig ? " / Instagram" : ""}</div>

      <GuideBox
        title="📘 Hướng dẫn nhanh — Messenger / Instagram"
        steps={[
          { t: "Bước 1 · Đăng nhập Facebook", d: <>Bấm <b>Đăng nhập với Facebook</b> bên dưới → chọn đúng <b>Page của shop</b> bạn.</> },
          { t: "Bước 2 · Bot tự trả lời", d: <>Xong là bot tự trả lời tin nhắn của Page{cfg.enable_ig ? " và Instagram liên kết" : ""}. Bạn <b>không cần</b> đụng gì vào trang lập trình của Facebook.</> },
          { t: "Bước 3 · Quản lý khách", d: <>Xem & xử lý hội thoại từng khách ở tab <b>Khách hàng</b>.</> },
        ]}
        note={<>Vendor đã lo phần app Meta + webhook. Nếu tin nhắn chưa chạy về, báo vendor kiểm tra webhook giúp.</>}
      />
      {!cfg.enable_ig && (
        <p className="hint">
          ℹ️ Instagram đang <b>tắt</b>. Bật bằng cách đặt <code>FB_ENABLE_IG=true</code> trong <code>.env</code> sau
          khi app Meta đã thêm sản phẩm Instagram và có IG Professional liên kết Page, rồi chạy lại máy chủ Meta.
        </p>
      )}

      <button className="btn-fb" onClick={connect} disabled={busy}>
        <span className="fb-ico">f</span>{busy ? "Đang kết nối…" : "Đăng nhập với Facebook"}
      </button>
      {msg && <div className="savemsg" style={{ marginTop: 10 }}>{msg}</div>}

      <div className="pages">
        <h4>Page đã kết nối</h4>
        {pages.length === 0 ? (
          <p className="hint">Chưa có Page nào.</p>
        ) : (
          <ul className="page-list">
            {pages.map((p) => (
              <li key={p.page_id} className="page-row">
                <div>
                  <div className="page-name">{p.name || p.page_id}</div>
                  <div className="page-sub">
                    Messenger {p.has_ig ? `· Instagram @${p.ig_username || ""}` : ""}
                  </div>
                </div>
                <button className="btn-mini danger" onClick={() => disconnect(p.page_id)}>Ngắt</button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
