/**
 * Zalo Node service — MULTI-ACCOUNT: quản lý NHIỀU tài khoản Zalo cá nhân
 * (mỗi SHOP 1 acc riêng, quét QR riêng) trong 1 tiến trình, dùng zca-js.
 *
 * Luồng:
 *   Khách nhắn Zalo (acc X) → listener của acc X → POST Python bridge (/incoming)
 *     kèm accId → brain xử lý → gọi ngược POST /send {acc: X} → gửi bằng đúng acc X.
 *
 * Multi-account:
 *   - Mỗi acc = 1 instance zca-js + 1 file session riêng + echo-filter riêng.
 *   - Acc "default" = tài khoản CHỦ NỀN TẢNG (tương thích 100% bản cũ: session
 *     ở ZALO_SESSION_FILE, user_id gửi bridge là uid TRẦN, tự mở QR khi boot).
 *   - Acc khác (shop thuê): session ở SESSIONS_DIR/<id>.json; chỉ mở QR khi
 *     shop bấm kết nối trong web; mọi endpoint nhận ?acc=<id> hoặc body.acc.
 *
 * Chạy:  npm start    (mặc định cổng 4000)
 */

import express from "express";
import cors from "cors";
import fs from "fs";
import path from "path";
import crypto from "crypto";
import { Zalo, ThreadType } from "zca-js";
import { imageSize } from "image-size";

// zca-js v2 cần hàm lấy kích thước ảnh để gửi ảnh (jpg/png/webp/gif).
// Thiếu hàm này thì sendMessage ném ZaloApiMissingImageMetadataGetter →
// ảnh không gửi được (chỉ caption text đi qua). Dùng image-size (thuần JS).
async function imageMetadataGetter(filePath) {
  try {
    const buffer = await fs.promises.readFile(filePath);
    const { width, height } = imageSize(buffer);
    return { width, height, size: buffer.length };
  } catch (e) {
    console.error("[image-size] lỗi đọc ảnh:", filePath, e.message);
    return null;
  }
}

