import { useEffect, useRef, useState } from "react";
import { photoApi } from "../photoApi.js";

/*
 * Thư viện ảnh (kiểu AloChat): shop tạo BỘ ẢNH đặt tên ("Bảng giá", "Phòng 301",
 * "Menu món chính"…) + keywords các cách khách hay hỏi → upload nhiều ảnh.
 * Khách nhắn trúng tên/keywords → bot tự gửi cả bộ (mọi kênh).
 */
export default function PhotoLibrary() {
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
      setMsg("✅ Đã tạo bộ — giờ thêm ảnh vào nhé.");
      load();
    } else {
      setMsg("❌ " + (r.body?.error || "Tạo bộ thất bại — server 5005 cần restart để có API ảnh?"));
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
      setMsg(`✅ Đã thêm ${r.body.saved.length} ảnh` + (errs.length ? ` · ⚠️ ${errs.join("; ")}` : ""));
      load();
    } else {
      setMsg("❌ " + (r.body?.error || "Upload thất bại"));
    }
  }

  async function delSet(s) {
    if (!confirm(`Xoá bộ ảnh "${s.name}" cùng toàn bộ ${s.files.length} ảnh?`)) return;
    await photoApi.deleteSet(s.slug);
    load();
  }
  async function delFile(slug, f) {
    if (!confirm(`Xoá ảnh ${f}?`)) return;
    await photoApi.removeFile(slug, f);
    load();
  }
  async function editKw(s) {
    const cur = (s.keywords || []).join(", ");
    const next = prompt('Các cách khách hay hỏi (phân cách bằng dấu phẩy):\nVD: bảng giá, giá dịch vụ, menu', cur);
    if (next === null) return;
    await photoApi.updateKeywords(s.slug, next.split(",").map((x) => x.trim()).filter(Boolean));
    load();
  }

  return (
    <div className="pl">
      <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={onFiles} />

      <div className="pl-head">
        <div>
          <h3>🖼️ Thư viện ảnh</h3>
          <span className="page-sub">
            Tạo bộ ảnh đặt tên — khách nhắn trúng tên/từ khoá là bot tự gửi cả bộ (mọi kênh).
          </span>
        </div>
      </div>

      {/* Tạo bộ mới */}
      <form className="pl-new" onSubmit={createSet}>
        <input placeholder='Tên bộ ảnh — VD: "Bảng giá", "Phòng 301", "Menu món chính"'
               value={name} onChange={(e) => setName(e.target.value)} />
        <input placeholder="Khách hay hỏi bằng từ nào? (phẩy) — VD: bảng giá, giá phòng, menu"
               value={kw} onChange={(e) => setKw(e.target.value)} />
        <button type="submit" className="btn-primary sm" disabled={busy || !name.trim()}>＋ Tạo bộ</button>
      </form>

      {msg && <div className="savemsg" style={{ margin: "10px 0" }}>{msg}</div>}

      {sets === null && <p className="hint">Đang tải thư viện ảnh…</p>}
      {sets === "offline" && (
        <p className="hint">⚠️ Không tải được thư viện ảnh — server 5005 chưa chạy hoặc chưa restart bản mới.</p>
      )}

      {Array.isArray(sets) && sets.length === 0 && (
        <div className="empty" style={{ padding: 24 }}>
          <p>Chưa có bộ ảnh nào. Tạo bộ đầu tiên — VD "Bảng giá" — rồi thêm ảnh vào.</p>
        </div>
      )}

      {Array.isArray(sets) && sets.map((s) => (
        <div key={s.slug} className="pl-set">
          <div className="pl-set-head" onClick={() => setOpenSlug(openSlug === s.slug ? null : s.slug)}>
            <div className="pl-set-info">
              <b>{s.name}</b>
              <span className="pl-count">{s.files.length} ảnh</span>
              {s.keywords?.length > 0 && (
                <span className="pl-kw">🔑 {s.keywords.join(" · ")}</span>
              )}
            </div>
            <div className="pl-set-actions" onClick={(e) => e.stopPropagation()}>
              <button className="btn-mini" onClick={() => pickFiles(s.slug)} disabled={busy}>＋ Thêm ảnh</button>
              <button className="btn-mini" onClick={() => editKw(s)}>🔑 Từ khoá</button>
              <button className="btn-mini danger" onClick={() => delSet(s)}>Xoá bộ</button>
            </div>
          </div>

          {openSlug === s.slug && (
            s.files.length === 0 ? (
              <p className="hint" style={{ padding: "4px 12px 12px" }}>
                Bộ này chưa có ảnh — bấm "＋ Thêm ảnh" (chọn được nhiều ảnh một lúc).
              </p>
            ) : (
              <div className="pl-grid">
                {s.files.map((f) => (
                  <div key={f} className="pl-thumb">
                    <img src={photoApi.fileUrl(s.slug, f)} alt={f} loading="lazy" />
                    <button className="pl-thumb-del" title="Xoá ảnh này"
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
