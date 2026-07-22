import { useEffect, useMemo, useRef, useState } from "react";
import { broadcastApi } from "../broadcastApi.js";
import { customersApi } from "../customersApi.js";
import { ChannelTile } from "./ChannelIcon.jsx";
import { STAGES } from "./CustomersSection.jsx";
import { useI18n } from "../i18n.jsx";

/*
 * TIN NHẮN HÀNG LOẠT (broadcast/remarketing) — chỉ CHỦ shop.
 * Soạn 1 tin → chọn kênh + nhóm khách (tất cả / còn ấm / im lặng lâu) →
 * ước lượng số người nhận → gửi. Worker backend gửi lần lượt có giãn cách
 * (throttle) để không bị nền tảng gắn cờ spam; tiến độ poll 3s.
 * Label kênh/segment/trạng thái: key i18n "bc.*" (i18n/campaigns.js).
 */

const CHANNELS = ["zalo", "zalooa", "meta", "telegram", "shopee", "webchat"];

const SEGMENTS = ["all", "active", "inactive", "tag", "stage"];

const ST_COLOR = {
  draft:     "#8a8fa3",
  sending:   "#4C6EF5",
  done:      "#23a065",
  cancelled: "#d9822b",
};

function fmtTime(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString("vi-VN"); } catch { return iso; }
}

