import { useEffect, useMemo, useRef, useState } from "react";
import { broadcastApi } from "../broadcastApi.js";
import { customersApi } from "../customersApi.js";
import { ChannelTile } from "./ChannelIcon.jsx";
import { STAGES } from "./CustomersSection.jsx";

/*
 * TIN NHẮN HÀNG LOẠT (broadcast/remarketing) — chỉ CHỦ shop.
 * Soạn 1 tin → chọn kênh + nhóm khách (tất cả / còn ấm / im lặng lâu) →
 * ước lượng số người nhận → gửi. Worker backend gửi lần lượt có giãn cách
 * (throttle) để không bị nền tảng gắn cờ spam; tiến độ poll 3s.
 */

const CHANNELS = [
  { key: "zalo",     label: "Zalo cá nhân", note: "⚠️ Gửi hàng loạt dễ bị Zalo gắn cờ spam — hệ thống tự gửi chậm, nên chọn nhóm nhỏ." },
  { key: "zalooa",   label: "Zalo OA",      note: "Chỉ tới khách nhắn OA trong 48h (ngoài cửa sổ Zalo từ chối — cần ZNS, chưa hỗ trợ)." },
  { key: "meta",     label: "Mess + IG",    note: "Meta chỉ cho nhắn khách tương tác trong 24h — khách cũ hơn sẽ báo lỗi từng người." },
  { key: "telegram", label: "Telegram",     note: "Gửi thoải mái, không giới hạn cửa sổ." },
  { key: "tiktok",   label: "TikTok",       note: "Cần app được TikTok duyệt (như DM)." },
  { key: "shopee",   label: "Shopee",       note: "Cần app vendor được Shopee duyệt." },
  { key: "webchat",  label: "Website",      note: "Khách thấy tin khi mở lại trang web có gắn widget." },
];

const SEGMENTS = [
  { key: "all",      label: "Tất cả khách" },
  { key: "active",   label: "Có nhắn trong … ngày (khách còn ấm)" },
  { key: "inactive", label: "Im lặng hơn … ngày (đánh thức khách cũ)" },
  { key: "tag",      label: "Theo nhãn 🏷 (VIP, khách sỉ…)" },
  { key: "stage",    label: "Theo vòng đời (tiềm năng / khách quen…)" },
];

const ST = {
  draft:     { label: "Nháp",      color: "#8a8fa3" },
  sending:   { label: "Đang gửi…", color: "#4C6EF5" },
  done:      { label: "Hoàn tất",  color: "#23a065" },
  cancelled: { label: "Đã dừng",   color: "#d9822b" },
};

function fmtTime(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString("vi-VN"); } catch { return iso; }
}

