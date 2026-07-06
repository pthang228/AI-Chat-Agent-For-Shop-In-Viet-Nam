/*
 * NovaChat widget — bong bóng chat nhúng vào website của chủ shop.
 * Nhúng:  <script src="<server>/widget.js" data-site="<site_id>" defer></script>
 *
 * Tự chứa 100% (không lib, CSS inject) — không đụng gì tới trang chủ nhà.
 * API base = origin của CHÍNH file script này → không cần cấu hình gì thêm.
 * visitor_id sinh ngẫu nhiên, lưu localStorage → khách quay lại vẫn nhớ hội thoại.
 * Giao thức: POST /webchat/pub/send (không preflight) + poll /webchat/pub/poll
 * (1s trong 30s sau khi gửi — chờ bot; 4s khi mở im — bắt tin chủ shop nhắn tay).
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script) return;
  var SITE = script.getAttribute("data-site") || "";
  if (!SITE) { console.warn("[NovaChat] thiếu data-site"); return; }
  var BASE = (function () {
    try { return new URL(script.src).origin; } catch (e) { return ""; }
  })();
  if (!BASE) return;
  if (document.getElementById("nvc-root")) return;   // chống nhúng 2 lần

  // ── visitor id bền theo trình duyệt ─────────────────────────────
  var VKEY = "nvc_visitor_" + SITE;
  var visitor = "";
  try { visitor = localStorage.getItem(VKEY) || ""; } catch (e) {}
  if (!/^[A-Za-z0-9_-]{6,64}$/.test(visitor)) {
    visitor = "v";
    var abc = "abcdefghijklmnopqrstuvwxyz0123456789";
    for (var i = 0; i < 15; i++) visitor += abc[Math.floor(Math.random() * abc.length)];
    try { localStorage.setItem(VKEY, visitor); } catch (e) {}
  }

  // ── CSS ──────────────────────────────────────────────────────────
  var css = [
    "#nvc-root{position:fixed;right:18px;bottom:18px;z-index:2147483000;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;line-height:1.45}",
    "#nvc-root *{box-sizing:border-box;margin:0;padding:0}",
    "#nvc-fab{width:56px;height:56px;border-radius:50%;border:0;cursor:pointer;background:linear-gradient(135deg,#7C3AED,#6d28d9);color:#fff;box-shadow:0 6px 20px rgba(109,40,217,.45);display:flex;align-items:center;justify-content:center;transition:transform .15s}",
    "#nvc-fab:hover{transform:scale(1.06)}",
    "#nvc-panel{display:none;position:absolute;right:0;bottom:70px;width:340px;max-width:calc(100vw - 36px);height:480px;max-height:calc(100vh - 110px);background:#fff;border-radius:16px;box-shadow:0 12px 40px rgba(20,10,50,.28);overflow:hidden;flex-direction:column}",
    "#nvc-panel.open{display:flex}",
    "#nvc-head{background:linear-gradient(135deg,#7C3AED,#6d28d9);color:#fff;padding:12px 14px;display:flex;align-items:center;gap:10px}",
    "#nvc-head .t{font-weight:700;font-size:14.5px}",
    "#nvc-head .s{font-size:11.5px;opacity:.85;display:flex;align-items:center;gap:5px}",
    "#nvc-head .dot{width:7px;height:7px;border-radius:50%;background:#4ade80;display:inline-block}",
    "#nvc-close{margin-left:auto;background:none;border:0;color:#fff;font-size:17px;cursor:pointer;opacity:.85;padding:4px}",
    "#nvc-body{flex:1;overflow-y:auto;padding:12px;background:linear-gradient(180deg,#f7f5fd,#f2eefb);display:flex;flex-direction:column;gap:4px}",
    ".nvc-msg{max-width:82%;padding:8px 12px;border-radius:16px;font-size:13.5px;white-space:pre-wrap;overflow-wrap:break-word}",
    ".nvc-msg.bot{align-self:flex-start;background:#eceaf3;color:#1c1533;border-bottom-left-radius:6px}",
    ".nvc-msg.me{align-self:flex-end;background:linear-gradient(135deg,#7C3AED,#6d28d9);color:#fff;border-bottom-right-radius:6px}",
    ".nvc-msg img{max-width:100%;border-radius:10px;display:block;margin:2px 0}",
    ".nvc-msg video,.nvc-msg audio{max-width:100%;display:block;margin:2px 0}",
    ".nvc-typing span{display:inline-block;width:6px;height:6px;border-radius:50%;background:#a78bda;margin:0 2px;animation:nvcb 1.1s infinite}",
    ".nvc-typing span:nth-child(2){animation-delay:.18s}.nvc-typing span:nth-child(3){animation-delay:.36s}",
    "@keyframes nvcb{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-4px);opacity:1}}",
    "#nvc-foot{display:flex;gap:8px;padding:10px;background:#fff;border-top:1px solid #eee9f8}",
    "#nvc-input{flex:1;border:0;background:#f1eef9;border-radius:22px;padding:10px 14px;font-size:13.5px;outline:none;color:#1c1533}",
    "#nvc-sendbtn{width:40px;height:40px;border-radius:50%;border:0;cursor:pointer;background:linear-gradient(135deg,#7C3AED,#6d28d9);color:#fff;font-size:15px;flex:none}",
    "#nvc-sendbtn:disabled{opacity:.5;cursor:default}",
    "#nvc-brand{text-align:center;font-size:10px;color:#b0a8c9;padding:3px 0 6px;background:#fff}",
    "#nvc-brand a{color:#8b7ec9;text-decoration:none}",
    "@media (max-width:420px){#nvc-panel{width:calc(100vw - 24px);right:-6px}}"
  ].join("\n");
  var st = document.createElement("style");
  st.textContent = css;
  document.head.appendChild(st);

  // ── DOM ──────────────────────────────────────────────────────────
  var root = document.createElement("div");
  root.id = "nvc-root";
  root.innerHTML =
    '<div id="nvc-panel" role="dialog" aria-label="Chat với shop">' +
      '<div id="nvc-head">' +
        '<div><div class="t" id="nvc-title">Hỗ trợ trực tuyến</div>' +
        '<div class="s"><span class="dot"></span>Thường trả lời ngay</div></div>' +
        '<button id="nvc-close" aria-label="Đóng">✕</button>' +
      "</div>" +
      '<div id="nvc-body"></div>' +
      '<div id="nvc-foot">' +
        '<input id="nvc-input" placeholder="Nhập tin nhắn..." maxlength="1000" autocomplete="off">' +
        '<button id="nvc-sendbtn" aria-label="Gửi">➤</button>' +
      "</div>" +
      '<div id="nvc-brand">Chạy bởi <a href="' + BASE + '" target="_blank" rel="noopener">NovaChat</a></div>' +
    "</div>" +
    '<button id="nvc-fab" aria-label="Mở chat">' +
      '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>' +
    "</button>";
  document.body.appendChild(root);

  var panel = document.getElementById("nvc-panel");
  var body = document.getElementById("nvc-body");
  var input = document.getElementById("nvc-input");
  var sendBtn = document.getElementById("nvc-sendbtn");

  // ── render ───────────────────────────────────────────────────────
  function mediaURL(u) { return /^https?:\/\//.test(u) ? u : BASE + u; }

  function addMsg(role, node) {
    var d = document.createElement("div");
    d.className = "nvc-msg " + (role === "me" ? "me" : "bot");
    if (typeof node === "string") d.textContent = node;
    else d.appendChild(node);
    body.appendChild(d);
    body.scrollTop = body.scrollHeight;
    return d;
  }

  function addMedia(entry) {
    var wrap = document.createElement("div");
    if (entry.caption) {
      var c = document.createElement("div");
      c.textContent = entry.caption;
      wrap.appendChild(c);
    }
    var url = mediaURL(entry.url || "");
    var el;
    if (entry.type === "image") { el = document.createElement("img"); el.src = url; el.alt = ""; }
    else if (entry.type === "video") { el = document.createElement("video"); el.src = url; el.controls = true; }
    else if (entry.type === "audio") { el = document.createElement("audio"); el.src = url; el.controls = true; }
    else { el = document.createElement("a"); el.href = url; el.target = "_blank"; el.rel = "noopener"; el.textContent = "📎 Tệp đính kèm"; }
    wrap.appendChild(el);
    addMsg("bot", wrap);
  }

  var typingEl = null;
  function setTyping(on) {
    if (on && !typingEl) {
      var t = document.createElement("div");
      t.innerHTML = "<span></span><span></span><span></span>";
      t.className = "nvc-typing";
      typingEl = addMsg("bot", t);
    } else if (!on && typingEl) {
      typingEl.remove();
      typingEl = null;
    }
  }

  // ── giao thức ────────────────────────────────────────────────────
  var seq = 0;            // con trỏ outbox đã đọc tới
  var fastUntil = 0;      // poll nhanh (1s) tới thời điểm này sau khi gửi
  var opened = false;
  var loaded = false;

  function qs() { return "site=" + encodeURIComponent(SITE) + "&visitor=" + encodeURIComponent(visitor); }

  function loadHistory() {
    fetch(BASE + "/webchat/pub/history?" + qs())
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.ok) return;
        loaded = true;
        seq = j.seq || 0;               // bỏ tin cũ đã nằm trong history
        body.innerHTML = "";
        if (j.name) document.getElementById("nvc-title").textContent = j.name;
        var msgs = j.messages || [];
        if (!msgs.length) addMsg("bot", "Chào bạn! 👋 Mình có thể giúp gì cho bạn ạ?");
        msgs.forEach(function (m) {
          addMsg(m.role === "user" ? "me" : "bot", m.content || "");
        });
      })
      .catch(function () {});
  }

  function poll() {
    if (!opened || !loaded) return;
    fetch(BASE + "/webchat/pub/poll?" + qs() + "&since=" + seq)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.ok) return;
        seq = j.seq || seq;
        (j.messages || []).forEach(function (m) {
          setTyping(false);
          if (m.type === "text") addMsg("bot", m.text || "");
          else addMedia(m);
        });
      })
      .catch(function () {});
  }
  var tick = 0;
  setInterval(function () {
    if (!opened) return;
    var fast = Date.now() < fastUntil;
    // nhịp 1s: poll khi đang chờ bot; nhịp 4s khi im (đếm bằng tick)
    tick++;
    if (fast || tick % 4 === 0) poll();
  }, 1000);

  function send() {
    var text = (input.value || "").trim();
    if (!text) return;
    input.value = "";
    addMsg("me", text);
    sendBtn.disabled = true;
    fetch(BASE + "/webchat/pub/send", {
      method: "POST",
      body: JSON.stringify({ site: SITE, visitor: visitor, text: text }),
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        sendBtn.disabled = false;
        if (!j.ok) {
          addMsg("bot", j.error === "rate"
            ? "Bạn nhắn hơi nhanh — chờ chút rồi gửi tiếp nhé 🙏"
            : "Không gửi được tin, bạn thử lại giúp mình nhé 🙏");
          return;
        }
        if (j.bot) setTyping(true);
        fastUntil = Date.now() + 30000;   // poll nhanh 30s chờ trả lời
      })
      .catch(function () {
        sendBtn.disabled = false;
        addMsg("bot", "Mất kết nối — bạn kiểm tra mạng rồi thử lại nhé 🙏");
      });
  }

  // ── events ───────────────────────────────────────────────────────
  document.getElementById("nvc-fab").addEventListener("click", function () {
    opened = !panel.classList.contains("open");
    panel.classList.toggle("open", opened);
    if (opened) {
      if (!loaded) loadHistory();
      setTimeout(function () { input.focus(); }, 50);
    }
  });
  document.getElementById("nvc-close").addEventListener("click", function () {
    panel.classList.remove("open");
    opened = false;
  });
  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") send();
  });
})();
