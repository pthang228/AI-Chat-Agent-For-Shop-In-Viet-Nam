import { brain } from "./brainApi.js";
import { meta } from "./metaApi.js";
import { tg } from "./telegramApi.js";
import { tiktok } from "./tiktokApi.js";
import { shopee } from "./shopeeApi.js";

// Tính from/to dựa trên period key
export function periodDates(period) {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const today = fmt(now);
  if (period === "today") return { from: today, to: today };
  if (period === "7d") {
    const d = new Date(now); d.setDate(d.getDate() - 6);
    return { from: fmt(d), to: today };
  }
  if (period === "30d") {
    const d = new Date(now); d.setDate(d.getDate() - 29);
    return { from: fmt(d), to: today };
  }
  if (period === "month") {
    return { from: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-01`, to: today };
  }
  if (period === "year") {
    return { from: `${now.getFullYear()}-01-01`, to: today };
  }
  return { from: null, to: null }; // all
}

function emptyStats() {
  return { total_conv: 0, total_msg: 0, user_msg: 0, bot_msg: 0, confirmed: 0, by_stage: {}, timeline: [] };
}

function mergeStats(a, b) {
  const by_stage = { ...a.by_stage };
  for (const [k, v] of Object.entries(b.by_stage || {}))
    by_stage[k] = (by_stage[k] || 0) + v;

  const tmap = {};
  for (const t of [...(a.timeline || []), ...(b.timeline || [])]) {
    if (!tmap[t.date]) tmap[t.date] = { date: t.date, conv: 0, msg: 0 };
    tmap[t.date].conv += t.conv;
    tmap[t.date].msg  += t.msg;
  }
  return {
    total_conv: a.total_conv + b.total_conv,
    total_msg:  a.total_msg  + b.total_msg,
    user_msg:   a.user_msg   + b.user_msg,
    bot_msg:    a.bot_msg    + b.bot_msg,
    confirmed:  a.confirmed  + b.confirmed,
    by_stage,
    timeline: Object.values(tmap).sort((x, y) => x.date.localeCompare(y.date)),
  };
}

// Lấy stats từ 1 kênh
async function fetchOne(channel, from, to) {
  let r;
  if (channel === "zalo")     r = await brain.stats(from, to);
  else if (channel === "meta") r = await meta.stats(from, to);
  else if (channel === "telegram") r = await tg.stats(from, to);
  else if (channel === "tiktok") r = await tiktok.stats(from, to);
  else if (channel === "shopee") r = await shopee.stats(from, to);
  else return emptyStats();
  return (r.ok && r.body) ? r.body : emptyStats();
}

// Lấy stats tổng hợp (Dashboard) hoặc từng kênh (AppDetail)
export async function fetchStats(channel, period) {
  const { from, to } = periodDates(period);
  if (channel === "all") {
    const [z, m, t, tt, sp] = await Promise.all([
      fetchOne("zalo", from, to),
      fetchOne("meta", from, to),
      fetchOne("telegram", from, to),
      fetchOne("tiktok", from, to),
      fetchOne("shopee", from, to),
    ]);
    const merged = mergeStats(mergeStats(mergeStats(mergeStats(z, m), t), tt), sp);
    return {
      ...merged,
      by_channel: {
        zalo: z.total_conv, meta: m.total_conv,
        telegram: t.total_conv, tiktok: tt.total_conv, shopee: sp.total_conv,
      },
    };
  }
  const data = await fetchOne(channel, from, to);
  return data;
}
