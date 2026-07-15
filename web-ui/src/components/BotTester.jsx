import { useEffect, useRef, useState } from "react";
import { promptApi } from "../promptApi.js";
import { billing } from "../billingApi.js";
import { PHOTO_BASE } from "../photoApi.js";
import { useI18n } from "../i18n.jsx";

/*
 * Test Bot AI — chat thử với bộ não đang dùng (AI THẬT), kèm chẩn đoán từng
 * câu: chế độ (lai/cũ), intent, các mẩu tri thức bot đã tra. KHÔNG lưu session,
 * KHÔNG gửi tới khách nào. Stateless: lịch sử giữ ở UI, gửi lên mỗi lần.
 */

const MODE_KEY = { hybrid: "bt.mode_hybrid", legacy: "bt.mode_legacy" };

function Diag({ d, intent }) {
  const { t } = useI18n();
  if (!d) return null;
  return (
    <div className="bt-diag">
      <span className="bt-chip">{MODE_KEY[d.mode] ? t(MODE_KEY[d.mode]) : d.mode}</span>
      {intent && <span className="bt-chip">🎯 {intent}</span>}
      {d.mode === "hybrid" && (
        d.chunks?.length
          ? <span className="bt-chip bt-kb" title={t("bt.kb_title")}>
              📚 {d.chunks.map((c) => c.title).join(" · ")}
            </span>
          : <span className="bt-chip">{t("bt.kb_none")}</span>
      )}
      {d.system_chars && <span className="bt-chip bt-dim">{t("bt.ctx_chars", { n: (d.system_chars / 1000).toFixed(1) })}</span>}
    </div>
  );
}

export default function BotTester({ onClose }) {
  const { t: tr } = useI18n();
  const [msgs, setMsgs] = useState([]);   // {role, content, debug?, intent?}
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [models, setModels] = useState([]);  // catalog model (từ /billing/me)
  const [model, setModel] = useState("");     // model thử ("" = model shop đang dùng)
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    billing.me().then((r) => {
      if (r.ok && Array.isArray(r.body?.ai_models)) setModels(r.body.ai_models);
    });
  }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);
  useEffect(() => {
    inputRef.current?.focus();
    function esc(e) { if (e.key === "Escape" && onClose) onClose(); }
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  async function send() {
    const t = text.trim();
    if (!t || busy) return;
    setErr(""); setText("");
    const history = msgs.map((m) => ({ role: m.role, content: m.content }));
    setMsgs((ms) => [...ms, { role: "user", content: t }]);
    setBusy(true);
    const r = await promptApi.test(t, history, model);
    setBusy(false);
    if (r.ok && r.body?.reply != null) {
      setMsgs((ms) => [...ms, {
        role: "assistant", content: r.body.reply,
        debug: r.body.debug, intent: r.body.intent,
        photos: r.body.photos || [],
      }]);
    } else {
      setErr("❌ " + (r.body?.error || (r.status === 0 ? tr("bt.err_conn") : tr("bt.err_ai"))));
    }
    inputRef.current?.focus();
  }

  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  return (
    <div className="bt-modal-bg" onClick={onClose}>
    <div className="bt-modal" onClick={(e) => e.stopPropagation()}>
      <div className="bt-head">
        <div className="bt-head-title">
          <b>{tr("bt.title")}</b>
          <span className="hint">{tr("bt.subtitle")}</span>
          <select className="bt-model" value={model} onChange={(e) => setModel(e.target.value)}
                  title={tr("bt.model_title")}>
            <option value="">{tr("bt.model_default")}</option>
            {models.map((m) => (
              <option key={m.key} value={m.key} disabled={!m.available}>
                {m.label}{m.available ? "" : tr("bt.no_key")}
              </option>
            ))}
          </select>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {msgs.length > 0 && (
            <button className="btn-mini" onClick={() => { setMsgs([]); setErr(""); }}>{tr("bt.reset")}</button>
          )}
          {onClose && <button className="btn-mini" onClick={onClose}>{tr("bt.close")}</button>}
        </div>
      </div>

      <div className="bt-body">
        {msgs.length === 0 && !busy && (
          <div className="bt-empty">
            <div style={{ fontSize: 34 }}>🤖</div>
            <p className="hint">{tr("bt.empty1")}<br />
              {tr("bt.empty2")}</p>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={"bt-msg " + (m.role === "user" ? "u" : "b")}>
            <div className={"bubble " + (m.role === "user" ? "b-user" : "b-bot")}>{m.content}</div>
            {/* Ảnh bot SẼ gửi kèm (bảng giá / ảnh phòng / bộ ảnh thư viện) */}
            {m.role === "assistant" && m.photos?.length > 0 && (
              <div className="bt-photos">
                {m.photos.map((p, j) => (
                  <figure key={j} className="bt-photo">
                    <img src={PHOTO_BASE + p.url} alt={p.caption} loading="lazy" />
                    <figcaption>{p.caption}</figcaption>
                  </figure>
                ))}
              </div>
            )}
            {m.role === "assistant" && <Diag d={m.debug} intent={m.intent} />}
          </div>
        ))}
        {busy && (
          <div className="bt-msg b">
            <div className="bubble b-bot bt-typing">{tr("bt.typing")}<span>.</span><span>.</span><span>.</span></div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {err && <div className="chat-send-err" style={{ padding: "0 14px" }}>{err}</div>}

      <div className="bt-input">
        <textarea
          ref={inputRef} rows={2} className="chat-input"
          placeholder={tr("bt.input_ph")}
          value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
          disabled={busy}
        />
        <button className="btn-primary sm" onClick={send} disabled={busy || !text.trim()}>
          {busy ? "…" : tr("bt.send")}
        </button>
      </div>
    </div>
    </div>
  );
}
