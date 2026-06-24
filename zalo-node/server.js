/**
 * Zalo Node service — dùng zca-js để đăng nhập QR + nhận/gửi tin Zalo,
 * làm cầu nối tới "não bộ" Python (brain.py) qua HTTP.
 *
 * Luồng:
 *   Khách nhắn Zalo → listener nhận → POST sang Python bridge (/incoming)
 *   Python brain xử lý → gọi ngược POST /send ở đây → zca-js gửi lại Zalo
 *
 * Chạy:  npm start    (mặc định cổng 4000)
 * Trang QR cơ bản:  http://localhost:4000
 */

import express from "express";
import cors from "cors";
import fs from "fs";
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
const BRIDGE_URL = process.env.PY_BRIDGE_URL || "http://127.0.0.1:5005/incoming";
const SESSION_FILE = "./zalo-session.json";
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// selfListen BẬT để nhận cả tin do tài khoản này gửi (cần cho owner-takeover).
// Tin bot tự gửi sẽ được lọc bằng msgId (xem sentMsgIds), tin còn lại = chủ gõ tay.
const ZALO_OPTS = { selfListen: true, imageMetadataGetter };

const app = express();
app.use(cors());
app.use(express.json({ limit: "15mb" }));

let zalo = new Zalo(ZALO_OPTS);
let api = null;

// ── Lọc echo: nhớ msgId các tin bot vừa gửi (giữ 2 phút) ──
const sentMsgIds = new Map(); // msgId(string) -> timestamp
function trackMsgId(id) {
  if (id !== undefined && id !== null) sentMsgIds.set(String(id), Date.now());
}
function isOwnEcho(id) {
  const now = Date.now();
  for (const [k, t] of sentMsgIds) if (now - t > 120000) sentMsgIds.delete(k);
  return id !== undefined && id !== null && sentMsgIds.has(String(id));
}
function trackSendResult(r) {
  const seen = new Set();
  function walk(v) {
    if (!v || typeof v !== "object" || seen.has(v)) return;
    seen.add(v);
    if (v.msgId !== undefined) trackMsgId(v.msgId);
    if (v.messageId !== undefined) trackMsgId(v.messageId);
    if (Array.isArray(v)) v.forEach(walk);
    else Object.values(v).forEach(walk);
  }
  walk(r);
}

// Cửa sổ "bot vừa gửi" theo từng thread — chống echo chắc chắn (không bị race như msgId).
// Đánh dấu NGAY TRƯỚC khi gọi api.sendMessage; mọi tin self tới thread đó trong
// SELF_WINDOW_MS coi là echo của bot, không phải chủ gõ tay.
const SELF_WINDOW_MS = 15000;
const MEDIA_SELF_WINDOW_MS = 120000;
const TEXT_ECHO_WINDOW_MS = 120000;
const lastBotSendAt = new Map(); // threadId(string) -> expiry timestamp
const sentTextFingerprints = new Map(); // `${threadId}:${sha1(text)}` -> timestamp

function markBotSend(threadId, windowMs = SELF_WINDOW_MS) {
  if (threadId === undefined || threadId === null) return;
  const key = String(threadId);
  const expiry = Date.now() + windowMs;
  lastBotSendAt.set(key, Math.max(lastBotSendAt.get(key) || 0, expiry));
}
function inBotSendWindow(threadId) {
  const key = String(threadId);
  const expiry = lastBotSendAt.get(key);
  if (expiry === undefined) return false;
  if (Date.now() < expiry) return true;
  lastBotSendAt.delete(key);
  return false;
}

function normalizeText(text) {
  return String(text || "").trim().replace(/\s+/g, " ");
}

function textFingerprint(text) {
  return crypto.createHash("sha1").update(normalizeText(text)).digest("hex");
}

function cleanupBotTextFingerprints() {
  const now = Date.now();
  for (const [k, t] of sentTextFingerprints) {
    if (now - t > TEXT_ECHO_WINDOW_MS) sentTextFingerprints.delete(k);
  }
}

function trackBotText(threadId, text) {
  const normalized = normalizeText(text);
  if (!normalized || threadId === undefined || threadId === null) return;
  cleanupBotTextFingerprints();
  sentTextFingerprints.set(`${String(threadId)}:${textFingerprint(normalized)}`, Date.now());
}

