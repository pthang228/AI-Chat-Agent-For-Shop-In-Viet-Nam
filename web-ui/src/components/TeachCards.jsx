// DẠY AI v2 — 3 card bổ trợ trang /prompt:
//   InterviewCard : AI phỏng vấn chủ shop từng câu → bản tổng hợp đổ vào ô hướng dẫn
//   ReportCard    : báo cáo câu bot bí (unknown_question) 14 ngày + bổ sung 1 chạm
//   HealthCard    : chấm điểm não — chạy bộ câu hỏi theo ngành qua não thật + AI giám khảo
import { useEffect, useRef, useState } from "react";
import { promptApi } from "../promptApi.js";
import { useI18n } from "../i18n.jsx";

// ── 🎙️ AI phỏng vấn ────────────────────────────────────────────────
export function InterviewCard({ onDone }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState([]);       // {role, content}
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState("");
  const boxRef = useRef(null);

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [msgs, busy]);

  async function ask(history) {
    setBusy(true);
    const r = await promptApi.interview(history);
    setBusy(false);
    if (!r.ok || !r.body?.ok) {
      setMsgs([...history, { role: "assistant", content: "❌ " + (r.body?.error || t("iv.fail")) }]);
      return;
    }
    if (r.body.done && r.body.summary) {
      setSummary(r.body.summary);
      setMsgs([...history, { role: "assistant", content: t("iv.done_msg") }]);
    } else {
      setMsgs([...history, { role: "assistant", content: r.body.question }]);
    }
  }

  function start() { setOpen(true); setSummary(""); setMsgs([]); ask([]); }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    await ask([...msgs, { role: "user", content: text }]);
  }

  return (
    <div className="panel set-card" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div>
          <b>🎙️ {t("iv.title")}</b>{" "}
          <span className="hint" style={{ fontWeight: 400 }}>{t("iv.hint")}</span>
        </div>
        {!open && <button className="btn-mini" onClick={start}>{t("iv.start")}</button>}
      </div>
      {open && (
        <>
          <div ref={boxRef} className="bubbles" style={{ maxHeight: 260, overflowY: "auto", margin: "10px 0" }}>
            {msgs.map((m, i) => (
              <div key={i} className={"bubble " + (m.role === "assistant" ? "b-bot" : "b-user")}>{m.content}</div>
            ))}
            {busy && <div className="bubble b-bot">…</div>}
          </div>
          {summary ? (
            <div>
              <pre className="sl-content">{summary}</pre>
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button className="btn-primary sm" onClick={() => { onDone?.(summary); setOpen(false); }}>
                  {t("iv.fill")}
                </button>
                <button className="btn-mini" onClick={start}>{t("iv.again")}</button>
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", gap: 8 }}>
              <input className="chat-input" style={{ flex: 1 }} value={input} disabled={busy}
                     placeholder={t("iv.input_ph")}
                     onChange={(e) => setInput(e.target.value)}
                     onKeyDown={(e) => e.key === "Enter" && send()} />
              <button className="btn-primary sm" onClick={send} disabled={busy || !input.trim()}>
                {t("iv.send")}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── ❓ Báo cáo câu bot bí ───────────────────────────────────────────
export function ReportCard() {
  const { t } = useI18n();
  const [misses, setMisses] = useState([]);
  const [total, setTotal] = useState(0);
  const [answers, setAnswers] = useState({});   // idx → text
  const [busyIdx, setBusyIdx] = useState(null);
  const [msg, setMsg] = useState("");

  async function load() {
    const r = await promptApi.report();
    if (r.ok && r.body?.ok) { setMisses(r.body.misses || []); setTotal(r.body.total || 0); }
  }
  useEffect(() => { load(); }, []);

  if (!total) return null;   // không có câu bí → không chiếm chỗ

  async function answer(i) {
    const m = misses[i];
    const a = (answers[i] || "").trim();
    if (!a) return;
    setBusyIdx(i); setMsg("");
    const r = await promptApi.reportAnswer(m.question, a, m.ids);
    setBusyIdx(null);
    if (r.ok && r.body?.ok) {
      setMsg(t("rpt.saved", { title: r.body.chunk?.title || "" }));
      load();
    } else setMsg("❌ " + (r.body?.error || t("rpt.fail")));
  }

  return (
    <div className="panel set-card gaps-box" style={{ marginBottom: 16 }}>
      <h3 style={{ fontSize: 16, marginBottom: 4 }}>❓ {t("rpt.title", { n: total })}</h3>
      <p className="hint">{t("rpt.hint")}</p>
      {misses.map((m, i) => (
        <details key={i} className="sl-item" style={{ marginBottom: 6 }}>
          <summary>
            <b>{m.question}</b>
            {m.count > 1 && <span className="sl-intent">×{m.count}</span>}
          </summary>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <input className="chat-input" style={{ flex: 1 }} placeholder={t("rpt.answer_ph")}
                   value={answers[i] || ""}
                   onChange={(e) => setAnswers({ ...answers, [i]: e.target.value })}
                   onKeyDown={(e) => e.key === "Enter" && answer(i)} />
            <button className="btn-primary sm" disabled={busyIdx === i || !(answers[i] || "").trim()}
                    onClick={() => answer(i)}>
              {busyIdx === i ? t("rpt.saving") : t("rpt.save")}
            </button>
          </div>
        </details>
      ))}
      {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}
    </div>
  );
}

// ── 🩺 Chấm điểm não ────────────────────────────────────────────────
export function HealthCard() {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");

  async function run() {
    setBusy(true); setErr(""); setRes(null);
    const r = await promptApi.health();
    setBusy(false);
    if (r.ok && r.body?.ok) setRes(r.body);
    else setErr("❌ " + (r.body?.error || t("hc.fail")));
  }

  return (
    <div className="panel set-card" style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div>
          <b>🩺 {t("hc.title")}</b>{" "}
          <span className="hint" style={{ fontWeight: 400 }}>{t("hc.hint")}</span>
        </div>
        <button className="btn-mini" onClick={run} disabled={busy}>
          {busy ? t("hc.running") : t("hc.run")}
        </button>
      </div>
      {err && <div className="savemsg" style={{ marginTop: 8 }}>{err}</div>}
      {res && (
        <div style={{ marginTop: 10 }}>
          <p><b>{t("hc.score", { p: res.passed, n: res.total })}</b>{" "}
            <span className="hint">({res.industry_label})</span></p>
          {res.items.filter((it) => !it.ok).map((it, i) => (
            <details key={i} className="sl-item" style={{ marginBottom: 6 }}>
              <summary>❌ <b>{it.question}</b>{it.note && <span className="sl-intent">{it.note}</span>}</summary>
              <pre className="sl-content">{it.reply}</pre>
            </details>
          ))}
          {res.passed === res.total && <p className="hint">{t("hc.all_ok")}</p>}
          {res.passed < res.total && <p className="hint">{t("hc.fix_hint")}</p>}
        </div>
      )}
    </div>
  );
}