const PORT = process.env.ZALO_NODE_PORT || 4000;
// BẢO MẬT: mặc định chỉ nghe localhost — service này KHÔNG có auth theo mặc
// định, bind mọi interface là ai cùng mạng cũng /send /logout được. Docker
// (Python gọi qua mạng nội bộ compose) đặt NODE_BIND=0.0.0.0.
const BIND_HOST = process.env.NODE_BIND || "127.0.0.1";
// NODE_API_KEY đặt → mọi request phải kèm header X-Node-Key khớp (middleware
// bên dưới). Rỗng = như cũ (dev/test local).
const NODE_API_KEY = process.env.NODE_API_KEY || "";
// BRIDGE_SECRET đặt → gửi kèm X-Bridge-Secret khi forward tin sang Python
// (bridge /incoming từ chối request thiếu secret khi production).
const BRIDGE_SECRET = process.env.BRIDGE_SECRET || "";
const BRIDGE_URL = process.env.PY_BRIDGE_URL || "http://127.0.0.1:5005/incoming";
// Alert vận hành: kênh Zalo cá nhân (zca-js) là kênh DỄ CHẾT nhất (session rớt,
// Zalo đóng socket) — khi listener chết, báo ngay qua Telegram để ops kết nối lại,
// đừng để "xanh giả" (bot im mà không ai biết). Dùng chung ALERT_TG_* với Python.
const ALERT_TG_BOT_TOKEN = process.env.ALERT_TG_BOT_TOKEN || "";
const ALERT_TG_CHAT_ID = process.env.ALERT_TG_CHAT_ID || "";
let _lastAlertAt = 0;
async function alertTelegram(text) {
  if (!ALERT_TG_BOT_TOKEN || !ALERT_TG_CHAT_ID) return;
  const now = Date.now();
  if (now - _lastAlertAt < 5 * 60 * 1000) return;   // throttle 5' (chống spam khi flapping)
  _lastAlertAt = now;
  try {
    await fetch(`https://api.telegram.org/bot${ALERT_TG_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: ALERT_TG_CHAT_ID, text: `⚠️ [NovaChat Zalo] ${text}` }),
    });
  } catch (e) {
    console.error("[alert] gửi Telegram lỗi:", e.message);
  }
}
// Acc default (chủ nền tảng) giữ NGUYÊN đường dẫn session cũ; acc shop thuê nằm
// trong SESSIONS_DIR (Docker: cả hai trỏ vào volume /data để giữ phiên qua restart).
const SESSION_FILE = process.env.ZALO_SESSION_FILE || "./zalo-session.json";
const SESSIONS_DIR = process.env.ZALO_SESSIONS_DIR ||
  path.join(path.dirname(SESSION_FILE), "zalo-sessions");
const CONFIG_FILE = process.env.ZALO_NODE_CONFIG || "./node-config.json";
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// selfListen BẬT để nhận cả tin do tài khoản này gửi (cần cho owner-takeover).
const ZALO_OPTS = { selfListen: true, imageMetadataGetter };

const SELF_WINDOW_MS = 15000;
const MEDIA_SELF_WINDOW_MS = 120000;
const TEXT_ECHO_WINDOW_MS = 120000;
const MAX_QR_REGEN = 20;

const app = express();
app.use(cors());
app.use(express.json({ limit: "15mb" }));

// So sánh chuỗi thời-gian-cố-định (chống timing attack); khác độ dài → false
// ngay (timingSafeEqual ném lỗi nếu buffer lệch độ dài).
function safeEqual(a, b) {
  const ba = Buffer.from(String(a || ""), "utf-8");
  const bb = Buffer.from(String(b || ""), "utf-8");
  return ba.length === bb.length && crypto.timingSafeEqual(ba, bb);
}

// BẢO MẬT: NODE_API_KEY đặt → mọi request (trừ GET /health) phải có header
// X-Node-Key khớp. Chặn kẻ cùng mạng gọi thẳng /send, /logout, /accounts…
// (service này điều khiển acc Zalo THẬT của các shop). Rỗng → như cũ.
app.use((req, res, next) => {
  if (!NODE_API_KEY) return next();
  if (req.method === "GET" && req.path === "/health") return next();
  if (safeEqual(req.get("X-Node-Key"), NODE_API_KEY)) return next();
  console.warn(`[auth] thiếu/sai X-Node-Key: ${req.method} ${req.path} từ ${req.ip}`);
  return res.status(401).json({ error: "unauthorized" });
});

// ── Config per-acc (nhóm/chủ nhận thông báo) ──
// Định dạng mới {accounts: {id: {ownerGroupId, ownerUserId}}}; file CŨ phẳng
// {ownerGroupId, ownerUserId} tự migrate thành accounts.default.
let configAll = { accounts: {} };
function loadConfig() {
  try {
    if (!fs.existsSync(CONFIG_FILE)) return;
    const raw = JSON.parse(fs.readFileSync(CONFIG_FILE, "utf-8")) || {};
    if (raw.accounts) configAll = { accounts: {}, ...raw };
    else configAll = { accounts: { default: { ownerGroupId: raw.ownerGroupId || "", ownerUserId: raw.ownerUserId || "" } } };
  } catch (e) {
    console.error("[config] load lỗi:", e.message);
  }
}
function saveConfig() {
  try {
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(configAll, null, 2), "utf-8");
  } catch (e) {
    console.error("[config] save lỗi:", e.message);
  }
}
function accConfig(id) {
  return (configAll.accounts[id] = configAll.accounts[id] || { ownerGroupId: "", ownerUserId: "" });
}

function normalizeText(text) {
  return String(text || "").trim().replace(/\s+/g, " ");
}
function textFingerprint(text) {
  return crypto.createHash("sha1").update(normalizeText(text)).digest("hex");
}
const SAFE_ID = /^[A-Za-z0-9_-]{1,40}$/;

// ═════════════════════════════════════════════════════════════════════
//  ZaloAccount — toàn bộ trạng thái của 1 tài khoản Zalo (1 shop)
// ═════════════════════════════════════════════════════════════════════
class ZaloAccount {
  constructor(id) {
    this.id = id;
    this.zalo = null;
    this.api = null;
    // status: idle | waiting_scan | scanned | logged_in | qr_expired |
    //         declined | disconnected | error
    this.state = { status: "idle", qrImage: null, ownId: null, userInfo: null };
    // echo filter riêng từng acc
    this.sentMsgIds = new Map();
    this.lastBotSendAt = new Map();
    this.sentTextFingerprints = new Map();
    this.avatarCache = new Map();
    // QR loop
    this.qrLoopActive = false;
    this.qrRegenCount = 0;
    this.qrLoopStartAt = 0;
  }

  sessionFile() {
    return this.id === "default" ? SESSION_FILE : path.join(SESSIONS_DIR, `${this.id}.json`);
  }
  sessionBak() { return this.sessionFile() + ".bak"; }

  // ── Echo filter ──
  trackMsgId(id) { if (id !== undefined && id !== null) this.sentMsgIds.set(String(id), Date.now()); }
  isOwnEcho(id) {
    const now = Date.now();
    for (const [k, t] of this.sentMsgIds) if (now - t > 120000) this.sentMsgIds.delete(k);
    return id !== undefined && id !== null && this.sentMsgIds.has(String(id));
  }
  trackSendResult(r) {
    const seen = new Set();
    const walk = (v) => {
      if (!v || typeof v !== "object" || seen.has(v)) return;
      seen.add(v);
      if (v.msgId !== undefined) this.trackMsgId(v.msgId);
      if (v.messageId !== undefined) this.trackMsgId(v.messageId);
      if (Array.isArray(v)) v.forEach(walk);
      else Object.values(v).forEach(walk);
    };
    walk(r);
  }
  markBotSend(threadId, windowMs = SELF_WINDOW_MS) {
    if (threadId === undefined || threadId === null) return;
    const key = String(threadId);
    this.lastBotSendAt.set(key, Math.max(this.lastBotSendAt.get(key) || 0, Date.now() + windowMs));
  }
  inBotSendWindow(threadId) {
    const key = String(threadId);
    const expiry = this.lastBotSendAt.get(key);
    if (expiry === undefined) return false;
    if (Date.now() < expiry) return true;
    this.lastBotSendAt.delete(key);
    return false;
  }
  _cleanFingerprints() {
    const now = Date.now();
    for (const [k, t] of this.sentTextFingerprints)
      if (now - t > TEXT_ECHO_WINDOW_MS) this.sentTextFingerprints.delete(k);
  }
  trackBotText(threadId, text) {
    const n = normalizeText(text);
    if (!n || threadId === undefined || threadId === null) return;
    this._cleanFingerprints();
    this.sentTextFingerprints.set(`${String(threadId)}:${textFingerprint(n)}`, Date.now());
  }
  isBotTextEcho(threadId, text) {
    const n = normalizeText(text);
    if (!n || threadId === undefined || threadId === null) return false;
    this._cleanFingerprints();
    return this.sentTextFingerprints.has(`${String(threadId)}:${textFingerprint(n)}`);
  }

  // ── Avatar (cache 1 lần/khách) ──
  async getAvatar(uid) {
    if (!uid || !this.api) return "";
    if (this.avatarCache.has(uid)) return this.avatarCache.get(uid);
    let url = "";
    try {
      const info = await this.api.getUserInfo(uid);
      const buckets = [info?.changed_profiles, info?.unchanged_profiles, info?.profiles];
      for (const b of buckets) {
        if (!b) continue;
        for (const [k, p] of Object.entries(b)) {
          if (k === uid || k.startsWith(uid + "_") || String(p?.userId) === uid) {
            url = p?.avatar || p?.avt || "";
            if (url) break;
          }
        }
        if (url) break;
      }
    } catch (e) {
      console.error(`[${this.id}][avatar] getUserInfo lỗi:`, e.message);
    }
    this.avatarCache.set(uid, url);
    return url;
  }

  // ── Đăng nhập xong: gắn listener, chuyển tin sang Python kèm accId ──
  attachListener(a) {
    this.api = a;
    this.state.status = "logged_in";
    try { this.state.ownId = a.getOwnId(); } catch { this.state.ownId = null; }
    this.state.qrImage = null;

    a.listener.on("message", async (message) => {
      try {
        const isGroup = message.type === ThreadType.Group;
        const content = typeof message.data.content === "string" ? message.data.content : "";

        let ownerTyped = false;
        if (message.isSelf) {
          if (isGroup) return;
          if (
            this.isOwnEcho(message.data.msgId) ||
            this.isBotTextEcho(message.threadId, content) ||
            this.inBotSendWindow(message.threadId)
          ) return;
          ownerTyped = true;   // chủ shop tự gõ tay trên điện thoại
        }

        const payload = {
          acc: this.id,                        // ← MULTI-ACC: shop nào
          userId: message.threadId,
          uidFrom: message.data.uidFrom,
          text: content,
          isSelf: message.isSelf,
          ownerTyped,
          isGroup,
          dName: message.data.dName,
          avatar: message.isSelf
            ? ""
            : message.data.avt || (await this.getAvatar(message.threadId)) || "",
          ownId: this.state.ownId,
        };
        // BRIDGE_SECRET đặt → gửi kèm X-Bridge-Secret (bridge production
        // từ chối POST /incoming thiếu secret — chống giả tin cùng mạng)
        const bridgeHeaders = { "Content-Type": "application/json" };
        if (BRIDGE_SECRET) bridgeHeaders["X-Bridge-Secret"] = BRIDGE_SECRET;
        const r = await fetch(BRIDGE_URL, {
          method: "POST",
          headers: bridgeHeaders,
          body: JSON.stringify(payload),
        });
        if (!r.ok) console.error(`[${this.id}][bridge] HTTP`, r.status);
      } catch (e) {
        console.error(`[${this.id}][bridge] gửi thất bại:`, e.message);
      }
    });

    // KẾT NỐI LẠI khi socket sống lại (zca-js emit "connected" cả lần đầu lẫn
    // sau mỗi lần tự reconnect) → health xanh trở lại.
    a.listener.on("connected", () => {
      if (this.state.status !== "logged_in") {
        console.log(`[${this.id}][listener] 🔄 kết nối lại OK → logged_in`);
      }
      this.state.status = "logged_in";
    });
    // Socket rớt (mạng/Zalo đóng): zca-js LUÔN emit "disconnected", rồi TỰ
    // reconnect nếu retryOnClose+code cho phép. Hạ status ≠ logged_in → /health
    // trả 503 (không còn "xanh giả" khi kênh chết) + báo ops qua Telegram.
    a.listener.on("disconnected", (code, reason) => {
      console.warn(`[${this.id}][listener] socket rớt (code=${code}) → đang tự kết nối lại`);
      this.state.status = "reconnecting";
      alertTelegram(`Kênh Zalo acc "${this.id}" rớt kết nối (code ${code}) — đang tự kết nối lại.`);
    });
    // Đóng HẲN (không retry được — vd session hết hạn / đăng nhập nơi khác):
    // cần quét QR lại. Giữ status disconnected để health đỏ tới khi chủ xử lý.
    a.listener.on("closed", (code, reason) => {
      console.error(`[${this.id}][listener] đóng hẳn (code=${code}) — cần đăng nhập lại`);
      this.state.status = "disconnected";
      alertTelegram(`Kênh Zalo acc "${this.id}" MẤT kết nối (code ${code}) — cần quét QR đăng nhập lại.`);
    });
    a.listener.on("error", (e) => console.error(`[${this.id}][listener] error:`, e?.message || e));
    // retryOnClose:true → zca-js TỰ kết nối lại khi socket rớt (trước đây mặc định
    // false → rớt là chết im, status kẹt "logged_in", health xanh giả — bug thật).
    a.listener.start({ retryOnClose: true });
    console.log(`[${this.id}][zalo] ✅ đăng nhập xong, ownId =`, this.state.ownId);
  }

  saveSession(cred) {
    try {
      const f = this.sessionFile();
      fs.mkdirSync(path.dirname(f), { recursive: true });
      fs.writeFileSync(f, JSON.stringify(cred, null, 2), "utf-8");
      try { fs.copyFileSync(f, this.sessionBak()); } catch {}
      console.log(`[${this.id}][zalo] đã lưu session →`, f);
    } catch (e) {
      console.error(`[${this.id}][zalo] lưu session lỗi:`, e.message);
    }
  }

  async tryResumeSession(autoQrIfMissing = false) {
    if (!fs.existsSync(this.sessionFile())) {
      if (autoQrIfMissing) {
        console.log(`[${this.id}][zalo] chưa có session — tự mở luồng QR`);
        this.startQrLogin(false);
      }
      return;
    }
    try {
      const cred = JSON.parse(fs.readFileSync(this.sessionFile(), "utf-8"));
      this.zalo = new Zalo(ZALO_OPTS);
      const a = await this.zalo.login(cred);
      this.attachListener(a);
      console.log(`[${this.id}][zalo] khôi phục session thành công`);
    } catch (e) {
      // Resume lỗi (có thể do mạng) → GIỮ session, mở QR để đăng nhập lại nếu muốn
      console.error(`[${this.id}][zalo] không khôi phục được session:`, e.message, "→ mở QR (giữ session cũ)");
      this.state.status = "idle";
      this.startQrLogin(false);
    }
  }

  // ── QR login với tự làm mới + backoff (chống Zalo throttle) ──
  async startQrLogin(isRetry = false) {
    if (this.state.status === "logged_in") return;
    if (this.qrLoopActive) return;
    if (!isRetry) this.qrRegenCount = 0;
    this.qrLoopActive = true;
    this.qrLoopStartAt = Date.now();
    this.state.status = "waiting_scan";
    this.state.qrImage = null;
    this.state.userInfo = null;

    try {
      this.zalo = new Zalo(ZALO_OPTS);
      const a = await this.zalo.loginQR({ userAgent: USER_AGENT }, (ev) => {
        switch (ev.type) {
          case 0:
            this.state.qrImage = ev.data.image;
            this.state.status = "waiting_scan";
            console.log(`[${this.id}][qr] đã sinh mã QR`);
            break;
          case 1:
            this.state.status = "qr_expired";
            console.log(`[${this.id}][qr] mã hết hạn → sẽ tự làm mới`);
            break;
          case 2:
            this.state.status = "scanned";
            this.state.userInfo = ev.data;
            console.log(`[${this.id}][qr] đã quét bởi`, ev.data.display_name);
            break;
          case 3:
            this.state.status = "declined";
            break;
          case 4:
            this.saveSession({ imei: ev.data.imei, cookie: ev.data.cookie, userAgent: ev.data.userAgent });
            break;
        }
      });
      this.qrLoopActive = false;
      if (a) { this.attachListener(a); return; }
      this._maybeRegenQr();
    } catch (e) {
      this.qrLoopActive = false;
      if (this.state.status === "logged_in" || this.state.status === "declined") return;
      console.log(`[${this.id}][qr] vòng QR kết thúc (`, e.message, ") → làm mới");
      this._maybeRegenQr();
    }
  }

  _maybeRegenQr() {
    if (this.state.status === "logged_in" || this.state.status === "declined") return;
    if (this.qrRegenCount >= MAX_QR_REGEN) {
      this.state.status = "qr_expired";
      console.log(`[${this.id}][qr] đã làm mới ${MAX_QR_REGEN} lần chưa ai quét → tạm dừng`);
      return;
    }
    this.qrRegenCount++;
    const lived = Date.now() - this.qrLoopStartAt;
    const delay = lived < 5000 ? 8000 : 1500;
    setTimeout(() => this.startQrLogin(true), delay);
  }

  statusPayload() {
    return {
      acc: this.id,
      status: this.state.status,
      qr: this.state.qrImage,
      ownId: this.state.ownId,
      userInfo: this.state.userInfo,
      hasSession: fs.existsSync(this.sessionFile()),
      hasBackup: fs.existsSync(this.sessionBak()),
    };
  }
}

// ── Registry account ──
const accounts = new Map();   // id → ZaloAccount
function getAccount(id) {
  id = String(id || "default");
  if (!SAFE_ID.test(id)) id = "default";
  if (!accounts.has(id)) accounts.set(id, new ZaloAccount(id));
  return accounts.get(id);
}
// acc từ request: ?acc= (GET) hoặc body.acc (POST); mặc định "default"
function reqAcc(req) {
  return getAccount((req.query && req.query.acc) || (req.body && req.body.acc) || "default");
}

// ═════════════════════════════════════════════════════════════════════
//  API — mọi endpoint nhận acc (mặc định "default" — tương thích bản cũ)
// ═════════════════════════════════════════════════════════════════════

// Health cho Docker healthcheck + uptime monitor. Trước đây middleware whitelist
// GET /health nhưng KHÔNG có route → 404: container "Up" xanh trong khi listener
// Zalo chết im lặng. 503 khi có account từng đăng nhập mà rơi khỏi logged_in.
app.get("/health", (req, res) => {
  const accs = [];
  let degraded = false;
  for (const [id, acct] of accounts) {
    const st = acct.state.status;
    accs.push({ acc: id, status: st });
    if (st !== "logged_in" && fs.existsSync(acct.sessionFile())) degraded = true;
  }
  res.status(degraded ? 503 : 200).json({ ok: !degraded, accounts: accs });
});

// Danh sách account đang quản lý (debug/quản trị)
app.get("/accounts", (req, res) => {
  const out = [];
  for (const [id, acct] of accounts) {
    out.push({ acc: id, status: acct.state.status, ownId: acct.state.ownId,
               hasSession: fs.existsSync(acct.sessionFile()) });
  }
  res.json({ accounts: out });
});

// Bắt đầu đăng nhập QR (chạy nền; QR lấy qua /status)
app.post("/login/qr", (req, res) => {
  const acct = reqAcc(req);
  if (acct.state.status === "logged_in") {
    return res.json({ status: "logged_in", ownId: acct.state.ownId });
  }
  acct.startQrLogin(false);
  res.json({ status: "starting", acc: acct.id });
});

// Trạng thái đăng nhập + ảnh QR hiện tại
app.get("/status", (req, res) => res.json(reqAcc(req).statusPayload()));

// Gửi text (Python brain gọi). body: {acc?, userId, text, type}
app.post("/send", async (req, res) => {
  const acct = reqAcc(req);
  const { userId, text, type } = req.body || {};
  if (!acct.api) return res.status(409).json({ error: "chưa đăng nhập Zalo", acc: acct.id });
  const tt = type === "group" ? ThreadType.Group : ThreadType.User;
  acct.markBotSend(userId);
  acct.trackBotText(userId, text);
  try {
    const r = await acct.api.sendMessage(String(text), String(userId), tt);
    acct.trackSendResult(r);
    res.json({ ok: true, result: r });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Gửi ảnh theo đường dẫn file
app.post("/send-image", async (req, res) => {
  const acct = reqAcc(req);
  const { userId, paths, type } = req.body || {};
  if (!acct.api) return res.status(409).json({ error: "chưa đăng nhập Zalo", acc: acct.id });
  const tt = type === "group" ? ThreadType.Group : ThreadType.User;
  acct.markBotSend(userId, MEDIA_SELF_WINDOW_MS);
  try {
    const r = await acct.api.sendMessage(
      { msg: "", attachments: Array.isArray(paths) ? paths : [paths] },
      String(userId), tt);
    acct.trackSendResult(r);
    res.json({ ok: true, result: r });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Liệt kê nhóm của acc (chọn nhóm nhận thông báo)
app.get("/groups", async (req, res) => {
  const acct = reqAcc(req);
  if (!acct.api) return res.status(409).json({ error: "chưa đăng nhập Zalo" });
  try {
    const all = await acct.api.getAllGroups();
    const ids = Object.keys(all.gridVerMap || {});
    const names = {};
    if (ids.length) {
      try {
        const info = await acct.api.getGroupInfo(ids);
        const m = info.gridInfoMap || {};
        for (const id of ids) names[id] = (m[id] && (m[id].name || m[id].groupName)) || "";
      } catch { /* vẫn trả id dù không lấy được tên */ }
    }
    res.json({ ownId: acct.state.ownId, groups: ids.map((id) => ({ groupId: id, name: names[id] || "" })) });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Avatar THẬT của 1 khách (bridge backfill)
app.get("/avatar/:uid", async (req, res) => {
  const acct = reqAcc(req);
  if (!acct.api) return res.status(409).json({ error: "chưa đăng nhập Zalo" });
  try {
    const url = await acct.getAvatar(String(req.params.uid));
    res.json({ uid: req.params.uid, avatar: url });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Bạn bè của acc
app.get("/friends", async (req, res) => {
  const acct = reqAcc(req);
  if (!acct.api) return res.status(409).json({ error: "chưa đăng nhập Zalo" });
  try {
    const fr = await acct.api.getAllFriends();
    const list = (fr || []).map((u) => ({
      userId: u.userId || u.uid || u.id,
      name: u.displayName || u.zaloName || u.dName || "",
    }));
    res.json({ ownId: acct.state.ownId, count: list.length, friends: list });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Cấu hình nhóm/chủ nhận thông báo — PER ACC
app.get("/config", (req, res) => res.json(accConfig(reqAcc(req).id)));
app.post("/config", (req, res) => {
  const acct = reqAcc(req);
  const cfg = accConfig(acct.id);
  const { ownerGroupId, ownerUserId } = req.body || {};
  if (ownerGroupId !== undefined) cfg.ownerGroupId = String(ownerGroupId || "");
  if (ownerUserId !== undefined) cfg.ownerUserId = String(ownerUserId || "");
  saveConfig();
  console.log(`[${acct.id}][config] cập nhật:`, cfg);
  res.json({ ok: true, config: cfg });
});

// Báo chủ shop — gửi tới nhóm/DM đã chọn CỦA ACC ĐÓ
app.post("/notify-owner", async (req, res) => {
  const acct = reqAcc(req);
  const cfg = accConfig(acct.id);
  const { text } = req.body || {};
  if (!acct.api) return res.status(409).json({ error: "chưa đăng nhập Zalo" });
  try {
    if (cfg.ownerGroupId) {
      const r = await acct.api.sendMessage(String(text), String(cfg.ownerGroupId), ThreadType.Group);
      acct.trackSendResult(r);
      return res.json({ ok: true, target: "group", result: r });
    }
    if (cfg.ownerUserId) {
      acct.markBotSend(cfg.ownerUserId);
      acct.trackBotText(cfg.ownerUserId, text);
      const r = await acct.api.sendMessage(String(text), String(cfg.ownerUserId), ThreadType.User);
      acct.trackSendResult(r);
      return res.json({ ok: true, target: "dm", result: r });
    }
    return res.status(400).json({ error: "chưa chọn nhóm/chủ nhận thông báo" });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// TẠM NGẮT — dừng bot nhưng GIỮ đăng nhập (kết nối lại không cần QR)
app.post("/disconnect", (req, res) => {
  const acct = reqAcc(req);
  try { if (acct.api) acct.api.listener.stop(); } catch {}
  acct.api = null;
  acct.qrLoopActive = false;
  acct.state = { status: "disconnected", qrImage: null, ownId: null, userInfo: null };
  console.log(`[${acct.id}][zalo] tạm ngắt (giữ session)`);
  res.json({ ok: true });
});

// KẾT NỐI LẠI từ session đã lưu — KHÔNG cần QR
app.post("/reconnect", (req, res) => {
  const acct = reqAcc(req);
  if (acct.state.status === "logged_in") return res.json({ ok: true, status: "logged_in" });
  if (!fs.existsSync(acct.sessionFile())) {
    return res.status(409).json({ error: "chưa có phiên đã lưu — cần quét QR" });
  }
  acct.qrLoopActive = false;
  res.json({ ok: true, status: "reconnecting" });
  acct.tryResumeSession();
});

// ĐĂNG XUẤT / ĐỔI TÀI KHOẢN — sao lưu session rồi xoá + mở QR mới
app.post("/logout", (req, res) => {
  const acct = reqAcc(req);
  try { if (acct.api) acct.api.listener.stop(); } catch {}
  acct.api = null;
  acct.qrLoopActive = false;
  try { if (fs.existsSync(acct.sessionFile())) fs.copyFileSync(acct.sessionFile(), acct.sessionBak()); } catch {}
  acct.state = { status: "idle", qrImage: null, ownId: null, userInfo: null };
  try { if (fs.existsSync(acct.sessionFile())) fs.unlinkSync(acct.sessionFile()); } catch {}
  res.json({ ok: true });
  acct.startQrLogin(false);
});

// KHÔI PHỤC tài khoản vừa đăng xuất (bản .bak) — không cần quét lại
app.post("/restore-session", (req, res) => {
  const acct = reqAcc(req);
  if (!fs.existsSync(acct.sessionBak())) {
    return res.status(409).json({ error: "không có bản sao lưu để khôi phục" });
  }
  try { fs.copyFileSync(acct.sessionBak(), acct.sessionFile()); }
  catch (e) { return res.status(500).json({ error: e.message }); }
  acct.qrLoopActive = false;
  acct.state = { status: "idle", qrImage: null, ownId: null, userInfo: null };
  res.json({ ok: true, status: "reconnecting" });
  acct.tryResumeSession();
});

// Trang QR cơ bản (acc default — bản dự phòng khi không dùng web React)
app.get("/", (req, res) => {
  res.type("html").send(`<!doctype html><html lang="vi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kết nối Zalo</title>
<style>
  body{font-family:-apple-system,'Segoe UI',sans-serif;background:#f0f2f5;margin:0;color:#1a1a1a}
  .wrap{max-width:420px;margin:40px auto;padding:0 16px}
  .card{background:#fff;border-radius:16px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,.08);text-align:center}
  h1{font-size:20px;color:#0068ff;margin:0 0 4px}
  .qr{width:240px;height:240px;margin:8px auto;display:flex;align-items:center;justify-content:center;
      border:2px dashed #d0d7de;border-radius:12px;background:#fafbfc}
  .qr img{width:100%;height:100%;border-radius:8px}
  .status{margin-top:16px;font-size:14px;font-weight:600}
  .muted{color:#8b95a1}.ok{color:#1a7f37}.warn{color:#c0392b}
  button{background:#0068ff;color:#fff;border:0;border-radius:10px;padding:11px 20px;
         font-size:15px;font-weight:600;cursor:pointer;margin-top:18px}
</style></head><body>
<div class="wrap"><div class="card">
  <h1>🏠 Kết nối Zalo (acc default)</h1>
  <div class="qr" id="qrBox"><span class="muted">Đang tải…</span></div>
  <div class="status muted" id="status">Chưa kết nối</div>
  <button onclick="startQR()" id="btn">Làm mới mã QR</button>
</div></div>
<script>
const labels={idle:["Chưa kết nối","muted"],waiting_scan:["Đang chờ quét mã…","muted"],
  scanned:["Đã quét! Xác nhận trên điện thoại…","ok"],logged_in:["✅ Đã kết nối Zalo","ok"],
  qr_expired:["Đang làm mới mã…","muted"],declined:["Bạn đã từ chối đăng nhập","warn"],
  disconnected:["Đã tạm ngắt","muted"],error:["Có lỗi xảy ra, thử lại","warn"]};
async function startQR(){await fetch('/login/qr',{method:'POST'});}
async function poll(){
  const s=await (await fetch('/status')).json();
  const [txt,cls]=labels[s.status]||["…","muted"];
  const st=document.getElementById('status'); st.textContent=txt; st.className='status '+cls;
  const box=document.getElementById('qrBox');
  if(s.status==='logged_in'){box.innerHTML='<span class="ok">🎉 Đã kết nối</span>';return;}
  if(s.qr){const src=s.qr.startsWith('data:')?s.qr:'data:image/png;base64,'+s.qr;
    box.innerHTML='<img src="'+src+'" alt="QR">';}
}
setInterval(poll,2000); poll();
</script></body></html>`);
});

// ── Boot: resume acc default (auto-QR như bản cũ) + mọi acc có session ──
// BIND_HOST mặc định 127.0.0.1 (chỉ máy này gọi được); Docker đặt NODE_BIND=0.0.0.0
app.listen(PORT, BIND_HOST, () => {
  console.log(`🌐 Zalo Node service (multi-account): http://${BIND_HOST}:${PORT}` +
              (NODE_API_KEY ? " (yêu cầu X-Node-Key)" : ""));
  loadConfig();
  getAccount("default").tryResumeSession(true);
  try {
    if (fs.existsSync(SESSIONS_DIR)) {
      for (const f of fs.readdirSync(SESSIONS_DIR)) {
        if (!f.endsWith(".json") || f.endsWith(".bak")) continue;
        const id = f.replace(/\.json$/, "");
        if (SAFE_ID.test(id)) getAccount(id).tryResumeSession(false);
      }
    }
  } catch (e) {
    console.error("[boot] quét sessions dir lỗi:", e.message);
  }
});
