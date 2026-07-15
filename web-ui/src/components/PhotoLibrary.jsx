import { useEffect, useRef, useState } from "react";
import { photoApi } from "../photoApi.js";
import { useI18n } from "../i18n.jsx";

/*
 * Thư viện ảnh (kiểu AloChat): shop tạo BỘ ẢNH đặt tên ("Bảng giá", "Phòng 301",
 * "Menu món chính"…) + keywords các cách khách hay hỏi → upload nhiều ảnh.
 * Khách nhắn trúng tên/keywords → bot tự gửi cả bộ (mọi kênh).
 */
export default function PhotoLibrary() {
  const { t } = useI18n();
  const [sets, setSets] = useState(null);   // null = đang tải
  const [name, setName] = useState("");
  const [kw, setKw] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [openSlug, setOpenSlug] = useState(null);
  const fileRef = useRef(null);
  const [uploadSlug, setUploadSlug] = useState(null);

  async function load() {
    const r = await photoApi.sets();
    if (r.ok && r.body?.sets) setSets(r.body.sets);
    else setSets("offline");
  }
  useEffect(() => { load(); }, []);

  async function createSet(e) {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true); setMsg("");
    const keywords = kw.split(",").map((s) => s.trim()).filter(Boolean);
    const r = await photoApi.createSet(name.trim(), keywords);
    setBusy(false);
    if (r.ok) {
      setName(""); setKw("");
      setOpenSlug(r.body.set.slug);
      setMsg(t("pl.created"));
      load();
    } else {
      setMsg("❌ " + (r.body?.error || t("pl.create_fail")));
    }
  }

  function pickFiles(slug) {
    setUploadSlug(slug);
    fileRef.current?.click();
  }
  async function onFiles(e) {
    const files = [...(e.target.files || [])];
    e.target.value = "";
    if (!files.length || !uploadSlug) return;
    setBusy(true); setMsg("");
    const r = await photoApi.upload(uploadSlug, files);
    setBusy(false);
    if (r.ok) {
      const errs = r.body.errors || [];
      setMsg(t("pl.added", { n: r.body.saved.length }) + (errs.length ? ` · ⚠️ ${errs.join("; ")}` : ""));
      load();
    } else {
      setMsg("❌ " + (r.body?.error || t("pl.upload_fail")));
    }
  }

  async function delSet(s) {
    if (!confirm(t("pl.del_set_confirm", { name: s.name, n: s.files.length }))) return;
    await photoApi.deleteSet(s.slug);
    load();
  }
  async function delFile(slug, f) {
    if (!confirm(t("pl.del_file_confirm", { f }))) return;
    await photoApi.removeFile(slug, f);
    load();
  }
  async function editKw(s) {
    const cur = (s.keywords || []).join(", ");
    const next = prompt(t("pl.kw_prompt"), cur);
    if (next === null) return;
    await photoApi.updateKeywords(s.slug, next.split(",").map((x) => x.trim()).filter(Boolean));
    load();
  }

  return (
    <div className="pl">
      <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={onFiles} />

      <div className="pl-head">
        <div>
          <h3>{t("pl.title")}</h3>
          <span className="page-sub">
            {t("pl.sub")}
          </span>
        </div>
      </div>

      {/* Tạo bộ mới */}
      <form className="pl-new" onSubmit={createSet}>
        <input placeholder={t("pl.name_ph")}
               value={name} onChange={(e) => setName(e.target.value)} />
        <input placeholder={t("pl.kw_ph")}
               value={kw} onChange={(e) => setKw(e.target.value)} />
        <button type="submit" className="btn-primary sm" disabled={busy || !name.trim()}>{t("pl.create_btn")}</button>
      </form>

      {msg && <div className="savemsg" style={{ margin: "10px 0" }}>{msg}</div>}

      {sets === null && <p className="hint">{t("pl.loading")}</p>}
      {sets === "offline" && (
        <p className="hint">{t("pl.offline")}</p>
      )}

      {Array.isArray(sets) && sets.length === 0 && (
        <div className="empty" style={{ padding: 24 }}>
          <p>{t("pl.empty")}</p>
        </div>
      )}

      {Array.isArray(sets) && sets.map((s) => (
        <div key={s.slug} className="pl-set">
          <div className="pl-set-head" onClick={() => setOpenSlug(openSlug === s.slug ? null : s.slug)}>
            <div className="pl-set-info">
              <b>{s.name}</b>
              <span className="pl-count">{t("pl.count", { n: s.files.length })}</span>
              {s.keywords?.length > 0 && (
                <span className="pl-kw">🔑 {s.keywords.join(" · ")}</span>
              )}
            </div>
            <div className="pl-set-actions" onClick={(e) => e.stopPropagation()}>
              <button className="btn-mini" onClick={() => pickFiles(s.slug)} disabled={busy}>{t("pl.add_btn")}</button>
              <button className="btn-mini" onClick={() => editKw(s)}>{t("pl.kw_btn")}</button>
              <button className="btn-mini danger" onClick={() => delSet(s)}>{t("pl.del_set")}</button>
            </div>
          </div>

          {openSlug === s.slug && (
            s.files.length === 0 ? (
              <p className="hint" style={{ padding: "4px 12px 12px" }}>
                {t("pl.set_empty")}
              </p>
            ) : (
              <div className="pl-grid">
                {s.files.map((f) => (
                  <div key={f} className="pl-thumb">
                    <img src={photoApi.fileUrl(s.slug, f)} alt={f} loading="lazy" />
                    <button className="pl-thumb-del" title={t("pl.del_file_title")}
                            onClick={() => delFile(s.slug, f)}>✕</button>
                  </div>
                ))}
              </div>
            )
          )}
        </div>
      ))}
    </div>
  );
}
