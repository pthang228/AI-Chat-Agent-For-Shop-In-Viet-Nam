// KHO MẪU HỘI THOẠI (Style RAG) — dạy bot GIỌNG + cách xử lý tình huống.
// Khác kho tri thức (fact): mẫu ở đây KHÔNG chứa số liệu (đã thay placeholder),
// bot chỉ học cách nói. Nguồn nạp: nút ⭐ trong Hội thoại, bot học từ chủ trả lời
// tay (hàng chờ duyệt), hoặc dán transcript / mô tả giọng cho AI sinh bộ mẫu ở đây.
import { useEffect, useState } from "react";
import { promptApi } from "../promptApi.js";
import { useI18n } from "../i18n.jsx";

export default function StyleLibrary() {
  const { t } = useI18n();
  const [chunks, setChunks] = useState(null);   // null = đang tải
  const [max, setMax] = useState(80);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(null); // list mẫu AI sinh (chưa lưu)
  const [picked, setPicked] = useState({});     // index → bool
  const [msg, setMsg] = useState("");

  async function load() {
    const r = await promptApi.styleList();
    if (r.ok && r.body?.ok) {
      setChunks(r.body.chunks || []);
      setMax(r.body.max || 80);
    } else setChunks([]);
  }
  useEffect(() => { load(); }, []);

  async function onGenerate() {
    setMsg(""); setBusy(true); setPreview(null);
    const r = await promptApi.styleGenerate(text);
    setBusy(false);
    if (r.ok && r.body?.ok && (r.body.chunks || []).length) {
      setPreview(r.body.chunks);
      setPicked(Object.fromEntries(r.body.chunks.map((_, i) => [i, true])));
    } else {
      setMsg("❌ " + (r.body?.error || t("sl.gen_fail")));
    }
  }

  async function onSavePicked() {
    const sel = (preview || []).filter((_, i) => picked[i]);
    if (!sel.length) return;
    setBusy(true);
    const r = await promptApi.styleAdd(sel);
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(t("sl.saved", { n: r.body.added }));
      setPreview(null); setText("");
      setChunks(r.body.chunks || []);
    } else {
      setMsg("❌ " + (r.body?.error || t("sl.save_fail")));
    }
  }

  async function onDelete(id) {
    if (!confirm(t("sl.del_confirm"))) return;
    const r = await promptApi.styleDelete(id);
    if (r.ok) load();
  }

  return (
    <div className="panel set-card" style={{ margin: "16px 0" }}>
      <h3 style={{ fontSize: 16, marginBottom: 4 }}>🎭 {t("sl.title")}</h3>
      <p className="hint">{t("sl.desc")}</p>

      {/* Kho hiện có */}
      {chunks === null ? (
        <p className="hint">{t("team.loading")}</p>
      ) : chunks.length === 0 ? (
        <p className="hint">{t("sl.empty")}</p>
      ) : (
        <>
          <p className="hint">{t("sl.count", { n: chunks.length, max })}</p>
          <div className="sl-list">
            {chunks.map((c) => (
              <details key={c.id} className="sl-item">
                <summary>
                  <b>{c.title || t("sl.untitled")}</b>
                  {c.intent && <span className="sl-intent">{c.intent}</span>}
                  <button className="btn-mini danger" style={{ float: "right" }}
                          onClick={(e) => { e.preventDefault(); onDelete(c.id); }}>
                    {t("team.del")}
                  </button>
                </summary>
                <pre className="sl-content">{c.content}</pre>
              </details>
            ))}
          </div>
        </>
      )}

      {/* Sinh bộ mẫu từ transcript / mô tả giọng */}
      <div style={{ marginTop: 14 }}>
        <label className="field-label">{t("sl.gen_label")}</label>
        <textarea rows={5} value={text} onChange={(e) => setText(e.target.value)}
                  placeholder={t("sl.gen_ph")} style={{ width: "100%" }} />
        <button className="btn-primary" disabled={busy || text.trim().length < 20}
                onClick={onGenerate} style={{ marginTop: 8 }}>
          {busy && !preview ? t("sl.generating") : t("sl.gen_btn")}
        </button>
      </div>

      {/* Preview mẫu AI sinh — chọn rồi lưu */}
      {preview && (
        <div style={{ marginTop: 12 }}>
          <p className="hint">{t("sl.preview_hint", { n: preview.length })}</p>
          {preview.map((c, i) => (
            <label key={i} className="sl-item sl-preview">
              <input type="checkbox" checked={!!picked[i]}
                     onChange={(e) => setPicked({ ...picked, [i]: e.target.checked })} />
              <b> {c.title || t("sl.untitled")}</b>
              {c.intent && <span className="sl-intent">{c.intent}</span>}
              <pre className="sl-content">{c.content}</pre>
            </label>
          ))}
          <button className="btn-primary" disabled={busy} onClick={onSavePicked}>
            {busy ? t("sl.saving") : t("sl.save_btn", { n: (preview || []).filter((_, i) => picked[i]).length })}
          </button>
        </div>
      )}

      {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}
    </div>
  );
}