function isBotTextEcho(threadId, text) {
  const normalized = normalizeText(text);
  if (!normalized || threadId === undefined || threadId === null) return false;
  cleanupBotTextFingerprints();
  return sentTextFingerprints.has(`${String(threadId)}:${textFingerprint(normalized)}`);
}

// ── Cấu hình do người dùng chọn trong UI (nhóm/chủ nhận thông báo) ──
const CONFIG_FILE = "./node-config.json";
let config = { ownerGroupId: "", ownerUserId: "" };
function loadConfig() {
  try {
    if (fs.existsSync(CONFIG_FILE))
      config = { ...config, ...JSON.parse(fs.readFileSync(CONFIG_FILE, "utf-8")) };
  } catch (e) {
    console.error("[config] load lỗi:", e.message);
  }
}
function saveConfig() {
  try {
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2), "utf-8");
  } catch (e) {
    console.error("[config] save lỗi:", e.message);
  }
}
// status: idle | waiting_scan | scanned | logged_in | qr_expired | declined | error
let state = { status: "idle", qrImage: null, ownId: null, userInfo: null };

// ── Sau khi đăng nhập: gắn listener, chuyển tiếp tin khách sang Python ──
function attachListener(a) {
  api = a;
  state.status = "logged_in";
  try { state.ownId = a.getOwnId(); } catch { state.ownId = null; }
  state.qrImage = null;

  a.listener.on("message", async (message) => {
    try {
      const isGroup = message.type === ThreadType.Group;
      const content =
        typeof message.data.content === "string" ? message.data.content : "";

      let ownerTyped = false;
      if (message.isSelf) {
        // Tin từ chính tài khoản này:
        //  - trùng msgId bot vừa gửi  → echo của bot → BỎ QUA
        //  - không trùng              → chủ nhà tự gõ tay → owner-takeover
        if (isGroup) return;                       // tin nhóm: bỏ qua
        // bot tự gửi (khớp msgId HOẶC vừa gửi tới thread này trong cửa sổ): bỏ qua
        if (
          isOwnEcho(message.data.msgId) ||
          isBotTextEcho(message.threadId, content) ||
          inBotSendWindow(message.threadId)
        ) return;
        ownerTyped = true;
      }

      const payload = {
        userId: message.threadId,            // khoá hội thoại (= id khách)
        uidFrom: message.data.uidFrom,
        text: content,
        isSelf: message.isSelf,
        ownerTyped,                          // true = chủ nhà tự nhắn khách
        isGroup,
        dName: message.data.dName,
        ownId: state.ownId,
      };
      const r = await fetch(BRIDGE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) console.error("[bridge] HTTP", r.status);
    } catch (e) {
      console.error("[bridge] gửi thất bại:", e.message);
    }
  });

  a.listener.on("error", (e) => console.error("[listener] error:", e));
  a.listener.start();
  console.log("[zalo] ✅ đăng nhập xong, ownId =", state.ownId);
}

function saveSession(cred) {
  try {
    fs.writeFileSync(SESSION_FILE, JSON.stringify(cred, null, 2), "utf-8");
    console.log("[zalo] đã lưu session →", SESSION_FILE);
  } catch (e) {
    console.error("[zalo] lưu session lỗi:", e.message);
  }
}

async function tryResumeSession() {
  if (!fs.existsSync(SESSION_FILE)) {
    console.log("[zalo] chưa có session — chờ đăng nhập QR");
    return;
  }
  try {
    const cred = JSON.parse(fs.readFileSync(SESSION_FILE, "utf-8"));
    const a = await zalo.login(cred);
    attachListener(a);
    console.log("[zalo] khôi phục session thành công");
  } catch (e) {
    console.error("[zalo] không khôi phục được session:", e.message);
    state.status = "idle";
  }
}

// ── API ───────────────────────────────────────────────────────────

