import { useState, useRef, useEffect } from "react";
import { useI18n } from "../i18n.jsx";

// Ô soạn tin cho dashboard — dùng chung mọi kênh.
// Props:
//   onSend(text) → Promise<bool>       gửi text (bắt buộc)
//   onSendMedia(file, caption) → bool  gửi ảnh/video/ghi âm (tuỳ chọn — có thì hiện nút đính kèm/ghi âm)
//   onAction(key) → bool               thao tác mẫu, vd "make_order" (tuỳ chọn — có thì hiện tab Thao tác)
//   canned: [{id,title,content}]       câu trả lời mẫu (tuỳ chọn — có thì hiện tab Mẫu)
//   disabled
export default function ChatSend({ onSend, onSendMedia, onAction, canned, disabled = false }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState(null);         // null | 'reply' | 'action'
  const [rec, setRec] = useState(null);         // MediaRecorder đang ghi | null
  const [recSec, setRecSec] = useState(0);
  const ref = useRef(null);
  const fileRef = useRef(null);
  const recRef = useRef(null);   // {timer}

  async function send() {
    const txt = text.trim();
    if (!txt || sending) return;
    setSending(true); setErr("");
    const ok = await onSend(txt);
    setSending(false);
    if (ok) { setText(""); ref.current?.focus(); }
    else setErr(t("chat.send_fail"));
  }
  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  // ── Đính kèm ảnh/video ──
  async function pickFile(e) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f || !onSendMedia) return;
    setErr(""); setSending(true);
    const ok = await onSendMedia(f, text.trim());
    setSending(false);
    if (ok) setText("");
    else setErr(t("chat.file_fail"));
  }

  // ── Ghi âm ──
  async function toggleRecord() {
    if (rec) { rec.stop(); return; }   // đang ghi → dừng (onstop tự gửi)
    if (!onSendMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks = [];
      mr.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data);
      mr.onstop = async () => {
        clearInterval(recRef.current?.timer);
        stream.getTracks().forEach((t) => t.stop());
        setRec(null); setRecSec(0);
        const blob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
        if (blob.size < 800) return;   // bấm nhầm, quá ngắn
        const ext = (mr.mimeType || "").includes("ogg") ? "ogg" : "webm";
        const file = new File([blob], `ghiam.${ext}`, { type: blob.type });
        setSending(true);
        const ok = await onSendMedia(file, text.trim());
        setSending(false);
        if (ok) setText(""); else setErr(t("chat.rec_fail"));
      };
      mr.start();
      const timer = setInterval(() => setRecSec((s) => s + 1), 1000);
      recRef.current = { timer };
      setRec(mr);
    } catch {
      setErr(t("chat.mic_fail"));
    }
  }
  useEffect(() => () => { try { rec?.stop(); } catch { /* ignore */ } }, [rec]);

  async function runAction(key, label) {
    setErr(""); setTab(null); setSending(true);
    const ok = await onAction?.(key);
    setSending(false);
    if (!ok) setErr(t("chat.action_fail", { label }));
  }

  const busy = sending || disabled;
  const showTools = onSendMedia || onAction || canned;

  return (
    <div className="cs-wrap">
      {/* Panel Mẫu / Thao tác */}
      {tab && (
        <div className="cs-panel">
          <div className="cs-panel-tabs">
            {canned && (
              <button className={"cs-ptab" + (tab === "reply" ? " active" : "")} onClick={() => setTab("reply")}>
                {t("chat.tab_canned")}
              </button>
            )}
            {onAction && (
              <button className={"cs-ptab" + (tab === "action" ? " active" : "")} onClick={() => setTab("action")}>
                {t("chat.tab_actions")}
              </button>
            )}
            <button className="cs-pclose" onClick={() => setTab(null)}>✕</button>
          </div>
          {tab === "reply" && (
            <div className="cs-canned">
              {(!canned || canned.length === 0)
                ? <p className="hint">{t("chat.canned_empty_pre")}<b>{t("chat.canned_empty_bold")}</b>{t("chat.canned_empty_post")}</p>
                : canned.map((c) => (
                    <button key={c.id} className="cs-canned-item" title={c.content}
                            onClick={() => { setText((prev) => (prev ? prev + " " : "") + c.content); setTab(null); ref.current?.focus(); }}>
                      <b>{c.title}</b><span>{c.content}</span>
                    </button>
                  ))}
            </div>
          )}
          {tab === "action" && (
            <div className="cs-actions">
              <button className="cs-action" disabled={busy} onClick={() => runAction("make_order", t("chat.make_order"))}>
                🧾 <div><b>{t("chat.make_order")}</b><span>{t("chat.make_order_desc")}</span></div>
              </button>
            </div>
          )}
        </div>
      )}

      {/* Thanh công cụ */}
      {showTools && (
        <div className="cs-toolbar">
          {onSendMedia && (
            <>
              <button className="cs-tool" title={t("chat.attach_title")} disabled={busy} onClick={() => fileRef.current?.click()}>{t("chat.attach")}</button>
              <button className={"cs-tool" + (rec ? " rec" : "")} title={t("chat.record_title")} disabled={busy && !rec} onClick={toggleRecord}>
                {rec ? t("chat.stop_rec", { s: recSec }) : t("chat.record")}
              </button>
              <input ref={fileRef} type="file" accept="image/*,video/*" hidden onChange={pickFile} />
            </>
          )}
          {canned && (
            <button className="cs-tool" disabled={busy} onClick={() => setTab(tab === "reply" ? null : "reply")}>{t("chat.tool_canned")}</button>
          )}
          {onAction && (
            <button className="cs-tool" disabled={busy} onClick={() => setTab(tab === "action" ? null : "action")}>{t("chat.tab_actions")}</button>
          )}
        </div>
      )}

      <div className="chat-input-area">
        <textarea
          ref={ref}
          className="chat-input"
          rows={2}
          placeholder={t("chat.input_ph")}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          disabled={busy}
        />
        <button className="btn-primary sm" onClick={send} disabled={busy || !text.trim()}>
          {sending ? t("chat.sending") : t("chat.send")}
        </button>
      </div>
      {err && <div className="chat-send-err">{err}</div>}
    </div>
  );
}
