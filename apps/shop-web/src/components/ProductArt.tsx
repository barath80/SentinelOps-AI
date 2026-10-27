import type { ArtKind } from "@/lib/products";

// Generated product illustrations: one drawing per product type, tinted with the selected colour
// on a matching gradient. No third-party photos or brand imagery, so there is nothing to license.

function shade(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const ch = (shift: number) => {
    const v = (n >> shift) & 255;
    const t = amount < 0 ? v * (1 + amount) : v + (255 - v) * amount;
    return Math.max(0, Math.min(255, Math.round(t)));
  };
  return `#${[16, 8, 0].map((s) => ch(s).toString(16).padStart(2, "0")).join("")}`;
}

function Shape({ kind, c, d, l }: { kind: ArtKind; c: string; d: string; l: string }) {
  const stroke = { stroke: d, strokeWidth: 3, strokeLinejoin: "round" as const };
  switch (kind) {
    case "headphones":
      return (<g><path d="M50 110 V95 a50 50 0 0 1 100 0 V110" fill="none" stroke={d} strokeWidth="10" strokeLinecap="round" />
        <rect x="36" y="100" width="34" height="52" rx="14" fill={c} {...stroke} /><rect x="130" y="100" width="34" height="52" rx="14" fill={c} {...stroke} />
        <rect x="44" y="110" width="10" height="32" rx="5" fill={l} /><rect x="146" y="110" width="10" height="32" rx="5" fill={l} /></g>);
    case "earbuds":
      return (<g><rect x="52" y="104" width="96" height="58" rx="26" fill={c} {...stroke} /><line x1="56" y1="126" x2="144" y2="126" stroke={d} strokeWidth="3" />
        <ellipse cx="78" cy="78" rx="16" ry="20" fill={l} {...stroke} /><rect x="73" y="88" width="10" height="22" rx="5" fill={l} {...stroke} />
        <ellipse cx="122" cy="78" rx="16" ry="20" fill={l} {...stroke} /><rect x="117" y="88" width="10" height="22" rx="5" fill={l} {...stroke} /></g>);
    case "phone":
      return (<g><rect x="66" y="30" width="68" height="140" rx="14" fill={c} {...stroke} /><rect x="73" y="42" width="54" height="112" rx="6" fill={l} />
        <circle cx="100" cy="36" r="3" fill={d} /><path d="M80 120 l14 -18 l10 12 l8 -10 l12 16 z" fill={c} opacity="0.6" /></g>);
    case "laptop":
      return (<g><rect x="46" y="52" width="108" height="72" rx="6" fill={c} {...stroke} /><rect x="54" y="60" width="92" height="56" rx="3" fill={l} />
        <path d="M30 128 H170 L160 146 H40 Z" fill={c} {...stroke} /><rect x="86" y="130" width="28" height="4" rx="2" fill={d} /></g>);
    case "watch":
      return (<g><rect x="80" y="26" width="40" height="148" rx="10" fill={c} {...stroke} /><circle cx="100" cy="100" r="40" fill={d} />
        <circle cx="100" cy="100" r="33" fill={l} /><line x1="100" y1="100" x2="100" y2="78" stroke={d} strokeWidth="4" strokeLinecap="round" />
        <line x1="100" y1="100" x2="116" y2="108" stroke={d} strokeWidth="3" strokeLinecap="round" /><rect x="139" y="92" width="8" height="16" rx="3" fill={d} /></g>);
    case "camera":
      return (<g><rect x="36" y="66" width="128" height="86" rx="12" fill={c} {...stroke} /><rect x="56" y="54" width="30" height="16" rx="4" fill={c} {...stroke} />
        <circle cx="104" cy="110" r="32" fill={d} /><circle cx="104" cy="110" r="22" fill={l} /><circle cx="104" cy="110" r="10" fill={d} />
        <rect x="140" y="76" width="14" height="8" rx="2" fill={l} /></g>);
    case "speaker":
      return (<g><rect x="60" y="34" width="80" height="134" rx="22" fill={c} {...stroke} /><circle cx="100" cy="68" r="14" fill={d} />
        <circle cx="100" cy="122" r="28" fill={d} /><circle cx="100" cy="122" r="16" fill={l} opacity="0.8" /></g>);
    case "keyboard":
      return (<g><rect x="26" y="70" width="148" height="64" rx="10" fill={c} {...stroke} />
        {Array.from({ length: 3 }, (_, r) => Array.from({ length: 10 }, (_, k) => (
          <rect key={`${r}-${k}`} x={34 + k * 13.4} y={78 + r * 15} width="10" height="11" rx="2.5" fill={l} />)))}
        <rect x="60" y="121" width="80" height="8" rx="3" fill={l} /></g>);
    case "tshirt":
      return (<path d="M70 40 L50 48 L28 76 L50 92 L58 84 V160 H142 V84 L150 92 L172 76 L150 48 L130 40 Q100 62 70 40 Z" fill={c} {...stroke} />);
    case "hoodie":
      return (<g><path d="M66 50 L46 58 L26 120 L46 126 L56 96 V162 H144 V96 L154 126 L174 120 L154 58 L134 50 Z" fill={c} {...stroke} />
        <path d="M70 50 Q100 20 130 50 Q100 78 70 50 Z" fill={d} /><rect x="76" y="124" width="48" height="22" rx="6" fill={d} opacity="0.35" />
        <line x1="94" y1="62" x2="92" y2="96" stroke={l} strokeWidth="3" /><line x1="106" y1="62" x2="108" y2="96" stroke={l} strokeWidth="3" /></g>);
    case "cap":
      return (<g><path d="M44 120 Q44 58 100 56 Q156 58 156 120 Z" fill={c} {...stroke} /><path d="M40 120 H176 Q172 136 120 134 H40 Z" fill={d} />
        <circle cx="100" cy="56" r="6" fill={d} /><path d="M100 60 V118" stroke={d} strokeWidth="2" opacity="0.5" /></g>);
    case "backpack":
      return (<g><path d="M78 46 Q100 22 122 46" fill="none" stroke={d} strokeWidth="8" /><rect x="52" y="46" width="96" height="124" rx="24" fill={c} {...stroke} />
        <rect x="64" y="100" width="72" height="52" rx="10" fill={d} opacity="0.3" /><path d="M52 80 Q100 98 148 80" fill="none" stroke={d} strokeWidth="3" />
        <rect x="92" y="108" width="16" height="6" rx="3" fill={l} /></g>);
    case "sneaker":
      return (<g><path d="M24 128 Q30 96 60 92 L92 74 Q110 100 140 104 Q172 108 178 128 Z" fill={c} {...stroke} />
        <path d="M22 128 H180 Q180 146 160 146 H34 Q22 146 22 128 Z" fill={l} {...stroke} />
        <path d="M78 86 l10 12 M88 80 l10 12 M98 76 l10 12" stroke={l} strokeWidth="4" strokeLinecap="round" /><path d="M110 112 Q140 116 166 124" stroke={d} strokeWidth="3" fill="none" /></g>);
    case "boot":
      return (<g><path d="M62 34 H118 V112 Q160 114 170 140 H58 Z" fill={c} {...stroke} /><path d="M54 140 H174 V156 H54 Z" fill={d} />
        <path d="M74 48 H106 M74 64 H106 M74 80 H106" stroke={l} strokeWidth="4" strokeLinecap="round" /></g>);
    case "lamp":
      return (<g><path d="M64 44 H136 L152 98 H48 Z" fill={c} {...stroke} /><rect x="96" y="98" width="8" height="54" fill={d} />
        <rect x="66" y="150" width="68" height="14" rx="7" fill={d} /><ellipse cx="100" cy="104" rx="30" ry="6" fill="#fde68a" opacity="0.8" /></g>);
    case "chair":
      return (<g><rect x="62" y="34" width="76" height="66" rx="20" fill={c} {...stroke} /><rect x="54" y="98" width="92" height="22" rx="10" fill={c} {...stroke} />
        <rect x="96" y="120" width="8" height="24" fill={d} /><path d="M66 166 L100 144 L134 166 M100 144 V168" stroke={d} strokeWidth="6" strokeLinecap="round" fill="none" /></g>);
    case "plant":
      return (<g><path d="M100 104 Q70 70 60 44 Q90 54 100 96 Z" fill="#22c55e" /><path d="M100 104 Q132 66 146 48 Q120 54 100 96 Z" fill="#16a34a" />
        <path d="M100 106 Q100 60 100 36" stroke="#15803d" strokeWidth="5" /><path d="M64 104 H136 L126 164 H74 Z" fill={c} {...stroke} /><rect x="60" y="100" width="80" height="12" rx="4" fill={d} /></g>);
    case "mug":
      return (<g><path d="M132 82 a22 22 0 0 1 0 48" fill="none" stroke={d} strokeWidth="10" /><rect x="58" y="64" width="78" height="96" rx="12" fill={c} {...stroke} />
        <path d="M78 52 q6 -10 0 -20 M98 52 q6 -10 0 -20 M118 52 q6 -10 0 -20" stroke={d} strokeWidth="3" fill="none" opacity="0.4" /><rect x="68" y="92" width="58" height="16" rx="4" fill={l} opacity="0.6" /></g>);
    case "bottle":
      return (<g><rect x="84" y="24" width="32" height="20" rx="6" fill={d} /><path d="M80 44 H120 L128 64 V168 Q128 176 120 176 H80 Q72 176 72 168 V64 Z" fill={c} {...stroke} />
        <rect x="80" y="92" width="40" height="44" rx="6" fill={l} opacity="0.55" /></g>);
    case "pan":
      return (<g><circle cx="82" cy="104" r="54" fill={d} /><circle cx="82" cy="104" r="44" fill={c} /><circle cx="82" cy="104" r="34" fill={shade(c, -0.25)} />
        <rect x="132" y="96" width="56" height="16" rx="8" fill={d} transform="rotate(-12 132 104)" /></g>);
    case "dumbbell":
      return (<g><rect x="56" y="94" width="88" height="12" rx="4" fill={l} {...stroke} />
        <rect x="34" y="66" width="24" height="68" rx="8" fill={c} {...stroke} /><rect x="142" y="66" width="24" height="68" rx="8" fill={c} {...stroke} />
        <rect x="20" y="78" width="16" height="44" rx="6" fill={d} /><rect x="164" y="78" width="16" height="44" rx="6" fill={d} /></g>);
    case "ball":
      return (<g><circle cx="100" cy="100" r="64" fill={c} {...stroke} /><path d="M36 100 H164 M100 36 V164" stroke={d} strokeWidth="4" />
        <path d="M54 54 Q100 100 54 146 M146 54 Q100 100 146 146" stroke={d} strokeWidth="4" fill="none" /></g>);
    case "perfume":
      return (<g><rect x="88" y="34" width="24" height="22" rx="4" fill={d} /><rect x="94" y="56" width="12" height="12" fill={d} />
        <rect x="56" y="68" width="88" height="100" rx="22" fill={c} opacity="0.9" {...stroke} /><rect x="72" y="100" width="56" height="34" rx="6" fill={l} /></g>);
    case "lipstick":
      return (<g><path d="M86 54 L114 42 V92 H86 Z" fill={c} {...stroke} /><rect x="80" y="90" width="40" height="22" rx="4" fill="#d4af37" />
        <rect x="76" y="110" width="48" height="60" rx="8" fill={d} /></g>);
    case "jar":
      return (<g><rect x="50" y="64" width="100" height="26" rx="8" fill={d} /><rect x="54" y="88" width="92" height="74" rx="18" fill={c} {...stroke} />
        <rect x="70" y="110" width="60" height="28" rx="6" fill={l} /></g>);
    case "robot":
      return (<g><line x1="100" y1="26" x2="100" y2="44" stroke={d} strokeWidth="4" /><circle cx="100" cy="24" r="6" fill={l} />
        <rect x="64" y="44" width="72" height="54" rx="14" fill={c} {...stroke} /><circle cx="86" cy="70" r="9" fill={l} /><circle cx="114" cy="70" r="9" fill={l} />
        <rect x="58" y="102" width="84" height="62" rx="12" fill={c} {...stroke} /><rect x="80" y="116" width="40" height="22" rx="4" fill={l} opacity="0.6" />
        <rect x="38" y="108" width="16" height="42" rx="8" fill={d} /><rect x="146" y="108" width="16" height="42" rx="8" fill={d} /></g>);
    case "blocks":
      return (<g><rect x="40" y="112" width="56" height="48" rx="6" fill={c} {...stroke} /><rect x="104" y="112" width="56" height="48" rx="6" fill="#f59e0b" {...stroke} />
        <rect x="72" y="60" width="56" height="48" rx="6" fill="#3b82f6" {...stroke} />
        {[52, 74, 116, 138, 84, 106].map((x, i) => <rect key={i} x={x - 6} y={i < 4 ? 104 : 52} width="12" height="9" rx="3" fill={d} opacity="0.5" />)}</g>);
    case "teddy":
      return (<g><circle cx="66" cy="54" r="18" fill={c} {...stroke} /><circle cx="134" cy="54" r="18" fill={c} {...stroke} />
        <ellipse cx="100" cy="130" rx="46" ry="40" fill={c} {...stroke} /><circle cx="100" cy="78" r="40" fill={c} {...stroke} />
        <ellipse cx="100" cy="92" rx="16" ry="12" fill={l} /><circle cx="86" cy="72" r="4" fill="#111" /><circle cx="114" cy="72" r="4" fill="#111" /><circle cx="100" cy="88" r="4" fill="#111" /></g>);
  }
}

export default function ProductArt({ kind, color, label, className }: { kind: ArtKind; color: string; label: string; className?: string }) {
  const light = shade(color, 0.85);
  const id = `g-${kind}-${color.slice(1)}`;
  return (
    <svg viewBox="0 0 200 200" role="img" aria-label={label} className={className}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={shade(color, 0.92)} />
          <stop offset="1" stopColor={shade(color, 0.7)} />
        </linearGradient>
      </defs>
      <rect width="200" height="200" fill={`url(#${id})`} />
      <ellipse cx="100" cy="176" rx="64" ry="8" fill="#000" opacity="0.08" />
      <Shape kind={kind} c={color} d={shade(color, -0.45)} l={light} />
    </svg>
  );
}
