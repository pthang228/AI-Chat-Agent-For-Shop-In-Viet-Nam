import { useState, useEffect } from "react";
import { webchat } from "../webchatApi.js";
import GuideBox from "./GuideBox.jsx";
import { ChannelTile } from "./ChannelIcon.jsx";

/*
 * Kết nối kênh Website — KHÔNG token, KHÔNG chờ duyệt: tạo site → nhận mã nhúng
 * 1 dòng <script> → chủ shop dán vào website của họ là bong bóng chat hiện ngay.
 */
export default function WebChatConnect() {
  const [cfg, setCfg] = useState(null);   // {public_base_url,...} | "offline"
  const [sites, setSites] = useState([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [copied, setCopied] = useState("");   // site_id vừa copy

  async function refreshSites() {
    const r = await webchat.sites();
    if (r.ok && Array.isArray(r.body)) setSites(r.body);
  }

  useEffect(() => {
    webchat.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshSites(); }
      else setCfg("offline");
    });
  }, []);

  async function createSite() {
    setBusy(true); setMsg("");
    const r = await webchat.createSite(name.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(`✅ Đã tạo site "${r.body.site.name}" — copy mã nhúng bên dưới dán vào website.`);
      setName("");
      refreshSites();
    } else {
      setMsg("❌ " + (r.body?.error || "Tạo site thất bại"));
    }
  }

  async function copySnippet(s) {
    try {
      await navigator.clipboard.writeText(s.snippet);
      setCopied(s.site_id);
      setTimeout(() => setCopied(""), 2000);
    } catch {
      prompt("Copy thủ công mã nhúng:", s.snippet);
    }
  }

  async function removeSite(s) {
    if (!confirm(
      `Xoá site "${s.name || s.site_id}"?\n\n` +
      `Widget trên website đang dán mã này sẽ NGỪNG hoạt động.\n` +
      `Lịch sử hội thoại với khách vẫn còn lưu.`
    )) return;
    await webchat.removeSite(s.site_id);
    refreshSites();
  }

  async function toggleSite(s) {
    await webchat.siteToggle(s.site_id, !s.bot_enabled);
    refreshSites();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">Đang tải…</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được máy chủ Webchat (cổng 5011)</div>
        <p className="hint">Chạy <code>python -m app.main_webchat</code> rồi tải lại trang.</p>
      </div>
    );

  return (
    <div className="connect">
      <div className="status ok"><ChannelTile ch="webchat" size={22} /> Kênh Website — bong bóng chat trên web của bạn</div>

      {/* Hướng dẫn cho chủ shop KHÔNG RÀNH kỹ thuật */}
      <GuideBox
        title="📘 Hướng dẫn — dán 1 dòng mã là chạy (không cần duyệt gì cả)"
        steps={[
          { t: "Kênh Website là gì?", d: <>Bong bóng chat hiện ở <b>góc phải website của bạn</b> (giống khung chat bạn hay thấy trên các trang bán hàng). Khách đang xem web hỏi là <b>bot trả lời ngay</b> — không cần khách cài app hay đăng nhập gì.</> },
          { t: "Bước 1 · Tạo site", d: <>Điền tên website (vd "Web Haru Homestay") → bấm <b>Tạo mã nhúng</b>. Xong ngay, không chờ ai duyệt.</> },
          { t: "Bước 2 · Dán mã vào website", d: <>Bấm <b>📋 Copy mã nhúng</b> → gửi cho người làm web của bạn dán vào <b>cuối trang (trước &lt;/body&gt;)</b>. Web WordPress/Haravan/Shopify đều có chỗ dán mã — chỉ 1 dòng duy nhất.</> },
          { t: "Bước 3 · Thử ngay", d: <>Mở website của bạn → thấy bong bóng chat tím góc phải → nhắn thử 1 câu, bot trả lời là xong. Mọi hội thoại hiện trong tab <b>Hội thoại</b> ở đây, bạn nhắn xen vào lúc nào cũng được (bot tự nhường).</> },
          { t: "Bước 4 · Nhận thông báo (tuỳ chọn)", d: <>Tự nhắn widget trên web của bạn 1 tin → vào tab <b>Khách hàng</b> → mở hội thoại của mình → <b>⭐ Đặt làm chủ</b>. Muốn nhận báo cả khi không mở web → nối thêm kênh Telegram/Zalo.</> },
        ]}
        note={
          <>
            ⚠️ <b>Lưu ý:</b> để khách trên internet nhắn được, máy chủ NovaChat phải có
            <b> địa chỉ công khai</b> (domain/tunnel). Hiện tại: <code>{cfg.public_base_url || "chưa cấu hình — mã nhúng dùng địa chỉ nội bộ, chỉ thử được trên máy này"}</code>
          </>
        }
      />

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
        <input
          style={{ flex: 1, minWidth: 200 }}
          placeholder="Tên website (vd: Web Haru Homestay)…"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn-primary sm" onClick={createSite} disabled={busy}>
          {busy ? "Đang tạo…" : "＋ Tạo mã nhúng"}
        </button>
      </div>
      {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}

      <div className="pages" style={{ marginTop: 14 }}>
        <h4>Site đã tạo</h4>
        {sites.length === 0 ? (
          <p className="hint">Chưa có site nào — tạo mã nhúng đầu tiên ở trên.</p>
        ) : (
          <ul className="page-list">
            {sites.map((s) => (
              <li key={s.site_id} className="page-row">
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="page-name">{s.name || s.site_id}</div>
                  <div className="page-sub">Mã site: {s.site_id}</div>
                  <div className="page-sub" style={{ wordBreak: "break-all" }}>
                    <code style={{ fontSize: 11 }}>{s.snippet}</code>
                  </div>
                  <div className="page-sub">
                    {s.owner_registered
                      ? `Chủ (nhận báo): ${s.owner_name || "đã đăng ký"} ✅`
                      : "Chưa có chủ — vào tab Khách hàng → ⭐ Đặt làm chủ"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button className="btn-mini" onClick={() => copySnippet(s)}>
                    {copied === s.site_id ? "✅ Đã copy" : "📋 Copy mã nhúng"}
                  </button>
                  <button
                    className={"btn-mini" + (s.bot_enabled ? "" : " danger")}
                    title={s.bot_enabled ? "Bot đang BẬT — bấm để TẮT" : "Bot đang TẮT — bấm để BẬT"}
                    onClick={() => toggleSite(s)}
                  >
                    {s.bot_enabled ? "🟢 Bot bật" : "🔴 Bot tắt"}
                  </button>
                  <button className="btn-mini danger" onClick={() => removeSite(s)}>Xoá</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
