import { useEffect, useRef, useState } from "react";
import { zalo } from "../zaloApi.js";
import GuideBox from "./GuideBox.jsx";

const LABELS = {
  checking: ["Đang kiểm tra kết nối…", "muted"],
  offline: ["Chưa chạy dịch vụ Zalo", "warn"],
  idle: ["Đang chuẩn bị mã QR…", "muted"],
  waiting_scan: ["Đang chờ quét mã QR…", "muted"],
  scanned: ["Đã quét! Xác nhận trên điện thoại…", "ok"],
  logged_in: ["✅ Đã kết nối Zalo", "ok"],
  qr_expired: ["Đang làm mới mã QR…", "muted"],
  disconnected: ["Đã tạm ngắt (vẫn giữ đăng nhập)", "muted"],
  declined: ["Bạn đã từ chối đăng nhập", "warn"],
  error: ["Có lỗi xảy ra, thử lại", "warn"],
};

export default function ZaloConnect() {
  const [status, setStatus] = useState("checking");
  const [qr, setQr] = useState(null);
  const [ownId, setOwnId] = useState(null);
  const [groups, setGroups] = useState([]);
  const [selGroup, setSelGroup] = useState("");
  const [saveMsg, setSaveMsg] = useState("");
  const [hasBackup, setHasBackup] = useState(false);   // có tài khoản trước để khôi phục
  const timer = useRef(null);
  const autoRef = useRef("");   // trạng thái đã tự-khởi-động QR (chống gọi lặp mỗi 2s)
  // MULTI-ACCOUNT: acc Zalo RIÊNG của shop (bridge cấp; chủ nền tảng = "default").
  // null = đang hỏi bridge — mọi call Node chờ tới khi có acc.
  const accRef = useRef(null);

  function stopPoll() { if (timer.current) clearInterval(timer.current); timer.current = null; }
  function startPoll() { stopPoll(); timer.current = setInterval(poll, 2000); }

  async function poll() {
    if (!accRef.current) {   // chưa biết acc của shop → hỏi bridge trước
      const r = await zalo.myAccount();
      if (r.ok && r.body?.acc) accRef.current = r.body.acc;
      else if (r.status === 0) { setStatus("offline"); return; }
      else { accRef.current = "default"; }   // bridge cũ chưa có route → dùng default
    }
    try {
      const { ok, body } = await zalo.status(accRef.current);
      // Lỗi mạng / Node chưa chạy → giữ trạng thái offline NHƯNG tiếp tục dò lại,
      // để khi Node bật lên thì tự động kết nối, không cần bấm "Thử lại".
      if (!ok) { setStatus("offline"); return; }
      setStatus(body.status);
      setQr(body.qr || null);
      setOwnId(body.ownId || null);
      setHasBackup(!!body.hasBackup);
      if (body.status === "logged_in") { stopPoll(); autoRef.current = ""; loadGroups(); return; }
      // Đã TẠM NGẮT chủ ý → KHÔNG tự mở QR (giữ nguyên để user bấm "Kết nối lại").
      if (body.status === "disconnected") { autoRef.current = ""; return; }
      // TỰ mở/làm mới QR: chưa đăng nhập mà đang "idle" (vd sau đăng xuất, hoặc
      // Node vừa dừng chuỗi tự-làm-mới) → gọi startQR để luôn có mã sống, KHÔNG
      // bắt user bấm nút. Chỉ gọi 1 lần cho mỗi lần rơi vào trạng thái đó.
      if ((body.status === "idle" || body.status === "qr_expired") && autoRef.current !== body.status) {
        autoRef.current = body.status;
        zalo.startQR(accRef.current).catch(() => {});
      }
      if (body.status === "waiting_scan" || body.status === "scanned") autoRef.current = "";
    } catch {
      setStatus("offline");
    }
  }

  async function loadGroups() {
    try {
      const [g, cfg] = await Promise.all([zalo.groups(accRef.current), zalo.getConfig(accRef.current)]);
      setGroups(g.body.groups || []);
      setSelGroup(cfg.body.ownerGroupId || "");
    } catch { /* ignore */ }
  }

  async function onStartQR() {
    setSaveMsg("");
    try { await zalo.startQR(accRef.current); startPoll(); poll(); }
    catch { setStatus("offline"); }
  }

  async function onSaveGroup() {
    const { ok } = await zalo.saveGroup(selGroup, accRef.current);
    setSaveMsg(ok ? "✅ Đã lưu nhóm nhận thông báo" : "❌ Lưu thất bại");
  }

  async function onDisconnect() {
    // Tạm ngắt: GIỮ đăng nhập, không xoá session → kết nối lại không cần QR
    try { await zalo.disconnect(accRef.current); } catch { /* ignore */ }
    setGroups([]); setSelGroup(""); setStatus("disconnected");
    startPoll(); poll();
  }

  async function onReconnect() {
    try { await zalo.reconnect(accRef.current); } catch { /* ignore */ }
    setStatus("checking"); startPoll(); poll();
  }

  async function onRestore() {
    try { await zalo.restoreSession(accRef.current); } catch { /* ignore */ }
    autoRef.current = ""; setStatus("checking"); startPoll(); poll();
  }

  async function onLogout() {
    if (!confirm("ĐỔI TÀI KHOẢN: đăng xuất tài khoản Zalo hiện tại và đăng nhập tài khoản KHÁC?\n\n" +
                 "Việc này cần QUÉT LẠI QR. Nếu chỉ muốn tạm dừng bot mà giữ đăng nhập, hãy dùng \"Tạm ngắt\".")) return;
    try { await zalo.logout(accRef.current); } catch { /* ignore */ }
    autoRef.current = "";   // cho phép tự mở lại QR ngay sau đăng xuất
    setStatus("idle"); setQr(null); setOwnId(null); setGroups([]); setSelGroup("");
    startPoll(); poll();
  }

  useEffect(() => { startPoll(); poll(); return stopPoll; }, []);

  const [label, cls] = LABELS[status] || ["…", "muted"];

  // ── Dịch vụ Node chưa chạy ──
  if (status === "offline") {
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được dịch vụ Zalo</div>
        <p className="hint">Hãy chạy dịch vụ Node trước:</p>
        <pre className="code">cd zalo-node{"\n"}npm start</pre>
        <button className="btn-primary" onClick={poll}>Thử lại</button>
      </div>
    );
  }

  // ── Đã đăng nhập: chọn nhóm + đăng xuất ──
  if (status === "logged_in") {
    return (
      <div className="connect">
        <div className="status ok">✅ Đã kết nối Zalo</div>
        {ownId && <p className="hint">ID tài khoản: {ownId}</p>}

        <div className="field">
          <label>📢 Nhóm nhận thông báo</label>
          <p className="hint">Bot sẽ báo vào nhóm này khi có khách đặt phòng / cần gặp chủ.</p>
          {groups.length === 0 ? (
            <p className="hint warn">Tài khoản chưa ở nhóm nào — tạo 1 nhóm trên Zalo rồi bấm “Tải lại”.</p>
          ) : (
            <select value={selGroup} onChange={(e) => setSelGroup(e.target.value)}>
              <option value="">— Chọn nhóm —</option>
              {groups.map((g) => (
                <option key={g.groupId} value={g.groupId}>{g.name || g.groupId}</option>
              ))}
            </select>
          )}
          <div className="row">
            <button className="btn-primary sm" onClick={onSaveGroup} disabled={!groups.length}>Lưu nhóm</button>
            <button className="btn-ghost" onClick={loadGroups}>Tải lại</button>
          </div>
          {saveMsg && <div className="savemsg">{saveMsg}</div>}
        </div>

        <div className="logout-row" style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <button className="btn-ghost" onClick={onDisconnect}>⏸ Tạm ngắt (giữ đăng nhập)</button>
          <button className="link-danger" onClick={onLogout}>↩ Đăng xuất / đổi tài khoản</button>
        </div>
        <p className="hint" style={{ marginTop: 8 }}>
          <b>Tạm ngắt</b>: dừng bot nhưng vẫn nhớ đăng nhập — bật lại KHÔNG cần quét QR.
          <br /><b>Đăng xuất</b>: chỉ dùng khi muốn đổi sang tài khoản Zalo khác (phải quét lại).
        </p>
      </div>
    );
  }

  // ── Đã tạm ngắt: kết nối lại không cần QR ──
  if (status === "disconnected") {
    return (
      <div className="connect">
        <div className="status muted">⏸ Đã tạm ngắt Zalo (vẫn giữ đăng nhập)</div>
        <p className="hint">Bot đang tạm dừng. Bấm dưới để kết nối lại — <b>không cần quét QR</b>.</p>
        <button className="btn-primary" onClick={onReconnect}>▶ Kết nối lại</button>
        <div className="logout-row" style={{ marginTop: 10 }}>
          <button className="link-danger" onClick={onLogout}>↩ Đăng xuất / đổi tài khoản khác</button>
        </div>
      </div>
    );
  }

  // ── Chưa đăng nhập: hiện QR ──
  const qrSrc = qr ? (qr.startsWith("data:") ? qr : "data:image/png;base64," + qr) : null;
  return (
    <div className="connect">
      <GuideBox
        title="📘 Hướng dẫn nhanh — Zalo"
        steps={[
          { t: "Bước 1 · Bật dịch vụ Zalo", d: <>Mở dịch vụ Zalo (chạy <code>start-all.bat</code>, hoặc <code>cd zalo-node</code> → <code>npm start</code>). Khi đã chạy thì mã QR sẽ hiện bên dưới.</> },
          { t: "Bước 2 · Quét QR đăng nhập", d: <>Bấm <b>Tạo mã QR</b> → mở <b>Zalo</b> trên điện thoại → quét mã → xác nhận. Nên dùng tài khoản Zalo riêng cho shop.</> },
          { t: "Bước 3 · Chọn nhóm nhận báo", d: <>Sau khi đăng nhập, chọn <b>nhóm Zalo</b> để bot báo khi khách đặt phòng / cần gặp chủ, rồi bấm <b>Lưu nhóm</b>.</> },
        ]}
        note={<>Bot tự trả lời khách 24/7. Quản lý từng khách ở tab <b>Khách hàng</b>.</>}
      />
      <p className="hint">Quét mã QR bằng app Zalo trên điện thoại để bot tự trả lời khách. Mã <b>tự làm mới</b> khi hết hạn — cứ mở app Zalo quét là được.</p>
      <div className="qrbox">
        {qrSrc ? <img src={qrSrc} alt="QR" /> : <span className="muted">Đang tạo mã QR…</span>}
      </div>
      <div className={"status " + cls}>{label}</div>
      <div className="row" style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
        <button className="btn-ghost" onClick={onStartQR} disabled={status === "waiting_scan" || status === "scanned"}>
          ↻ Làm mới mã QR
        </button>
        {hasBackup && (
          <button className="btn-primary sm" onClick={onRestore}>
            ↩ Dùng lại tài khoản trước (không cần quét)
          </button>
        )}
      </div>
    </div>
  );
}
