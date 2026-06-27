import { useEffect, useRef, useState } from "react";
import { zalo } from "../zaloApi.js";
import GuideBox from "./GuideBox.jsx";

const LABELS = {
  checking: ["Đang kiểm tra kết nối…", "muted"],
  offline: ["Chưa chạy dịch vụ Zalo", "warn"],
  idle: ["Chưa kết nối", "muted"],
  waiting_scan: ["Đang chờ quét mã QR…", "muted"],
  scanned: ["Đã quét! Xác nhận trên điện thoại…", "ok"],
  logged_in: ["✅ Đã kết nối Zalo", "ok"],
  qr_expired: ["Mã QR hết hạn, tạo lại nhé", "warn"],
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
  const timer = useRef(null);

  function stopPoll() { if (timer.current) clearInterval(timer.current); timer.current = null; }
  function startPoll() { stopPoll(); timer.current = setInterval(poll, 2000); }

  async function poll() {
    try {
      const { ok, body } = await zalo.status();
      // Lỗi mạng / Node chưa chạy → giữ trạng thái offline NHƯNG tiếp tục dò lại,
      // để khi Node bật lên thì tự động kết nối, không cần bấm "Thử lại".
      if (!ok) { setStatus("offline"); return; }
      setStatus(body.status);
      setQr(body.qr || null);
      setOwnId(body.ownId || null);
      if (body.status === "logged_in") { stopPoll(); loadGroups(); }
    } catch {
      setStatus("offline");
    }
  }

  async function loadGroups() {
    try {
      const [g, cfg] = await Promise.all([zalo.groups(), zalo.getConfig()]);
      setGroups(g.body.groups || []);
      setSelGroup(cfg.body.ownerGroupId || "");
    } catch { /* ignore */ }
  }

  async function onStartQR() {
    setSaveMsg("");
    try { await zalo.startQR(); startPoll(); poll(); }
    catch { setStatus("offline"); }
  }

  async function onSaveGroup() {
    const { ok } = await zalo.saveGroup(selGroup);
    setSaveMsg(ok ? "✅ Đã lưu nhóm nhận thông báo" : "❌ Lưu thất bại");
  }

  async function onLogout() {
    if (!confirm("Đăng xuất tài khoản Zalo hiện tại để đăng nhập lại?")) return;
    try { await zalo.logout(); } catch { /* ignore */ }
    setStatus("idle"); setQr(null); setOwnId(null); setGroups([]); setSelGroup("");
    poll();
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

        <div className="logout-row">
          <button className="link-danger" onClick={onLogout}>↩ Đăng xuất / đổi tài khoản</button>
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
          { t: "Bước 2 · Quét QR đăng nhập", d: <>Bấm <b>Tạo mã QR</b> → mở <b>Zalo</b> trên điện thoại → quét mã → xác nhận. Nên dùng tài khoản Zalo riêng cho homestay.</> },
          { t: "Bước 3 · Chọn nhóm nhận báo", d: <>Sau khi đăng nhập, chọn <b>nhóm Zalo</b> để bot báo khi khách đặt phòng / cần gặp chủ, rồi bấm <b>Lưu nhóm</b>.</> },
        ]}
        note={<>Bot tự trả lời khách 24/7. Quản lý từng khách ở tab <b>Khách hàng</b>.</>}
      />
      <p className="hint">Quét mã QR bằng app Zalo trên điện thoại để bot tự trả lời khách.</p>
      <div className="qrbox">
        {qrSrc ? <img src={qrSrc} alt="QR" /> : <span className="muted">Nhấn nút bên dưới để tạo mã QR</span>}
      </div>
      <div className={"status " + cls}>{label}</div>
      <button className="btn-primary" onClick={onStartQR} disabled={status === "waiting_scan" || status === "scanned"}>
        {qrSrc ? "Tạo mã QR mới" : "Tạo mã QR đăng nhập"}
      </button>
    </div>
  );
}