// Bắt đầu đăng nhập QR (chạy nền, trả về ngay; QR lấy qua /status)
app.post("/login/qr", (req, res) => {
  if (state.status === "logged_in") {
    return res.json({ status: "logged_in", ownId: state.ownId });
  }
  state.status = "waiting_scan";
  state.qrImage = null;
  state.userInfo = null;
  res.json({ status: "starting" });

  zalo = new Zalo(ZALO_OPTS);
  zalo
    .loginQR({ userAgent: USER_AGENT }, (ev) => {
      switch (ev.type) {
        case 0: // QRCodeGenerated
          state.qrImage = ev.data.image; // base64 PNG
          state.status = "waiting_scan";
          console.log("[qr] đã sinh mã QR");
          break;
        case 1: // QRCodeExpired
          state.status = "qr_expired";
          break;
        case 2: // QRCodeScanned
          state.status = "scanned";
          state.userInfo = ev.data; // { display_name, avatar }
          console.log("[qr] đã quét bởi", ev.data.display_name);
          break;
        case 3: // QRCodeDeclined
          state.status = "declined";
          break;
        case 4: // GotLoginInfo
          saveSession({
            imei: ev.data.imei,
            cookie: ev.data.cookie,
            userAgent: ev.data.userAgent,
          });
          break;
      }
    })
    .then((a) => { if (a) attachListener(a); })
    .catch((e) => {
      console.error("[qr] lỗi:", e.message);
      state.status = "error";
    });
});

// Trạng thái đăng nhập + ảnh QR hiện tại
app.get("/status", (req, res) => {
  res.json({
    status: state.status,
    qr: state.qrImage,
    ownId: state.ownId,
    userInfo: state.userInfo,
  });
});

