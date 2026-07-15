import { useEffect, useRef, useState } from "react";
import { zalo } from "../zaloApi.js";
import GuideBox from "./GuideBox.jsx";
import { useI18n } from "../i18n.jsx";

// [key i18n, class] — dịch bằng t() lúc render
const LABELS = {
  checking: ["cn.zalo_st_checking", "muted"],
  offline: ["cn.zalo_st_offline", "warn"],
  idle: ["cn.zalo_st_idle", "muted"],
  waiting_scan: ["cn.zalo_st_waiting", "muted"],
  scanned: ["cn.zalo_st_scanned", "ok"],
  logged_in: ["cn.zalo_connected", "ok"],
  qr_expired: ["cn.zalo_st_qr_expired", "muted"],
  disconnected: ["cn.zalo_st_disconnected", "muted"],
  declined: ["cn.zalo_st_declined", "warn"],
  error: ["cn.zalo_st_error", "warn"],
};

export default function ZaloConnect() {
  const { t } = useI18n();
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
    setSaveMsg(ok ? t("cn.zalo_group_saved") : t("cn.zalo_group_save_fail"));
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
    if (!confirm(t("cn.zalo_logout_confirm"))) return;
    try { await zalo.logout(accRef.current); } catch { /* ignore */ }
    autoRef.current = "";   // cho phép tự mở lại QR ngay sau đăng xuất
    setStatus("idle"); setQr(null); setOwnId(null); setGroups([]); setSelGroup("");
    startPoll(); poll();
  }

  useEffect(() => { startPoll(); poll(); return stopPoll; }, []);

  const [labelKey, cls] = LABELS[status] || [null, "muted"];
  const label = labelKey ? t(labelKey) : "…";

  // ── Dịch vụ Node chưa chạy ──
  if (status === "offline") {
    return (
      <div className="connect">
        <div className="status warn">{t("cn.zalo_offline_title")}</div>
        <p className="hint">{t("cn.zalo_offline_hint")}</p>
        <pre className="code">cd zalo-node{"\n"}npm start</pre>
        <button className="btn-primary" onClick={poll}>{t("cn.retry")}</button>
      </div>
    );
  }

  // ── Đã đăng nhập: chọn nhóm + đăng xuất ──
  if (status === "logged_in") {
    return (
      <div className="connect">
        <div className="status ok">{t("cn.zalo_connected")}</div>
        {ownId && <p className="hint">{t("cn.zalo_account_id", { id: ownId })}</p>}

        <div className="field">
          <label>{t("cn.zalo_group_label")}</label>
          <p className="hint">{t("cn.zalo_group_hint")}</p>
          {groups.length === 0 ? (
            <p className="hint warn">{t("cn.zalo_no_groups")}</p>
          ) : (
            <select value={selGroup} onChange={(e) => setSelGroup(e.target.value)}>
              <option value="">{t("cn.zalo_group_placeholder")}</option>
              {groups.map((g) => (
                <option key={g.groupId} value={g.groupId}>{g.name || g.groupId}</option>
              ))}
            </select>
          )}
          <div className="row">
            <button className="btn-primary sm" onClick={onSaveGroup} disabled={!groups.length}>{t("cn.zalo_save_group")}</button>
            <button className="btn-ghost" onClick={loadGroups}>{t("cn.reload")}</button>
          </div>
          {saveMsg && <div className="savemsg">{saveMsg}</div>}
        </div>

        <div className="logout-row" style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <button className="btn-ghost" onClick={onDisconnect}>{t("cn.zalo_pause_btn")}</button>
          <button className="link-danger" onClick={onLogout}>{t("cn.zalo_logout_btn")}</button>
        </div>
        <p className="hint" style={{ marginTop: 8 }}>
          <b>{t("cn.zalo_pause_word")}</b>: {t("cn.zalo_pause_desc")}
          <br /><b>{t("cn.zalo_logout_word")}</b>: {t("cn.zalo_logout_desc")}
        </p>
      </div>
    );
  }

  // ── Đã tạm ngắt: kết nối lại không cần QR ──
  if (status === "disconnected") {
    return (
      <div className="connect">
        <div className="status muted">{t("cn.zalo_paused_title")}</div>
        <p className="hint">{t("cn.zalo_paused_hint")} <b>{t("cn.zalo_paused_noqr")}</b>.</p>
        <button className="btn-primary" onClick={onReconnect}>{t("cn.zalo_reconnect")}</button>
        <div className="logout-row" style={{ marginTop: 10 }}>
          <button className="link-danger" onClick={onLogout}>{t("cn.zalo_logout_btn2")}</button>
        </div>
      </div>
    );
  }

  // ── Chưa đăng nhập: hiện QR ──
  const qrSrc = qr ? (qr.startsWith("data:") ? qr : "data:image/png;base64," + qr) : null;
  return (
    <div className="connect">
      <GuideBox
        title={t("cn.zalo_guide_title")}
        steps={[
          { t: t("cn.zalo_g1_t"), d: <>{t("cn.zalo_g1_d1")} <code>start-all.bat</code>{t("cn.zalo_g1_d2")} <code>cd zalo-node</code> → <code>npm start</code>{t("cn.zalo_g1_d3")}</> },
          { t: t("cn.zalo_g2_t"), d: <>{t("cn.zalo_g2_d1")} <b>{t("cn.zalo_g2_qr")}</b> {t("cn.zalo_g2_d2")} <b>Zalo</b> {t("cn.zalo_g2_d3")}</> },
          { t: t("cn.zalo_g3_t"), d: <>{t("cn.zalo_g3_d1")} <b>{t("cn.zalo_g3_b1")}</b> {t("cn.zalo_g3_d2")} <b>{t("cn.zalo_save_group")}</b>.</> },
        ]}
        note={<>{t("cn.zalo_note1")} <b>{t("cn.tab_customers")}</b>.</>}
      />
      <p className="hint">{t("cn.zalo_scan_hint1")} <b>{t("cn.zalo_scan_hint_b")}</b> {t("cn.zalo_scan_hint2")}</p>
      <div className="qrbox">
        {qrSrc ? <img src={qrSrc} alt="QR" /> : <span className="muted">{t("cn.qr_creating")}</span>}
      </div>
      <div className={"status " + cls}>{label}</div>
      <div className="row" style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
        <button className="btn-ghost" onClick={onStartQR} disabled={status === "waiting_scan" || status === "scanned"}>
          {t("cn.zalo_refresh_qr")}
        </button>
        {hasBackup && (
          <button className="btn-primary sm" onClick={onRestore}>
            {t("cn.zalo_restore")}
          </button>
        )}
      </div>
    </div>
  );
}
