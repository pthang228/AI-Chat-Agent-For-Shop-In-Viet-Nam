import { useState, useEffect } from "react";
import { tiktok } from "../tiktokApi.js";
import GuideBox from "./GuideBox.jsx";

// Kết nối TikTok ĐA KHÁCH trong web: dán access token TikTok Business + business ID.
export default function TikTokConnect() {
  const [cfg, setCfg] = useState(null);   // {verify_token,...} | "offline"
  const [accounts, setAccounts] = useState([]);
  const [token, setToken] = useState("");
  const [bizId, setBizId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function refreshAccounts() {
    const r = await tiktok.accounts();
    if (r.ok && Array.isArray(r.body)) setAccounts(r.body);
  }

  useEffect(() => {
    tiktok.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshAccounts(); }
      else setCfg("offline");
    });
  }, []);

  async function connect() {
    if (!token.trim() || !bizId.trim()) {
      setMsg("❌ Cần cả access token và Business ID.");
      return;
    }
    setBusy(true); setMsg("");
    const r = await tiktok.connect(token.trim(), bizId.trim(), name.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(r.body.verified
        ? `✅ Đã kết nối & xác thực account ${r.body.account.name || r.body.account.business_id}`
        : `✅ Đã lưu account ${r.body.account.business_id} (chưa xác thực được với TikTok — token sẽ dùng khi API sẵn sàng)`);
      setToken(""); setBizId(""); setName("");
      refreshAccounts();
    } else {
      setMsg("❌ " + (r.body?.error || "Kết nối thất bại"));
    }
  }

  async function disconnect(a) {
    if (!confirm(
      `Ngắt kết nối account ${a.name || a.business_id}?\n\n` +
      `Token sẽ bị xoá khỏi hệ thống. Lịch sử hội thoại với khách vẫn còn lưu.\n` +
      `Bạn có thể kết nối lại bất kỳ lúc nào bằng cách dán token mới.`
    )) return;
    await tiktok.removeAccount(a.business_id);
    refreshAccounts();
  }

  async function toggleAccount(a) {
    await tiktok.accountToggle(a.business_id, !a.bot_enabled);
    refreshAccounts();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">Đang tải…</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được máy chủ TikTok (cổng 5008)</div>
        <p className="hint">Chạy <code>python -m app.main_tiktok</code> rồi tải lại trang.</p>
      </div>
    );

  const webhookUrl = (cfg.public_base_url || "<PUBLIC_BASE_URL>") + (cfg.webhook_path || "/tiktok/webhook");

  return (
    <div className="connect">
      <div className="status ok">🎵 Kết nối TikTok</div>

      <GuideBox
        title="📘 Hướng dẫn kết nối — TikTok"
        steps={[
          { t: "Bước 1 · Tài khoản TikTok Business", d: <>Tài khoản TikTok của homestay phải chuyển sang <b>Business Account</b> (Cài đặt → Tài khoản → Chuyển sang tài khoản Doanh nghiệp — miễn phí).</> },
          { t: "Bước 2 · Lấy access token", d: <>Vào <b>business.tiktok.com</b> / TikTok for Developers → tạo app (hoặc dùng app của nhà cung cấp) → cấp quyền <b>Business Messaging</b> → copy <b>Access Token</b> và <b>Business ID</b> của tài khoản.</> },
          { t: "Bước 3 · Dán & kết nối", d: <>Dán token + Business ID vào ô dưới, bấm <b>Kết nối</b>. Sau đó khai webhook nhận tin: <code>{webhookUrl}</code> (verify token: <code>{cfg.verify_token}</code>).</> },
          { t: "Bước 4 · Đặt chủ nhà", d: <>Chủ nhắn thử account TikTok 1 tin → vào tab <b>Khách hàng</b> → mở hội thoại của chủ → bấm <b>⭐ Đặt làm chủ</b> để nhận tin báo khi khách chốt phòng.</> },
        ]}
        note={
          <>
            ⚠️ <b>Lưu ý:</b> API nhắn tin TikTok (Business Messaging) hiện TikTok chỉ mở cho
            app được duyệt. Chưa có token thật thì hệ thống vẫn lưu cấu hình và chạy
            chế độ thử nghiệm — khi TikTok duyệt là dùng được ngay, không phải sửa gì.
          </>
        }
      />

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
        <input
          placeholder="Dán Access Token TikTok Business…"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder="Business ID (bắt buộc)"
            value={bizId}
            onChange={(e) => setBizId(e.target.value)}
          />
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder="Tên hiển thị (tuỳ chọn)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button className="btn-primary sm" onClick={connect} disabled={busy}>
            {busy ? "Đang kết nối…" : "Kết nối"}
          </button>
        </div>
      </div>
      {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}

      <div className="pages" style={{ marginTop: 14 }}>
        <h4>Account đã kết nối</h4>
        {accounts.length === 0 ? (
          <p className="hint">Chưa có account nào.</p>
        ) : (
          <ul className="page-list">
            {accounts.map((a) => (
              <li key={a.business_id} className="page-row">
                <div>
                  <div className="page-name">
                    {a.name || a.username || a.business_id}
                    {a.username && ` (@${a.username})`}
                  </div>
                  <div className="page-sub">Business ID: {a.business_id}</div>
                  <div className="page-sub">
                    {a.owner_registered
                      ? `Chủ (nhận báo): ${a.owner_name || "đã đăng ký"} ✅`
                      : "Chưa có chủ — vào tab Khách hàng → ⭐ Đặt làm chủ"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    className={"btn-mini" + (a.bot_enabled ? "" : " danger")}
                    title={a.bot_enabled ? "Bot đang BẬT — bấm để TẮT" : "Bot đang TẮT — bấm để BẬT"}
                    onClick={() => toggleAccount(a)}
                  >
                    {a.bot_enabled ? "🟢 Bot bật" : "🔴 Bot tắt"}
                  </button>
                  <button className="btn-mini danger" onClick={() => disconnect(a)}>Ngắt</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
