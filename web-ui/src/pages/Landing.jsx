import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { IcHome, IcArrow } from "../components/icons.jsx";
import { IcZalo, IcMessenger, IcInstagram, IcTelegram, IcTikTok, IcAI, IcCalendar, IcPhone, IcImage } from "../components/brandIcons.jsx";

// Trang chủ BÁN HÀNG — phong cách Marketeam: hero tối full màn hình,
// heading typewriter 2 màu, orbit 4 vòng tròn quay icon kênh, ticker logo chạy vô hạn.

const H1_DARK = "Khách nhắn là chốt đơn ngay — ";
const H1_LIGHT = "bot AI trực 5 kênh chat, kể cả khi bạn đang say giấc!";
const H1_TEXT = H1_DARK + H1_LIGHT;

// Vệ tinh bay trên quỹ đạo — dùng LOGO THẬT của kênh + glyph tính năng (màu nền theo brand).
const SATS = [
  { orbit: 1, deg: 270, r: 176, sz: 58, Icon: IcAI,        sq: true,          bg: "linear-gradient(135deg,#A068FF,#5b21b6)", glow: "rgba(160,104,255,.7)",  dl: 0.6 },
  { orbit: 2, deg: 60,  r: 250, sz: 58, Icon: IcZalo,                         bg: "linear-gradient(135deg,#2f88ff,#0068ff)", glow: "rgba(0,104,255,.6)",    dl: 0.8 },
  { orbit: 2, deg: 180, r: 250, sz: 78, Icon: IcInstagram,                    bg: "linear-gradient(135deg,#feda75,#fa7e1e 28%,#d62976 62%,#962fbf 100%)", glow: "rgba(214,41,118,.6)", dl: 1.0 },
  { orbit: 2, deg: 300, r: 250, sz: 58, Icon: IcCalendar,  sq: true,          bg: "linear-gradient(135deg,#34a853,#188038)", glow: "rgba(52,168,83,.55)",   dl: 1.2 },
  { orbit: 3, deg: 130, r: 324, sz: 88, Icon: IcMessenger,                    bg: "linear-gradient(135deg,#00c6ff,#0072ff 52%,#a033ff)", glow: "rgba(0,114,255,.55)", dl: 1.4 },
  { orbit: 4, deg: 30,  r: 398, sz: 58, Icon: IcTelegram,                     bg: "linear-gradient(135deg,#37bbfe,#229ed9)", glow: "rgba(34,158,217,.6)",   dl: 1.6 },
  { orbit: 4, deg: 95,  r: 398, sz: 88, Icon: IcTikTok,    sq: true, lg: true, bg: "linear-gradient(135deg,#111114,#000)",   glow: "rgba(37,244,238,.5)",   dl: 1.8 },
  { orbit: 4, deg: 220, r: 398, sz: 88, Icon: IcPhone,     sq: true, lg: true, bg: "linear-gradient(135deg,#A068FF,#5b21b6)", glow: "rgba(160,104,255,.5)",  dl: 2.05 },
  { orbit: 4, deg: 320, r: 398, sz: 58, Icon: IcImage,                        bg: "linear-gradient(135deg,#b18cff,#7C3AED)", glow: "rgba(160,104,255,.65)", dl: 2.3 },
];

const TICKER = [
  { Icon: IcZalo,      name: "Zalo",      color: "#2f88ff" },
  { Icon: IcMessenger, name: "Messenger", color: "#0072ff" },
  { Icon: IcInstagram, name: "Instagram", color: "#d62976" },
  { Icon: IcTelegram,  name: "Telegram",  color: "#229ed9" },
  { Icon: IcTikTok,    name: "TikTok",    color: "#111114" },
];

const FEATURES = [
  { icon: "🤖", title: "AI tư vấn & chốt khách 24/7", desc: "Khách nhắn lúc 2h sáng vẫn được trả lời ngay: báo giá, dịch vụ, lịch trống — như một nhân viên không bao giờ ngủ." },
  { icon: "📅", title: "Tự tra lịch & dữ liệu shop", desc: "Kết nối Google Sheets của bạn. Khách hỏi \"hôm nay còn chỗ không\" — bot tự tra và báo lịch trống, giá, tồn kho chính xác." },
  { icon: "🖼️", title: "Gửi ảnh dịch vụ & bảng giá", desc: "Khách xin ảnh mẫu? Bot gửi nguyên bộ ảnh + bảng giá đẹp trong 2 giây, không cần bạn động tay." },
  { icon: "📞", title: "Nhắn + gọi điện báo chủ", desc: "Khách chốt đơn hoặc cần gặp người thật — bot nhắn nhóm VÀ gọi điện cho bạn tới khi bắt máy. Không bỏ lỡ đơn nào." },
  { icon: "🧠", title: "Dạy AI trong 1 phút", desc: "Dán link bảng giá, website của bạn + vài dòng dặn dò — AI tự soạn kịch bản tư vấn cực chi tiết. Duyệt là chạy." },
  { icon: "📊", title: "Dashboard & thống kê", desc: "Xem mọi hội thoại trên 1 màn hình, tự nhắn xen vào lúc nào cũng được (bot tự nhường), thống kê tỷ lệ chốt đơn." },
];

