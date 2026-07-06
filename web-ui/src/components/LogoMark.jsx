// Logo NovaChat — ảnh thật (public/logo.png). Dùng chung landing/sidebar/topbar.
export default function LogoMark({ size = 34, className = "" }) {
  return (
    <img
      src="/logo.png"
      width={size}
      height={size}
      alt="NovaChat"
      className={"logo-mark " + className}
      style={{ display: "block", borderRadius: Math.round(size * 0.24), objectFit: "cover" }}
    />
  );
}
