import { ImageResponse } from "next/og";
import { getProduct, formatPrice } from "@/lib/products";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const p = getProduct(id);
  const color = p?.colors[0].hex ?? "#4338ca";

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: 80,
          background: "#18181b",
          color: "white",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", maxWidth: 720 }}>
          <div style={{ fontSize: 22, textTransform: "uppercase", letterSpacing: 2, color: "#fbbf24" }}>
            {p?.brand ?? "ShopSphere"}
          </div>
          <div style={{ fontSize: 56, fontWeight: 800, marginTop: 12, lineHeight: 1.1 }}>
            {p?.name ?? "Product"}
          </div>
          {p && <div style={{ fontSize: 40, marginTop: 24, color: "#fbbf24", fontWeight: 700 }}>{formatPrice(p.priceCents)}</div>}
        </div>
        <div style={{ width: 220, height: 220, borderRadius: 24, background: color, flexShrink: 0 }} />
      </div>
    ),
    size,
  );
}
