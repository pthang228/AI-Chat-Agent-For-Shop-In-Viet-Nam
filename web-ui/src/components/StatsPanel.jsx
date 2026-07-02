import { useEffect, useState } from "react";
import { fetchStats, periodDates } from "../statsApi.js";

const PERIODS = [
  { key: "today", label: "Hôm nay" },
  { key: "7d",    label: "7 ngày"  },
  { key: "30d",   label: "30 ngày" },
  { key: "month", label: "Tháng"   },
  { key: "year",  label: "Năm"     },
  { key: "all",   label: "Tất cả"  },
];

const STAGE_LABEL = {
  greeting:       "Chào hỏi",
  checking:       "Kiểm tra lịch",
  offering:       "Đề xuất phòng",
  confirmed:      "Đã đặt",
  owner_notified: "Chờ chủ",
};
const STAGE_COLOR = {
  greeting:       "#9aa39b",
  checking:       "#229ed9",
  offering:       "#c1923a",
  confirmed:      "#4f9d6b",
  owner_notified: "#7b3fb3",
};
const CH_COLOR = { zalo: "#0068ff", meta: "#7b3fb3", telegram: "#229ed9", tiktok: "#161823" };
const CH_LABEL = { zalo: "Zalo", meta: "Mess+IG", telegram: "Telegram", tiktok: "TikTok" };

function StatCard({ icon, label, value, sub, accent }) {
  return (
    <div className="sc" style={{ "--accent": accent || "var(--green)" }}>
      <div className="sc-accent-bar" />
      <div className="sc-icon">{icon}</div>
      <div className="sc-val">{value ?? "—"}</div>
      <div className="sc-label">{label}</div>
      {sub && <div className="sc-sub">{sub}</div>}
    </div>
  );
}

const CHART_H = 60; // px — chiều cao vùng bar

