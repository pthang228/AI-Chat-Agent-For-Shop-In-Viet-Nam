// Logo NovaChat — ảnh thật. Dùng chung landing/sidebar/topbar.
//  - Mặc định: bản MÀU trên ô vuông trắng (public/logo.png) — hợp nền sáng (sidebar/topbar).
//  - color="#..." : tô silhouette (public/logo-white.png = chỉ bong bóng+vòng+chấm, KHÔNG có
//    ô vuông) sang màu bất kỳ bằng CSS mask — hợp nền tối (hero landing). VD mint #4FE3C1.
//  - white=true : silhouette trắng (ảnh thẳng).
export default function LogoMark({ size = 34, color = null, white = false, className = "" }) {
  if (color) {
    const mask = {
      WebkitMaskImage: "url(/logo-white.png)", maskImage: "url(/logo-white.png)",
      WebkitMaskSize: "contain", maskSize: "contain",
      WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat",
      WebkitMaskPosition: "center", maskPosition: "center",
    };
    return (
      <span role="img" aria-label="NovaChat" className={"logo-mark " + className}
            style={{ display: "inline-block", width: size, height: size, background: color, ...mask }} />
    );
  }
  return (
    <img
      src={white ? "/logo-white.png" : "/logo.png"}
      width={size}
      height={size}
      alt="NovaChat"
      className={"logo-mark " + className}
      style={{ display: "block", objectFit: "contain", borderRadius: white ? 0 : Math.round(size * 0.24) }}
    />
  );
}
