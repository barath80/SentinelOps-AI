import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #4338ca, #7c3aed, #d946ef)",
          color: "white",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", fontSize: 96, fontWeight: 800 }}>
          Shop<span style={{ color: "#fbbf24" }}>Sphere</span>
        </div>
        <div style={{ fontSize: 32, marginTop: 16, opacity: 0.9 }}>A demo online store</div>
      </div>
    ),
    size,
  );
}
