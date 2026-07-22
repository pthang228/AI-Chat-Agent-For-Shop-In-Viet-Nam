import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { IcHome, IcArrow } from "../components/icons.jsx";
import LogoMark from "../components/LogoMark.jsx";
import { IcZalo, IcMessenger, IcInstagram, IcTelegram, IcAI, IcCalendar, IcPhone, IcImage } from "../components/brandIcons.jsx";
import { useI18n } from "../i18n.jsx";

// Trang chủ BÁN HÀNG — phong cách Marketeam: hero tối full màn hình,
// heading typewriter 2 màu, orbit 4 vòng tròn quay icon kênh, ticker logo chạy vô hạn.
// Mọi chuỗi hiển thị lấy từ i18n (fragment src/i18n/landing.js, prefix "land.").

// Vệ tinh bay trên quỹ đạo — dùng LOGO THẬT của kênh + glyph tính năng (màu nền theo brand).
const SATS = [
  { orbit: 1, deg: 270, r: 176, sz: 58, Icon: IcAI,        sq: true,          bg: "linear-gradient(135deg,#A068FF,#5b21b6)", glow: "rgba(160,104,255,.7)",  dl: 0.6 },
  { orbit: 2, deg: 60,  r: 250, sz: 58, Icon: IcZalo,                         bg: "linear-gradient(135deg,#2f88ff,#0068ff)", glow: "rgba(0,104,255,.6)",    dl: 0.8 },
  { orbit: 2, deg: 180, r: 250, sz: 78, Icon: IcInstagram,                    bg: "linear-gradient(135deg,#feda75,#fa7e1e 28%,#d62976 62%,#962fbf 100%)", glow: "rgba(214,41,118,.6)", dl: 1.0 },
  { orbit: 2, deg: 300, r: 250, sz: 58, Icon: IcCalendar,  sq: true,          bg: "linear-gradient(135deg,#34a853,#188038)", glow: "rgba(52,168,83,.55)",   dl: 1.2 },
  { orbit: 3, deg: 130, r: 324, sz: 88, Icon: IcMessenger,                    bg: "linear-gradient(135deg,#00c6ff,#0072ff 52%,#a033ff)", glow: "rgba(0,114,255,.55)", dl: 1.4 },
  { orbit: 4, deg: 30,  r: 398, sz: 58, Icon: IcTelegram,                     bg: "linear-gradient(135deg,#37bbfe,#229ed9)", glow: "rgba(34,158,217,.6)",   dl: 1.6 },
  { orbit: 4, deg: 220, r: 398, sz: 88, Icon: IcPhone,     sq: true, lg: true, bg: "linear-gradient(135deg,#A068FF,#5b21b6)", glow: "rgba(160,104,255,.5)",  dl: 2.05 },
  { orbit: 4, deg: 320, r: 398, sz: 58, Icon: IcImage,                        bg: "linear-gradient(135deg,#b18cff,#7C3AED)", glow: "rgba(160,104,255,.65)", dl: 2.3 },
];

const TICKER = [
  { Icon: IcZalo,      name: "Zalo",      color: "#2f88ff" },
  { Icon: IcMessenger, name: "Messenger", color: "#0072ff" },
  { Icon: IcInstagram, name: "Instagram", color: "#d62976" },
  { Icon: IcTelegram,  name: "Telegram",  color: "#229ed9" },
];

// Nội dung động: chỉ giữ key i18n, gọi t() lúc render.
const FEATURES = [
  { icon: "🤖",  tk: "land.f1_t", dk: "land.f1_d" },
  { icon: "📅",  tk: "land.f2_t", dk: "land.f2_d" },
  { icon: "🖼️", tk: "land.f3_t", dk: "land.f3_d" },
  { icon: "📞",  tk: "land.f4_t", dk: "land.f4_d" },
  { icon: "🧠",  tk: "land.f5_t", dk: "land.f5_d" },
  { icon: "📊",  tk: "land.f6_t", dk: "land.f6_d" },
];

const STEPS = [
  { n: "1", tk: "land.s1_t", dk: "land.s1_d" },
  { n: "2", tk: "land.s2_t", dk: "land.s2_d" },
  { n: "3", tk: "land.s3_t", dk: "land.s3_d" },
];