const STEPS = [
  { n: "1", title: "Đăng ký & kết nối kênh", desc: "Tạo tài khoản miễn phí, quét QR Zalo hoặc đăng nhập Facebook — 3 phút là xong, không cần kỹ thuật." },
  { n: "2", title: "Dạy AI về shop của bạn", desc: "Dán link bảng giá + viết vài dòng hướng dẫn như dặn nhân viên mới. AI tự học hết." },
  { n: "3", title: "Bot bắt đầu chốt khách", desc: "Từ giây này mọi tin nhắn được trả lời tức thì. Bạn chỉ nhận thông báo khi khách chốt đơn." },
];

const PRICING = [
  {
    tier: "starter", icon: "🌱", name: "Khởi đầu", month: "250.000₫",
    desc: "Cho shop nhỏ mới bắt đầu",
    feats: ["6.000 lượt AI trả lời/tháng", "1 kênh tự chọn", "Xem lịch + gửi ảnh + bảng giá", "Dashboard hội thoại"],
    cta: "Dùng thử miễn phí", hot: false,
  },
  {
    tier: "pro", icon: "⭐", name: "Pro", month: "500.000₫",
    desc: "Được chọn nhiều nhất",
    feats: ["30.000 lượt AI trả lời/tháng", "TẤT CẢ kênh (Zalo, Mess, IG, Telegram, TikTok)", "Gọi điện báo chủ khi khách chốt", "Thống kê nâng cao", "Có gói vĩnh viễn 10.000.000₫"],
    cta: "Dùng thử miễn phí", hot: true,
  },
  {
    tier: "business", icon: "🏢", name: "Chuỗi", month: "1.300.000₫",
    desc: "Cho chủ nhiều cơ sở",
    feats: ["150.000 lượt AI trả lời/tháng", "Tất cả kênh, không giới hạn bot/page", "Gọi điện báo chủ", "Thống kê nhiều cơ sở", "Có gói vĩnh viễn 26.000.000₫"],
    cta: "Dùng thử miễn phí", hot: false,
  },
];

const FAQS = [
  { q: "Tôi không rành công nghệ, có dùng được không?", a: "Được. Kết nối Zalo chỉ là quét mã QR như đăng nhập Zalo PC; Messenger chỉ là bấm \"Đăng nhập Facebook\". Mọi bước đều có hướng dẫn từng ảnh trong web, và bạn luôn có thể nhắn hỗ trợ ở bong bóng chat góc màn hình." },
  { q: "Bot trả lời sai thì sao?", a: "Bạn duyệt kịch bản trước khi bot chạy, và có thể tự nhắn xen vào bất kỳ hội thoại nào — bot tự im lặng 48 giờ để nhường bạn. Tắt bot từng khách hoặc từng kênh chỉ bằng 1 nút gạt." },
  { q: "Dùng thử có mất phí không?", a: "Hoàn toàn miễn phí 3 ngày, mỗi ngày 500 lượt AI trả lời — không cần thẻ, không tự động trừ tiền. Có mã giới thiệu thì được 7 ngày." },
  { q: "Thanh toán thế nào?", a: "Nạp ví bằng chuyển khoản ngân hàng ngay trong web (có mã nội dung riêng, tiền vào ví trong vài phút) rồi chọn gói theo tháng / quý / năm / vĩnh viễn." },
];

