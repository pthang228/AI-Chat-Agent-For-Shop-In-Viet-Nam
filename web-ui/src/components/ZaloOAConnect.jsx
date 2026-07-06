import { useState, useEffect } from "react";
import { zalooa } from "../zaloOaApi.js";
import GuideBox from "./GuideBox.jsx";
import { ChannelTile } from "./ChannelIcon.jsx";

// Kết nối Zalo OA ĐA KHÁCH trong web: dán OA ID + access token (+ refresh token
// để hệ thống TỰ GIA HẠN — token Zalo chỉ sống ~25 giờ).
export default function ZaloOAConnect() {
  const [cfg, setCfg] = useState(null);   // {app_configured,...} | "offline"
  const [oas, setOas] = useState([]);
  const [token, setToken] = useState("");
  const [refresh, setRefresh] = useState("");
  const [oaId, setOaId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function refreshOas() {
    const r = await zalooa.accounts();
    if (r.ok && Array.isArray(r.body)) setOas(r.body);
  }

  useEffect(() => {
    zalooa.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshOas(); }
      else setCfg("offline");
    });
  }, []);

  async function connect() {
    if (!token.trim()) {
      setMsg("❌ Cần dán Access Token.");
      return;
    }
    setBusy(true); setMsg("");
    const r = await zalooa.connect(token.trim(), oaId.trim(), name.trim(), refresh.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(r.body.verified
        ? `✅ Đã kết nối & xác thực OA ${r.body.oa.name || r.body.oa.oa_id}`
        : `✅ Đã lưu OA ${r.body.oa.oa_id} (chưa xác thực được với Zalo — kiểm tra lại token nếu bot không trả lời)`);
      setToken(""); setRefresh(""); setOaId(""); setName("");
      refreshOas();
    } else {
      setMsg("❌ " + (r.body?.error || "Kết nối thất bại"));
    }
  }

  async function disconnect(s) {
    if (!confirm(
      `Ngắt kết nối OA ${s.name || s.oa_id}?\n\n` +
      `Token sẽ bị xoá khỏi hệ thống. Lịch sử hội thoại với khách vẫn còn lưu.\n` +
      `Bạn có thể kết nối lại bất kỳ lúc nào.`
    )) return;
    await zalooa.removeAccount(s.oa_id);
    refreshOas();
  }

  async function toggleOa(s) {
    await zalooa.accountToggle(s.oa_id, !s.bot_enabled);
    refreshOas();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">Đang tải…</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được máy chủ Zalo OA (cổng 5010)</div>
        <p className="hint">Chạy <code>python -m app.main_zalo_oa</code> rồi tải lại trang.</p>
      </div>
    );

  const webhookUrl = (cfg.public_base_url || "<PUBLIC_BASE_URL>") + (cfg.webhook_path || "/zalooa/webhook");

  return (
    <div className="connect">
      <div className="status ok"><ChannelTile ch="zalooa" size={22} /> Kết nối Zalo OA (Official Account)</div>

      {/* Hướng dẫn viết cho chủ shop KHÔNG RÀNH kỹ thuật — từng bước cụ thể */}
      <GuideBox
        title="📘 Hướng dẫn kết nối — Zalo OA (đọc 1 phút là hiểu)"
        steps={[
          { t: "Zalo OA khác gì Zalo thường?", d: <>Zalo OA là <b>tài khoản chính thức cho doanh nghiệp</b> (như Page trên Facebook) — khách bấm Quan tâm rồi nhắn tin, bot trả lời qua API <b>chính thức của Zalo</b>, không lo khoá tài khoản như Zalo cá nhân. Chưa có OA? Tạo miễn phí tại <b>oa.zalo.me</b>.</> },
          { t: "Bước 1 · Bạn cần gì?", d: <>Một <b>Zalo OA đã tạo</b> (oa.zalo.me, nên xác thực OA để khách lạ nhắn được nhiều) — không cần biết kỹ thuật.</> },
          { t: "Bước 2 · Uỷ quyền cho NovaChat", d: <>Bấm <b>link uỷ quyền</b> do NovaChat gửi bạn → đăng nhập Zalo quản trị OA → bấm <b>Cho phép</b>. Hệ thống hiện <b>Access Token</b> và <b>Refresh Token</b> — copy cả 2. <i>(Uỷ quyền chỉ cho phép đọc & trả lời tin nhắn — không đụng gì khác của OA.)</i></> },
          { t: "Bước 3 · Dán vào ô bên dưới", d: <>Dán <b>Access Token</b> + <b>Refresh Token</b> vào 2 ô dưới rồi bấm <b>Kết nối</b>. Có refresh token thì hệ thống <b>tự gia hạn</b> (token Zalo chỉ sống ~25 giờ) — bạn không phải dán lại mỗi ngày.</> },
          { t: "Bước 4 · Đặt người nhận thông báo", d: <>Dùng Zalo cá nhân của bạn nhắn OA 1 tin → vào tab <b>Khách hàng</b> → mở hội thoại của mình → bấm <b>⭐ Đặt làm chủ</b>. Khách chốt đơn là bot nhắn báo bạn ngay. <i>(Mẹo: thỉnh thoảng nhắn OA 1 tin — Zalo chỉ cho OA nhắn lại người đã tương tác trong 48h.)</i></> },
        ]}
        note={
          <>
            ⚠️ <b>Lưu ý:</b> bot chỉ <b>trả lời</b> khi khách nhắn trước (quy định cửa sổ 48h của
            Zalo — trả lời khách thì luôn hợp lệ). Nhắn chủ động cho khách im lâu cần ZNS
            (chưa hỗ trợ). Kỹ thuật viên khai webhook trên developers.zalo.me: <code>{webhookUrl}</code>
          </>
        }
      />

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
        <input
          placeholder="Dán Access Token (Zalo cấp khi uỷ quyền)…"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <input
          placeholder="Dán Refresh Token (để hệ thống tự gia hạn — nên có)…"
          value={refresh}
          onChange={(e) => setRefresh(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder="OA ID (bỏ trống nếu không biết — hệ thống tự tra)"
            value={oaId}
            onChange={(e) => setOaId(e.target.value)}
          />
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder="Tên OA hiển thị (tuỳ chọn)"
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
        <h4>OA đã kết nối</h4>
        {oas.length === 0 ? (
          <p className="hint">Chưa có OA nào.</p>
        ) : (
          <ul className="page-list">
            {oas.map((s) => (
              <li key={s.oa_id} className="page-row">
                <div>
                  <div className="page-name">{s.name || s.oa_id}</div>
                  <div className="page-sub">OA ID: {s.oa_id}</div>
                  <div className="page-sub">
                    {s.has_refresh
                      ? "Tự gia hạn token: BẬT ✅"
                      : "⚠️ Chưa có refresh token — token sẽ hết hạn sau ~25h, nên dán lại kèm refresh token"}
                  </div>
                  <div className="page-sub">
                    {s.owner_registered
                      ? `Chủ (nhận báo): ${s.owner_name || "đã đăng ký"} ✅`
                      : "Chưa có chủ — vào tab Khách hàng → ⭐ Đặt làm chủ"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    className={"btn-mini" + (s.bot_enabled ? "" : " danger")}
                    title={s.bot_enabled ? "Bot đang BẬT — bấm để TẮT" : "Bot đang TẮT — bấm để BẬT"}
                    onClick={() => toggleOa(s)}
                  >
                    {s.bot_enabled ? "🟢 Bot bật" : "🔴 Bot tắt"}
                  </button>
                  <button className="btn-mini danger" onClick={() => disconnect(s)}>Ngắt</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
