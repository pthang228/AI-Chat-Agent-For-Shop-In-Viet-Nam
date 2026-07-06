import { useState, useEffect, useRef } from "react";
import { tg } from "../telegramApi.js";
import GuideBox from "./GuideBox.jsx";
import { ChannelTile } from "./ChannelIcon.jsx";

// Kết nối Telegram ĐA KHÁCH ngay trong web: dán token bot (@BotFather) → tự động.
// Mỗi bot tự đăng nhập "acc gọi" (Telethon) bằng QR để gọi điện cho chủ.
export default function TelegramConnect() {
  const [cfg, setCfg] = useState(null);   // {setup_code,...} | "offline"
  const [bots, setBots] = useState([]);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  // Đăng nhập acc gọi (QR)
  const [loginBot, setLoginBot] = useState(null);   // bot_id đang đăng nhập | null
  const [login, setLogin] = useState(null);         // {state, png, profile, error}
  const [pw, setPw] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const poll = useRef(null);

  async function refreshBots() {
    const r = await tg.bots();
    if (r.ok && Array.isArray(r.body)) setBots(r.body);
  }

  useEffect(() => {
    tg.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshBots(); }
      else setCfg("offline");
    });
  }, []);

  // Poll trạng thái đăng nhập trong lúc mở modal QR
  useEffect(() => {
    clearInterval(poll.current);
    if (!loginBot) return;
    poll.current = setInterval(async () => {
      const { ok, body } = await tg.callerLoginStatus(loginBot);
      if (!ok || !body) return;
      setLogin(body);
      if (["done", "expired", "error", "need_password"].includes(body.state)) {
        clearInterval(poll.current);
        if (body.state === "done") {
          await refreshBots();
          setTimeout(() => setLoginBot(null), 900);
        }
      }
    }, 2000);
    return () => clearInterval(poll.current);
  }, [loginBot]);

  async function connect() {
    if (!token.trim()) return;
    setBusy(true); setMsg("");
    const r = await tg.connect(token.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(`✅ Đã kết nối bot @${r.body.bot.username || r.body.bot.bot_id}`);
      setToken("");
      refreshBots();
    } else {
      setMsg("❌ " + (r.body?.error || "Kết nối thất bại"));
    }
  }

  async function disconnect(bot) {
    const name = bot.username ? `@${bot.username}` : bot.bot_id;
    if (!confirm(
      `Ngắt kết nối bot ${name}?\n\n` +
      `Thao tác này sẽ XOÁ:\n` +
      `• Token bot khỏi hệ thống\n` +
      `• Thông tin chủ nhà đã đăng ký\n` +
      `• Phiên đăng nhập acc gọi\n\n` +
      `Lịch sử hội thoại với khách vẫn còn lưu.\n` +
      `Bạn có thể kết nối lại bất kỳ lúc nào bằng cách dán token mới.`
    )) return;
    await tg.removeBot(bot.bot_id);
    refreshBots();
  }

  async function toggleBot(bot) {
    await tg.botToggle(bot.bot_id, !bot.bot_enabled);
    refreshBots();
  }

  async function openLogin(botId) {
    setPw(""); setLogin({ state: "starting" }); setLoginBot(botId);
    const r = await tg.callerQrLogin(botId);
    if (r.ok && r.body) setLogin(r.body);
    else setLogin({ state: "error", error: "Không gọi được máy chủ" });
  }

  function closeLogin() {
    clearInterval(poll.current);
    if (login && login.state !== "done") tg.callerLogout(loginBot);  // dọn phiên dở
    setLoginBot(null); setLogin(null); setPw("");
  }

  async function sendPassword() {
    if (!pw.trim()) return;
    setPwBusy(true);
    const r = await tg.callerPassword(loginBot, pw);
    setPwBusy(false);
    if (r.ok && r.body?.ok) {
      setLogin({ state: "done", profile: r.body.profile });
      await refreshBots();
      setTimeout(() => setLoginBot(null), 900);
    } else {
      setLogin((s) => ({ ...s, state: "need_password", error: r.body?.error || "Sai mật khẩu" }));
      setPw("");
    }
  }

  async function callerLogout(botId) {
    if (!confirm("Đăng xuất acc gọi của bot này? (sẽ không gọi được cho chủ tới khi đăng nhập lại)")) return;
    await tg.callerLogout(botId);
    refreshBots();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">Đang tải…</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được máy chủ Telegram (cổng 5007)</div>
        <p className="hint">Chạy <code>python -m app.main_telegram</code> rồi tải lại trang.</p>
      </div>
    );

  return (
    <div className="connect">
      <div className="status ok"><ChannelTile ch="telegram" size={22} /> Kết nối Telegram</div>

      <GuideBox
        title="📘 Hướng dẫn 3 bước — Telegram"
        steps={[
          { t: "Bước 1 · Tạo bot & kết nối", d: <>Mở Telegram chat với <b>@BotFather</b> → gửi <code>/newbot</code> → đặt tên & username → copy <b>token</b> (dạng <code>123456:ABC…</code>) → dán vào ô dưới, bấm <b>Kết nối</b>. Xong là người lạ nhắn được ngay (không cần duyệt như Facebook).</> },
          { t: "Bước 2 · Đăng ký chủ nhà", d: <>Ở dòng bot bên dưới bấm <b>Đăng ký chủ</b> rồi bấm <b>Start</b> trên Telegram (hoặc chủ tự mở chat bot gõ <code>/chunha</code>). Chủ là người <b>nhận tin báo + cuộc gọi</b> khi khách chốt phòng.</> },
          { t: "Bước 3 · Đăng nhập acc gọi", d: <>Bấm <b>📞 Đăng nhập acc gọi</b> → quét QR bằng <b>tài khoản Telegram dùng để gọi</b> (nên là 1 acc thứ 2, có quen chủ). Đây là acc sẽ tự bấm gọi cho chủ.</> },
        ]}
        note={
          <>
            ☎️ <b>Khi khách chốt phòng / đòi gặp người</b>, bot tự nhắn <b>và gọi</b> cho chủ.
            Chủ <b>bắt máy</b> là chuỗi gọi dừng; nếu không nghe, máy sẽ gọi lại mỗi 3 phút (tối đa 10 lần).
          </>
        }
      />

      <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
        <input
          style={{ flex: 1 }}
          placeholder="Dán token bot ở đây…"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <button className="btn-primary sm" onClick={connect} disabled={busy}>
          {busy ? "Đang kết nối…" : "Kết nối"}
        </button>
      </div>
      {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}

      <div className="pages" style={{ marginTop: 14 }}>
        <h4>Bot đã kết nối</h4>
        {bots.length === 0 ? (
          <p className="hint">Chưa có bot nào.</p>
        ) : (
          <ul className="page-list">
            {bots.map((b) => (
              <li key={b.bot_id} className="page-row">
                <div>
                  <div className="page-name">@{b.username || b.bot_id}</div>
                  <div className="page-sub">
                    {b.owner_registered
                      ? `Chủ (nhận cuộc gọi): ${b.owner_name || "đã đăng ký"} ✅`
                      : "Chưa có chủ — bấm 'Đăng ký chủ'"}
                  </div>
                  <div className="page-sub">
                    {b.caller_logged_in
                      ? `Acc gọi: ${b.caller_name || ""}${b.caller_username ? ` (@${b.caller_username})` : ""} 📞 ✅`
                      : "Chưa có acc gọi — bấm 'Đăng nhập acc gọi' để quét QR"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    className={"btn-mini" + (b.bot_enabled ? "" : " danger")}
                    title={b.bot_enabled ? "Bot đang BẬT — bấm để TẮT" : "Bot đang TẮT — bấm để BẬT"}
                    onClick={() => toggleBot(b)}
                  >
                    {b.bot_enabled ? "🟢 Bot bật" : "🔴 Bot tắt"}
                  </button>
                  {!b.owner_registered && b.owner_link && (
                    <a className="btn-mini" href={b.owner_link} target="_blank" rel="noreferrer">Đăng ký chủ</a>
                  )}
                  {b.caller_logged_in
                    ? <button className="btn-mini" onClick={() => callerLogout(b.bot_id)}>Đăng xuất acc gọi</button>
                    : <button className="btn-mini" onClick={() => openLogin(b.bot_id)}>📞 Đăng nhập acc gọi</button>}
                  {b.link && <a className="btn-mini" href={b.link} target="_blank" rel="noreferrer">Mở chat</a>}
                  <button className="btn-mini danger" onClick={() => disconnect(b)}>Ngắt</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {loginBot && login && (
        <div className="tg-modal-overlay" onClick={closeLogin}>
          <div className="tg-modal" onClick={(e) => e.stopPropagation()}>
            <h4 style={{ marginTop: 0 }}>Đăng nhập tài khoản gọi</h4>

            {login.state === "starting" && <p className="hint">Đang tạo mã QR…</p>}

            {login.state === "pending" && (
              <>
                <p className="hint">
                  Mở <b>Telegram</b> trên điện thoại → <b>Cài đặt → Thiết bị → Liên kết thiết bị</b> →
                  quét mã dưới đây bằng <b>tài khoản dùng để gọi cho chủ</b>.
                </p>
                {login.png && <img src={login.png} alt="QR" style={{ width: 220, height: 220, display: "block", margin: "8px auto" }} />}
                <p className="hint" style={{ textAlign: "center" }}>Mã tự làm mới khi hết hạn…</p>
              </>
            )}

            {login.state === "need_password" && (
              <>
                <p className="hint">Tài khoản có bật <b>mật khẩu 2 lớp (2FA)</b>. Nhập mật khẩu để hoàn tất:</p>
                <input
                  type="password"
                  style={{ width: "100%" }}
                  placeholder="Mật khẩu 2FA"
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendPassword()}
                />
                {login.error && <div className="status warn" style={{ marginTop: 8 }}>❌ {login.error}</div>}
                <button className="btn-primary sm" style={{ marginTop: 10 }} onClick={sendPassword} disabled={pwBusy}>
                  {pwBusy ? "Đang xác thực…" : "Xác nhận"}
                </button>
              </>
            )}

            {login.state === "done" && (
              <div className="status ok">
                ✅ Đăng nhập thành công{login.profile?.first_name ? `: ${login.profile.first_name}` : ""}
                {login.profile?.username ? ` (@${login.profile.username})` : ""}
              </div>
            )}

            {login.state === "expired" && (
              <>
                <div className="status warn">⏱️ Mã QR đã hết hạn.</div>
                <button className="btn-primary sm" style={{ marginTop: 10 }} onClick={() => openLogin(loginBot)}>Tạo mã mới</button>
              </>
            )}

            {login.state === "error" && (
              <>
                <div className="status warn">❌ {login.error || "Lỗi đăng nhập"}</div>
                <button className="btn-primary sm" style={{ marginTop: 10 }} onClick={() => openLogin(loginBot)}>Thử lại</button>
              </>
            )}

            <button className="btn-mini" style={{ marginTop: 12 }} onClick={closeLogin}>Đóng</button>
          </div>
        </div>
      )}
    </div>
  );
}