export default function BroadcastSection() {
  const { t } = useI18n();

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

  const chLabel = (k) => (CHANNELS.includes(k) ? t("bc.ch." + k) : k);

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
    else setMsg("❌ " + (r.body?.error || t("bc.preview_fail")));
  }

  async function doSend(sendNow) {
    if (busy) return;
    setMsg("");
    if (message.trim().length < 5) { setMsg(t("bc.err_short")); return; }
    if (!chans.length) { setMsg(t("bc.err_nochan")); return; }
    if (sendNow) {
      const r0 = preview || (await broadcastApi.preview(chans, segment)).body;
      const n = r0?.count ?? "?";
      if (!confirm(t("bc.confirm_send", { n }))) return;
    }
    setBusy(true);
    const r = await broadcastApi.create({ name, message: message.trim(), channels: chans, segment, send_now: sendNow });
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(sendNow ? t("bc.started") : t("bc.saved_draft"));
      setName(""); setMessage(""); setPreview(null);
      loadList();
    } else {
      setMsg("❌ " + (r.body?.error || t("bc.create_fail")));
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
        <h3 style={{ fontSize: 17, marginBottom: 4 }}>{t("bc.title")}</h3>
        <p className="hint" style={{ marginBottom: 12 }}>{t("bc.desc")}</p>

        <div className="field">
          <label className="field-label">{t("bc.name_label")}</label>
          <input placeholder={t("bc.name_ph")} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label className="field-label">{t("bc.msg_label")}</label>
          <textarea rows={4} placeholder={t("bc.msg_ph")}
                    value={message} onChange={(e) => setMessage(e.target.value)} />
        </div>

        <label className="field-label" style={{ marginTop: 4 }}>{t("bc.channels_label")}</label>
        <div className="bc-chans">
          {CHANNELS.map((k) => (
            <label key={k} className={"bc-chan" + (chans.includes(k) ? " on" : "")}>
              <input type="checkbox" checked={chans.includes(k)} onChange={() => toggleChan(k)} />
              <ChannelTile ch={k} size={18} />
              <span className="bc-chan-lbl">{t("bc.ch." + k)}</span>
            </label>
          ))}
        </div>
        {chans.map((k) => (
          CHANNELS.includes(k)
            ? <p key={k} className="hint bc-note">• <b>{t("bc.ch." + k)}</b>: {t("bc.ch." + k + "_note")}</p>
            : null
        ))}

        <label className="field-label" style={{ marginTop: 10 }}>{t("bc.seg_label")}</label>
        <div className="bc-seg">
          {SEGMENTS.map((s) => (
            <label key={s} className={"bc-seg-opt" + (segType === s ? " on" : "")}>
              <input type="radio" name="bc-seg" checked={segType === s} onChange={() => setSegType(s)} />
              <span>{t("bc.seg." + s)}</span>
            </label>
          ))}
          {(segType === "active" || segType === "inactive") && (
            <div className="bc-days">
              <input type="number" min="1" max="365" value={days}
                     onChange={(e) => setDays(e.target.value)} /> {t("bc.days_unit")}
            </div>
          )}
          {segType === "tag" && (
            <div className="bc-days">
              {allTags.length === 0
                ? <span className="hint">{t("bc.no_tags")}</span>
                : (
                  <select value={segTag} onChange={(e) => setSegTag(e.target.value)} style={{ width: "auto" }}>
                    {allTags.map((tg) => (
                      <option key={tg.tag} value={tg.tag}>
                        {t("bc.tag_opt", { tag: tg.tag, count: tg.count })}
                      </option>
                    ))}
                  </select>
                )}
            </div>
          )}
          {segType === "stage" && (
            <div className="bc-days">
              <select value={segStage} onChange={(e) => setSegStage(e.target.value)} style={{ width: "auto" }}>
                {Object.entries(STAGES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {t("cust.stage." + k) === "cust.stage." + k ? v.label : t("cust.stage." + k)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14, flexWrap: "wrap" }}>
          <button className="btn-outline" style={{ width: "auto" }} onClick={doPreview}>
            {t("bc.preview_btn")}
          </button>
          {preview && (
            <span className="bc-est">
              ≈ <b>{preview.count}</b> {t("bc.est_unit")}
              {Object.entries(preview.by_channel || {}).map(([k, n]) =>
                ` · ${chLabel(k)}: ${n}`).join("")}
            </span>
          )}
          <button className="btn-primary sm" style={{ width: "auto" }} disabled={busy} onClick={() => doSend(true)}>
            {busy ? t("bc.processing") : t("bc.send_now")}
          </button>
          <button className="btn-mini" onClick={() => doSend(false)} disabled={busy}>{t("bc.save_draft")}</button>
        </div>
        {msg && <div className="savemsg" style={{ marginTop: 10 }}>{msg}</div>}
      </div>

      {/* ── Danh sách chiến dịch ── */}
      <div className="panel bc-list">
        <h3 style={{ fontSize: 17, marginBottom: 10 }}>{t("bc.list_title")}</h3>
        {list === null && <p className="hint">{t("team.loading")}</p>}
        {list === "offline" && <p className="hint">{t("team.offline")}</p>}
        {Array.isArray(list) && list.length === 0 && <p className="hint">{t("bc.none")}</p>}
        {Array.isArray(list) && list.map((b) => {
          const stKey = ST_COLOR[b.status] ? b.status : "draft";
          const pct = b.total ? Math.round(((b.sent + b.failed) / b.total) * 100) : 0;
          return (
            <div key={b.id} className="bc-item">
              <div className="bc-item-head">
                <div>
                  <b>{b.name}</b>
                  <span className="bc-item-sub"> · {fmtTime(b.created_at)}
                    {(b.channels || []).map((k) => ` · ${chLabel(k)}`).join("")}
                  </span>
                </div>
                <span className="bc-status" style={{ "--c": ST_COLOR[stKey] }}>{t("bc.st." + stKey)}</span>
              </div>
              <div className="bc-item-msg">{b.message}</div>
              {(b.status === "sending" || b.total > 0) && (
                <div className="bc-progress">
                  <div className="bc-bar"><i style={{ width: pct + "%" }} /></div>
                  <span className="hint">
                    {t("bc.progress", { sent: b.sent, failed: b.failed, total: b.total })}
                  </span>
                </div>
              )}
              <div className="bc-item-actions">
                {b.status === "draft" && (
                  <button className="btn-mini" onClick={async () => { await broadcastApi.send(b.id); loadList(); }}>
                    {t("bc.send_btn")}
                  </button>
                )}
                {b.status === "sending" && (
                  <button className="btn-mini danger" onClick={async () => { await broadcastApi.cancel(b.id); loadList(); }}>
                    {t("bc.stop_btn")}
                  </button>
                )}
                {b.failed > 0 && (
                  <button className="btn-mini" onClick={() => openErrors(b)}>
                    {expanded === b.id ? t("bc.hide_errors") : t("bc.view_errors", { n: b.failed })}
                  </button>
                )}
              </div>
              {expanded === b.id && (
                <div className="bc-errors">
                  {!detail ? <p className="hint">{t("team.loading")}</p> :
                    (detail.errors || []).length === 0 ? <p className="hint">{t("bc.no_errors")}</p> :
                    detail.errors.map((e) => (
                      <div key={e.id} className="bc-err">
                        <code>{e.user_id}</code> — {e.error || t("bc.unknown_error")}
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