// Kịch bản demo chạy trong khung chat
const DEMO_SCRIPT = [
  { role: "user", text: "Tối nay còn phòng không shop ơi?" },
  { role: "bot", text: "Dạ còn ạ! 😊 Tối nay bên em còn Phòng 201 (500k/đêm, view thành phố) và Phòng 301 (700k/đêm, ban công). Anh/chị đi mấy người ạ?" },
  { role: "user", text: "2 người, cho xem ảnh phòng 301 đi" },
  { role: "bot", text: "📸 Dạ em gửi ảnh Phòng 301 liền ạ… Phòng có ban công ngắm hoàng hôn cực chill luôn 🌇" },
  { role: "user", text: "Ok chốt 301 tối nay nhé!" },
  { role: "bot", text: "Tuyệt vời ạ! 🎉 Em đã giữ Phòng 301 tối nay cho mình. Chủ nhà sẽ gọi xác nhận trong ít phút. Cảm ơn anh/chị ❤️" },
];

// ── Heading gõ chữ từng ký tự, 2 màu đen/trắng, con trỏ tím nhấp nháy ──
function TypewriterHeading({ text, darkLen, speed = 35, delay = 400 }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    let i = 0, timer;
    const start = setTimeout(() => {
      timer = setInterval(() => {
        i += 1; setN(i);
        if (i >= text.length) clearInterval(timer);
      }, speed);
    }, delay);
    return () => { clearTimeout(start); clearInterval(timer); };
  }, [text, speed, delay]);
  const typed = text.slice(0, n);
  const done = n >= text.length;
  return (
    <h1 className="ld-h1">
      {/* ghost giữ đúng chiều cao để trang không giật khi đang gõ */}
      <span className="ghost" aria-hidden="true">{text}</span>
      <span className="typed">
        <span className="dark">{typed.slice(0, darkLen)}</span>
        <span className="light">{typed.slice(darkLen)}</span>
        {!done && <span className="ld-caret" />}
      </span>
    </h1>
  );
}

// ── Đếm số 0 → target với easeOutCubic (tâm orbit) ──
function useCountUp(target, duration = 2000, delay = 1200) {
  const [val, setVal] = useState(0);
  const raf = useRef(0);
  useEffect(() => {
    const t0 = setTimeout(() => {
      const start = performance.now();
      const tick = (now) => {
        const p = Math.min(1, (now - start) / duration);
        setVal(Math.round(target * (1 - Math.pow(1 - p, 3))));
        if (p < 1) raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);
    }, delay);
    return () => { clearTimeout(t0); cancelAnimationFrame(raf.current); };
  }, [target, duration, delay]);
  return val;
}

function ChevronIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

function CursorTag() {
  return (
    <div className="ld-cursor">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="#A068FF">
        <path d="M4 2l16 7.6-7 2.2-3.2 6.6L4 2z" />
      </svg>
      <span className="ld-cursor-badge">Chủ shop</span>
    </div>
  );
}

function Orbits() {
  const cnt = useCountUp(24);
  return (
    <div className="ld-orbits">
      {[1, 2, 3, 4].map((o) => (
        <div key={o} className={`orbit orbit-${o}`}>
          {SATS.filter((s) => s.orbit === o).map((s, i) => (
            <div key={i} className="ld-sat" style={{ "--deg": `${s.deg}deg`, "--r": `${s.r}px` }}>
              <div className="ld-sat-spin">
                <div
                  className={"ld-tile" + (s.sq ? " sq" : "") + (s.lg ? " lg" : "")}
                  style={{ "--sz": `${s.sz}px`, "--tile-bg": s.bg, "--tile-glow": s.glow, "--dl": `${s.dl}s` }}
                >
                  <s.Icon className="ld-tile-ico" />
                </div>
              </div>
            </div>
          ))}
        </div>
      ))}
      <div className="ld-center">
        <div className="ld-center-num">{cnt}/7</div>
        <div className="ld-center-lbl">Trực tin nhắn</div>
      </div>
    </div>
  );
}

function DemoChat() {
  const [shown, setShown] = useState(1);
  useEffect(() => {
    if (shown >= DEMO_SCRIPT.length) {
      const t = setTimeout(() => setShown(1), 6000);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setShown((s) => s + 1), DEMO_SCRIPT[shown - 1]?.role === "user" ? 900 : 1700);
    return () => clearTimeout(t);
  }, [shown]);

  return (
    <div className="ld-demo">
      <div className="ld-demo-head">
        <span className="ld-demo-ava">🏡</span>
        <div>
          <div className="ld-demo-name">Haru Staycation</div>
          <div className="ld-demo-status"><span className="cw-dot" /> Bot đang trực · trả lời trong 2s</div>
        </div>
        <span className="ld-demo-ch">💬 Zalo</span>
      </div>
      <div className="ld-demo-body">
        {DEMO_SCRIPT.slice(0, shown).map((m, i) => (
          <div key={i} className={"ld-demo-msg " + m.role} style={{ animationDelay: "0s" }}>
            {m.text}
          </div>
        ))}
        {shown < DEMO_SCRIPT.length && DEMO_SCRIPT[shown].role === "bot" && (
          <div className="ld-demo-msg bot cw-typing"><span /><span /><span /></div>
        )}
      </div>
    </div>
  );
}