// Format date LOCAL (không dùng toISOString vì sẽ bị UTC shift ở VN UTC+7)
function localFmt(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function BarChart({ timeline, period }) {
  const { from, to } = periodDates(period);
  const todayLocal = localFmt(new Date());

  // Year → 12 cột tháng; mọi period khác → daily
  const isYear = period === "year";

  let slots = [];
  let tmap = {};

  if (isYear) {
    // Slots = 12 tháng của năm hiện tại (YYYY-MM)
    const year = new Date().getFullYear();
    for (let m = 1; m <= 12; m++) slots.push(`${year}-${String(m).padStart(2, "0")}`);
    // Gộp timeline theo tháng
    for (const t of timeline) {
      const key = t.date.slice(0, 7);
      if (!tmap[key]) tmap[key] = { date: key, conv: 0, msg: 0 };
      tmap[key].conv += t.conv; tmap[key].msg += t.msg;
    }
  } else {
    // Daily slots từ from→to
    if (from && to) {
      const cur = new Date(from + "T00:00:00");
      const end = new Date(to + "T00:00:00");
      while (cur <= end) { slots.push(localFmt(cur)); cur.setDate(cur.getDate() + 1); }
    } else {
      for (const t of timeline) slots.push(t.date);
    }
    // tmap từng ngày
    for (const t of timeline) tmap[t.date] = t;
  }

  const data = slots.map((d) => tmap[d] || { date: d, conv: 0, msg: 0 });
  const maxConv = Math.max(...data.map((d) => d.conv), 1);
  const n = data.length;
  if (n === 0) return null;

  const labelStep = Math.max(1, Math.ceil(n / 7));

  function fmtLabel(dateStr) {
    if (isYear) return dateStr.slice(5); // "06" (tháng)
    return dateStr.slice(8);            // "28" (ngày)
  }

  function isHighlight(dateStr) {
    if (isYear) return dateStr === todayLocal.slice(0, 7);
    return dateStr === todayLocal;
  }

  return (
    <div className="barchart-wrap">
      <div className="barchart-bars">
        {data.map((d, i) => {
          const barH = d.conv > 0
            ? Math.max(Math.round((d.conv / maxConv) * CHART_H), 4)
            : 0;
          return (
            <div key={d.date} className="bc-col" title={`${d.date}: ${d.conv} hội thoại`}>
              {barH > 0 && (
                <div className="bc-bar" style={{
                  height: barH + "px",
                  width: "80%",
                  background: isHighlight(d.date) ? "#c1923a" : "#2f5d46",
                }} />
              )}
            </div>
          );
        })}
      </div>
      <div className="barchart-labels">
        {data.map((d, i) => (
          <div key={d.date} className="bc-lbl">
            {i % labelStep === 0 ? fmtLabel(d.date) : ""}
          </div>
        ))}
      </div>
    </div>
  );
}

function StageBar({ byStage }) {
  const total = Object.values(byStage).reduce((a, b) => a + b, 0);
  if (total === 0) return null;
  const entries = Object.entries(byStage).sort((a, b) => b[1] - a[1]);
  return (
    <div className="stage-bar-wrap">
      <div className="stage-bar-track">
        {entries.map(([st, cnt]) => (
          <div key={st} className="stage-bar-seg"
               title={`${STAGE_LABEL[st] || st}: ${cnt}`}
               style={{ width: `${(cnt / total) * 100}%`, background: STAGE_COLOR[st] || "#ccc" }} />
        ))}
      </div>
      <div className="stage-legend">
        {entries.map(([st, cnt]) => (
          <span key={st} className="stage-leg-item">
            <span className="stage-dot" style={{ background: STAGE_COLOR[st] || "#ccc" }} />
            {STAGE_LABEL[st] || st} <b>{cnt}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

function ChannelBar({ byChannel }) {
  if (!byChannel) return null;
  const total = Object.values(byChannel).reduce((a, b) => a + b, 0);
  if (total === 0) return null;
  return (
    <div className="ch-bar-list">
      {Object.entries(byChannel).map(([ch, cnt]) => (
        <div key={ch} className="ch-bar-row">
          <span className="ch-bar-label" style={{ color: CH_COLOR[ch] }}>{CH_LABEL[ch] || ch}</span>
          <div className="ch-bar-track">
            <div className="ch-bar-fill"
                 style={{ width: `${total ? (cnt / total) * 100 : 0}%`, background: CH_COLOR[ch] }} />
          </div>
          <span className="ch-bar-cnt">{cnt}</span>
        </div>
      ))}
    </div>
  );
}

export default function StatsPanel({ channel = "all", onClose }) {
  const [period, setPeriod] = useState("30d");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let dead = false;
    setLoading(true);
    fetchStats(channel, period)
      .then((d) => { if (!dead) { setData(d); setLoading(false); } })
      .catch(() => { if (!dead) { setData(null); setLoading(false); } });
    return () => { dead = true; };
  }, [channel, period]);

  const rate = data && data.total_conv > 0
    ? Math.round((data.confirmed / data.total_conv) * 100) : 0;

  return (
    <div className="stats-panel">
      {/* Header */}
      <div className="sp-header">
        <div className="sp-header-left">
          <span className="sp-header-icon">📊</span>
          <span className="sp-header-title">Thống kê hoạt động</span>
        </div>
        {onClose && (
          <button className="sp-close" onClick={onClose} title="Đóng">✕</button>
        )}
      </div>

      {/* Period selector */}
      <div className="period-bar">
        {PERIODS.map((p) => (
          <button key={p.key}
                  className={"period-btn" + (period === p.key ? " active" : "")}
                  onClick={() => setPeriod(p.key)}>
            {p.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="stats-loading">
          <div className="stats-spinner" />
          Đang tải…
        </div>
      ) : !data ? (
        <p className="hint" style={{ textAlign: "center", padding: "24px 12px" }}>
          ⚠️ Không tải được thống kê — kiểm tra server đang chạy không.
        </p>
      ) : (
        <div className="sp-body">
          {/* Stat cards */}
          <div className="sc-row">
            <StatCard icon="💬" label="Hội thoại"     value={data.total_conv} accent="var(--green)" />
            <StatCard icon="📨" label="Tin nhắn"       value={data.user_msg}
              sub={`Bot: ${data.bot_msg}`} accent="#229ed9" />
            <StatCard icon="✅" label="Đặt phòng"     value={data.confirmed}
              sub={data.total_conv > 0 ? `${rate}% tỷ lệ` : "—"} accent="var(--ok)" />
            <StatCard icon="⏳" label="Chờ xử lý"    value={data.by_stage?.owner_notified ?? 0}
              accent="var(--gold)" />
          </div>

          {/* Biểu đồ hội thoại theo ngày/tháng */}
          {data.total_conv > 0 && (
            <div className="sc-section">
              <div className="sc-section-title">
                {period === "year" ? "Hội thoại theo tháng" : "Hội thoại theo ngày"}
              </div>
              <BarChart timeline={data.timeline || []} period={period} />
            </div>
          )}

          {/* Stage breakdown */}
          {data.by_stage && Object.keys(data.by_stage).length > 0 && (
            <div className="sc-section">
              <div className="sc-section-title">Giai đoạn tư vấn</div>
              <StageBar byStage={data.by_stage} />
            </div>
          )}

          {/* Channel breakdown — chỉ hiện khi có dữ liệu */}
          {data.by_channel && Object.values(data.by_channel).some((v) => v > 0) && (
            <div className="sc-section">
              <div className="sc-section-title">Theo kênh</div>
              <ChannelBar byChannel={data.by_channel} />
            </div>
          )}

          {data.total_conv === 0 && (
            <p className="hint" style={{ textAlign: "center", padding: "16px 0" }}>
              Chưa có dữ liệu trong khoảng thời gian này.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
