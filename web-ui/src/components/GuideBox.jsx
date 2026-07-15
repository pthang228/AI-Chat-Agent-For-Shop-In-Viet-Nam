import { useState } from "react";
import { useI18n } from "../i18n.jsx";

// Hộp hướng dẫn gấp/mở dùng chung cho mỗi kênh (Connect tab).
// <GuideBox title="..." steps={[{t:'Tiêu đề', d:<>mô tả</>}]} note={<>...</>} />
export default function GuideBox({ title = null, steps = [], note = null, defaultOpen = true }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="guidebox">
      <button className="guidebox-head" onClick={() => setOpen((o) => !o)}>
        <span>{title ?? t("guide.title")}</span>
        <span className="guidebox-toggle">{open ? t("guide.collapse") : t("guide.view")}</span>
      </button>
      {open && (
        <div className="guidebox-body">
          <ol className="guide-steps">
            {steps.map((s, i) => (
              <li key={i}>
                {s.t && <b>{s.t}</b>}
                {s.t && s.d ? " — " : ""}
                {s.d}
              </li>
            ))}
          </ol>
          {note && <div className="guide-note">{note}</div>}
        </div>
      )}
    </div>
  );
}