export default function BroadcastSection() {
  // ── Form tạo chiến dịch ──
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const [chans, setChans] = useState(["zalo"]);
  const [segType, setSegType] = useState("all");
  const [days, setDays] = useState(30);
  const [segTag, setSegTag] = useState("");
  const [segStage, setSegStage] = useState("lead");
  const [allTags, setAllTags] = useState([]);
  const [preview, setPreview] = useState(null);   // {count, by_channel}
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  // ── Danh sách chiến dịch ──
  const [list, setList] = useState(null);
  const [expanded, setExpanded] = useState(null);  // id đang xem lỗi
  const [detail, setDetail] = useState(null);
  const timer = useRef(null);

  const segment = useMemo(
    () => ({ type: segType, days: Number(days) || 30, tag: segTag, stage: segStage }),
    [segType, days, segTag, segStage]);

  useEffect(() => {   // nhãn cho segment "tag" — nạp 1 lần
    customersApi.tags().then((r) => {
      if (r.ok && Array.isArray(r.body)) {
        setAllTags(r.body);
        if (r.body.length && !segTag) setSegTag(r.body[0].tag);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadList() {
    const r = await broadcastApi.list();
    if (r.ok && Array.isArray(r.body)) setList(r.body);
    else if (list === null) setList("offline");
  }
  useEffect(() => {
    loadList();
    timer.current = setInterval(loadList, 3000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { setPreview(null); }, [chans, segType, days]);

  function toggleChan(k) {
    setChans((c) => (c.includes(k) ? c.filter((x) => x !== k) : [...c, k]));
  }

  async function doPreview() {
    setMsg("");
    const r = await broadcastApi.preview(chans, segment);
    if (r.ok && r.body?.ok) setPreview(r.body);
    else setMsg("❌ " + (r.body?.error || "Không ước lượng được (server 5005 cần restart bản mới?)"));
  }

  async function doSend(sendNow) {
    if (busy) return;
    setMsg("");
    if (message.trim().length < 5) { setMsg("❌ Nội dung tin quá ngắn."); return; }
    if (!chans.length) { setMsg("❌ Chọn ít nhất 1 kênh."); return; }
    if (sendNow) {
      const r0 = preview || (await broadcastApi.preview(chans, segment)).body;
      const n = r0?.count ?? "?";
      if (!confirm(`Gửi tin này cho ${n} khách? Tin sẽ gửi lần lượt có giãn cách, không thu hồi được.`)) return;
    }
    setBusy(true);
    const r = await broadcastApi.create({ name, message: message.trim(), channels: chans, segment, send_now: sendNow });
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(sendNow ? "🚀 Đã bắt đầu gửi — theo dõi tiến độ ở danh sách bên dưới." : "✅ Đã lưu nháp.");
      setName(""); setMessage(""); setPreview(null);
      loadList();
    } else {
      setMsg("❌ " + (r.body?.error || "Không tạo được chiến dịch"));
    }
  }

  async function openErrors(b) {
    if (expanded === b.id) { setExpanded(null); setDetail(null); return; }
    setExpanded(b.id); setDetail(null);
    const r = await broadcastApi.get(b.id);
    if (r.ok && r.body?.ok) setDetail(r.body.broadcast);
  }

  return (
    <div className="bc">
      {/* ── Soạn chiến dịch ── */}
      <div className="panel bc-form">
        <h3 style={{ fontSize: 17, marginBottom: 4 }}>📣 Soạn tin gửi hàng loạt</h3>
        <p className="hint" style={{ marginBottom: 12 }}>
          Chăm sóc lại khách cũ: báo khuyến mãi, nhắc lịch, chúc lễ Tết. Tin được lưu vào
          lịch sử hội thoại từng khách; khách trả lời thì bot vẫn tiếp tục tư vấn như thường.
        </p>

        <div className="field">
          <label className="field-label">Tên chiến dịch (để bạn nhớ)</label>
          <input placeholder="VD: Khuyến mãi 20/10" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label className="field-label">Nội dung tin nhắn</label>
          <textarea rows={4} placeholder={"VD: Chào bạn! Tháng này shop giảm 10% cho khách quen…"}
                    value={message} onChange={(e) => setMessage(e.target.value)} />
        </div>

        <label className="field-label" style={{ marginTop: 4 }}>Gửi qua kênh</label>
        <div className="bc-chans">
          {CHANNELS.map((c) => (
            <label key={c.key} className={"bc-chan" + (chans.includes(c.key) ? " on" : "")}>
              <input type="checkbox" checked={chans.includes(c.key)} onChange={() => toggleChan(c.key)} />
              <ChannelTile ch={c.key} size={18} />
              <span className="bc-chan-lbl">{c.label}</span>
            </label>
          ))}
        </div>
        {chans.map((k) => {
          const c = CHANNELS.find((x) => x.key === k);
          return c ? <p key={k} className="hint bc-note">• <b>{c.label}</b>: {c.note}</p> : null;
        })}

        <label className="field-label" style={{ marginTop: 10 }}>Gửi cho nhóm khách</label>
        <div className="bc-seg">
          {SEGMENTS.map((s) => (
            <label key={s.key} className={"bc-seg-opt" + (segType === s.key ? " on" : "")}>
              <input type="radio" name="bc-seg" checked={segType === s.key} onChange={() => setSegType(s.key)} />
              <span>{s.label}</span>
            </label>
          ))}
          {(segType === "active" || segType === "inactive") && (
            <div className="bc-days">
              <input type="number" min="1" max="365" value={days}
                     onChange={(e) => setDays(e.target.value)} /> ngày
            </div>
          )}
          {segType === "tag" && (
            <div className="bc-days">
              {allTags.length === 0
                ? <span className="hint">Chưa có nhãn nào — gắn nhãn cho khách ở mục Khách hàng trước.</span>
                : (
                  <select value={segTag} onChange={(e) => setSegTag(e.target.value)} style={{ width: "auto" }}>
                    {allTags.map((t) => <option key={t.tag} value={t.tag}>🏷 {t.tag} ({t.count} khách)</option>)}
                  </select>
                )}
            </div>
          )}
          {segType === "stage" && (
            <div className="bc-days">
              <select value={segStage} onChange={(e) => setSegStage(e.target.value)} style={{ width: "auto" }}>
                {Object.entries(STAGES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14, flexWrap: "wrap" }}>
          <button className="btn-outline" style={{ width: "auto" }} onClick={doPreview}>
            🔎 Ước lượng người nhận
          </button>
          {preview && (
            <span className="bc-est">
              ≈ <b>{preview.count}</b> khách
              {Object.entries(preview.by_channel || {}).map(([k, n]) =>
                ` · ${CHANNELS.find((c) => c.key === k)?.label || k}: ${n}`).join("")}
            </span>
          )}
          <button className="btn-primary sm" style={{ width: "auto" }} disabled={busy} onClick={() => doSend(true)}>
            {busy ? "Đang xử lý…" : "🚀 Gửi ngay"}
          </button>
          <button className="btn-mini" onClick={() => doSend(false)} disabled={busy}>💾 Lưu nháp</button>
        </div>
        {msg && <div className="savemsg" style={{ marginTop: 10 }}>{msg}</div>}
      </div>

      {/* ── Danh sách chiến dịch ── */}
      <div className="panel bc-list">
        <h3 style={{ fontSize: 17, marginBottom: 10 }}>Chiến dịch đã tạo</h3>
        {list === null && <p className="hint">Đang tải…</p>}
        {list === "offline" && <p className="hint">⚠️ Chưa kết nối máy chủ (cổng 5005) — hoặc server cần restart bản mới.</p>}
        {Array.isArray(list) && list.length === 0 && <p className="hint">Chưa có chiến dịch nào.</p>}
        {Array.isArray(list) && list.map((b) => {
          const st = ST[b.status] || ST.draft;
          const pct = b.total ? Math.round(((b.sent + b.failed) / b.total) * 100) : 0;
          return (
            <div key={b.id} className="bc-item">
              <div className="bc-item-head">
                <div>
                  <b>{b.name}</b>
                  <span className="bc-item-sub"> · {fmtTime(b.created_at)}
                    {(b.channels || []).map((k) => ` · ${CHANNELS.find((c) => c.key === k)?.label || k}`).join("")}
                  </span>
                </div>
                <span className="bc-status" style={{ "--c": st.color }}>{st.label}</span>
              </div>
              <div className="bc-item-msg">{b.message}</div>
              {(b.status === "sending" || b.total > 0) && (
                <div className="bc-progress">
                  <div className="bc-bar"><i style={{ width: pct + "%" }} /></div>
                  <span className="hint">
                    ✅ {b.sent} gửi · ❌ {b.failed} lỗi / {b.total} khách
                  </span>
                </div>
              )}
              <div className="bc-item-actions">
                {b.status === "draft" && (
                  <button className="btn-mini" onClick={async () => { await broadcastApi.send(b.id); loadList(); }}>
                    🚀 Gửi
                  </button>
                )}
                {b.status === "sending" && (
                  <button className="btn-mini danger" onClick={async () => { await broadcastApi.cancel(b.id); loadList(); }}>
                    ⏹ Dừng
                  </button>
                )}
                {b.failed > 0 && (
                  <button className="btn-mini" onClick={() => openErrors(b)}>
                    {expanded === b.id ? "Ẩn lỗi" : `Xem lỗi (${b.failed})`}
                  </button>
                )}
              </div>
              {expanded === b.id && (
                <div className="bc-errors">
                  {!detail ? <p className="hint">Đang tải…</p> :
                    (detail.errors || []).length === 0 ? <p className="hint">Không có lỗi.</p> :
                    detail.errors.map((e) => (
                      <div key={e.id} className="bc-err">
                        <code>{e.user_id}</code> — {e.error || "lỗi không rõ"}
                      </div>
                    ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