// Hiện dần các phần tử [data-reveal] khi cuộn tới (IntersectionObserver).
// Có LƯỚI AN TOÀN: trình duyệt không hỗ trợ / viewport lạ → vẫn hiện đủ nội dung.
function useReveal() {
  useEffect(() => {
    const els = [...document.querySelectorAll("[data-reveal]")];
    const showAll = () => els.forEach((el) => el.classList.add("is-in"));
    if (!("IntersectionObserver" in window)) { showAll(); return; }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    els.forEach((el, i) => { el.style.transitionDelay = `${(i % 4) * 70}ms`; io.observe(el); });
    // An toàn: nếu sau 3s khách chưa cuộn (hoặc IO không chạy) → hiện hết, không bao giờ để trắng
    const t = setTimeout(showAll, 3000);
    return () => { io.disconnect(); clearTimeout(t); };
  }, []);
}

export default function Landing() {
  useReveal();
  return (
    <div className="ld">
      {/* ═══ HERO full màn hình kiểu Marketeam ═══ */}
      <section className="ld-vp">
        {/* Header */}
        <header className="ld-top">
          <div className="ld-top-in">
            <div className="ld-top-left">
              <div className="ld-logo"><span className="brand-logo sm"><IcHome width={18} height={18} /></span> <span className="ld-logo-txt">Nova<b>Chat</b></span></div>
              <nav className="ld-nav">
                <a href="#features">Tính năng</a>
                <a href="#how">Cách hoạt động</a>
                <a href="#pricing">Bảng giá</a>
                <a href="#faq">FAQ</a>
              </nav>
            </div>
            <div className="ld-top-cta">
              <Link to="/login" className="ld-login">Đăng nhập</Link>
              <div className="btn-border-wrap">
                <Link to="/register" className="ld-btn"><span>Dùng thử miễn phí</span></Link>
              </div>
            </div>
          </div>
        </header>

        {/* Hero 2 cột */}
        <div className="ld-hero">
          <div className="ld-hero-left">
            <TypewriterHeading text={H1_TEXT} darkLen={H1_DARK.length} />
            <p className="ld-sub2">
              Tự xem lịch trống, gửi ảnh &amp; bảng giá, chốt đơn / đặt lịch rồi <b>gọi điện báo bạn</b> —
              trên Zalo, Messenger, Instagram, Telegram, TikTok. Không cần thẻ · 500 lượt AI miễn phí mỗi ngày.
            </p>
            <div className="ld-hero-cta btn-border-wrap">
              <Link to="/register" className="ld-btn big from-right">
                <span>Dùng thử miễn phí 3 ngày</span>
                <ChevronIcon />
              </Link>
            </div>
            <CursorTag />
          </div>
          <div className="ld-hero-right">
            <Orbits />
          </div>
        </div>

        {/* Ticker logo kênh */}
        <div className="ld-ticker">
          <div className="ld-ticker-track">
            {[0, 1].map((g) => (
              <div key={g} className="ld-tick-group" aria-hidden={g === 1}>
                {[...TICKER, ...TICKER].map((t, i) => (
                  <span key={i} className="ld-tick-item"><span className="ico" style={{ "--ic": t.color }}><t.Icon className="ld-tick-svg" /></span>{t.name}</span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Stats band */}
      <section className="ld-stats">
        <div className="ld-wrap ld-stats-in">
          <div><b>24/7</b><span>trực tin nhắn không nghỉ</span></div>
          <div><b>5 kênh</b><span>Zalo · Mess · IG · Telegram · TikTok</span></div>
          <div><b>~2 giây</b><span>tốc độ trả lời khách</span></div>
          <div><b>5 phút</b><span>từ đăng ký tới bot chạy</span></div>
        </div>
      </section>

      {/* Demo chat */}
      <section className="ld-sec" id="demo">
        <div className="ld-wrap">
          <div className="ld-sec-tag">Xem thử</div>
          <h2 className="ld-h2">Bot chốt khách như nhân viên thật</h2>
          <p className="ld-sec-sub">Ví dụ một homestay đang dùng — spa, salon, quán ăn hay shop online của bạn cũng dạy bot y như vậy.</p>
          <div className="ld-demo-wrap">
            <DemoChat />
            <div className="ld-float ld-float-1">📞 Khách chốt đơn — đang gọi cho chủ…</div>
            <div className="ld-float ld-float-2">✅ +1 đặt phòng · Phòng 301 · tối nay</div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="ld-sec ld-sec-alt" id="features">
        <div className="ld-wrap">
          <div className="ld-sec-tag">Tính năng</div>
          <h2 className="ld-h2">Một nhân viên sale giỏi, giá bằng 1/10</h2>
          <p className="ld-sec-sub">Mọi thứ một shop dịch vụ cần để không bỏ lỡ bất kỳ khách nào.</p>
          <div className="ld-feats">
            {FEATURES.map((f) => (
              <div key={f.title} className="ld-feat" data-reveal>
                <div className="ld-feat-ico">{f.icon}</div>
                <h3>{f.title}</h3>
                <p>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="ld-sec" id="how">
        <div className="ld-wrap">
          <div className="ld-sec-tag">Cách hoạt động</div>
          <h2 className="ld-h2">Chạy trong 3 bước</h2>
          <div className="ld-steps">
            {STEPS.map((s) => (
              <div key={s.n} className="ld-step" data-reveal>
                <div className="ld-step-n">{s.n}</div>
                <h3>{s.title}</h3>
                <p>{s.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="ld-sec ld-sec-alt" id="pricing">
        <div className="ld-wrap">
          <div className="ld-sec-tag">Bảng giá</div>
          <h2 className="ld-h2">Rõ ràng, không phí ẩn</h2>
          <p className="ld-sec-sub">Mua theo quý/năm rẻ hơn tới ~17%. Mọi gói đều bắt đầu bằng 3 ngày dùng thử miễn phí.</p>
          <div className="ld-price-grid">
            {PRICING.map((p) => (
              <div key={p.tier} className={"ld-price" + (p.hot ? " hot" : "")} data-reveal>
                {p.hot && <div className="plan-badge">Phổ biến nhất</div>}
                <div className="ld-price-ico">{p.icon}</div>
                <h3>{p.name}</h3>
                <div className="ld-price-num">{p.month}<span>/tháng</span></div>
                <div className="ld-price-desc">{p.desc}</div>
                <ul>
                  {p.feats.map((f) => <li key={f}>✓ {f}</li>)}
                </ul>
                {p.hot ? (
                  <div className="btn-border-wrap" style={{ width: "100%" }}>
                    <Link to="/register" className="ld-btn ld-price-btn"><span>{p.cta}</span></Link>
                  </div>
                ) : (
                  <Link to="/register" className="ld-btn ld-price-btn"><span>{p.cta}</span></Link>
                )}
              </div>
            ))}
          </div>
          <p className="ld-price-note">🎁 Có <b>mã giới thiệu</b>? Nhập khi đăng ký để được dùng thử 7 ngày.</p>
        </div>
      </section>

      {/* FAQ */}
      <section className="ld-sec" id="faq">
        <div className="ld-wrap ld-faq-wrap">
          <div className="ld-sec-tag">Câu hỏi thường gặp</div>
          <h2 className="ld-h2">Bạn hỏi, chúng tôi trả lời</h2>
          <div className="ld-faqs">
            {FAQS.map((f) => (
              <details key={f.q} className="ld-faq" data-reveal>
                <summary>{f.q}</summary>
                <p>{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="ld-final">
        <div className="ld-wrap ld-final-in">
          <h2>Đêm nay để bot trực tin nhắn cho bạn</h2>
          <p>3 ngày miễn phí · 500 lượt AI mỗi ngày · Cài trong 5 phút</p>
          <div className="btn-border-wrap">
            <Link to="/register" className="ld-btn big on-light">
              <span>Bắt đầu miễn phí</span>
              <IcArrow width={18} height={18} />
            </Link>
          </div>
        </div>
      </section>

      <footer className="ld-footer">
        <div className="ld-wrap ld-footer-in">
          <div className="ld-logo"><span className="brand-logo sm"><IcHome width={16} height={16} /></span> <span className="ld-logo-txt">Nova<b>Chat</b></span></div>
          <div className="ld-footer-links">
            <a href="#features">Tính năng</a>
            <a href="#pricing">Bảng giá</a>
            <Link to="/login">Đăng nhập</Link>
            <Link to="/register">Đăng ký</Link>
          </div>
          <div className="ld-footer-note">Trợ lý AI đa kênh cho shop dịch vụ Việt Nam</div>
        </div>
      </footer>
    </div>
  );
}
