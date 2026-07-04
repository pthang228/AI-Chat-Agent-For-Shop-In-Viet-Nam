import { useState, useEffect } from "react";
import { shopee } from "../shopeeApi.js";
import GuideBox from "./GuideBox.jsx";

// Kết nối Shopee ĐA KHÁCH trong web: dán Shop ID + access token (shop đã uỷ quyền
// cho app của NovaChat trên Shopee Open Platform).
export default function ShopeeConnect() {
  const [cfg, setCfg] = useState(null);   // {partner_configured,...} | "offline"
  const [shops, setShops] = useState([]);
  const [token, setToken] = useState("");
  const [shopId, setShopId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function refreshShops() {
    const r = await shopee.shops();
    if (r.ok && Array.isArray(r.body)) setShops(r.body);
  }

  useEffect(() => {
    shopee.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshShops(); }
      else setCfg("offline");
    });
  }, []);

  async function connect() {
    if (!token.trim() || !shopId.trim()) {
      setMsg("❌ Cần cả Shop ID và Access Token.");
      return;
    }
    setBusy(true); setMsg("");
    const r = await shopee.connect(token.trim(), shopId.trim(), name.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(r.body.verified
        ? `✅ Đã kết nối & xác thực shop ${r.body.shop.name || r.body.shop.shop_id}`
        : `✅ Đã lưu shop ${r.body.shop.shop_id} (chưa xác thực được với Shopee — cấu hình sẽ dùng ngay khi app được duyệt)`);
      setToken(""); setShopId(""); setName("");
      refreshShops();
    } else {
      setMsg("❌ " + (r.body?.error || "Kết nối thất bại"));
    }
  }

  async function disconnect(s) {
    if (!confirm(
      `Ngắt kết nối shop ${s.name || s.shop_id}?\n\n` +
      `Token sẽ bị xoá khỏi hệ thống. Lịch sử hội thoại với khách vẫn còn lưu.\n` +
      `Bạn có thể kết nối lại bất kỳ lúc nào.`
    )) return;
    await shopee.removeShop(s.shop_id);
    refreshShops();
  }

  async function toggleShop(s) {
    await shopee.shopToggle(s.shop_id, !s.bot_enabled);
    refreshShops();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">Đang tải…</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được máy chủ Shopee (cổng 5009)</div>
        <p className="hint">Chạy <code>python -m app.main_shopee</code> rồi tải lại trang.</p>
      </div>
    );

  const webhookUrl = (cfg.public_base_url || "<PUBLIC_BASE_URL>") + (cfg.webhook_path || "/shopee/webhook");

  return (
    <div className="connect">
      <div className="status ok">🛒 Kết nối Shopee</div>

      {/* Hướng dẫn viết cho chủ shop KHÔNG RÀNH kỹ thuật — từng bước cụ thể */}
      <GuideBox
        title="📘 Hướng dẫn kết nối — Shopee (đọc 1 phút là hiểu)"
        steps={[
          { t: "Bot Shopee làm gì cho bạn?", d: <>Khách nhắn vào <b>khung chat shop Shopee</b> của bạn (hỏi giá, hỏi size, hỏi ship…) → bot tự trả lời ngay 24/7 bằng đúng bộ não bạn đã dạy ở mục <b>Dạy AI</b>. Khách muốn gặp người thật → bot tự báo cho bạn.</> },
          { t: "Bước 1 · Bạn cần gì?", d: <>Chỉ cần <b>shop đang bán trên Shopee</b> (có tài khoản người bán đăng nhập được <b>banhang.shopee.vn</b>). Không cần biết kỹ thuật.</> },
          { t: "Bước 2 · Uỷ quyền cho NovaChat", d: <>Bấm <b>link uỷ quyền</b> do NovaChat gửi bạn (qua Zalo/email khi đăng ký) → đăng nhập Shopee người bán → bấm <b>Xác nhận uỷ quyền</b>. Shopee sẽ hiện <b>Shop ID</b> và cấp <b>Access Token</b> — copy 2 thứ đó lại. <i>(Uỷ quyền chỉ cho phép đọc & trả lời tin nhắn chat — không đụng tiền, đơn hàng của bạn.)</i></> },
          { t: "Bước 3 · Dán vào ô bên dưới", d: <>Dán <b>Shop ID</b> + <b>Access Token</b> vào 2 ô dưới rồi bấm <b>Kết nối</b>. Xong! Nhắn thử vào chat shop của mình để xem bot trả lời.</> },
          { t: "Bước 4 · Đặt người nhận thông báo", d: <>Dùng tài khoản Shopee cá nhân của bạn nhắn thử shop 1 tin → vào tab <b>Khách hàng</b> → mở hội thoại của mình → bấm <b>⭐ Đặt làm chủ</b>. Từ đó khách chốt đơn là bot nhắn báo bạn ngay.</> },
        ]}
        note={
          <>
            ⚠️ <b>Lưu ý thật lòng:</b> tính năng chat qua API là do <b>Shopee xét duyệt</b> cho
            ứng dụng NovaChat (đang trong quá trình duyệt). Trong lúc chờ, bạn vẫn kết nối
            và cấu hình được bình thường — hệ thống chạy <b>chế độ thử nghiệm</b> (bot trả lời
            trong trang Test bot, chưa gửi thật lên Shopee). Ngay khi Shopee duyệt, bot chạy
            thật <b>không cần bạn làm lại gì</b>. Kỹ thuật viên khai webhook: <code>{webhookUrl}</code>
          </>
        }
      />

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
        <input
          placeholder="Dán Access Token (Shopee cấp khi uỷ quyền)…"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder="Shop ID (dãy số, bắt buộc)"
            value={shopId}
            onChange={(e) => setShopId(e.target.value)}
          />
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder="Tên shop hiển thị (tuỳ chọn)"
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
        <h4>Shop đã kết nối</h4>
        {shops.length === 0 ? (
          <p className="hint">Chưa có shop nào.</p>
        ) : (
          <ul className="page-list">
            {shops.map((s) => (
              <li key={s.shop_id} className="page-row">
                <div>
                  <div className="page-name">{s.name || s.shop_id}</div>
                  <div className="page-sub">Shop ID: {s.shop_id}</div>
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
                    onClick={() => toggleShop(s)}
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