const PRICING = [
  {
    tier: "starter", icon: "🌱", nameK: "land.p1_name", month: "250.000₫",
    descK: "land.p1_desc",
    feats: ["land.p1_f1", "land.p1_f2", "land.p1_f3", "land.p1_f4"],
    hot: false,
  },
  {
    tier: "pro", icon: "⭐", nameK: "land.p2_name", month: "500.000₫",
    descK: "land.p2_desc",
    feats: ["land.p2_f1", "land.p2_f2", "land.p2_f3", "land.p2_f4", "land.p2_f5"],
    hot: true,
  },
  {
    tier: "business", icon: "🏢", nameK: "land.p3_name", month: "1.300.000₫",
    descK: "land.p3_desc",
    feats: ["land.p3_f1", "land.p3_f2", "land.p3_f3", "land.p3_f4", "land.p3_f5"],
    hot: false,
  },
];

const FAQS = [
  { qk: "land.faq1_q", ak: "land.faq1_a" },
  { qk: "land.faq2_q", ak: "land.faq2_a" },
  { qk: "land.faq3_q", ak: "land.faq3_a" },
  { qk: "land.faq4_q", ak: "land.faq4_a" },
];

// Kịch bản demo chạy trong khung chat
const DEMO_SCRIPT = [
  { role: "user", key: "land.demo_m1" },
  { role: "bot",  key: "land.demo_m2" },
  { role: "user", key: "land.demo_m3" },
  { role: "bot",  key: "land.demo_m4" },
  { role: "user", key: "land.demo_m5" },
  { role: "bot",  key: "land.demo_m6" },
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
  const { t } = useI18n();
  return (
    <div className="ld-cursor">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="#A068FF">
        <path d="M4 2l16 7.6-7 2.2-3.2 6.6L4 2z" />
      </svg>
      <span className="ld-cursor-badge">{t("land.cursor_owner")}</span>
    </div>
  );
}

function Orbits() {
  const { t } = useI18n();
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
        <div className="ld-center-lbl">{t("land.orbit_lbl")}</div>
      </div>
    </div>
  );
}

