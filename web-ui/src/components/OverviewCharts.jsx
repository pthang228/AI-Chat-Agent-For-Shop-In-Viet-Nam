import { useEffect, useMemo, useState } from "react";
import { fetchStats, fetchQuality, periodDates } from "../statsApi.js";
import { useI18n } from "../i18n.jsx";

/* ── Bảng màu kênh (khớp Dashboard/StatsPanel) ── */
const CH = {
  zalo:     { label: "Zalo",        color: "#0068ff" },
  meta:     { label: "Mess + IG",   color: "#7b3fb3" },
  telegram: { label: "Telegram",    color: "#229ed9" },
  shopee:   { label: "Shopee",      color: "#EE4D2D" },
  zalooa:   { label: "Zalo OA",     color: "#005AE0" },
  webchat:  { label: "Website",     color: "#4F46E5" },
};

/* Ngày dạng local (tránh lệch UTC ở VN) */
function localFmt(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/* Dựng danh sách ngày từ from→to (hoặc theo timeline nếu "all") */
function buildDays(period, timeline) {
  const { from, to } = periodDates(period);
  const days = [];
  if (from && to) {
    const cur = new Date(from + "T00:00:00");
    const end = new Date(to + "T00:00:00");
    while (cur <= end) { days.push(localFmt(cur)); cur.setDate(cur.getDate() + 1); }
  } else {
    for (const t of timeline) days.push(t.date);
    if (!days.length) days.push(localFmt(new Date()));
  }
  return days;
}

/* ─────────────────────────────────────────────────────────
 * LineChart SVG tái dùng — nhiều series, lưới ngang, nhãn trục,
 * chấm điểm + tooltip khi rê chuột.
 * series: [{ name, color, values:number[], dash?:bool, fill?:bool }]
 * ───────────────────────────────────────────────────────── */
function LineChart({ labels, series, yMax, yTicks = 4, ySuffix = "", height = 210 }) {
  const [hover, setHover] = useState(null);
  const W = 640, H = height;
  const padL = 34, padR = 12, padT = 14, padB = 26;
  const iw = W - padL - padR, ih = H - padT - padB;
  const n = labels.length;

  const max = Math.max(yMax || 0, ...series.flatMap((s) => s.values), 1);
  const nice = niceMax(max);
  const x = (i) => padL + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v) => padT + ih - (v / nice) * ih;

  const ticks = Array.from({ length: yTicks + 1 }, (_, i) => (nice / yTicks) * i);
  const labelStep = Math.max(1, Math.ceil(n / 7));

  return (
    <div className="lc-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} className="lc-svg" preserveAspectRatio="none"
           onMouseLeave={() => setHover(null)}>
        {/* Lưới + nhãn trục Y */}
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)}
                  stroke="var(--line)" strokeWidth="1" strokeDasharray="3 4" />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" className="lc-axis">
              {fmtNum(t)}{ySuffix}
            </text>
          </g>
        ))}

        {/* Vùng fill (nếu có) + đường */}
        {series.map((s, si) => {
          const pts = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
          return (
            <g key={si}>
              {s.fill && (
                <polygon
                  points={`${padL},${y(0)} ${pts} ${W - padR},${y(0)}`}
                  fill={s.color} opacity="0.10" />
              )}
              <polyline points={pts} fill="none" stroke={s.color} strokeWidth="2.4"
                        strokeLinejoin="round" strokeLinecap="round"
                        strokeDasharray={s.dash ? "6 5" : "none"} />
              {s.values.map((v, i) => (
                <circle key={i} cx={x(i)} cy={y(v)} r={hover === i ? 4.5 : 2.6}
                        fill="#fff" stroke={s.color} strokeWidth="2" />
              ))}
            </g>
          );
        })}

        {/* Nhãn trục X */}
        {labels.map((lb, i) => (
          i % labelStep === 0 || i === n - 1 ? (
            <text key={i} x={x(i)} y={H - 8} textAnchor="middle" className="lc-axis">
              {lb.slice(5)}
            </text>
          ) : null
        ))}

        {/* Vùng bắt hover theo cột */}
        {labels.map((_, i) => (
          <rect key={i} x={x(i) - iw / (2 * Math.max(n - 1, 1))} y={padT}
                width={iw / Math.max(n - 1, 1)} height={ih} fill="transparent"
                onMouseEnter={() => setHover(i)} />
        ))}
        {hover != null && (
          <line x1={x(hover)} x2={x(hover)} y1={padT} y2={padT + ih}
                stroke="var(--faint)" strokeWidth="1" />
        )}
      </svg>

      {/* Tooltip */}
      {hover != null && (
        <div className="lc-tip" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <div className="lc-tip-date">{labels[hover]}</div>
          {series.map((s, si) => (
            <div key={si} className="lc-tip-row">
              <span className="lc-tip-dot" style={{ background: s.color }} />
              {s.name}: <b>{fmtNum(s.values[hover])}{ySuffix}</b>
            </div>
          ))}
        </div>
      )}

      {/* Chú thích */}
      <div className="lc-legend">
        {series.map((s, si) => (
          <span key={si} className="lc-leg">
            <span className="lc-leg-line" style={{
              background: s.dash ? "none" : s.color,
              borderTop: s.dash ? `2px dashed ${s.color}` : "none",
            }} />
            {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ── Donut SVG cho "Tin nhắn theo nền tảng" ── */
function Donut({ data }) {
  const { t } = useI18n();
  const entries = Object.entries(data).filter(([, v]) => v > 0);
  const total = entries.reduce((a, [, v]) => a + v, 0);
  const R = 70, SW = 26, C = 90, circ = 2 * Math.PI * R;

  if (total === 0) {
    return <div className="don-empty">{t("chart.empty")}</div>;
  }

  let acc = 0;
  return (
    <div className="don-wrap">
      <svg viewBox="0 0 180 180" className="don-svg">
        <circle cx={C} cy={C} r={R} fill="none" stroke="var(--line)" strokeWidth={SW} />
        {entries.map(([ch, v]) => {
          const frac = v / total;
          const dash = `${frac * circ} ${circ}`;
          const seg = (
            <circle key={ch} cx={C} cy={C} r={R} fill="none"
                    stroke={(CH[ch] || {}).color || "#999"} strokeWidth={SW}
                    strokeDasharray={dash} strokeDashoffset={-acc * circ}
                    transform={`rotate(-90 ${C} ${C})`} strokeLinecap="butt" />
          );
          acc += frac;
          return seg;
        })}
        <text x={C} y={C - 2} textAnchor="middle" className="don-center">
          {entries.length === 1 ? "100%" : total}
        </text>
        <text x={C} y={C + 16} textAnchor="middle" className="don-center-sub">
          {entries.length === 1 ? "" : "tin nhắn"}
        </text>
      </svg>
      <div className="don-legend">
        {entries.map(([ch, v]) => (
          <div key={ch} className="don-leg">
            <span className="don-dot" style={{ background: (CH[ch] || {}).color || "#999" }} />
            {(CH[ch] || {}).label || ch}: <b>{v}</b>
            <span className="don-pct">({Math.round((v / total) * 100)}%)</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChartCard({ title, extra, children }) {
  return (
    <div className="chart-card">
      <div className="chart-card-head">
        <h3>{title}</h3>
        {extra}
      </div>
      {children}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────
 * OverviewCharts — 4 biểu đồ như ảnh AloChat.
 * Lấy data thật qua fetchStats("all", period).
 * ───────────────────────────────────────────────────────── */
export default function OverviewCharts({ period = "30d", onData }) {
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [quality, setQuality] = useState(null);   // {latency:{avg,p95,timeline}, misses}
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let dead = false;
    setLoading(true);
    Promise.all([fetchStats("all", period), fetchQuality(period)])
      .then(([d, q]) => {
        if (dead) return;
        setData(d); setQuality(q); setLoading(false);
        // đính avg latency vào payload cho KPI "Thời gian phản hồi TB" ở Overview
        if (onData) onData(d ? { ...d, latency_avg: q?.latency?.avg ?? 0, latency_n: q?.latency?.n ?? 0 } : null);
      })
      .catch(() => { if (!dead) { setData(null); setQuality(null); setLoading(false); if (onData) onData(null); } });
    return () => { dead = true; };
  }, [period]);

  const built = useMemo(() => {
    if (!data) return null;
    const days = buildDays(period, data.timeline || []);
    const tmap = {};
    for (const t of data.timeline || []) tmap[t.date] = t;
    const conv = days.map((d) => (tmap[d]?.conv) || 0);
    const msg  = days.map((d) => (tmap[d]?.msg) || 0);
    // Tỷ lệ AI trả lời/ngày — THẬT: tin bot / tin khách của hội thoại chốt ngày
    // đó (server trả user/bot theo ngày; server cũ chưa có → fallback proxy cũ)
    const aiRate = days.map((d) => {
      const e = tmap[d];
      if (!e) return 0;
      if (e.user != null && e.user > 0) return Math.min(100, Math.round((e.bot / e.user) * 100));
      return e.msg > 0 ? 100 : 0;
    });
    // Thời gian phản hồi theo ngày (avg + P95) từ latency_log
    const lmap = {};
    for (const l of quality?.latency?.timeline || []) lmap[l.date] = l;
    const latAvg = days.map((d) => lmap[d]?.avg || 0);
    const latP95 = days.map((d) => lmap[d]?.p95 || 0);
    return { days, conv, msg, aiRate, latAvg, latP95 };
  }, [data, quality, period]);

  if (loading) {
    return <div className="ov-loading"><div className="stats-spinner" /> {t("chart.loading")}</div>;
  }
  if (!data) {
    return <p className="hint" style={{ textAlign: "center", padding: 24 }}>
      {t("chart.load_fail")}
    </p>;
  }

  const botMsg = data.bot_msg || 0;
  // Donut "TIN NHẮN theo nền tảng" dùng SỐ TIN (by_channel_msg); bản cũ dùng
  // nhầm by_channel (số hội thoại) — giữ fallback cho server cũ
  const byChannel = data.by_channel_msg || data.by_channel || {};
  const hasLatency = (quality?.latency?.n || 0) > 0;
  const misses = quality?.misses || 0;

  return (
    <div className="charts-grid">
      {/* 1 — Hội thoại & tin nhắn theo ngày */}
      <ChartCard title={t("chart.conv_msg")}>
        <LineChart
          labels={built.days}
          series={[
            { name: t("nav.chat"), color: "#4C6EF5", values: built.conv },
            { name: t("chart.messages"),  color: "#7C3AED", values: built.msg, fill: true },
          ]}
        />
      </ChartCard>

      {/* 2 — Tin nhắn theo nền tảng (donut) */}
      <ChartCard title={t("chart.by_platform")}>
        <Donut data={byChannel} />
      </ChartCard>

      {/* 3 — Thời gian phản hồi (giây) — số THẬT từ latency_log (đo ở não bot) */}
      <ChartCard
        title={t("chart.latency")}
        extra={hasLatency ? (
          <span className="chart-sub">
            TB <b style={{ color: "#23a065" }}>{quality.latency.avg}s</b> · P95{" "}
            <b style={{ color: "#cf9536" }}>{quality.latency.p95}s</b>
          </span>
        ) : null}
      >
        <LineChart
          labels={built.days}
          ySuffix="s"
          series={[
            { name: t("chart.avg"), color: "#23a065", values: built.latAvg, fill: true },
            { name: "P95",        color: "#cf9536", values: built.latP95, dash: true },
          ]}
        />
        {!hasLatency && <div className="chart-note">{t("chart.latency_note")}</div>}
      </ChartCard>

      {/* 4 — Tỷ lệ AI trả lời theo ngày (bot/khách) + số câu bot BÍ trong kỳ */}
      <ChartCard
        title={t("chart.ai_rate")}
        extra={<span className="chart-sub">
          <b style={{ color: "var(--ok)" }}>{botMsg} {t("chart.ok")}</b> / <b>{misses} {t("chart.fail")}</b>
        </span>}
      >
        <LineChart
          labels={built.days}
          ySuffix="%"
          yMax={100}
          yTicks={4}
          series={[
            { name: t("kpi.rate"), color: "#23a065", values: built.aiRate, fill: true },
          ]}
        />
      </ChartCard>
    </div>
  );
}

/* ── helpers ── */
function niceMax(v) {
  if (v <= 1) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = v / pow;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * pow;
}
function fmtNum(v) {
  if (Number.isInteger(v)) return v;
  return Math.round(v * 10) / 10;
}