// Gửi text (Python brain gọi vào đây). type: "user" (mặc định) | "group"
app.post("/send", async (req, res) => {
  const { userId, text, type } = req.body || {};
  if (!api) return res.status(409).json({ error: "chưa đăng nhập Zalo" });
  const tt = type === "group" ? ThreadType.Group : ThreadType.User;
  markBotSend(userId); // đánh dấu TRƯỚC khi gửi để echo không bị hiểu nhầm là chủ gõ
  trackBotText(userId, text);
  try {
    const r = await api.sendMessage(String(text), String(userId), tt);
    trackSendResult(r);
    res.json({ ok: true, result: r });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Gửi ảnh theo đường dẫn file (Python brain gọi vào đây)
app.post("/send-image", async (req, res) => {
  const { userId, paths, type } = req.body || {};
  if (!api) return res.status(409).json({ error: "chưa đăng nhập Zalo" });
  const tt = type === "group" ? ThreadType.Group : ThreadType.User;
  markBotSend(userId, MEDIA_SELF_WINDOW_MS); // chống echo ảnh bot tự gửi
  try {
    const r = await api.sendMessage(
      { msg: "", attachments: Array.isArray(paths) ? paths : [paths] },
      String(userId),
      tt,
    );
    trackSendResult(r);
    res.json({ ok: true, result: r });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Liệt kê các NHÓM acc đang ở (để lấy OWNER_GROUP_ID hợp lệ cho acc này)
app.get("/groups", async (req, res) => {
  if (!api) return res.status(409).json({ error: "chưa đăng nhập Zalo" });
  try {
    const all = await api.getAllGroups();
    const ids = Object.keys(all.gridVerMap || {});
    const names = {};
    if (ids.length) {
      try {
        const info = await api.getGroupInfo(ids);
        const m = info.gridInfoMap || {};
        for (const id of ids) names[id] = (m[id] && (m[id].name || m[id].groupName)) || "";
      } catch { /* vẫn trả id dù không lấy được tên */ }
    }
    res.json({ ownId: state.ownId, groups: ids.map((id) => ({ groupId: id, name: names[id] || "" })) });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Liệt kê BẠN BÈ (để lấy OWNER_ZALO_ID hợp lệ nếu muốn báo qua DM)
app.get("/friends", async (req, res) => {
  if (!api) return res.status(409).json({ error: "chưa đăng nhập Zalo" });
  try {
    const fr = await api.getAllFriends();
    const list = (fr || []).map((u) => ({
      userId: u.userId || u.uid || u.id,
      name: u.displayName || u.zaloName || u.dName || "",
    }));
    res.json({ ownId: state.ownId, count: list.length, friends: list });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Lấy / lưu cấu hình nhóm-chủ (UI gọi vào đây)
app.get("/config", (req, res) => res.json(config));
app.post("/config", (req, res) => {
  const { ownerGroupId, ownerUserId } = req.body || {};
  if (ownerGroupId !== undefined) config.ownerGroupId = String(ownerGroupId || "");
  if (ownerUserId !== undefined) config.ownerUserId = String(ownerUserId || "");
  saveConfig();
  console.log("[config] cập nhật:", config);
  res.json({ ok: true, config });
});

// Thông báo cho chủ nhà — gửi tới nhóm/chủ đã chọn trong UI (Python brain gọi vào đây)
app.post("/notify-owner", async (req, res) => {
  const { text } = req.body || {};
  if (!api) return res.status(409).json({ error: "chưa đăng nhập Zalo" });
  try {
    if (config.ownerGroupId) {
      const r = await api.sendMessage(String(text), String(config.ownerGroupId), ThreadType.Group);
      trackSendResult(r);
      return res.json({ ok: true, target: "group", result: r });
    }
    if (config.ownerUserId) {
      markBotSend(config.ownerUserId); // chống echo khi báo chủ qua DM
      trackBotText(config.ownerUserId, text);
      const r = await api.sendMessage(String(text), String(config.ownerUserId), ThreadType.User);
      trackSendResult(r);
      return res.json({ ok: true, target: "dm", result: r });
    }
    console.warn("[notify-owner] chưa chọn nhóm/chủ nhận thông báo");
    return res.status(400).json({ error: "chưa chọn nhóm/chủ nhận thông báo" });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Đăng xuất / xoá session
app.post("/logout", (req, res) => {
  try { if (api) api.listener.stop(); } catch {}
  api = null;
  state = { status: "idle", qrImage: null, ownId: null, userInfo: null };
  if (fs.existsSync(SESSION_FILE)) fs.unlinkSync(SESSION_FILE);
  res.json({ ok: true });
});

// ── Trang web cơ bản hiển thị QR (bản tạm, sẽ thay bằng React) ──
app.get("/", (req, res) => {
  res.type("html").send(`<!doctype html><html lang="vi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kết nối Zalo</title>
<style>
  body{font-family:-apple-system,'Segoe UI',sans-serif;background:#f0f2f5;margin:0;color:#1a1a1a}
  .wrap{max-width:420px;margin:40px auto;padding:0 16px}
  .card{background:#fff;border-radius:16px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,.08);text-align:center}
  h1{font-size:20px;color:#0068ff;margin:0 0 4px}
  p.sub{color:#666;font-size:13px;margin:0 0 20px}
  .qr{width:240px;height:240px;margin:8px auto;display:flex;align-items:center;justify-content:center;
      border:2px dashed #d0d7de;border-radius:12px;background:#fafbfc}
  .qr img{width:100%;height:100%;border-radius:8px}
  .status{margin-top:16px;font-size:14px;font-weight:600}
  .muted{color:#8b95a1}.ok{color:#1a7f37}.warn{color:#c0392b}
  button{background:#0068ff;color:#fff;border:0;border-radius:10px;padding:11px 20px;
         font-size:15px;font-weight:600;cursor:pointer;margin-top:18px}
  button:hover{opacity:.9}  button:disabled{opacity:.5;cursor:default}
  .settings{margin-top:22px;text-align:left;border-top:1px solid #eee;padding-top:18px;display:none}
  .settings h2{font-size:15px;margin:0 0 4px}
  .settings p{font-size:12px;color:#666;margin:0 0 10px}
  select{width:100%;padding:10px;border:1px solid #d0d7de;border-radius:8px;font-size:14px;background:#fff}
  .savemsg{font-size:12px;margin-top:8px;min-height:16px}
</style></head><body>
<div class="wrap"><div class="card">
  <h1>🏠 Kết nối Zalo</h1>
  <p class="sub">Quét mã QR bằng app Zalo trên điện thoại để bot tự trả lời khách</p>
  <div class="qr" id="qrBox"><span class="muted">Nhấn nút bên dưới để tạo mã QR</span></div>
  <div class="status muted" id="status">Chưa kết nối</div>
  <button onclick="startQR()" id="btn">Tạo mã QR đăng nhập</button>

  <div class="settings" id="settings">
    <h2>📢 Nhóm nhận thông báo</h2>
    <p>Chọn nhóm Zalo để bot báo khi có khách đặt phòng / cần gặp chủ.</p>
    <select id="grpSel"><option value="">— Đang tải danh sách nhóm… —</option></select>
    <button onclick="saveGroup()" id="saveBtn" style="margin-top:12px">Lưu nhóm</button>
    <div class="savemsg muted" id="saveMsg"></div>
    <div style="margin-top:18px;border-top:1px solid #eee;padding-top:12px">
      <a href="#" onclick="logout();return false" style="color:#c0392b;font-size:13px;text-decoration:none">↩ Đăng xuất / đổi tài khoản</a>
    </div>
  </div>
</div></div>
<script>
const labels={idle:["Chưa kết nối","muted"],waiting_scan:["Đang chờ quét mã…","muted"],
  scanned:["Đã quét! Xác nhận trên điện thoại…","ok"],logged_in:["✅ Đã kết nối Zalo","ok"],
  qr_expired:["Mã QR hết hạn, tạo lại nhé","warn"],declined:["Bạn đã từ chối đăng nhập","warn"],
  error:["Có lỗi xảy ra, thử lại","warn"]};
let timer=null, groupsLoaded=false;
async function startQR(){
  document.getElementById('btn').disabled=true;
  await fetch('/login/qr',{method:'POST'});
  if(timer)clearInterval(timer);
  timer=setInterval(poll,1500); poll();
}
async function poll(){
  const s=await (await fetch('/status')).json();
  const [txt,cls]=labels[s.status]||["…","muted"];
  const st=document.getElementById('status'); st.textContent=txt; st.className='status '+cls;
  const box=document.getElementById('qrBox');
  if(s.status==='logged_in'){
    box.innerHTML='<span class="ok">🎉 Đã kết nối</span>';
    if(timer)clearInterval(timer);
    document.getElementById('btn').style.display='none';
    document.getElementById('settings').style.display='block';
    if(!groupsLoaded){groupsLoaded=true; loadGroups();}
    return;
  }
  if(s.qr){const src=s.qr.startsWith('data:')?s.qr:'data:image/png;base64,'+s.qr;
    box.innerHTML='<img src="'+src+'" alt="QR">';}
  document.getElementById('btn').disabled=false;
}
async function loadGroups(){
  const sel=document.getElementById('grpSel');
  try{
    const [g,cfg]=await Promise.all([
      (await fetch('/groups')).json(), (await fetch('/config')).json()]);
    const groups=g.groups||[];
    if(!groups.length){sel.innerHTML='<option value="">(Tài khoản chưa ở nhóm nào — tạo 1 nhóm trên Zalo trước)</option>';return;}
    sel.innerHTML='<option value="">— Chọn nhóm —</option>'+
      groups.map(x=>'<option value="'+x.groupId+'">'+(x.name||x.groupId)+'</option>').join('');
    if(cfg.ownerGroupId)sel.value=cfg.ownerGroupId;
  }catch(e){sel.innerHTML='<option value="">(Lỗi tải nhóm: '+e+')</option>';}
}
async function saveGroup(){
  const sel=document.getElementById('grpSel'), msg=document.getElementById('saveMsg');
  const r=await fetch('/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ownerGroupId:sel.value})});
  if(r.ok){msg.textContent='✅ Đã lưu nhóm nhận thông báo';msg.className='savemsg ok';}
  else{msg.textContent='❌ Lưu thất bại';msg.className='savemsg warn';}
}
async function logout(){
  if(!confirm('Đăng xuất tài khoản Zalo hiện tại để đăng nhập lại?'))return;
  await fetch('/logout',{method:'POST'});
  location.reload();
}
poll();
</script></body></html>`);
});

app.listen(PORT, () => {
  console.log(`🌐 Zalo Node service: http://localhost:${PORT}`);
  loadConfig();
  tryResumeSession();
});