function DemoChat() {
  const { t } = useI18n();
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
          <div className="ld-demo-name">Ban Mai Homestay</div>
          <div className="ld-demo-status"><span className="cw-dot" /> {t("land.demo_status")}</div>
        </div>
        <span className="ld-demo-ch">💬 Zalo</span>
      </div>
      <div className="ld-demo-body">
        {DEMO_SCRIPT.slice(0, shown).map((m, i) => (
          <div key={i} className={"ld-demo-msg " + m.role} style={{ animationDelay: "0s" }}>
            {t(m.key)}
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
  const { t } = useI18n();
  useReveal();
  const h1Dark = t("land.h1_dark");
  const h1Text = h1Dark + t("land.h1_light");
  return (
    <div className="ld">
      {/* ═══ HERO full màn hình kiểu Marketeam ═══ */}
      <section className="ld-vp">
        {/* Header */}
        <header className="ld-top">
          <div className="ld-top-in">
            <div className="ld-top-left">
              <div className="ld-logo"><LogoMark color="#FF9A78" size={34} /> <span className="ld-logo-txt">Nova<b>Chat</b></span></div>
              <nav className="ld-nav">
                <a href="#features">{t("land.nav_features")}</a>
                <a href="#how">{t("land.nav_how")}</a>
                <a href="#pricing">{t("land.nav_pricing")}</a>
                <a href="#faq">{t("land.nav_faq")}</a>
              </nav>
            </div>
            <div className="ld-top-cta">
              <Link to="/login" className="ld-login">{t("land.login")}</Link>
              <div className="btn-border-wrap">
                <Link to="/register" className="ld-btn"><span>{t("land.cta_try")}</span></Link>
              </div>
            </div>
          </div>
        </header>

        {/* Hero 2 cột */}
        <div className="ld-hero">
          <div className="ld-hero-left">
            <TypewriterHeading text={h1Text} darkLen={h1Dark.length} />
            <p className="ld-sub2">
              {t("land.sub1")}<b>{t("land.sub_bold")}</b>{t("land.sub2")}
            </p>
            <div className="ld-hero-cta btn-border-wrap">
              <Link to="/register" className="ld-btn big from-right">
                <span>{t("land.cta_try3")}</span>
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
                {[...TICKER, ...TICKER].map((c, i) => (
                  <span key={i} className="ld-tick-item"><span className="ico" style={{ "--ic": c.color }}><c.Icon className="ld-tick-svg" /></span>{c.name}</span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Stats band */}
      <section className="ld-stats">
        <div className="ld-wrap ld-stats-in">
          <div><b>24/7</b><span>{t("land.stat1")}</span></div>
          <div><b>{t("land.stat2_b")}</b><span>Zalo · Mess · IG · Telegram</span></div>
          <div><b>{t("land.stat3_b")}</b><span>{t("land.stat3")}</span></div>
          <div><b>{t("land.stat4_b")}</b><span>{t("land.stat4")}</span></div>
        </div>
      </section>

      {/* Demo chat */}
      <section className="ld-sec" id="demo">
        <div className="ld-wrap">
          <div className="ld-sec-tag">{t("land.demo_tag")}</div>
          <h2 className="ld-h2">{t("land.demo_h2")}</h2>
          <p className="ld-sec-sub">{t("land.demo_sub")}</p>
          <div className="ld-demo-wrap">
            <DemoChat />
            <div className="ld-float ld-float-1">{t("land.float1")}</div>
            <div className="ld-float ld-float-2">{t("land.float2")}</div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="ld-sec ld-sec-alt" id="features">
        <div className="ld-wrap">
          <div className="ld-sec-tag">{t("land.nav_features")}</div>
          <h2 className="ld-h2">{t("land.feat_h2")}</h2>
          <p className="ld-sec-sub">{t("land.feat_sub")}</p>
          <div className="ld-feats">
            {FEATURES.map((f) => (
              <div key={f.tk} className="ld-feat" data-reveal>
                <div className="ld-feat-ico">{f.icon}</div>
                <h3>{t(f.tk)}</h3>
                <p>{t(f.dk)}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="ld-sec" id="how">
        <div className="ld-wrap">
          <div className="ld-sec-tag">{t("land.nav_how")}</div>
          <h2 className="ld-h2">{t("land.how_h2")}</h2>
          <div className="ld-steps">
            {STEPS.map((s) => (
              <div key={s.n} className="ld-step" data-reveal>
                <div className="ld-step-n">{s.n}</div>
                <h3>{t(s.tk)}</h3>
                <p>{t(s.dk)}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="ld-sec ld-sec-alt" id="pricing">
        <div className="ld-wrap">
          <div className="ld-sec-tag">{t("land.nav_pricing")}</div>
          <h2 className="ld-h2">{t("land.price_h2")}</h2>
          <p className="ld-sec-sub">{t("land.price_sub")}</p>
          <div className="ld-price-grid">
            {PRICING.map((p) => (
              <div key={p.tier} className={"ld-price" + (p.hot ? " hot" : "")} data-reveal>
                {p.hot && <div className="plan-badge">{t("land.badge_hot")}</div>}
                <div className="ld-price-ico">{p.icon}</div>
                <h3>{t(p.nameK)}</h3>
                <div className="ld-price-num">{p.month}<span>{t("land.per_month")}</span></div>
                <div className="ld-price-desc">{t(p.descK)}</div>
                <ul>
                  {p.feats.map((f) => <li key={f}>✓ {t(f)}</li>)}
                </ul>
                {p.hot ? (
                  <div className="btn-border-wrap" style={{ width: "100%" }}>
                    <Link to="/register" className="ld-btn ld-price-btn"><span>{t("land.cta_try")}</span></Link>
                  </div>
                ) : (
                  <Link to="/register" className="ld-btn ld-price-btn"><span>{t("land.cta_try")}</span></Link>
                )}
              </div>
            ))}
          </div>
          <p className="ld-price-note">{t("land.note1")}<b>{t("land.note_bold")}</b>{t("land.note2")}</p>
        </div>
      </section>

      {/* FAQ */}
      <section className="ld-sec" id="faq">
        <div className="ld-wrap ld-faq-wrap">
          <div className="ld-sec-tag">{t("land.faq_tag")}</div>
          <h2 className="ld-h2">{t("land.faq_h2")}</h2>
          <div className="ld-faqs">
            {FAQS.map((f) => (
              <details key={f.qk} className="ld-faq" data-reveal>
                <summary>{t(f.qk)}</summary>
                <p>{t(f.ak)}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="ld-final">
        <div className="ld-wrap ld-final-in">
          <h2>{t("land.final_h2")}</h2>
          <p>{t("land.final_sub")}</p>
          <div className="btn-border-wrap">
            <Link to="/register" className="ld-btn big on-light">
              <span>{t("land.final_btn")}</span>
              <IcArrow width={18} height={18} />
            </Link>
          </div>
        </div>
      </section>

      <footer className="ld-footer">
        <div className="ld-wrap ld-footer-in">
          <div className="ld-logo"><LogoMark color="#FF9A78" size={30} /> <span className="ld-logo-txt">Nova<b>Chat</b></span></div>
          <div className="ld-footer-links">
            <a href="#features">{t("land.nav_features")}</a>
            <a href="#pricing">{t("land.nav_pricing")}</a>
            <Link to="/login">{t("land.login")}</Link>
            <Link to="/register">{t("land.register")}</Link>
          </div>
          <div className="ld-footer-note">{t("land.footer_note")}</div>
        </div>
      </footer>
    </div>
  );
}
